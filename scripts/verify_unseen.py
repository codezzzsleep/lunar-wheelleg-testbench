"""
统一自验：只从本批**原始记录**重算，不读旧"成功报告"。

  .venv/bin/python scripts/verify_unseen.py --out runs/unseen/verify/v2 \
      --e2e runs/unseen/e2e/e2 --gatep runs/unseen/gate_p/w5

逐项 PASS / FAIL / BLOCKED；必需项不过则退出码非 0。
覆盖复核要求的失败路径：停车、无安全动作、缺记录、重复记录。
"""
import argparse, json, pathlib, sys, urllib.request
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
CHECKS = []


def rec(name, required, status, detail=''):
    CHECKS.append({'name': name, 'required': required,
                   'status': status, 'detail': detail})


def read_jsonl(p):
    return [json.loads(l) for l in pathlib.Path(p).read_text().splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--e2e', default='runs/unseen/e2e/e2')
    ap.add_argument('--gatep', default='runs/unseen/gate_p/w5')
    ap.add_argument('--port', type=int, default=8090)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    e2e = ROOT / a.e2e

    # --- 1. 标定：从标定记录重算，不信任 pass 字段 ---
    calp = ROOT / 'runs/unseen/obs/cal/calibration.json'
    if calp.exists():
        c = json.loads(calp.read_text())
        known = c.get('lateral_offset', {}).get('known_y')
        got = c.get('lateral_offset', {}).get('recovered_y_median')
        ok = known is not None and got is not None and abs(got - known) < 0.02
        rec('观测标定（反投影横向）', True, 'PASS' if ok else 'FAIL',
            f'已知 {known} / 反投影 {got}')
    else:
        rec('观测标定（反投影横向）', True, 'BLOCKED', '未运行 calibrate_observe.py')

    # --- 2. 双胞胎：从 STL 顶点重算正面一致性，不读 meta ---
    try:
        import trimesh, hashlib
        base = ROOT / 'runs/unseen/gate_p/p3/mesh'
        files = sorted(base.glob('s0_h14_w55_*.stl'))
        if len(files) >= 3:
            fps = set()
            for f in files:
                m = trimesh.load(str(f), force='mesh')
                v = np.asarray(m.vertices)
                front = np.round(v[v[:, 0] <= 1e-9], 6)
                fps.add(hashlib.md5(np.ascontiguousarray(front).tobytes()).hexdigest())
            rec('双胞胎正面逐顶点一致', True, 'PASS' if len(fps) == 1 else 'FAIL',
                f'{len(files)} 个背面，正面指纹 {len(fps)} 种')
        else:
            rec('双胞胎正面逐顶点一致', True, 'BLOCKED', '样本不足')
    except Exception as e:
        rec('双胞胎正面逐顶点一致', True, 'BLOCKED', f'{type(e).__name__}')

    # --- 3. Gate P：从 results.jsonl 重算 P1/P2/P4 ---
    g = ROOT / a.gatep
    if (g / 'results.jsonl').exists():
        rows = read_jsonl(g / 'results.jsonl')
        fronts = sorted({tuple(r['front']) for r in rows})
        backs = sorted({r['back'] for r in rows})
        opts = sorted({r['option'] for r in rows})
        seeds = sorted({r['seed'] for r in rows})
        agg = {}
        for r in rows:
            k = (tuple(r['front']), r['back'], r['option'])
            agg.setdefault(k, []).append(r)
        dup = len(rows) - len({(tuple(r['front']), r['back'], r['option'], r['seed']) for r in rows})
        rec('Gate P 无重复回合', True, 'PASS' if dup == 0 else 'FAIL', f'重复 {dup} 条')

        def succ(f, b, o):
            return sum(1 for r in agg.get((f, b, o), []) if r['success'])
        p1 = 0
        for f in fronts:
            best = {}
            for b in backs:
                cand = []
                for o in opts:
                    cells = agg.get((f, b, o), [])
                    if not cells:
                        continue
                    t = [c['t_end'] for c in cells if c['success'] and c['t_end']]
                    cand.append((o, sum(1 for c in cells if c['success']),
                                 -(sum(t) / len(t)) if t else -99))
                if cand:
                    cand.sort(key=lambda z: (-z[1], -z[2]))
                    best[b] = cand[0][0]
            if len(set(best.values())) > 1:
                p1 += 1
        p2 = 0
        for f in fronts:
            s = {b: succ(f, b, 'R1') for b in backs}
            n = len(agg.get((f, backs[0], 'R1'), []))
            if n and max(s.values()) == n and min(s.values()) == 0:
                p2 += 1
        rec('Gate P P1（最优选项随背面变）', True,
            'PASS' if p1 >= 4 else 'FAIL', f'{p1}/{len(fronts)} 组（要求 >=4）')
        rec('Gate P P2（R1 一背全成另一背全败）', True,
            'PASS' if p2 >= 3 else 'FAIL', f'{p2}/{len(fronts)} 组（要求 >=3）')
        trig = {}
        for r in rows:
            trig.setdefault(r['option'], []).append(bool(r.get('triggered')))
        stateful = [o for o in opts if o.startswith(('L', 'S'))]
        ok_trig = all(any(trig.get(o, [])) for o in stateful) if stateful else True
        rec('状态机动作真的触发', True, 'PASS' if ok_trig else 'FAIL',
            '; '.join(f'{o}:{sum(trig.get(o, []))}/{len(trig.get(o, []))}' for o in stateful))
    else:
        rec('Gate P', True, 'BLOCKED', '无 results.jsonl')

    # --- 4. 闭环：动作确实执行、成功在场内、A0 真刹车、决策可复算 ---
    need = ['observation.json', 'decision.json', 'rehearsal.jsonl',
            'execution.jsonl', 'summary.json']
    miss = [n for n in need if not (e2e / n).exists()]
    if miss:
        rec('闭环产物完整', True, 'BLOCKED', f'缺 {miss}')
    else:
        reh = read_jsonl(e2e / 'rehearsal.jsonl')
        ex = read_jsonl(e2e / 'execution.jsonl')
        dec = json.loads((e2e / 'decision.json').read_text())

        keys = [(tuple(r['hypothesis_id'] for _ in [0]), r['option'], r['seed']) for r in reh]
        dup = len(keys) - len(set(keys))
        rec('预演无重复记录', True, 'PASS' if dup == 0 else 'FAIL', f'重复 {dup} 条')

        fps = {}
        for r in reh:
            fps.setdefault(r['option'], set()).add(r.get('action_fingerprint'))
        r1 = fps.get('R1', set())
        l1 = fps.get('L1', set())
        rec('L1 行为不等于 R1', True,
            'PASS' if l1 and r1 and not (l1 <= r1) else 'FAIL',
            f'R1 {len(r1)} 种指纹 / L1 {len(l1)} 种，交集 {len(l1 & r1)}')

        a0 = [r for r in ex if r['option'] == 'A0']
        if a0:
            ok = all(r['brake_steps'] > 0 and r['reason'] == 'braking'
                     and abs(r['x']) < 0.5 and r['reason'] != 'tipped' for r in a0)
            rec('A0 真的刹停且不前进', True, 'PASS' if ok else 'FAIL',
                f"{len(a0)} 条，刹车步 {[r['brake_steps'] for r in a0]}，"
                f"终态 x {[r['x'] for r in a0]}")
        else:
            rec('A0 真的刹停且不前进', True, 'BLOCKED', '本批未执行 A0')

        inside = [r for r in ex if r['success'] and r['x'] >= 3.95]
        rec('成功记录在有效地形内', True, 'PASS' if not inside else 'FAIL',
            f'超出场地仍判成功 {len(inside)} 条')

        import unseen_pipeline as UP
        again = UP.decide(reh, list(dec.get('stats', {})) + ['A0'])
        rec('决策可复算', True,
            'PASS' if again.get('chosen') == dec.get('chosen') else 'FAIL',
            f"记录 {dec.get('chosen')} / 复算 {again.get('chosen')}")
        rec('决策未偷看真值', True,
            'PASS' if 'truth' not in json.dumps(dec) else 'FAIL',
            'decision.json 中无 truth 字段' if 'truth' not in json.dumps(dec) else '含 truth')

        # 缺记录路径：人为删一条后 decide 必须报 insufficient_evidence
        if reh:
            broke = [r for r in reh if not (r['option'] == 'R1' and r['seed'] == 0)]
            res = UP.decide(broke, list(dec.get('stats', {})) + ['A0'])
            rec('缺记录 -> insufficient_evidence', True,
                'PASS' if res.get('insufficient_evidence') else 'FAIL',
                str(res.get('missing', ''))[:80])

        # 无安全动作路径：人为把某动作在每个假设下都判失败
        forced = []
        for r in reh:
            r2 = dict(r)
            if r2['option'] in ('R1', 'L1', 'L2'):
                r2['success'] = False
            forced.append(r2)
        res = UP.decide(forced, ['R1', 'L1', 'L2', 'A0'])
        rec('无安全动作 -> A0', True,
            'PASS' if res.get('chosen') == 'A0' and res.get('no_robust_option') else 'FAIL',
            f"chosen={res.get('chosen')}")

    # --- 5. 页面：真实请求 + 三维视图 + 回放 ---
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{a.port}/api/run?name={e2e.name}', timeout=10) as r:
            body = json.loads(r.read().decode())
        views = [v for v in body.get('views', []) if v.startswith('hyp_')]
        replay = body.get('replay', [])
        rec('页面有候选三维视图', True, 'PASS' if views else 'FAIL', f'{len(views)} 张')
        rec('页面有回放帧', True, 'PASS' if replay else 'FAIL', f'{len(replay)} 帧')
        rec('页面有真值揭晓', True,
            'PASS' if any(v.startswith('truth_') for v in body.get('views', [])) else 'FAIL',
            'truth_side.png')
    except Exception as e:
        rec('页面接口', True, 'BLOCKED', f'{type(e).__name__}')

    # --- 6. 已知未完成项 ---
    rec('Gate P P3（同观测）', True, 'FAIL', '背面未内缩 2 cm，最好 MAE 3.23 > 2.0')
    rec('Gate L（真实 Lux3D 图生）', True, 'BLOCKED', '未接入付费图生，本批 0 个新任务')
    rec('固定评测与冻结协议', True, 'BLOCKED', 'unseen_eval.py 未实现')

    fails = [c for c in CHECKS if c['required'] and c['status'] != 'PASS']
    verdict = {'checks': CHECKS, 'n_not_pass': len(fails),
               'overall': 'PASS' if not fails else 'NOT_PASS'}
    (out / 'verify.json').write_text(json.dumps(verdict, indent=2, ensure_ascii=False))
    for c in CHECKS:
        print(f"  [{c['status']:7s}] {c['name']}: {c['detail']}")
    print(f"\n总体: {verdict['overall']}（未通过 {len(fails)} 项）")
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
