"""渲染-比对配准：复用 align.render_eval，在 yaw×scale 网格上最大化掩码 IoU。"""
import argparse, json, pathlib, sys
import numpy as np, trimesh
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
import align as A

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs', required=True); ap.add_argument('--cands', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--accept-iou', type=float, default=0.85)
    ap.add_argument('--max-cands', type=int, default=6)
    a = ap.parse_args()
    obs = ROOT/a.obs
    rows = []
    for d in sorted((ROOT/a.cands).glob('*/parent/body.stl'))[:a.max_cands]:
        m = trimesh.load(d, force='mesh', process=False)
        m.apply_translation(-m.bounds.mean(0))
        # 前沿对齐：把网格最小 x 对环境观测前沿，避免整体偏移
        vis = json.loads((obs/'observation.json').read_text())['visible']
        # 先把原始网格缩放到观测高度，再在其附近搜索（此前漏了这一步，导致尺度网格严重偏离）
        h = float(m.bounds[1][2]-m.bounds[0][2])
        if h > 1e-6:
            m.apply_scale(float(vis['H_vis'])/h)
        best = None
        for yaw in range(-180, 180, 30):
            for sc in (0.92, 0.96, 1.0, 1.04, 1.08):
                for dx in (-0.10, -0.05, 0.0, 0.05, 0.10):
                    M = np.eye(4)
                    c, s = np.cos(np.deg2rad(yaw)), np.sin(np.deg2rad(yaw))
                    M[:3,:3] = np.array([[c,-s,0],[s,c,0],[0,0,1]]) * sc
                    front = float(m.bounds[0][0] * sc)
                    M[:3,3] = [float(vis['x_front']) - front + dx, vis['y_center'], 0.0]
                    mw = A.apply_T(m, M)
                    tmp = ROOT/'/tmp/v2reg'/'m.stl'; tmp.parent.mkdir(parents=True, exist_ok=True)
                    mw.export(tmp)
                    try:
                        r = A.render_eval(mw, obs, tmpdir=str(tmp), W=None, H=None,
                                          want_vis_pt=False)
                    except Exception as e:
                        continue
                    iou = float(r.get('mask_iou') or 0)
                    if best is None or iou > best[0]:
                        best = (iou, r.get('freespace_violation'), yaw, sc, dx)
        name = d.parent.parent.name
        iou = best[0] if best else 0.0
        rec = {'candidate': name, 'mask_iou': round(iou,4),
               'freespace': round(float(best[1] or 0),4) if best else None,
               'yaw_deg': best[2] if best else None, 'scale': best[3] if best else None,
               'dx': best[4] if best else None,
               'accepted': bool(iou >= a.accept_iou),
               'status': 'ok' if iou >= a.accept_iou else 'registration_failed'}
        rows.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
    p = ROOT/a.out; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'schema':'v2-register/v4','accept_iou':a.accept_iou,'rows':rows},
                            ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
