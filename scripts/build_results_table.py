"""从逐回合记录生成主表（不手抄数字，标签与 checkpoint 哈希都来自产物）。"""
import hashlib, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda: f.read(1<<20), b''): h.update(b)
    return h.hexdigest()[:12]

def load(path, label):
    d=json.loads((ROOT/path).read_text())
    rows=[]
    for r in d['results']:
        rows.append({'label': r['label'], 'table': label,
                     'per_scene': f"{r['per_scene_success']}/{r['n_scenes']}",
                     'per_scene_rate': r['per_scene_rate'],
                     'contact_success': r['per_scene_contact_success'],
                     'across': r['across_seeds']['rate'],
                     'n': r['across_seeds']['n']})
    return rows

def main():
    specs=[('runs/v4_baseline_M/baselines.json','M 任务（安全通行）'),
           ('runs/v4_baseline_K/baselines.json','K 任务（接触越障）')]
    out=['| 任务 | 策略 | 按场景成功 | 接触成功 | 多初态成功率 | 样本 |',
         '| --- | --- | --- | --- | --- | --- |']
    ck={}
    for p,lab in specs:
        for r in load(p,lab):
            out.append(f"| {lab} | {r['label']} | {r['per_scene']} | "
                       f"{r['contact_success']} | {r['across']:.3f} | {r['n']} |")
    for c in sorted((ROOT/'runs/v4M').glob('M_s*/checkpoints/final.npz')):
        ck[f'v4M/{c.parent.parent.name}']=sha(c)
    print('\n'.join(out))
    print('\ncheckpoint 身份:')
    for k,v in ck.items(): print(f'  {k}  sha256:{v}')
    (ROOT/'runs/results_table.md').write_text('\n'.join(out)+'\n')
    (ROOT/'runs/checkpoint_ids.json').write_text(json.dumps(ck,indent=2))

if __name__=='__main__': main()
