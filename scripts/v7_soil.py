"""
V7-R1 §10：月壤配置解析器 + 判别验证。

三个配置必须是**真正不同的物理参数**，不是只换名字：

| 参数 | nominal | low_traction | high_drag |
|---|---:|---:|---:|
| n | 1.0 | 1.0 | 1.0 |
| kc | 1400 | 1400 | 700 |
| kphi | 820000 | 820000 | 410000 |
| cohesion_pa | 170 | 100 | 170 |
| phi_deg | 35 | 30 | 35 |
| k_shear_m | 0.018 | 0.018 | 0.018 |

判别（同轮载、同轮宽）：
  · low_traction 的牵引上限 H_cap 必须 < nominal；
  · high_drag 的压实阻力 Rc 必须 > nominal。

  .venv/bin/python scripts/v7_soil.py --out runs/.../soil/params.json
"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import soil as SOIL

CONFIGS = {
    'nominal': dict(n=1.0, kc=1400.0, kphi=820000.0, cohesion_pa=170.0,
                    phi_deg=35.0, k_shear=0.018),
    'low_traction': dict(n=1.0, kc=1400.0, kphi=820000.0, cohesion_pa=100.0,
                         phi_deg=30.0, k_shear=0.018),
    'high_drag': dict(n=1.0, kc=700.0, kphi=410000.0, cohesion_pa=170.0,
                      phi_deg=35.0, k_shear=0.018),
}
NOTE = ('纲领范围内的实验配置（同轮载同轮宽扫描），不是实测月壤统计分布；'
        'n 固定为 1，kc/kphi 单位分别为 N/m²、N/m³。')


def resolve(mode):
    """mode -> {'mode','params','params_sha'}；rigid 不调用土壤力。"""
    if mode == 'rigid':
        return {'mode': 'rigid', 'params': None, 'params_sha': None}
    if mode not in CONFIGS:
        raise SystemExit(f'未知土壤配置 {mode}（可用：rigid, {", ".join(CONFIGS)}）')
    p = CONFIGS[mode]
    sha = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:32]
    return {'mode': 'soil', 'label': mode, 'params': p, 'params_sha': sha}


def specimen(load_n=120.0, width_m=0.045, radius_m=0.08595, contact_area_m2=0.0012):
    """判别量：同轮载、同轮宽下的牵引上限 H_cap 与压实阻力 Rc。

    Rc 必须先用**同一**下陷 z 计算，否则比较的是不同工况。这里两种方式都报：
      · 各自按自己参数求下陷后的 Rc（真实工况）
      · 固定同一 z=5 mm 的 Rc（只看参数本身）
    """
    out = {}
    for name in CONFIGS:
        sp = SOIL.SoilParams(**CONFIGS[name])
        h = float(sp.traction_limit(load_n, contact_area_m2))
        z = float(sp.sinkage(load_n, width_m, wheel_radius_m=radius_m))
        rc = float(sp.compaction_resistance(z, width_m))
        rc_fixed = float(sp.compaction_resistance(0.005, width_m))
        out[name] = {'H_cap_n': round(h, 3), 'sinkage_mm': round(z * 1000, 4),
                     'Rc_n_at_own_z': round(rc, 4),
                     'Rc_n_at_5mm': round(rc_fixed, 4),
                     'params_sha': resolve(name)['params_sha']}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    rep = {'schema': 'soil-config/v7', 'note': NOTE,
           'configs': {k: {**v, 'params_sha': resolve(k)['params_sha']} for k, v in CONFIGS.items()},
           'discrimination': specimen()}
    d = rep['discrimination']
    try:
        nominal_h = d['nominal']['H_cap_n']
        rep['checks'] = {
            'low_traction_H_lower': d['low_traction']['H_cap_n'] < nominal_h,
            'high_drag_Rc_higher_at_own_z': d['high_drag']['Rc_n_at_own_z'] > d['nominal']['Rc_n_at_own_z'],
            'high_drag_Rc_higher_at_same_z': d['high_drag']['Rc_n_at_5mm'] > d['nominal']['Rc_n_at_5mm'],
            'params_hashes_distinct': len({v['params_sha'] for v in d.values()}) == len(d),
        }
    except Exception as e:
        rep['checks'] = {'error': f'{type(e).__name__}: {e}'}
    # 判据用"真实工况"（各自下陷后的 Rc）；固定同一 z 的对照只作说明，
    # 因为它剥离了下陷效应，反而会得到相反结论（更软→同 z 阻力更低）
    required = ['low_traction_H_lower', 'high_drag_Rc_higher_at_own_z',
                'params_hashes_distinct']
    rep['all_pass'] = (all(rep['checks'].get(k) for k in required)
                       if 'error' not in rep['checks'] else False)
    rep['required_checks'] = required
    rep['informational'] = {'high_drag_Rc_higher_at_same_z':
                            rep['checks'].get('high_drag_Rc_higher_at_same_z'),
                            'note': ('same-z 对照会得到相反结论：更软的参数在固定下陷下阻力更低；'
                                     '真实工况是"更软→更深下陷→更高压实阻力"，判据取真实工况。')}
    if a.out:
        p = ROOT / a.out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({'discrimination': d, 'checks': rep['checks'],
                      'all_pass': rep['all_pass']}, ensure_ascii=False, indent=1))
    return 0 if rep['all_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
