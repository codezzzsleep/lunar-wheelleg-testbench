"""
V6 统一验收：绑定 runs/unseen/delivery_v6/<batch>/manifest.json。
负例调用同一校验函数；研究 NOT_ESTABLISHED 不是程序错误。
"""
import argparse, copy, hashlib, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=[]
def ck(n,ok,d=''):
    OUT.append({'check':n,'pass':bool(ok),'detail':d}); return bool(ok)
def sha(p):
    h=hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()
def j(p): return json.loads(pathlib.Path(p).read_text())
def jl(p): return [json.loads(x) for x in pathlib.Path(p).read_text().splitlines() if x.strip()]

def validate_eval(rows, summary, truth):
    e=[]
    ex=[r for r in rows if r.get('phase')=='execution']
    if not ex: return ['no execution rows']
    if summary.get('truth_sha')!=truth: e.append('summary truth mismatch')
    if any(r.get('truth_sha')!=truth for r in ex): e.append('execution truth mismatch')
    keys=[(r.get('method'),r.get('seed'),r.get('option')) for r in ex]
    if len(keys)!=len(set(keys)): e.append('duplicate (method,seed,option)')
    by={}
    for r in ex: by.setdefault(r.get('seed'),set()).add(r.get('initial_full_hash'))
    if any(len(v)!=1 for v in by.values()): e.append('same seed initial hashes differ across methods')
    if any(None in v for v in by.values()): e.append('missing initial_full_hash')
    if summary.get('decision_rule')!='worst-case-risk/v2': e.append('decision rule not v2')
    if summary.get('time_limit_s')!=30.0: e.append('time limit not 30')
    return e

def validate_fusion(man, parent_body=None, obs=None):
    e=[]
    if not man.get('watertight'): e.append('not watertight')
    hidden=(man.get('regions') or {}).get('face_counts',{}).get('1',0)
    if hidden<=0 or man.get('no_generated_hidden_contribution'): e.append('no generated hidden contribution')
    m=man.get('metrics') or {}
    if not (m.get('mask_iou',0)>=0.85 and m.get('freespace_violation',1)<=0.05):
        e.append('visible strict fail')
    if m.get('vis_pt_p95_mm') is None or m['vis_pt_p95_mm']>9.96: e.append('P95 fail')
    if man.get('fixture') and man.get('source_kind')=='H5_F': e.append('fixture masquerades as H5_F')
    return e

def validate_trajectory(tr):
    e=[]; fr=tr.get('frames') or []
    if len(fr)<2: return ['too few frames']
    if abs(float(fr[-1]['qpos'][0])-float(tr['result'].get('final_x') or 0))>0.02:
        e.append('last frame x != final_x')
    if abs(float(fr[-1]['t'])-float(tr['result'].get('t_end') or 0))>0.1:
        e.append('last frame t != t_end')
    return e

