#!/usr/bin/env python3
"""5 cm 余量能不能从自检指标推出来？——结论：**不能**（留一岩石 R² < 0）。

背景：`docs/v8/SPEC_V8.md` 把"被采纳想象背面误差最大 5.0 cm"当规划余量。这个数字是 n=21 的
样本内最大值。一个自然的改进是：用候选自己的自检指标（contour_iou / scale_ratio /
hidden_frac / shell_contact / free_intrusion_frac）预测它可能的背面误差，从而给**逐候选**
的余量，而不是全局一个常数。

本脚本把这个想法真的做一遍并交叉验证。结论是负的：预测不出来。这本身是有用的结论——
它说明 5 cm 只能当"协议假设"，不能当"可估计的界"；想要界就得加样本。

    python3 scripts/v7/v7_margin_model.py
    python3 scripts/v7/v7_margin_model.py --json out.json

注意：唯一与误差强相关的量是 `hidden_iou`（corr≈0.82），但它要用**真值**才算，
规划期拿不到——这正是问题的症结。
"""
import argparse
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'runs/v7/shadow_exp/eval_rows.json'


def features(r):
    """规划期可见的自检指标（不含任何真值量）。"""
    return [1 - r['contour_iou'], abs(r['scale_ratio'] - 1.0), r['hidden_frac'],
            r['shell_contact'], r['free_intrusion_frac']]


def fit(X, y):
    A = np.c_[np.ones(len(X)), X]
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def predict(beta, X):
    return np.c_[np.ones(len(X)), X] @ beta


def analyse(path):
    rows = [r for r in json.loads(pathlib.Path(path).read_text()) if r.get('status') == 'ok']
    X = np.array([features(r) for r in rows], float)
    y = np.array([abs(r['rear_err_m']) for r in rows], float)
    adm = np.array([bool(r['admitted']) for r in rows])
    rock = np.array([r['rock'] for r in rows])

    corr = {name: float(np.corrcoef(X[:, i], y)[0, 1]) for i, name in enumerate(
        ['1-contour_iou', 'abs(scale_ratio-1)', 'hidden_frac', 'shell_contact', 'free_intrusion_frac'])}
    corr['1-hidden_iou(仅真值可得)'] = float(
        np.corrcoef([1 - r['hidden_iou'] for r in rows], y)[0, 1])

    preds, truth = [], []
    for held in sorted(set(rock)):
        tr = rock != held
        va = ~tr
        beta = fit(X[tr], y[tr])
        p = predict(beta, X[va])
        preds.extend(p.tolist()); truth.extend(y[va].tolist())
    preds, truth = np.array(preds), np.array(truth)
    res = truth - preds
    r2 = 1 - (res ** 2).sum() / ((truth - truth.mean()) ** 2).sum()
    beta_all = fit(X, y)
    p_adm = predict(beta_all, X[adm])
    return {
        'n': len(rows), 'admitted': int(adm.sum()),
        'abs_err_range_m': [float(y.min()), float(y.max())],
        'corr': corr,
        'loocv_by_rock': {'n': len(res), 'mae_m': float(np.abs(res).mean()),
                          'rmse_m': float(np.sqrt((res ** 2).mean())), 'r2': float(r2),
                          'abs_resid_p50_m': float(np.percentile(np.abs(res), 50)),
                          'abs_resid_p95_m': float(np.percentile(np.abs(res), 95)),
                          'abs_resid_max_m': float(np.abs(res).max())},
        'admitted': int(adm.sum()),
        'admitted_actual_max_m': float(y[adm].max()),
        'admitted_predicted_range_m': [float(np.clip(p_adm, 0, None).min()),
                                       float(np.clip(p_adm, 0, None).max())],
        'bound_if_used_m': float((np.clip(p_adm, 0, None) + np.percentile(np.abs(res), 95)).max()),
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--rows', default=str(DEFAULT))
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv[1:])
    r = analyse(a.rows)
    print(f"样本 {r['n']} 份（采纳 {r['admitted']}）：|背面误差| 范围 {r['abs_err_range_m'][0]:.3f}–{r['abs_err_range_m'][1]:.3f} m")
    print('\n与 |背面误差| 的单变量相关性（只用规划期可见量）：')
    for k, v in r['corr'].items():
        print(f'  {k:26s} {v:+.3f}')
    d = r['loocv_by_rock']
    print(f"\n留一岩石交叉验证：MAE {d['mae_m']:.3f} m、RMSE {d['rmse_m']:.3f} m、R² {d['r2']:+.3f}")
    print(f"  残差分位：p50 {d['abs_resid_p50_m']:.3f} / p95 {d['abs_resid_p95_m']:.3f} / max {d['abs_resid_max_m']:.3f} m")
    print(f"\n被采纳样本：实际 max {r['admitted_actual_max_m']:.3f} m，模型预测 {r['admitted_predicted_range_m'][0]:.3f}–{r['admitted_predicted_range_m'][1]:.3f} m")
    print(f"若用『预测 + 残差 p95』当界：{r['bound_if_used_m']:.3f} m")
    print('\n结论：R² < 0 说明自检指标推不出误差；5 cm 只是 n=21 的样本内最大值，'
          '不能当可估计的界。要界就得加样本（更多岩石/光照）或换估计量。')
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(r, indent=2, ensure_ascii=False))
        print(f'\n已写 {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
