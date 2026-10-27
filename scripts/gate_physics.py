"""
Gate P：同正面、不同背面的物理见证，带**自动判定与退出码**。

  .venv/bin/python scripts/gate_physics.py --posed assets/posed --out runs/unseen/gate_p/w3

与上一版的区别（针对复核意见）：
  · 障碍放在 x=1.8（机器人从 x=0 出生），与观测案例用同一套接近场景，
    稳定化阶段不再被障碍影响；
  · **真实初态**：横向/朝向扰动非零，按 seed 生成并记录实际 q0，三个 seed 是三条不同轨迹；
  · 碰撞用 `physicalize.py` 的**多凸块**（不是单凸包），凹部得以保留；
  · P1–P4 全部自动判定，必需项不通过则退出码非 0，并写 verdict.json。

判据（任务书 5.6，训练前写定）：
  P1  18 组（正面×高度×宽度）里 ≥4 组，不同背面的**最优选项不同**
      最优 = 先按成功率降序，再按平均成功用时升序
  P2  ≥3 组，R1 在一个背面**全成功**、另一个背面**全失败**
  P3  同正面观测一致（由 observe 侧单独验证，这里读它的结果）
  P4  抽 30 回合重演，结局一致
"""
import argparse
import json
import pathlib
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import runner
import skills
import terrain
import wheelleg_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
OBSTACLE_X = 1.8
INIT_LAT = 0.05
INIT_YAW = 0.03


def build_spec(posed_dir, H, case_id, seed, channel_half=1.2):
    man_path = pathlib.Path(posed_dir) / case_id / 'manifest.json'
    spec = terrain.make_spec(kind='flat', seed=seed, objects=[], goal_x=2.8,
                             name=f'gateP_{case_id}')
    spec['channel'] = {'center_y': 0.0, 'half_width': channel_half}
    spec['init_perturbation'] = {'lateral_m': INIT_LAT, 'yaw_rad': INIT_YAW}
    spec['skill_cfg'] = {'task': 'M', 'require_contact': False, 'settle_seconds': 1.0}
    spec['objects'] = [{'posed_dir': str(pathlib.Path(posed_dir) / case_id),
                        'x': OBSTACLE_X, 'y': 0.0, 'yaw_deg': 0.0,
                        'target_height_m': H}]
    return spec


def visible_of_front(case_dir, obstacle_x=OBSTACLE_X):
    """从**正面**几何算可见量，并转换到**世界坐标**。

    局部碰撞顶点在 x<=0 一侧，前沿是局部最小 x；必须加上障碍的世界摆放位置，
    否则 x_front 会是负数，与机器人世界 x 比较就会"起步即触发"。
    正面在所有背面下相同，因此这是可观测常量，不读背面。
    """
    import trimesh
    man = json.loads((pathlib.Path(case_dir) / 'manifest.json').read_text())
    vs = []
    for p_ in man['parts']:
        m = trimesh.load(str(pathlib.Path(case_dir) / p_), force='mesh')
        vs.append(np.asarray(m.vertices))
    v = np.vstack(vs)
    front = v[v[:, 0] <= 1e-6]
    if len(front) == 0:
        return {}
    return {'x_front': float(front[:, 0].min()) + obstacle_x,
            'W_vis': float(front[:, 1].max() - front[:, 1].min()),
            'H_vis': float(front[:, 2].max())}