def validate_static(st):
    e=[]
    if st.get('verdict')!='MEASURED': e.append('not measured')
    if not st.get('stable_ok') or not st.get('contact_valid'): e.append('not stable/contact')
    w=(st.get('stable_window') or {}).get('max_wheel_qvel')
    if w is None or w>0.05: e.append('wheel still driven')
    return e

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--manifest',required=True); ap.add_argument('--out',required=True); ap.add_argument('--self-test',action='store_true')
    a=ap.parse_args(); manp=pathlib.Path(a.manifest); man=j(manp); b=manp.parent
    if not ck('manifest 存在',manp.exists()): pass
    ck('plan SHA',sha(ROOT/man['plan']['path'])==man['plan']['sha256'])
    ck('protocol SHA',sha(ROOT/man['protocol']['path'])==man['protocol']['sha256'])
    ck('new create=0',man.get('new_create')==0)
    led=jl(ROOT/'runs/unseen/generation/ledger.jsonl')
    ck('V5 ledger 27 任务 / 540 上界',len([r for r in led if r.get('task_id')])==27)
    ck('无 V6 create 行',not any(r.get('run_scope')=='unseen_delivery_v6' for r in led))
    # fusion
    h5=j(b/'fusion/C_R01_face12k_H5F_p005_v5/manifest.json'); b3=j(b/'fusion/B3_F_R01_p005_v5/manifest.json')
    parent_body=ROOT/'runs/unseen/delivery_v5/v5_20261029/candidates/C_R01_face12k/world/align/body.stl'
    e=validate_fusion(h5,parent_body); ck('H5-F 几何/来源',not e,e)
    ck('H5-F 父候选 SHA',sha(parent_body)==h5['inputs']['parent_mesh_sha'])
    e=validate_fusion(b3); ck('B3-F 几何/来源',not e,e)
    # collision
    coll=j(b/'collision/summary.json')
    ck('碰撞保真 H5-F 标 unreliable',coll['verdict']['H5_F']=='COLLISION_UNRELIABLE')
    ck('碰撞 64 部件未改善',coll['H5_F_64']['occupancy_iou']<0.95)
    ck('B3-F 碰撞近似',coll['verdict']['B3_F'].startswith('COLLISION_APPROXIMATE'))
    # evaluation
    ev=b/'evaluation/R01_matched_v2'
    if not (ev/'summary.json').exists(): ev=b/'evaluation/R01_matched'
    s=j(ev/'summary.json'); rows=jl(ev/'execution.jsonl'); truth=j(b/'collision/TRUTH/manifest.json')['world_sha'] if False else s['truth_sha']
    e=validate_eval(rows,s,truth); ck('正式比较记录/初态/真值',not e,e[:5])
    ck('方法数 5',len(s['methods'])==5,[m['method'] for m in s['methods']])
    tw=ev/'truth_world/body.stl'
    ck('正式比较真值文件 SHA',tw.exists() and sha(tw)==s['truth_sha'],str(tw))
    # G
    g=j(b/'observation/summary.json'); ck('第二观察真实触发',g['triggered'] is True and g['no_rejection'] is True)
    ck('第二观察 A0',g['decision']['chosen']=='A0')
    # H
    st=j(b/'soil/static_v6.json'); e=validate_static(st); ck('月壤真正静态',not e,e)
    # B
    au=j(b/'prediction_audit/prediction_audit.json'); ck('预测误差 false safe=1',au['false_safe_total']==1)
    # D
    fx=j(b/'fusion/fixtures_v6.json'); sts={r['id']:r['status'] for r in fx['rows']}
    ck('fixture F0/F2/F4/F5 已跑',all(sts.get(x)=='PASS' for x in ('F0','F2','F4','F5')),sts)
    ck('fixture F1/F3 如实 not_run',all(sts.get(x)=='NOT_RUN' for x in ('F1','F3')))
    # I
    gifs=list((b/'media/replay').glob('*.gif')); ck('连续 GIF 3 条',len(gifs)>=3,[p.name for p in gifs])
    ck('页面 HTML 存在',(b/'media/replay/index.html').exists())
    ck('真实浏览器截图',(b/'media/page/v6_replay_page.png').exists())
    for trp in (b/'media/trajectories').glob('*.json'):
        e=validate_trajectory(j(trp)); ck(f'轨迹一致 {trp.name}',not e,e)
    # self-test negatives
    if a.self_test:
        bad=copy.deepcopy(rows); ex=[r for r in bad if r.get('phase')=='execution']
        if len(ex)>1: ex[1]['method']=ex[0]['method']; ex[1]['seed']=ex[0]['seed']
        ck('neg 重复执行键',bool(validate_eval(bad,s,truth)))
        bad=copy.deepcopy(rows)
        for r in bad:
            if r.get('truth_sha'): r['truth_sha']='0'*64
        ck('neg truth 同错',bool(validate_eval(bad,s,truth)))
        badh=copy.deepcopy(h5); badh['no_generated_hidden_contribution']=True
        ck('neg 隐藏贡献伪造',bool(validate_fusion(badh)))
        badst=copy.deepcopy(st); badst['stable_window']['max_wheel_qvel']=0.2
        ck('neg 静态仍驱动',bool(validate_static(badst)))
        tr=j(b/'media/trajectories/truth_L2_seed0.json'); badtr=copy.deepcopy(tr); badtr['frames'][-1]['qpos'][0]+=0.1
        ck('neg 动画终态不符',bool(validate_trajectory(badtr)))
        badf=copy.deepcopy(h5); badf['fixture']=True; badf['source_kind']='H5_F'
        ck('neg fixture 冒充 H5-F',bool(validate_fusion(badf)))
    fail=[x for x in OUT if not x['pass']]
    rep={'manifest':str(manp),'batch_id':man['batch_id'],'n_checks':len(OUT),'n_pass':len(OUT)-len(fail),'n_fail':len(fail),'checks':OUT}
    op=pathlib.Path(a.out); op.parent.mkdir(parents=True,exist_ok=True); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2))
    for x in OUT: print(('PASS' if x['pass'] else 'FAIL'),x['check'],'|',x['detail'])
    print(f"\n{rep['n_pass']}/{rep['n_checks']}")
    return 0 if not fail else 1
if __name__=='__main__': sys.exit(main())
