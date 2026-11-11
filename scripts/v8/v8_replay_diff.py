#!/usr/bin/env python3
"""量化"重放观测"与"原始观测"的差异：V8 复用判定的取证工具。

背景（2026-11-11）：`v8_lux.same_inputs` 要求两次拍到的观测与裁剪图 **逐字节相同**
才允许复用已有的 Lux3D 结果，否则退出码 11。这条规则防止"拿旧结果冒充"，但会让
换机器继续跑变得不可能：同一段物理在本机重跑后，第二眼的停车位姿与沙箱差
0.19 mm / 0.0085°，渲染出的像素就全变了。

本脚本不参与判定，只把差异量化出来并写成 JSON，便于在文档里引用具体数字：

    python3 scripts/v8/v8_replay_diff.py runs/v8/main/imagination/looks/look2

输出：`<look 目录>/REPLAY_DIFF.json`（存在 `<look>_replay` 时才写）。
字段：位姿差（m / deg）、RGB 平均绝对差与受影响像素数、深度差的中位数与分位数、
逐项 sha256 是否相同。
"""
import json
import pathlib
import sys

import numpy as np
from PIL import Image


def _pose(a, b):
    pa = a.get('local_frame') or {}
    pb = b.get('local_frame') or {}
    out = {}
    for k in ('x0', 'y0'):
        if k in pa and k in pb:
            out[f'd{k}_mm'] = round((pb[k] - pa[k]) * 1000.0, 4)
    if 'yaw0' in pa and 'yaw0' in pb:
        out['dyaw_deg'] = round(float(np.degrees(pb['yaw0'] - pa['yaw0'])), 6)
    return out


def _rgb(old, new):
    o = np.asarray(Image.open(old)).astype(np.int16)
    n = np.asarray(Image.open(new)).astype(np.int16)
    if o.shape != n.shape:
        return {'shape_mismatch': [list(o.shape), list(n.shape)]}
    d = np.abs(o - n)
    return {'mean_abs_diff': round(float(d.mean()), 4),
            'max_abs_diff': int(d.max()),
            'pixels_gt8': int((d.max(axis=2) > 8).sum()),
            'pixels': int(o.shape[0] * o.shape[1])}


def _depth(old, new):
    o = np.load(old)
    n = np.load(new)
    m = np.isfinite(o) & np.isfinite(n)
    if not m.any():
        return {'finite_common': 0}
    d = np.abs(o[m] - n[m]) * 1000.0
    return {'finite_common': int(m.sum()),
            'p50_mm': round(float(np.percentile(d, 50)), 4),
            'p90_mm': round(float(np.percentile(d, 90)), 3),
            'p99_mm': round(float(np.percentile(d, 99)), 2),
            'gt_1mm': int((d > 1).sum()), 'gt_50mm': int((d > 50).sum())}


def diff_look(look_dir):
    look = pathlib.Path(look_dir)
    rep = look.parent / f'{look.name}_replay'
    if not rep.exists():
        return None
    out = {'look': look.name, 'replay_dir': str(rep), 'targets': {}}
    for td in sorted(p for p in look.glob('T*') if p.is_dir()):
        rd = rep / td.name
        if not rd.exists():
            continue
        old = json.loads((td / 'state.json').read_text())
        new = json.loads((rd / 'state.json').read_text())
        e = {'pose_delta': _pose(old, new),
             'sha_equal': {'observation': old.get('observation_sha256') == new.get('observation_sha256'),
                           'crops': ({k: v['sha256'] for k, v in old.get('crops', {}).items()} ==
                                     {k: v['sha256'] for k, v in new.get('crops', {}).items()})}}
        for name in ('rgb.png', 'depth.npy', 'mask.png'):
            a, b = td / name, rd / name
            if not (a.exists() and b.exists()):
                continue
            e['rgb' if name == 'rgb.png' else ('depth' if name == 'depth.npy' else 'mask')] = (
                _rgb(a, b) if name.endswith('.png') and name != 'mask.png' else
                (_depth(a, b) if name == 'depth.npy' else
                 {'same': bool(np.array_equal(np.asarray(Image.open(a)), np.asarray(Image.open(b))))}))
        out['targets'][td.name] = e
    (look / 'REPLAY_DIFF.json').write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    got = None
    for d in argv[1:]:
        got = diff_look(d) or got
        print(f'{d}: 无 _replay 目录，跳过' if got is None else f'{d}: 已写 REPLAY_DIFF.json')
    if got is None:
        raise SystemExit('没有找到任何 <look>_replay 目录')
    print(json.dumps(got, indent=2, ensure_ascii=False)[:1500])


if __name__ == '__main__':
    main(sys.argv)