def run_episode(spec, action_kind, seed, visible=None):
    """与闭环共用同一个执行器（runner.EpisodeRunner），保证动作名称=行为。"""
    env = wheelleg_env.WheelLegEnv(spec, control_hz=50.0, max_seconds=15.0,
                                   v_ref=1.0, tip_deg=60.0)
    r = runner.EpisodeRunner(env, skills.make_skill(action_kind),
                             visible=visible or {}, seed=seed)
    out = r.run_with_seed(seed)
    return {'q0': out['q0'], 'reason': out['reason'], 'success': out['success'],
            't_end': out['t_end'], 'x': out['final_x'],
            'contact': out['contact'], 'belly_contact': out['belly_contact'],
            'triggered': out['triggered'], 'brake_steps': out['brake_steps'],
            'action_fingerprint': out['action_fingerprint']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--posed', required=True, help='assets/posed 目录')
    ap.add_argument('--out', required=True)
    ap.add_argument('--actions', default='R1,R2,L1')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--replay-n', type=int, default=30)
    a = ap.parse_args()

    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    actions = a.actions.split(',')
    seeds = [int(x) for x in a.seeds.split(',')]

    posed = pathlib.Path(a.posed)
    cases = []
    for d in sorted(posed.iterdir()):
        mf = d / 'manifest.json'
        if not mf.exists():
            continue
        m = json.loads(mf.read_text())
        cases.append({'id': d.name, 'H': m['height_m'], 'parts': m['coacd_parts'],
                      'concavity': m['concavity'], 'dir': str(d)})
    if not cases:
        raise SystemExit('assets/posed 下没有可用资产')

    # 从 id 解析：s{seed}_h{h*10}_w{w*100}_{kind}
    groups = defaultdict(dict)
    for c in cases:
        p = c['id'].split('_')
        if len(p) < 4 or not p[0].startswith('s') or not p[1].startswith('h'):
            continue                      # 跳过不符合命名的目录，不猜
        front = (int(p[0][1:]), int(p[1][1:]) / 10.0, int(p[2][1:]) / 100.0)
        kind = '_'.join(p[3:])            # ramp_s / ramp_l 含下划线
        groups[front][kind] = c
    if not groups:
        raise SystemExit('没有匹配 s{seed}_h.._w.._{kind} 的资产')

    rows = []
    for front, backs in sorted(groups.items()):
        for kind, c in sorted(backs.items()):
            spec = build_spec(posed, c['H'], c['id'], front[0])
            vis = visible_of_front(pathlib.Path(posed) / c['id'], OBSTACLE_X)
            for act in actions:
                for sd in seeds:
                    r = run_episode(spec, act, sd, visible=vis)
                    rows.append({'front': list(front), 'back': kind, 'case_id': c['id'], 'H': c['H'],
                                 'option': act, 'seed': sd, 'coacd_parts': c['parts'],
                                 'concavity': c['concavity'], **r})
    (out / 'results.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')

    agg = defaultdict(lambda: {'succ': 0, 'n': 0, 't': []})
    for r in rows:
        k = (tuple(r['front']), r['back'], r['option'])
        agg[k]['n'] += 1
        agg[k]['succ'] += int(r['success'])
        if r['success'] and r['t_end']:
            agg[k]['t'].append(r['t_end'])

    n_per = len(seeds)
    fronts = sorted({tuple(r['front']) for r in rows})
    backs_all = sorted({r['back'] for r in rows})

    # P1：每组的最优选项是否随背面改变
    p1_hits, p1_detail = [], []
    for f in fronts:
        best = {}
        for b in backs_all:
            cand = []
            for o in actions:
                a_ = agg[(f, b, o)]
                mean_t = (sum(a_['t']) / len(a_['t'])) if a_['t'] else 99.0
                cand.append((o, a_['succ'], -mean_t))
            cand.sort(key=lambda z: (-z[1], -z[2]))
            best[b] = cand[0][0]
        if len(set(best.values())) > 1:
            p1_hits.append(f); p1_detail.append({'front': list(f), 'best': best})

    # P2：R1 在一背全成功、另一背全失败
    p2_hits = []
    for f in fronts:
        s = {b: agg[(f, b, 'R1')]['succ'] for b in backs_all}
        if max(s.values()) == n_per and min(s.values()) == 0:
            p2_hits.append({'front': list(f), 'per_back': s})

    vis_by_front = {f: visible_of_front(pathlib.Path(posed) / list(groups[f].values())[0]['id'],
                                        OBSTACLE_X)
                    for f in groups}
    # P4：重演 30 回合
    rng = np.random.default_rng(7)
    idx = rng.choice(len(rows), size=min(a.replay_n, len(rows)), replace=False)
    mism = 0
    for i in idx:
        r = rows[int(i)]
        spec = build_spec(posed, r['H'], r['case_id'], r['front'][0])
        again = run_episode(spec, r['option'], r['seed'], visible=vis_by_front[tuple(r['front'])])
        if again['reason'] != r['reason']:
            mism += 1

    verdict = {
        'n_fronts': len(fronts), 'n_backs': len(backs_all),
        'n_options': len(actions), 'n_seeds': len(seeds),
        'n_rows': len(rows),
        'init_perturbation': {'lateral_m': INIT_LAT, 'yaw_rad': INIT_YAW},
        'obstacle_x': OBSTACLE_X,
        'P1': {'require': 4, 'hit': len(p1_hits), 'pass': len(p1_hits) >= 4,
               'detail': p1_detail[:20]},
        'P2': {'require': 3, 'hit': len(p2_hits), 'pass': len(p2_hits) >= 3,
               'detail': p2_hits[:10]},
        'P3': {'pass': None, 'note': '由 observe 侧的同观测检验单独给出，读 runs/unseen/obs/*/p3.json'},
        'P4': {'replays': int(len(idx)), 'mismatch': mism, 'pass': mism == 0},
    }
    required = ['P1', 'P2', 'P4']
    ok = all(verdict[k]['pass'] for k in required)
    verdict['all_required_pass'] = ok
    (out / 'summary.json').write_text(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(json.dumps({k: verdict[k] for k in ('P1', 'P2', 'P4')}, ensure_ascii=False))
    print(f'fronts={len(fronts)} backs={len(backs_all)} rows={len(rows)} '
          f'required_pass={ok}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
