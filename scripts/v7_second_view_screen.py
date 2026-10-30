"""
V7 §8.1：用**第二观察**筛选已有候选（固定候选几何与世界位姿，不做重新配准）。

规则（任务书要求）：
  · 候选几何与世界位姿冻结；第二相机只是"再看一眼"，不允许为迎合新观测而重新配准；
  · 每个候选分别报告在两个视角下的指标，**不合并**成一个数字；
  · 同一张表里写清：父候选身份、融合输入观测、融合资产身份、被评价视角、指标版本、资格结果。

  .venv/bin/python scripts/v7_second_view_screen.py --batch <batch> \
      --obs1 <front obs> --obs2 <driven obs> --hypotheses <json> --out <json>
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import align
import trimesh


def sha(p):
    import hashlib
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--obs1', required=True)
    ap.add_argument('--obs2', required=True)
    ap.add_argument('--hypotheses', required=True, help='[{id, world, fusion_obs, ...}]')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    hyps = json.loads(pathlib.Path(a.hypotheses).read_text())
    rows = []
    for h in hyps:
        wd = ROOT / h['world']
        mesh = trimesh.load(str(wd / 'body.stl'), force='mesh', process=False)
        r = {'candidate': h['id'], 'world': h['world'],
             'world_sha': sha(wd / 'body.stl'),
             'fusion_input_observation': h.get('fusion_obs'),
             'metric_version': 'align-metric/v2.1'}
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='v7screen_')) / 'cand.stl'
        mesh.export(tmp)
        for tag, obs in (('obs1_front', a.obs1), ('obs2_driven', a.obs2)):
            try:
                # 必须显式计算可见点 P95；缺测一律 not_evaluated，不能用默认大误差代替
                ev = align.render_eval(mesh, ROOT / obs, tmpdir=tmp, want_vis_pt=True)
                r[tag] = {k: ev.get(k) for k in ('mask_iou', 'vis_pt_med_mm',
                                                 'vis_pt_p95_mm', 'freespace_violation',
                                                 'freespace_n_px', 'freespace_denom_px',
                                                 'depth_p95_mm')}
                r[tag]['observation'] = obs
                r[tag]['metric_version'] = ev.get('metric_version')
                r[tag]['measurement_status'] = 'measured'
                if ev.get('freespace_violation') is None or ev.get('vis_pt_p95_mm') is None:
                    r[tag]['measurement_status'] = 'not_evaluated'
            except Exception as e:
                r[tag] = {'error': f'{type(e).__name__}: {e}',
                          'measurement_status': 'not_evaluated'}
        o1, o2 = r['obs1_front'], r['obs2_driven']

        def _verdict(v):
            # 缺测 = not_evaluated（不是 rejected）；零误差是合法值，不能被 `or` 吃掉
            if v.get('measurement_status') != 'measured':
                return 'not_evaluated'
            iou = v.get('mask_iou'); p95 = v.get('vis_pt_p95_mm'); free = v.get('freespace_violation')
            if iou is None or p95 is None or free is None:
                return 'not_evaluated'
            ok = (float(iou) >= 0.90 and float(p95) <= 5.0 and float(free) <= 0.05)
            return 'kept' if ok else 'rejected'

        r['verdict_first_view'] = _verdict(o1)
        r['verdict_second_view'] = _verdict(o2)
        # 第一视角已不合格 -> 只能进诊断池；第二视角好不能抵消第一视角冲突
        if r['verdict_first_view'] == 'rejected':
            r['verdict_final'] = 'rejected(first_view)'
        elif r['verdict_second_view'] == 'not_evaluated' or r['verdict_first_view'] == 'not_evaluated':
            r['verdict_final'] = 'not_evaluated'
        elif r['verdict_second_view'] == 'rejected':
            r['verdict_final'] = 'rejected(second_view)'
        else:
            r['verdict_final'] = 'kept'
        r['kept_by_second_view'] = (r['verdict_final'] == 'kept')
        r['note'] = ('固定候选几何与位姿，只用第二相机评价；未重新配准。'
                     '两个视角的指标分开报告，不合并。')
        rows.append(r)
        print(json.dumps({'candidate': h['id'],
                          'obs1_iou': (o1 or {}).get('mask_iou'),
                          'obs2_iou': (o2 or {}).get('mask_iou'),
                          'obs2_p95': (o2 or {}).get('vis_pt_p95_mm'),
                          'obs2_free': (o2 or {}).get('freespace_violation'),
                          'verdict': r['verdict_final']}, ensure_ascii=False))
    out = {'schema': 'second-view-screen/v7', 'obs1': a.obs1, 'obs2': a.obs2,
           'rule': 'fixed geometry/pose; second camera only; no re-registration',
           'rows': rows}
    p = ROOT / a.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
