"""生产入口自检：build_collision 缓存身份（缺源/参数变/内容变/同身份）。

  python scripts/v3_selftest_collision.py

断言：
  1. 同身份重复调用 -> cached=True，且 cache_key 相同；
  2. downsample 变 -> 必须重建（cached=False），cache_key 变；
  3. 源占据内容变（改一个体素）-> 必须重建，cache_key 变；
  4. manifest 存在但源头文件缺失/被删 -> 不得返回 cached=True；
  5. 盒文件数量与 manifest 不一致 -> 不得返回 cached=True。
退出码 0 表示全部通过。
"""
import json
import pathlib
import shutil
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core


def make_occ(path, n=24, pitch=0.002, seed=0):
    import hashlib
    rng = np.random.default_rng(seed)
    occ = np.zeros((n, n, n), bool)
    occ[4:14, 6:16, 2:8] = True
    if seed:
        occ[2:5, 2:5, 2:5] = True
    np.savez_compressed(path, occupied=occ,
                        origin=np.array([0.0, 0.0, 0.0]),
                        pitch=np.float64(pitch), dims=np.array([n, n, n]),
                        content_sha=np.array(hashlib.sha256(
                            np.ascontiguousarray(occ).tobytes()).hexdigest()),
                        convention=np.array('voxel_center = origin + (index+0.5)*pitch'))
    return path


def main():
    tmp = ROOT / 'runs/v3/selftest_collision'
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    occ = make_occ(tmp / 'occ_a.npz')
    out = tmp / 'coll'
    checks = []

    r1 = v3_core.build_collision(occ, out, pitch=0.002, downsample=2)
    ok1 = r1.get('ok') and not r1.get('cached')
    checks.append(('first_build_not_cached', ok1, r1.get('n_boxes')))

    r2 = v3_core.build_collision(occ, out, pitch=0.002, downsample=2)
    ok2 = r2.get('ok') and r2.get('cached') and r2.get('cache_key') == r1.get('cache_key')
    checks.append(('same_identity_cached', ok2, r2.get('cached')))

    r3 = v3_core.build_collision(occ, out, pitch=0.002, downsample=1)
    ok3 = r3.get('ok') and not r3.get('cached') and r3.get('cache_key') != r1.get('cache_key')
    checks.append(('param_change_invalidates', ok3, r3.get('cache_rebuilt_reason')))

    # 内容变：同一路径写不同内容
    occ2 = tmp / 'occ_b.npz'
    make_occ(occ2, seed=1)
    shutil.copy2(occ2, occ)
    r4 = v3_core.build_collision(occ, out, pitch=0.002, downsample=1)
    ok4 = r4.get('ok') and not r4.get('cached')
    checks.append(('content_change_invalidates', ok4, r4.get('cache_rebuilt_reason')))

    # 缺源：删掉源文件后不得命中缓存
    occ.unlink()
    try:
        r5 = v3_core.build_collision(occ, out, pitch=0.002, downsample=1)
        ok5 = (not r5.get('ok')) and (not r5.get('cached'))
        detail = r5.get('error') or r5.get('status')
    except Exception as e:  # noqa: BLE001
        ok5 = True
        detail = f'raised {type(e).__name__}'
    checks.append(('missing_source_no_cache', ok5, detail))

    # 盒文件被删：不得命中缓存
    make_occ(occ, seed=2)
    r6 = v3_core.build_collision(occ, out, pitch=0.002, downsample=1)
    parts = sorted((out / 'parts').glob('box_*.stl'))
    if parts:
        parts[0].unlink()
    r7 = v3_core.build_collision(occ, out, pitch=0.002, downsample=1)
    ok7 = r7.get('ok') and not r7.get('cached')
    checks.append(('missing_part_no_cache', ok7, r7.get('cache_rebuilt_reason')))

    rows = [{'check': c, 'ok': bool(o), 'detail': str(d)[:120]} for c, o, d in checks]
    all_ok = all(r['ok'] for r in rows)
    (tmp / 'result.json').write_text(json.dumps(
        {'schema': 'v3-collision-selftest/v1', 'all_ok': all_ok, 'rows': rows},
        ensure_ascii=False, indent=2))
    print(json.dumps({'all_ok': all_ok, 'rows': rows}, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
