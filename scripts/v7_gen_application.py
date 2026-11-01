"""生成申请材料（可直接审批）：入选石头的输入图、完整哈希、模型与版本、创建顺序、费用上界。"""
import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np


def sha(p):
    h = hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selection', required=True)
    ap.add_argument('--pool', default='assets/procedural_rocks')
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-rocks', type=int, default=8)
    ap.add_argument('--credits-per-task', type=float, default=1.0)
    ap.add_argument('--ceiling-per-task', type=float, default=20.0)
    ap.add_argument('--budget', type=float, default=500.0)
    a = ap.parse_args()
    sel = json.loads((ROOT / a.selection).read_text())
    pool = json.loads((ROOT / a.pool / 'index.json').read_text())
    by_id = {r['id']: r for r in pool['rocks']}
    chosen = [s for s in sel['rows'] if s['status'] == 'selected']
    chosen.sort(key=lambda s: s['object'])
    chosen = chosen[:a.max_rocks]
    out = ROOT / a.out
    (out / 'images').mkdir(parents=True, exist_ok=True)

    import observe
    import v7_holdout_scan as HS
    case = json.loads((ROOT / 'cases/unseen_v1/R02.json').read_text())
    tasks, images = [], []
    for i, s in enumerate(chosen):
        rid = s['object']
        rock = by_id[rid]
        env = HS.make_env_for_rock(rock, case)
        env.reset(seed=7)
        d = out / 'images' / rid
        observe.capture_observation(env, d, case_id=rid)
        crop = d / 'crop_raw.png'
        img = crop if crop.is_file() else (d / 'rgb.png')
        images.append({'rock': rid, 'image': str(img.relative_to(ROOT)), 'sha256': sha(img)})
        for k, view in enumerate(('front',)):
            tasks.append({'create_order': len(tasks),
                          'rock': rid, 'view': view,
                          'image': str(img.relative_to(ROOT)),
                          'image_sha256': sha(img),
                          'model': 'Lux3D', 'version': 'g1-turbo',
                          'task_type': 'image-to-3d', 'face_count': 30000,
                          'sample_index': 0,
                          'estimated_credits': a.credits_per_task,
                          'ceiling_credits': a.ceiling_per_task,
                          'rock_sha256': rock['sha256'], 'height_m': rock['height_m']})
    contact = out / 'contact_sheet.png'
    try:
        from PIL import Image
        imgs = [Image.open(ROOT / im['image']).convert('RGB') for im in images]
        if imgs:
            w, h = imgs[0].size
            cols = min(4, len(imgs)); rows = (len(imgs) + cols - 1) // cols
            sheet = Image.new('RGB', (cols * w, rows * h), (20, 20, 20))
            for k, im in enumerate(imgs):
                sheet.paste(im.resize((w, h)), ((k % cols) * w, (k // cols) * h))
            sheet.save(contact)
    except Exception as e:
        print('contact sheet skipped:', e)

    expected = len(tasks) * a.credits_per_task
    ceiling = len(tasks) * a.ceiling_per_task
    rec = {'schema': 'generation-application/v1',
           'selection': a.selection, 'n_rocks': len(chosen), 'n_tasks': len(tasks),
           'model': 'Lux3D', 'version': 'g1-turbo', 'task_type': 'image-to-3d',
           'face_count': 30000,
           'price': {'credits_per_task_verified': a.credits_per_task,
                     'source': "供应商任务列表 list_tasks 的 consumedCredits 字段（本批实测）",
                     'text_to_3d_credits': 13,
                     'ceiling_per_task': a.ceiling_per_task,
                     'expected_total_credits': expected,
                     'ceiling_total_credits': ceiling,
                     'budget_available_credits': a.budget,
                     'within_budget': ceiling <= a.budget,
                     'actual_charge': 'unknown（以外部账单为准）'},
           'images': images,
           'contact_sheet': str(contact.relative_to(ROOT)) if contact.is_file() else None,
           'tasks': tasks,
           'rules': ['按 create_order 固定提交，不按下载完成顺序重排',
                     '固定首候选失败不换第二个',
                     '失败不自动重提',
                     '试点：先交前 2 个对象（2 任务），核对几何可用性与实际扣费后再放行其余'],
           'authorization': {'status': 'pending_user_approval',
                             'not_authorized_by_this_file': True}}
    (out / 'application.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: rec[k] for k in ('n_rocks', 'n_tasks', 'price', 'contact_sheet')},
                     ensure_ascii=False)[:600])


if __name__ == '__main__':
    main()
