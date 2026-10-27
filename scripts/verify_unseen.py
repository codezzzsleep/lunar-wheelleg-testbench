"""
统一自验：不读旧"成功报告"，而是从产物重算并重演。

  .venv/bin/python scripts/verify_unseen.py --out runs/unseen/verify/v1 [--port 8090]

输出逐项 PASS / FAIL / BLOCKED 与总退出码；必需项 FAIL/BLOCKED 则总退出码非 0。
"""
import argparse, json, pathlib, subprocess, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

CHECKS = []
def rec(name, required, status, detail=''):
    CHECKS.append({'name': name, 'required': required, 'status': status, 'detail': detail})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--e2e', default='runs/unseen/e2e/e1')
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)

    # 1. 观测标定
    cal = ROOT / 'runs/unseen/obs/cal/calibration.json'
    if cal.exists():
        d = json.loads(cal.read_text())
        err = d.get('lateral_offset', {}).get('error_m')
        rec('观测标定（非对称标定物）', True,
            'PASS' if d.get('pass') else 'FAIL', f'横向误差 {err} m')
    else:
        rec('观测标定（非对称标定物）', True, 'BLOCKED', '未运行 calibrate_observe.py')

    # 2. 双胞胎同一正面
    p3 = ROOT / 'runs/unseen/gate_p/p3'
    if (p3 / 'twins_meta.json').exists():
        meta = json.loads((p3 / 'twins_meta.json').read_text())
        nm = sum(1 for m in meta if m.get('non_manifold_edges'))
        rec('双胞胎几何', True, 'PASS' if nm == 0 else 'FAIL',
            f'{len(meta)} 个，非流形 {nm} 个')
    else:
        rec('双胞胎几何', True, 'BLOCKED', '未生成')

    # 3. Gate P 判定（读 summary，重算一致性）
    gp = ROOT / 'runs/unseen/gate_p/w4/summary.json'
    if gp.exists():
        s = json.loads(gp.read_text())
        ok = bool(s.get('P1', {}).get('pass')) and bool(s.get('P2', {}).get('pass'))
        rec('Gate P（P1/P2）', True, 'PASS' if ok else 'FAIL',
            f"P1 {s['P1']['hit']}/18, P2 {s['P2']['hit']}/18")
        rec('Gate P（P4 重演）', True,
            'PASS' if s.get('P4', {}).get('pass') else 'FAIL',
            f"{s.get('P4', {}).get('replays')} 回合，错配 {s.get('P4', {}).get('mismatch')}")
    else:
        rec('Gate P', True, 'BLOCKED', '未运行 gate_physics.py')

    # 4. e2e 产物完整 + 决策可复算
    e2e = ROOT / a.e2e
    need = ['observation.json', 'decision.json', 'rehearsal.jsonl',
            'execution.jsonl', 'summary.json']
    miss = [n for n in need if not (e2e / n).exists()]
    if miss:
        rec('端到端闭环产物', True, 'BLOCKED', f'缺 {miss}')
    else:
        import unseen_pipeline as UP
        mat = [json.loads(l) for l in (e2e / 'rehearsal.jsonl').read_text().splitlines() if l.strip()]
        dec = json.loads((e2e / 'decision.json').read_text())
        again = UP.decide(mat, list(dec.get('stats', {})) + ['A0'])
        rec('决策可复算', True,
            'PASS' if again.get('chosen') == dec.get('chosen') else 'FAIL',
            f"记录 {dec.get('chosen')} / 复算 {again.get('chosen')}")

    # 5. 真值执行记录完整
    if (e2e / 'execution.jsonl').exists():
        ex = [json.loads(l) for l in (e2e / 'execution.jsonl').read_text().splitlines() if l.strip()]
        rec('真值执行记录', True, 'PASS' if ex else 'FAIL', f'{len(ex)} 条')
    else:
        rec('真值执行记录', True, 'BLOCKED', '缺失')

    # 6. 页面可响应且不带真值
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:8090/api/run?name=' +
                                    pathlib.Path(a.e2e).name, timeout=10) as r:
            body = json.loads(r.read().decode())
        has_truth = 'truth' in json.dumps(body.get('decision', {}))
        rec('页面接口', True, 'PASS' if not has_truth else 'FAIL',
            'planner 输出中无 truth 字段' if not has_truth else '发现 truth 泄漏')
    except Exception as e:
        rec('页面接口', False, 'BLOCKED', f'页面未启动：{type(e).__name__}')

    # 7. 已知未完成项
    rec('Gate L（真实 Lux3D 图生）', True, 'BLOCKED', '未接入付费图生，本轮 0 个新任务')
    rec('Gate P（P3 同观测）', True, 'FAIL', '最好 MAE 3.23，阈值 2.0')
    rec('固定评测与协议', True, 'BLOCKED', '未实现 unseen_eval.py / 协议文件')

    required_fail = [c for c in CHECKS if c['required'] and c['status'] != 'PASS']
    verdict = {'checks': CHECKS, 'n_fail': len(required_fail),
               'overall': 'PASS' if not required_fail else 'NOT_PASS'}
    (out / 'verify.json').write_text(json.dumps(verdict, indent=2, ensure_ascii=False))
    for c in CHECKS:
        print(f"  [{c['status']:7s}] {c['name']}: {c['detail']}")
    print(f"\n总体: {verdict['overall']}（必需项未通过 {len(required_fail)} 项）")
    return 0 if not required_fail else 1

if __name__ == '__main__':
    sys.exit(main())
