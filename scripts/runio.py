"""
每次运行独立目录 + 可追溯记录。

目录结构：
  runs/<run_id>/
    config.json        本批的完整配置（含 trial 清单）
    environment.json   软件版本、git 提交、模型提交、硬件
    results.jsonl      逐 trial 原始记录（唯一事实来源）
    summary.json       分组汇总（由 results 计算，不独立保存结论）
    report.md          分析产出
    figures/  logs/  replays/
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


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _pkg_version(name):
    try:
        mod = __import__(name)
        return getattr(mod, '__version__', 'unknown')
    except Exception:
        return None


def _git(path, *args):
    try:
        return subprocess.run(['git', '-C', str(path), *args], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ''


def environment_snapshot():
    commit = _git(ROOT, 'rev-parse', 'HEAD')
    dirty = bool(_git(ROOT, 'status', '--porcelain'))
    vendor = ROOT / 'vendor/unitree_mujoco'
    try:
        cpu = os.cpu_count()
    except Exception:
        cpu = None
    return {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'cpu_count': cpu,
        'packages': {n: _pkg_version(n) for n in
                     ('mujoco', 'numpy', 'trimesh', 'coacd', 'manifold3d')},
        'code': {'commit': commit, 'uncommitted_changes': dirty,
                 'branch': _git(ROOT, 'rev-parse', '--abbrev-ref', 'HEAD')},
        'robot_model': {'path': str(vendor.relative_to(ROOT)) if vendor.exists() else None,
                        'commit': _git(vendor, 'rev-parse', 'HEAD') or None},
    }


def new_run(out_dir, suite, config):
    """创建运行目录并写入 config/environment。返回 (run_dir, run_id)。"""
    run_dir = pathlib.Path(out_dir).resolve()
    run_id = run_dir.name
    for sub in ('figures', 'logs', 'replays'):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    config = {**config, 'run_id': run_id, 'suite': suite,
              'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    (run_dir / 'config.json').write_text(json.dumps(config, indent=2, ensure_ascii=False))
    (run_dir / 'environment.json').write_text(
        json.dumps(environment_snapshot(), indent=2, ensure_ascii=False))
    return run_dir, run_id


def trial_id(config):
    """基于影响结果的规范化配置生成稳定 id。"""
    keys = ('asset', 'controller', 'stance', 'y_offset', 'obstacle_x',
            'gravity', 'friction', 'seconds')
    norm = {k: config.get(k) for k in keys if k in config}
    blob = json.dumps(norm, sort_keys=True, separators=(',', ':'))
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def append_result(run_dir, rec):
    """逐条落盘并 flush，中断后可识别已完成任务。"""
    p = pathlib.Path(run_dir) / 'results.jsonl'
    with p.open('a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def load_results(path):
    """只读显式指定的文件，绝不 glob。"""
    rows, bad = [], 0
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return rows, bad


def already_done(run_dir):
    p = pathlib.Path(run_dir) / 'results.jsonl'
    if not p.exists():
        return set()
    done = set()
    for line in p.read_text().splitlines():
        try:
            rec = json.loads(line)
            done.add(rec.get('trial_id'))
        except Exception:
            pass
    return done


def asset_fingerprint(asset_dir):
    """碰撞资产的哈希：记录实际参与仿真的文件，而不是提示词。"""
    d = pathlib.Path(asset_dir)
    parts = sorted(d.glob('parts/*.stl'))
    h = hashlib.sha256()
    for p in parts:
        h.update(p.name.encode())
        h.update(sha256_file(p).encode())
    return {'collision_sha': h.hexdigest()[:32], 'n_parts': len(parts)}
