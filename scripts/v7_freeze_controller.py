"""冻结共同控制器：写出一份带身份与参数的清单，后续所有比较引用它。

  .venv/bin/python scripts/v7_freeze_controller.py --out plans/r1_controller_freeze.json
"""
import argparse, hashlib, json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import actions as ACT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='plans/r1_controller_freeze.json')
    a = ap.parse_args()
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                          capture_output=True, text=True).stdout.strip()
    files = ['scripts/wheelleg_env.py', 'scripts/skills.py', 'scripts/actions.py',
             'scripts/runner.py', 'scripts/drive_observe.py']
    shas = {}
    for f in files:
        p = ROOT / f
        shas[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None
    cfg = {
        'schema': 'controller-freeze/v1', 'frozen_from_commit': head,
        'env': {'class': 'wheelleg_env.WheelLegEnv', 'control_hz': 50.0,
                'max_seconds_default': 30.0, 'obs': '_obs()'},
        'actions': {'registry': 'actions.OPTIONS', 'options': list(ACT.OPTIONS),
                    'rule_version': getattr(ACT, 'RULE_VERSION', None)},
        'runner': {'class': 'runner.EpisodeRunner', 'entry': '_loop',
                   'direct_continue': 'run_current()', 'record_trajectory': True},
        'drive_policy': {'mode': 'nav', 'target_y': 0.30, 'stop_x': 1.30, 'v': 0.10,
                         'max_s': 10.0, 'settle_max_s': 6.0,
                         'evidence': 'runs/unseen/delivery_v7/v7_20261030_r1/evaluation/same_scene_usable'},
        'file_shas': shas,
        'note': ('后续正式比较必须引用本清单；更换控制器需新建冻结文件并记录更正，'
                 '旧表格保留为历史记录。'),
    }
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    print(json.dumps({'out': a.out, 'commit': head, 'rule': cfg['actions']['rule_version'],
                      'files': len(shas)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
