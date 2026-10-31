"""动作接线检查：观察→适用性→动作内部相位与参数来源（非 R1 也要覆盖）。

对每个动作：用同一份公开可见量，从同一冻结状态起跑固定时长，记录
是否触发相位、动作向量、以及可见量是否真的进入技能（改可见量应改变行为）。
"""
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np, eval_six, runner, skills, actions as ACT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--collision', required=True)
    ap.add_argument('--visible', required=True)
    ap.add_argument('--state', required=True)
    ap.add_argument('--actions', default='L1,L2,D1,D2,S1')
    ap.add_argument('--seconds', type=float, default=4.0)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    vis = json.loads((ROOT / a.visible).read_text())
    snap = json.loads((ROOT / a.state).read_text())
    rows = []
    for act in a.actions.split(','):
        ok, why = ACT.applicable(act, vis)
        env = eval_six.build_env(ROOT / a.collision, 2.6, 30.0, 'nominal', 0)
        env.reset(seed=0)
        env.restore_state(snap, mode='project')
        sk = skills.make_skill(act)
        r = runner.EpisodeRunner(env, sk, visible=vis, seed=0, record_trajectory=True)
        first = np.asarray(sk.act(env._obs(), env.robot_state()), dtype=float).reshape(-1)
        r0 = r.run_current()
        # 可见量敏感性：把 W_vis 放大 50%，动作向量应变化（否则说明没接线）
        vis2 = dict(vis); vis2['W_vis'] = float(vis.get('W_vis') or 0) * 1.5
        sk2 = skills.make_skill(act)
        r2 = runner.EpisodeRunner(env, sk2, visible=vis2, seed=0)
        first2 = np.asarray(sk2.act(env._obs(), env.robot_state()), dtype=float).reshape(-1)
        rows.append({'action': act, 'applicable': ok, 'reason': why,
                     'phases': r0.get('phases'), 'triggered': bool(r0.get('triggered')),
                     'success': r0.get('success'), 'reason_out': r0.get('reason'),
                     'action_first': [round(float(x), 4) for x in first],
                     'visible_sensitive': bool(np.abs(first - first2).max() > 1e-6),
                     'contract': getattr(ACT, 'RULE_VERSION', None)})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'n': len(rows), 'items': rows}, ensure_ascii=False, indent=2))
    print(json.dumps({'n': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
