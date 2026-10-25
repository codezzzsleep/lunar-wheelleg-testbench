"""
第 1 关 · 碰撞对照测试
证明：MuJoCo 对闭合网格按凸包碰撞（孔洞被盖上）；CoACD 拆凸块后孔洞真实存在。
"""
import trimesh, numpy as np, mujoco, coacd, time, json, sys, pathlib

BALL_R = 0.02

def build(mesh_parts, label):
    """mesh_parts: list of trimesh.Trimesh; first is the visual, all take part in collision."""
    assets, geoms = [], []
    for i, part in enumerate(mesh_parts):
        f = f'/tmp/part_{label}_{i}.stl'
        part.export(f)
        assets.append(f'<mesh name="p{i}" file="{f}"/>')
        geoms.append(f'<geom type="mesh" mesh="p{i}" mass="0.1" rgba=".7 .6 .5 1"/>')
    XML = f"""
    <mujoco>
      <option gravity="0 0 -1.62" timestep="0.002"/>
      <worldbody>
        <geom type="plane" size="3 3 .1" rgba=".2 .2 .25 1"/>
        <body pos="0 0 0.30">{''.join(geoms)}</body>
        <body pos="0 0 0.70"><freejoint/><geom type="sphere" size="{BALL_R}" mass=".05" rgba="1 .5 .2 1"/></body>
      </worldbody>
      <asset>{''.join(assets)}</asset>
    </mujoco>"""
    return XML

def drop(xml, steps=2500):
    mod = mujoco.MjModel.from_xml_string(xml); d = mujoco.MjData(mod)
    mujoco.mj_forward(mod, d)
    for _ in range(steps): mujoco.mj_step(mod, d)
    return float(d.qpos[2])

def coacd_parts(mesh, threshold=0.05):
    m = coacd.Mesh(mesh.vertices, mesh.faces)
    t0 = time.time()
    parts = coacd.run_coacd(m, threshold=threshold, max_convex_hull=32)
    dt = time.time() - t0
    out = [trimesh.Trimesh(np.asarray(v), np.asarray(f)) for v, f in parts]
    return out, dt

torus = trimesh.creation.torus(major_radius=0.15, minor_radius=0.035, major_segments=64, minor_segments=24)
print(f'torus: {len(torus.faces)} faces, watertight={torus.is_watertight}, hole r≈0.115 m')

raw_z = drop(build([torus], 'raw'))
print(f'  RAW mesh      -> ball rests at z={raw_z:.3f}   {"BLOCKED (convex hull)" if raw_z > 0.25 else "passed"}')

parts, dt = coacd_parts(torus)
print(f'  CoACD         -> {len(parts)} convex parts in {dt:.1f}s')
dec_z = drop(build(parts, 'dec'))
print(f'  DECOMPOSED    -> ball rests at z={dec_z:.3f}   {"BLOCKED" if dec_z > 0.25 else "PASSED THROUGH THE HOLE"}')

result = {
    'torus_faces': int(len(torus.faces)),
    'raw_final_z': round(raw_z, 4),
    'coacd_parts': len(parts),
    'coacd_seconds': round(dt, 2),
    'decomposed_final_z': round(dec_z, 4),
    'raw_blocked': raw_z > 0.25,
    'decomposed_passes': dec_z < 0.25,
    'gate2_pass': (raw_z > 0.25) and (dec_z < 0.25),
}
print(json.dumps(result, indent=2))
print('GATE-1 ITEM 2:', 'PASS' if result['gate2_pass'] else 'FAIL')
pathlib.Path('runs').mkdir(exist_ok=True)
pathlib.Path('runs/gate1_collision.json').write_text(json.dumps(result, indent=2))
raise SystemExit(0 if result['gate2_pass'] else 1)
