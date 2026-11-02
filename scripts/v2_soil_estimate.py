"""v2 共享土壤估计：低速激励 → 有效牵引 mu 与等效阻力 b 的区间。

模型（简化，不反演全部 Bekker 参数）：
    m * a  =  mu * N  -  b * v
N 为声明为**模拟传感器**的轮载合计（四轮接触力竖直分量），
v、a 来自机体速度与差分，转矩来自执行器输出。

只使用接近段（平地、低速、未越障），并记录激励幅度。
识别不足时保留不确定性：区间取拟合值的 ± 置信半宽，下限截断到 0。

  python scripts/v2_soil_estimate.py --out <json> [--seeds 7,11,13]
"""
import argparse, json, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import v7_soil, wheelleg_env, terrain

def build(soil_label, seed):
    case = json.loads((ROOT/'cases/unseen_v1/R02.json').read_text())
    spec = terrain.make_spec(kind='flat', seed=0, objects=[], goal_x=case['goal_x'], name='soil_est')
    spec['channel'] = {'center_y': 0.0, 'half_width': case.get('channel_half', 1.2)}
    spec['init_perturbation'] = {'lateral_m': 0.0, 'yaw_rad': 0.0}
    spec['skill_cfg'] = {'task': 'M'}
    spec['front_cam'] = {'pos': [0.42, 0.0, 0.0], 'pitch_deg': 0.0, 'fovy': 70.0}
    spec['objects'] = []
    r = v7_soil.resolve(soil_label)
    spec['soil'] = ({'mode':'rigid','label':soil_label} if r.get('mode')=='rigid'
                    else {'mode':'soil','label':r.get('label'),'params':r['params']})
    env = wheelleg_env.WheelLegEnv(spec, max_seconds=30.0)
    env.reset(seed=seed)
    return env

def wheel_load(env):
    """模拟轮载传感器：四轮接触竖直力之和。"""
    d = env.data; total = 0.0
    for c in range(d.ncon):
        con = d.contact[c]
        f = np.zeros(6); import mujoco
        mujoco.mj_contactForce(env.model, d, c, f)
        total += abs(float(f[0]))
    return total            # N：接触法向力合计（不再除以 g）

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--seeds', default='7,11,13')
    ap.add_argument('--excite', default='0.06,0.12,0.18')
    ap.add_argument('--mass', type=float, default=12.0)
    a = ap.parse_args()
    rows = []
    for seed in [int(s) for s in a.seeds.split(',')]:
        for vcmd in [float(x) for x in a.excite.split(',')]:
            env = build('nominal', seed)
            v_prev = float(env.data.qvel[0]); t_prev = float(env.t); a_prev = 0.0
            for k in range(120):
                env.step_drive(vcmd, 0.0)
                if k % 3: continue
                v = float(env.data.qvel[0]); t = float(env.t)
                dt = max(1e-6, t - t_prev)
                acc = (v - v_prev)/dt
                N = wheel_load(env)
                # 实际驱动力由驱动转矩与轮半径换算，不用"最大可提供牵引力"
                tau = float(np.sum(np.abs(env.data.actuator_force)))
                r_w = 0.08595
                F_drive = tau / r_w
                rows.append({'seed': seed, 'v_cmd': vcmd, 't': t, 'v': v, 'a': acc, 'N': N,
                             'F_drive': F_drive,
                             'x': float(env.data.qpos[0])})
                v_prev, t_prev = v, t
    arr = {k: np.array([r[k] for r in rows]) for k in ('v','a','N','x','F_drive')}
    good = (arr['v'] > 0.02) & (arr['N'] > 1.0) & (np.abs(arr['a']) < 20)
    # 动力学：m*a = F_drive - b*v  （驱动力来自转矩，不再把 N 当驱动力）
    X = np.stack([np.ones_like(arr['v'][good]), -arr['v'][good]], axis=1)
    y = a.mass * arr['a'][good] - arr['F_drive'][good]
    from scipy.optimize import lsq_linear
    # 物理约束：mu>=0，b>=0（负阻力无意义，直接有界最小二乘）
    sol = lsq_linear(X, y, bounds=([0.0, 0.0], [3.0, 200.0]))
    coef = sol.x
    mu, b = float(coef[0]), float(coef[1])
    pred = X @ coef
    resid = y - pred
    sd = float(np.std(resid)) if len(resid) else 0.0
    # 置信半宽：残差标准差传递到系数（简化对角近似）
    XtX_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.diag(XtX_inv)) * sd
    rec = {'schema':'v2-soil-estimate/v1',
           'model':'m*a = F_drive - b*v（F_drive 由驱动转矩/轮半径换算）',
           'samples': int(good.sum()), 'seeds': a.seeds, 'excite': a.excite,
           'mu_hat': round(mu, 4), 'mu_se': round(float(se[0]), 4),
           'b_hat': round(b, 4), 'b_se': round(float(se[1]), 4),
           'mu_interval': [round(max(0.0, mu-2*se[0]), 4), round(mu+2*se[0], 4)],
           'b_interval': [round(max(0.0, b-2*se[1]), 4), round(b+2*se[1], 4)],
           'resid_sd': round(sd, 4),
           'note': '轮载为声明为模拟传感器的接触力合计；未激励到牵引极限，区间只作局部稳健规划依据'}
    p = ROOT/a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: rec[k] for k in ('samples','mu_hat','mu_interval','b_hat','b_interval')},
                     ensure_ascii=False))

if __name__ == '__main__':
    main()
