"""
运行身份、资产解析、批次隔离、安全续跑。

三条约定（对应第二轮任务书）：
  1. **一个函数完成资产的读取 / 路径解析 / 预检**，返回实际参与仿真的绝对文件列表。
     XML 加载、存在性检查、哈希计算都用这一份列表。
  2. **路径以 manifest 所在目录为基准**。manifest 里优先存相对路径（parts/xx.stl）；
     旧的绝对路径按兼容规则回退，并记录 path_mode。
  3. **新建与续跑显式区分**：新运行只接受不存在或空的目录；续跑必须 --resume
     并校验完整身份，否则非零退出且不改动原文件。
"""
import hashlib
import json
import os
import pathlib
import platform
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN_SCHEMA = 2

# 影响仿真结果的源码：任何一个变化都改变运行身份
SIM_SOURCE_FILES = ['scripts/exam.py', 'scripts/controllers.py',
                    'scripts/build_scene.py', 'scripts/drive_test.py']


# ------------------------------------------------------------------ 基础工具

def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def identity_of(payload):
    return sha256_bytes(canonical_json(payload).encode())[:32]


def _git(path, *args):
    try:
        return subprocess.run(['git', '-C', str(path), *args], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ''


def _dist_version(name):
    try:
        import importlib.metadata as md
        return md.version(name)
    except Exception:
        try:
            mod = __import__(name)
            return getattr(mod, '__version__', None) or 'unknown'
        except Exception:
            return 'unknown'


# ------------------------------------------------------------------ 身份

def source_identity():
    """影响仿真的源码内容哈希 + git 信息（git 仅作参考，不参与唯一性）。"""
    files = {}
    for rel in SIM_SOURCE_FILES:
        p = ROOT / rel
        files[rel] = sha256_file(p) if p.exists() else None
    return {
        'files': files,
        'content_sha': sha256_bytes(canonical_json(files).encode())[:32],
        'git_commit': _git(ROOT, 'rev-parse', 'HEAD') or None,
        'git_dirty': bool(_git(ROOT, 'status', '--porcelain')),
    }


def model_identity():
    src = ROOT / 'vendor/unitree_mujoco'
    xml = src / 'unitree_robots/go2w/go2w.xml'
    if not xml.exists():
        return {'available': False}
    return {
        'available': True,
        'go2w_xml_sha': sha256_file(xml)[:32],
        'git_commit': _git(src, 'rev-parse', 'HEAD') or None,
        'git_dirty': bool(_git(src, 'status', '--porcelain')),
    }


def environment_snapshot():
    try:
        cpu = os.cpu_count()
    except Exception:
        cpu = None
    return {
        'captured_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'cpu_count': cpu,
        'packages': {n: _dist_version(n) for n in
                     ('mujoco', 'numpy', 'trimesh', 'coacd', 'manifold3d', 'pillow')},
        'source': source_identity(),
        'model': model_identity(),
    }


# ------------------------------------------------------------------ 资产解析

def resolve_asset(asset_dir):
    """
    读取 manifest、解析 parts 路径、预检，返回实际参与仿真的文件列表。

    返回 dict: ok, reason, manifest, part_paths(abs, 顺序同 manifest),
               collision_sha, path_mode, missing
    """
    d = pathlib.Path(asset_dir)
    base = {'ok': False, 'manifest': None, 'part_paths': [], 'collision_sha': None,
            'path_mode': None, 'missing': []}
    if not d.exists():
        return {**base, 'reason': 'asset_dir_missing'}
    mf = d / 'manifest.json'
    if not mf.exists():
        return {**base, 'reason': 'manifest_missing'}
    try:
        man = json.loads(mf.read_text())
    except Exception:
        return {**base, 'reason': 'manifest_unreadable'}
    if not isinstance(man, dict):
        return {**base, 'reason': 'manifest_not_object'}

    raw_parts = man.get('parts')
    if not isinstance(raw_parts, list) or not raw_parts:
        return {**base, 'reason': 'no_collision_parts', 'manifest': man}

    resolved, missing, modes = [], [], set()
    for p in raw_parts:
        if not isinstance(p, str) or not p.strip():
            missing.append(repr(p))
            continue
        pp = pathlib.Path(p)
        if pp.is_absolute():
            if pp.exists():
                resolved.append(pp.resolve())
                modes.add('absolute_compat')
                continue
            cand = d / 'parts' / pp.name     # 兼容：绝对路径失效时按命名回退
            if cand.exists():
                resolved.append(cand.resolve())
                modes.add('absolute_compat_fallback')
                continue
            missing.append(str(pp))
        else:
            # 约定：相对 manifest 所在目录；兼容旧数据里"相对仓库根"的写法
            cand = d / pp
            if cand.exists():
                resolved.append(cand.resolve())
                modes.add('relative')
                continue
            legacy = ROOT / pp
            if legacy.exists():
                resolved.append(legacy.resolve())
                modes.add('root_relative_compat')
                continue
            tail = d / 'parts' / pp.name
            if tail.exists():
                resolved.append(tail.resolve())
                modes.add('basename_fallback')
                continue
            missing.append(str(cand))

    if missing:
        return {**base, 'reason': 'missing_part', 'manifest': man,
                'part_paths': resolved, 'path_mode': '+'.join(sorted(modes)) or None,
                'missing': missing}

    # 哈希必须对应实际参与仿真的文件，顺序与 manifest 一致，
    # 未被 manifest 引用的残留 STL 不参与
    h = hashlib.sha256()
    for p in resolved:
        h.update(p.name.encode())
        h.update(sha256_file(p).encode())
    collision_sha = h.hexdigest()[:32]
    mode = '+'.join(sorted(modes))

    try:
        height = float(man['height_m'])
        rel_w = float(man['rel_width'])
    except Exception:
        return {**base, 'reason': 'bad_dimensions', 'manifest': man,
                'part_paths': resolved, 'collision_sha': collision_sha, 'path_mode': mode}
    if not (height > 0) or not (rel_w > 0):
        return {**base, 'reason': 'nonpositive_dimensions', 'manifest': man,
                'part_paths': resolved, 'collision_sha': collision_sha, 'path_mode': mode}
    if man.get('pass', True) is False:
        return {**base, 'reason': 'manifest_pass_false', 'manifest': man,
                'part_paths': resolved, 'collision_sha': collision_sha, 'path_mode': mode}

    return {'ok': True, 'reason': 'ok', 'manifest': man, 'part_paths': resolved,
            'collision_sha': collision_sha, 'path_mode': mode, 'missing': []}


def asset_fingerprint(asset_dir):
    r = resolve_asset(asset_dir)
    return {'ok': r['ok'], 'collision_sha': r['collision_sha'],
            'n_parts': len(r['part_paths']), 'reason': r['reason'],
            'path_mode': r['path_mode']}


# ------------------------------------------------------------------ trial 身份

def make_context(control, scene):
    """把影响结果的全局量打包成身份上下文。"""
    src, mdl = source_identity(), model_identity()
    return {
        'control': control,
        'scene': scene,
        'model_sha': mdl.get('go2w_xml_sha'),
        'source_sha': src['content_sha'],
    }


def trial_identity(trial, ctx):
    payload = {
        'schema': RUN_SCHEMA,
        'asset': trial.get('asset'),
        'collision_sha': trial.get('collision_sha'),
        'controller': trial.get('controller'),
        'stance': trial.get('stance'),
        'y_offset': trial.get('y_offset'),
        'obstacle_x': trial.get('obstacle_x'),
        'seconds': trial.get('seconds'),
        'control': ctx['control'],
        'scene': ctx['scene'],
        'model': ctx['model_sha'],
        'source': ctx['source_sha'],
    }
    return identity_of(payload)[:16]


def run_identity(trials, ctx, suite):
    payload = {'schema': RUN_SCHEMA, 'suite': suite, 'ctx': ctx,
               'trial_ids': sorted(t['trial_id'] for t in trials)}
    return identity_of(payload)


# ------------------------------------------------------------------ 批次

def _is_effectively_empty(d):
    return (not d.exists()) or (not any(d.iterdir()))


def new_run(out_dir, suite, config, resume=False):
    """
    新运行：目录必须不存在或为空，否则拒绝。
    续跑：目录必须存在且有 manifest，suite / 任务集合 / 身份都必须一致。
    """
    run_dir = pathlib.Path(out_dir).resolve()
    man_path = run_dir / 'manifest.json'

    if resume:
        if not man_path.exists():
            raise SystemExit(f'拒绝续跑：{run_dir} 下没有 manifest.json')
        manifest = json.loads(man_path.read_text())
        if manifest.get('schema') != RUN_SCHEMA:
            raise SystemExit(f'拒绝续跑：manifest schema={manifest.get("schema")} '
                             f'与本代码 (={RUN_SCHEMA}) 不一致')
        if manifest.get('suite') != suite:
            raise SystemExit(f'拒绝续跑：suite 不一致（manifest={manifest.get("suite")}, '
                             f'本次={suite}）')
        if manifest.get('identity') != config['identity']:
            raise SystemExit(
                '拒绝续跑：运行身份不一致（控制参数 / 资产指纹 / 模型 / 仿真源码有变化）。\n'
                '  如需用新配置，请换一个新的输出目录。')
        expected = set(manifest['trial_ids'])
        got = {t['trial_id'] for t in config['trials']}
        if expected != got:
            raise SystemExit(f'拒绝续跑：任务集合不一致（缺失 {len(expected - got)}，'
                             f'多出 {len(got - expected)}）')
        return run_dir, manifest

    if not _is_effectively_empty(run_dir):
        raise SystemExit(
            f'拒绝新建：{run_dir} 非空。\n'
            '  要续跑请加 --resume；要重跑请换一个新目录。本工具不会覆盖已有证据。')

    # **先拍环境快照，再创建任何文件**。否则本运行目录自身会成为未跟踪文件，
    # 让 git_dirty 变成 true，证据包会自证"源码不干净"。
    env = environment_snapshot()

    for sub in ('figures', 'logs', 'replays'):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)

    manifest = {**config, 'schema': RUN_SCHEMA, 'suite': suite,
                'run_id': run_dir.name,
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (run_dir / 'environment.json').write_text(
        json.dumps(env, indent=2, ensure_ascii=False))
    return run_dir, manifest


def append_result(run_dir, rec):
    p = pathlib.Path(run_dir) / 'results.jsonl'
    with p.open('a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def load_results(path):
    """返回 (rows, bad_lines)。坏行带行号，不静默丢弃。"""
    rows, bad = [], []
    p = pathlib.Path(path)
    if not p.exists():
        return rows, bad
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            bad.append({'line': i, 'error': f'json:{e.msg}'})
            continue
        if not isinstance(obj, dict):
            bad.append({'line': i, 'error': 'not_an_object'})
            continue
        rows.append(obj)
    return rows, bad


def already_done(run_dir):
    rows, _ = load_results(pathlib.Path(run_dir) / 'results.jsonl')
    return {r.get('trial_id') for r in rows if r.get('trial_id')}


# ------------------------------------------------------------------ 互斥锁

class RunLock:
    """同一目录只允许一个写入进程。异常退出留下的锁需人工确认后删除。"""

    def __init__(self, run_dir):
        self.path = pathlib.Path(run_dir) / '.run.lock'

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SystemExit(
                f'拒绝写入：{self.path} 已存在，可能有另一个进程正在写。\n'
                '  确认无其他进程后手动删除该文件再重试。')
        os.write(fd, json.dumps({'pid': os.getpid(),
                                 'at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return False
