"""把 R03 两视角案例打成最小可复现演示包（任务书 §三）。

只放"不能靠仓库重建"的输入 + 验收证据；box STL 不复制，从 occ.npz 重建。

  .venv/bin/python scripts/v7_make_demo_pack.py --out demo/r1_r03_two_view
"""
import argparse, hashlib, json, pathlib, shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
B = ROOT / 'runs/unseen/delivery_v7/v7_20261030_r1'


def sha(p):
    h = hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='demo/r1_r03_two_view')
    a = ap.parse_args()
    out = ROOT / a.out
    if out.exists():
        shutil.rmtree(out)
    (out / 'inputs').mkdir(parents=True)

    items = []

    def put(src, dst, note):
        src = ROOT / src
        if not src.exists():
            items.append({'path': str(dst), 'status': 'missing', 'source': str(src)})
            return
        target = out / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target)
            n = sum(1 for _ in target.rglob('*') if _.is_file())
            items.append({'path': str(dst), 'kind': 'dir', 'n_files': n,
                          'sha256_tree': sha_dir(target), 'note': note})
        else:
            shutil.copy2(src, target)
            items.append({'path': str(dst), 'kind': 'file', 'bytes': target.stat().st_size,
                          'sha256': sha(target), 'note': note})

    put('cases/unseen_v1/R03.json', 'inputs/case.json', '案例描述（对象、位置、可见量来源）')
    put('runs/unseen/recovery_r3/obs_R03', 'inputs/obs_first', '第一视角观测包')
    put(f'{B.relative_to(ROOT)}/observation/obs_R03_at_driven', 'inputs/obs_second', '真实行驶后第二视角观测')
    put('runs/unseen/delivery_v7/v7_20261030/candidates/V7_R03_s1/world/align/body.stl',
        'inputs/parent/body.stl', 'Lux3D 父候选网格')
    put('configs/unseen_v7_r1_fusion_offset1.json', 'inputs/config_fusion.json', '有效融合配置')
    put(f'{B.relative_to(ROOT)}/fusion_diagnostics/tvocc_R03_s1_v3/occ.npz',
        'inputs/occ_two_view.npz', '两视角占据实体（坐标约定写在文件内）')
    put(f'{B.relative_to(ROOT)}/fusion_diagnostics/tvocc_R03_s1_v3/collision/manifest.json',
        'inputs/collision_manifest.json', '碰撞构建清单（box 定义，STL 可重建）')
    put(f'{B.relative_to(ROOT)}/fusion_diagnostics/tvocc_R03_s1_v3/visible_two_view.json',
        'acceptance/visible.json', '可见双视角验收')
    put(f'{B.relative_to(ROOT)}/fusion_diagnostics/tvocc_R03_s1_v3/collision/metrics_occ.json',
        'acceptance/collision.json', '碰撞保真验收')
    for f in ('matrix.jsonl', 'decisions.json', 'decision_events.jsonl', 'closed_loop.json'):
        put(f'{B.relative_to(ROOT)}/evaluation/cl_v3_three_soils/{f}', f'closed_loop/{f}',
            '闭环原始证据')

    man = {'schema': 'demo-pack/v1', 'name': a.out.split('/')[-1],
           'case': 'R03 two-view update', 'code_head': None,
           'rebuild_steps': [
               'python scripts/v7_rebuild_from_occ.py --occ inputs/occ_two_view.npz --out rebuilt',
               'python scripts/collision_box_union.py --occupancy inputs/occ_two_view.npz '
               '--out rebuilt/collision --pitch 0.0025 --hypothesis-id demo',
               'python scripts/collision_occupancy_metrics.py --mesh rebuilt/body.stl '
               '--collision rebuilt/collision --out rebuilt/collision/metrics.json --parity full'],
           'items': items}
    import subprocess
    try:
        man['code_head'] = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                                          capture_output=True, text=True).stdout.strip()
    except Exception:
        pass
    (out / 'MANIFEST.json').write_text(json.dumps(man, ensure_ascii=False, indent=2))
    print(json.dumps({'out': a.out, 'n_items': len(items),
                      'missing': [i['path'] for i in items if i.get('status') == 'missing'],
                      'bytes': sum(i.get('bytes', 0) for i in items)}, ensure_ascii=False))


def sha_dir(d):
    h = hashlib.sha256()
    for f in sorted(pathlib.Path(d).rglob('*')):
        if f.is_file():
            h.update(str(f.relative_to(d)).encode())
            h.update(sha(f).encode())
    return h.hexdigest()


if __name__ == '__main__':
    main()
