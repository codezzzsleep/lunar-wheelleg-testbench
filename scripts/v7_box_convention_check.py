"""验证 box 索引的闭区间约定：单格资产加载后必须正好 1 cm 宽。"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import numpy as np, mujoco
import v7_common_matrix as MX

def load_extent(asset_dir):
    env = MX.build_env({'config_id': 'chk', 'case_config': 'cases/unseen_v1/R02.json',
                        'mesh': 'runs/unseen/delivery_v7/v7_20261030_r1/scan_assets/R02_s0.9/body.stl',
                        'budget_s': 30.0, 'truth_collision': None},
                       'nominal', collision_dir=asset_dir)
    import mujoco as _mj
    geom = []
    for g in range(env.model.ngeom):
        b = _mj.mj_id2name(env.model, _mj.mjtObj.mjOBJ_BODY, env.model.geom_bodyid[g]) or ''
        if b.startswith('obstacle') and env.model.geom_type[g] == _mj.mjtGeom.mjGEOM_BOX:
            geom.append(g)
    if not geom:
        raise SystemExit(f'没有加载到障碍 box geom（body 名：{[_mj.mj_id2name(env.model, _mj.mjtObj.mjOBJ_BODY, i) for i in range(env.model.nbody)][-3:]}）')
    out = []
    for g in geom:
        out.append((env.model.geom_pos[g].tolist(), env.model.geom_size[g].tolist()))
    return out

if __name__ == '__main__':
    out = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1/box_convention_check'
    out.mkdir(parents=True, exist_ok=True)
    cell = 0.01
    origin = [1.03, -1.20, 0.0]
    boxes = [[0, 0, 0, 0, 0, 14]]     # 单格，高 15 cm
    man = {'schema': 'asset-manifest/v1', 'asset_id': 'chk', 'hypothesis_id': 'chk',
           'version': 'elev25d/v1', 'coordinate_frame': 'world', 'source_kind': 'elevation',
           'boxes': boxes, 'pitch_m': cell, 'grid_origin': origin, 'grid_dims': [1, 1],
           'n_boxes': 1, 'parts': [], 'T_world_from_asset': [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
           'body_pose_expected': {'pos': [0,0,0], 'quat': [1,0,0,0]}, 'rest_pose': False, 'pass': True}
    d = out / 'single_cell'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'manifest.json').write_text(json.dumps(man))
    got = load_extent(str(d))
    pos, size = got[0]
    xmin, xmax = pos[0] - size[0], pos[0] + size[0]
    ymin, ymax = pos[1] - size[1], pos[1] + size[1]
    zmin, zmax = pos[2] - size[2], pos[2] + size[2]
    rec = {'schema': 'box-convention-check/v1', 'cell_m': cell, 'origin': origin,
           'index_box': boxes[0], 'loaded': {'pos': pos, 'size': size},
           'world_x': [round(xmin, 6), round(xmax, 6)],
           'world_y': [round(ymin, 6), round(ymax, 6)],
           'world_z': [round(zmin, 6), round(zmax, 6)],
           'width_x_m': round(xmax - xmin, 6), 'width_y_m': round(ymax - ymin, 6),
           'height_m': round(zmax - zmin, 6),
           'expected': {'width_x_m': cell, 'width_y_m': cell, 'height_m': 15 * cell},
           'pass': (abs((xmax - xmin) - cell) < 1e-9 and abs((ymax - ymin) - cell) < 1e-9
                    and abs((zmax - zmin) - 15 * cell) < 1e-9)}
    (out / 'check.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: rec[k] for k in ('loaded', 'width_x_m', 'width_y_m', 'height_m', 'pass')},
                     ensure_ascii=False))
