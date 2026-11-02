"""v2 八行主表聚合：只读结果文件，不做仿真。

每状态：B1_height / B2_F / B3_F / E25D_block / E25D_fill / Lux3D_first /
Lux3D_multi / U_truth。Lux3D 行同时带 strict.pass、kept_ratio、
generation_ablation_outcome；B3_F 行标 comparison_label=mirror_completion。

  python scripts/v2_main_table.py --states plans/v2_main_states.json \
      --root runs/.../v3batch --out runs/.../v3table
"""
import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROWS = ['B1_height', 'B2_F', 'B3_F', 'E25D_block', 'E25D_fill',
        'Lux3D_first', 'Lux3D_multi', 'U_truth']


def load_json(p):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.is_file() else None


def outcome_of(row, truth_pass):
    if not row:
        return 'missing'
    if row.get('status') in ('asset_missing', 'error', 'ablation_missing'):
        return row['status']
    if row.get('success'):
        return 'pass'
    chosen = row.get('chosen')
    if chosen in (None, 'A0'):
        return 'over_conservative' if truth_pass else 'safe_stop_no_reference'
    return 'wrong_safe_prediction' if truth_pass else 'task_failure'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--states', required=True)
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    states = json.loads((ROOT / a.states).read_text())['selected']
    root = ROOT / a.root
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    table = {'schema': 'v2-main-table/v1', 'states': {}, 'counts': {}}
    md = ['# v2 八行主表', '',
          '| 状态 | 行 | 决策 | 结局 | 类别 | strict.pass | kept_ratio | '
          '生成贡献消融 | 备注 |',
          '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    counts = {r: {} for r in ROWS}
    for st in states:
        key = st.replace('|', '_')
        nd = root / key
        nonlux = load_json(nd / 'nonlux.json') or {}
        multi = load_json(nd / 'multi.json') or {}
        nrows = nonlux.get('rows') or {}
        mrows = multi.get('rows') or {}
        vq = multi.get('visible_quality') or {}
        truth = nrows.get('U_truth') or {}
        truth_pass = bool(truth.get('success'))
        rows = {}
        for fam in ROWS:
            if fam == 'Lux3D_first':
                src = mrows.get('first')
                ab = mrows.get('first_ablation')
                tag = 'A1'
            elif fam == 'Lux3D_multi':
                src = mrows.get('multi')
                ab = mrows.get('multi_ablation')
                tag = None
            elif fam == 'B3_F':
                src = nrows.get('B3_F')
                ab = None
                tag = None
            else:
                src = nrows.get(fam)
                ab = None
                tag = None
            if src is None:
                rows[fam] = {'status': 'missing'}
                counts[fam]['missing'] = counts[fam].get('missing', 0) + 1
                continue
            rec = dict(src)
            rec['outcome_class'] = outcome_of(src, truth_pass)
            rec['comparison_label'] = ('mirror_completion' if fam == 'B3_F'
                                       else ('lux3d' if fam.startswith('Lux3D') else fam))
            if fam.startswith('Lux3D'):
                q = vq.get(tag) if tag else None
                if q:
                    rec.update({'strict_pass': q.get('fused_strict_pass'),
                                'mask_iou': q.get('fused_mask_iou'),
                                'vis_p95_mm': q.get('fused_vis_p95_mm'),
                                'kept_ratio': q.get('kept_ratio'),
                                'kept_voxels': q.get('kept_voxels'),
                                'shell_voxels': q.get('shell_voxels')})
                if ab:
                    rec['generation_ablation_outcome'] = outcome_of(ab, truth_pass)
                    rec['generation_ablation_chosen'] = ab.get('chosen')
                    rec['generation_ablation_success'] = ab.get('success')
                else:
                    rec['generation_ablation_outcome'] = 'not_run'
            rows[fam] = rec
            c = counts[fam]
            c[rec['outcome_class']] = c.get(rec['outcome_class'], 0) + 1
            note = ''
            if fam == 'B3_F':
                note = '镜像补全（非壳层对照、非生成消融）'
            if fam.startswith('Lux3D'):
                note = ('strict=%s kept=%s abl=%s' % (
                    rec.get('strict_pass'), rec.get('kept_ratio'),
                    rec.get('generation_ablation_outcome')))
            md.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                st, fam, rec.get('chosen'), rec.get('success'),
                rec['outcome_class'], rec.get('strict_pass', ''),
                rec.get('kept_ratio', ''), rec.get('generation_ablation_outcome', ''),
                note))
        table['states'][st] = {'truth_pass': truth_pass, 'truth_chosen': truth.get('chosen'),
                               'rows': rows}
    table['counts'] = counts
    (out / 'main_table.json').write_text(json.dumps(table, ensure_ascii=False, indent=2))
    (out / 'main_table.md').write_text('\n'.join(md) + '\n')
    print(json.dumps({'states': len(states), 'counts': counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()
