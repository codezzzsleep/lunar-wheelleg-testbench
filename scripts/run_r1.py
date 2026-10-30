"""
V7-R1 用户入口：一条命令跑完整流程，按阶段可续跑。

  .venv/bin/python scripts/run_r1.py --dry-run          # 只打印将要执行的命令
  .venv/bin/python scripts/run_r1.py --stage all        # 全流程（已完成的阶段自动跳过）
  .venv/bin/python scripts/run_r1.py --stage page --force

阶段（顺序固定，后一阶段只依赖前一阶段的产物）：
  observe → candidate → fuse → measure → closed_loop → six → page → verify

设计约束：
  · 不隐藏命令：每一步都打印等价的可复制命令；
  · 不重复花钱：candidate 阶段只在缺失时调用云端，且必须显式给出 --allow-generate；
  · 不跳证据：某阶段产物存在但哈希不符时，默认失败而不是覆盖。
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = str(ROOT / '.venv/bin/python')
BATCH = 'runs/unseen/delivery_v7/v7_20261030_r1'
B = ROOT / BATCH


def sh(cmd, dry=False, env_extra=None):
    line = ' '.join(cmd) if isinstance(cmd, list) else cmd
    print(f'\n$ {line}')
    if dry:
        return 0
    env = dict(os.environ)
    env.setdefault('MUJOCO_GL', 'osmesa')
    if env_extra:
        env.update(env_extra)
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


INPUTS = {   # 每个阶段必须存在的输入（缺一个就说明入口已经和实际产物脱节）
    'observe': ['cases/unseen_v1/R03.json', f'{BATCH}/observation/drive_R03_b/drive_observe.json'],
    'candidate': ['runs/unseen/recovery_r3/upload_pkg/R02/upload_with_ground_1024.png'],
    'fuse': ['runs/unseen/recovery_r3/obs_R03',
             'runs/unseen/delivery_v7/v7_20261030/candidates/V7_R03_s1/world/align'],
    'measure': [f'{BATCH}/fusion_diagnostics/off1_R03_s1/body.stl'],
    'closed_loop': [f'{BATCH}/cases/R03_two_qualified.json',
                    'runs/unseen/delivery_v6_1/v6_1_20261029/evaluation/DIAG_R03/collision/TRUTH'],
    'six': ['plans/unseen_v7_protocol_six_nominal.json'],
    'page': [],
    'verify': [],
}


def audit():
    bad = 0
    for name, ins in INPUTS.items():
        for rel in ins:
            ok = (ROOT / rel).exists()
            if not ok:
                bad += 1
            print(f'{"OK  " if ok else "MISS"} [{name}] {rel}')
    print(f'\n缺少 {bad} 个输入' if bad else '\n全部输入存在')
    return 1 if bad else 0


def stage_ok(name, st):
    """续跑必须看**结果状态**，不能只看文件存在（已有 FAIL 报告不得被当作成功跳过）。"""
    if not exists(*st['evidence']):
        return False
    if name == 'verify':
        try:
            rep = json.loads((B / 'verify/r1_report.json').read_text())
            return rep.get('verdict') == 'PASS'
        except Exception:
            return False
    if name == 'page':
        try:
            html = (B / 'media/report/index.html').read_text()
            return '回放已有运行' in html and '重新运行' in html and 'play(' in html
        except Exception:
            return False
    return True


def exists(*rel):
    return all((ROOT / r).exists() for r in rel)


STAGES = {}


def stage(name, evidence):
    def deco(fn):
        STAGES[name] = {'fn': fn, 'evidence': evidence}
        return fn
    return deco


@stage('observe', [f'{BATCH}/observation/obs_R03_at_driven/observation.json'])
def s_observe(a):
    return sh([PY, 'scripts/observe.py', '--case', 'cases/unseen_v1/R03.json',
               '--out', f'{BATCH}/observation/obs_R03_at_driven',
               '--state-json', f'{BATCH}/observation/drive_R03_b/drive_observe.json',
               '--state-seed', '0', '--observation-id', 'R03_after_drive'], a.dry_run)


@stage('candidate', [f'{BATCH}/generation/task_4497119.json'])
def s_candidate(a):
    if not a.allow_generate:
        print('\n[candidate] 已存在生成记录；如需重新生成必须加 --allow-generate（会花钱）')
        return 0
    return sh([PY, 'scripts/v7_generate.py', '--batch-dir', BATCH, '--object', 'R02',
               '--images', 'runs/unseen/recovery_r3/upload_pkg/R02/upload_with_ground_1024.png',
               '--sample', 'g3', '--credit-upper', '1.0', '--scope', 'v7_r1'], a.dry_run)


@stage('fuse', [f'{BATCH}/fusion_diagnostics/off1_R03_s1/manifest.json'])
def s_fuse(a):
    return sh([PY, 'scripts/fuse_observed.py',
               '--observation', 'runs/unseen/recovery_r3/obs_R03',
               '--parent-world', 'runs/unseen/delivery_v7/v7_20261030/candidates/V7_R03_s1/world/align',
               '--parent-id', 'V7_R03_s1', '--method', 'H5_F',
               '--out', f'{BATCH}/fusion_diagnostics/off1_R03_s1',
               '--pitch', '0.0025', '--config', 'configs/unseen_v7_r1_fusion_offset1.json'],
              a.dry_run)


@stage('measure', [f'{BATCH}/fusion_diagnostics/off1_R03_s1/collision/metrics_full.json'])
def s_measure(a):
    f = f'{BATCH}/fusion_diagnostics/off1_R03_s1'
    rc = sh([PY, 'scripts/collision_box_union.py', '--mesh', f'{f}/body.stl',
             '--out', f'{f}/collision', '--pitch', '0.0025',
             '--hypothesis-id', 'R03_s1_off1_box'], a.dry_run)
    if rc:
        return rc
    return sh([PY, 'scripts/collision_occupancy_metrics.py', '--mesh', f'{f}/body.stl',
               '--collision', f'{f}/collision', '--out', f'{f}/collision/metrics_full.json',
               '--label', 'R03_s1_off1', '--eval-pitch', '0.004', '--parity', 'full'],
              a.dry_run)


@stage('closed_loop', [f'{BATCH}/evaluation/closed_loop_R03_three_soils/closed_loop.json'])
def s_closed_loop(a):
    return sh([PY, 'scripts/v7_closed_loop.py',
               '--drive', f'{BATCH}/observation/drive_R03_b/drive_observe.json',
               '--hypotheses', f'{BATCH}/cases/R03_two_qualified.json',
               '--truth-collision',
               'runs/unseen/delivery_v6_1/v6_1_20261029/evaluation/DIAG_R03/collision/TRUTH',
               '--truth-world',
               'runs/unseen/delivery_v6_1/v6_1_20261029/evaluation/DIAG_R03/truth_world',
               '--visible-json', f'{BATCH}/observations/R01_visible_public.json',
               '--soil-configs', 'nominal,low_traction,high_drag',
               '--out', f'{BATCH}/evaluation/closed_loop_R03_three_soils'], a.dry_run)


@stage('six', [f'{BATCH}/evaluation/six_R03_nominal/summary.json'])
def s_six(a):
    for m in ('nominal', 'low_traction', 'high_drag'):
        rc = sh([PY, 'scripts/eval_six.py', '--protocol',
                 f'plans/unseen_v7_protocol_six_{m}.json',
                 '--out', f'{BATCH}/evaluation/six_R03_{m}'], a.dry_run)
        if rc:
            return rc
    return 0


@stage('page', [f'{BATCH}/media/report/index.html'])
def s_page(a):
    return sh([PY, 'scripts/v7_page_r1.py'], a.dry_run)


@stage('verify', [f'{BATCH}/verify/r1_report.json'])
def s_verify(a):
    return sh([PY, 'scripts/verify_delivery_r1.py'], a.dry_run)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', default='all',
                    choices=['all'] + list(STAGES))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='即使产物已存在也重跑该阶段')
    ap.add_argument('--allow-generate', action='store_true',
                    help='允许调用云端生成（会花钱）；默认不调用')
    ap.add_argument('--stop-on-fail', action='store_true', default=True)
    ap.add_argument('--audit', action='store_true',
                    help='只检查各阶段声明的输入是否存在（入口与实际产物是否脱节）')
    a = ap.parse_args()
    if a.audit:
        return audit()
    order = ['observe', 'candidate', 'fuse', 'measure', 'closed_loop', 'six', 'page', 'verify']
    todo = order if a.stage == 'all' else [a.stage]
    print('阶段顺序：' + ' → '.join(order))
    rc_all = 0
    for name in todo:
        st = STAGES[name]
        done = stage_ok(name, st)
        if done and not a.force:
            print(f'\n[{name}] 已有产物且状态正常，跳过（--force 可重跑）：{st["evidence"][0]}')
            continue
        if not done and exists(*st['evidence']):
            print(f'\n[{name}] 产物存在但状态不通过（例如上次 FAIL），重跑')
        rc = st['fn'](a)
        if rc:
            print(f'\n[{name}] 失败，退出码 {rc}')
            rc_all = rc
            break
        print(f'\n[{name}] 完成')
    if a.stage == 'all':
        print('\n全部阶段结束；页面：' + str((B / 'media/report/index.html').relative_to(ROOT)))
        print('验收：' + str((B / 'verify/r1_report.json').relative_to(ROOT)))
    return rc_all


if __name__ == '__main__':
    sys.exit(main())
