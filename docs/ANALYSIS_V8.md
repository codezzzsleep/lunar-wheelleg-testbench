# 分析：V8 的"停车"有多稳？（2026-11-11）

> 本文回答一个问题：**V8 想象车"两眼之后停车"这个结论，离"开出去"有多远？**
> 三个离线分析 + 两次真跑。所有数字都能用文中命令复算；不跑物理的部分不需要 GL、不调 API。

## 0 一句话

**1.36%**。把准入门槛整体放宽 **1.36%**（`contour_iou_min` 0.7068 → 0.6972），look1 的
T2 就会从 **0/4 变 1/4**，决策从"停车"变成"有路"，执行结果是 **t≈89.7 s 撞上石头**。
放宽 10% 同样撞。也就是说：V8 的负面结论不是"无能"，而是**保守得恰好**——门槛的严格程度
正是拦住这次碰撞的那道闸；而这道闸只差一个百分点就守不住。

## 1 问题与材料

- 现象（`docs/v8/STATUS.md` §3.2）：想象车首眼 T1 采纳 2/6、T2 **0/4**，第二眼 **0/3**，
  两次决策都是 `imagined_blocked`，两眼后停车（`result=stuck`）。
- 疑问：`0/3` 到底是**候选太差**，还是**门槛太紧**？
- 材料：`runs/v8/main/imagination/looks/*/T*/decide/target_decision.json`（每份候选的 5 项指标
  与阈值都在里面）、`configs/v5_admission.json`（标定门槛）、`runs/v7/shadow_exp/eval_rows.json`（64 份单图样本）。

## 2 逐候选归因：11 次拒绝全部首卡 `contour_iou`

```bash
python3 scripts/v8/v8_admission_report.py --run runs/v8/main
```

| 眼 | 目标 | 候选 | 采纳 | 首卡指标 | 距阈值 | 其余未过项 |
| --- | --- | --- | --- | --- | --- | --- |
| look1 | T1 | A1 | ❌ | contour_iou | 0.7022 vs 0.7068（差 **0.7%**） | — |
| look1 | T1 | A2 | ❌ | contour_iou | 0.6919（差 2.1%） | — |
| look1 | T1 | B1 | ❌ | contour_iou | 0.5160（差 27%） | free_intrusion 未过 |
| look1 | T1 | B2 | ✅ | — | — | — |
| look1 | T1 | C1 | ❌ | contour_iou | 0.5830（差 18%） | free_intrusion 未过 |
| look1 | T1 | C2 | ✅ | — | — | — |
| look1 | T2 | A1 | ❌ | contour_iou | 0.4747（差 33%） | scale_ratio 未过 |
| look1 | T2 | A2 | ❌ | contour_iou | 0.6972（差 **1.4%**） | — |
| look1 | T2 | C1 | ❌ | contour_iou | 0.4684（差 34%） | scale_ratio 未过 |
| look1 | T2 | C2 | ❌ | contour_iou | 0.4658（差 34%） | scale_ratio 未过 |
| look2 | T2 | M1 | ❌ | contour_iou | 0.5573（差 21%） | scale_ratio 未过 |
| look2 | T2 | M2 | ❌ | contour_iou | 0.5150（差 27%） | — |
| look2 | T2 | M3 | ❌ | contour_iou | 0.4239（差 40%） | scale_ratio 未过 |

- **13 份候选里 11 份被拒，全部由 `contour_iou` 首卡**；其余指标只在少数候选上叠加不通过。
- 最有意思的是三份"差一点点"：T1/A1 差 0.7%、T2/A2 差 **1.4%**、T1/A2 差 2.1%。
  它们不是"想得离谱"，而是**轮廓比阈值低了一点点**。

## 3 阈值敏感性：放宽 10% 会多认 5 份，收紧 10% 一份不剩

```bash
python3 scripts/v8/v8_admission_report.py --run runs/v8/main --perturb 0.10
```

| 扰动 | 采纳 | 谁 |
| --- | --- | --- |
| 标定门槛 | 2 | T1/B2、T1/C2 |
| 放宽 10% | **5** | 追加 T1/A1、T1/A2、T2/A2 |
| 收紧 10% | **0** | 连 T1/B2、T1/C2 都过不了 |

并可用二分法算出**每份候选需要放宽多少才能过线**：T1/A1 **0.65%**、T2/A2 **1.36%**、
T1/A2 2.1%，其余 3 份需要 33% 以上（确实差）。

## 4 真跑：门槛放宽 1.4% 与 10%，车都撞了

两个隔离目录（不覆盖归档运行），同一批观测、同一批 GLB，只改门槛：

```bash
# 放宽 1.4%（= T2/A2 的临界值）
python3 scripts/v8/v8_run.py --policy imagination --imagine lux --adm-relax 0.014 \
        --accept-replay-drift --out runs/v8/relax014
# 放宽 10%
python3 scripts/v8/v8_run.py --policy imagination --imagine lux --adm-relax 0.10 \
        --accept-replay-drift --out runs/v8/relax10
```

| 运行 | 准入（look1） | 决策 | 规划期余量 | 预演 | 执行结果 |
| --- | --- | --- | --- | --- | --- |
| 标定门槛（归档） | T1{B2,C2}、T2{} | `imagined_blocked` → 看第二眼 → 停车 | — | — | **stuck**，2 眼，52.72 s |
| 放宽 10% | T1{A1,A2,B2,C2}、T2{A2} | 有路，直接走 | **−0.23 m** | 4 窗全无碰撞 | **collision**，t=89.7 s，92.2 s |
| **放宽 1.4%**（= T2/A2 的临界值） | T1{A1,B2,C2}、T2{A2} | 有路，直接走（**不看第二眼**） | **−0.23 m** | 3 窗全无碰撞 | **collision**，t=89.18 s，91.68 s |

- 两档放宽（1.4% 与 10%）都撞在同一块石头 `obstacle1`、同一位置附近（x≈6.94 m）：说明差别不在
  "放宽多少"，而在**一旦 T2 有候选过线，规划器就会穿进真值里那 0.23 m 没被想象到的石头**。
- 离线二分法预测的临界点是 1.36%，真跑 1.4% 就翻盘——预测与实测一致。这也说明结论对门槛的
  敏感度是**可预测的**，不是随机漂移。

> 注：`--adm-relax` 只改准入门槛，不动其他任何条件；放宽后的阈值会写进每份
> `target_decision.json` 的 `thresholds` 与 `summary.admission_relax`，便于审计。

## 5 V7 的门槛工作点与 5 cm 余量的留一检验

```bash
python3 scripts/v7/v7_gate_report.py
```

| 项 | 值 |
| --- | --- |
| 样本（`runs/v7/shadow_exp/eval_rows.json`） | 64 份 ok，坏(隐藏 IoU<0.5) 32、好(≥0.6) 31 |
| 敏感度（坏的被拒） | **32/32（100%）** |
| 特异度（好的被采纳） | 21/31 → **误拒 10 份 = 32%** |
| 被采纳样本的 \|背面误差\| | p50 0.032 / p90 0.040 / **max 0.050 m** |

**留一太阳条件**（用其余条件的最大误差去预测被留出的条件）：

| 留出条件 | 其余条件 max | 留出实际 max | 是否超出 |
| --- | --- | --- | --- |
| high_side | 0.042 m | **0.050 m** | **超出 8 mm** |
| low_behind | 0.050 m | 0.038 m | 未超出 |
| low_front | 0.050 m | 0.042 m | 未超出 |
| low_side | 0.050 m | 0.024 m | 未超出 |

结论：`SPEC_V8.md` 里的 **5 cm 余量是样本内最大值，不是界限**——留出一整个太阳方位后，
其余条件给出的 4.2 cm 会被 5.0 cm 打破。它能当"经验尺度"用，不能当保证用。

## 6 结论

1. **自检是"宁拒勿滥"的工作点**：零假阳性、牺牲约三分之一的好候选（V7：21/31）。
   这解释了 V8 为什么反复 `imagined_blocked`——不全是候选差，也有门槛把能用的拒了。
2. **但当前工作点在安全侧**：只要把门槛放宽到能让 T2 那个候选过线（1.36%），车就会开出去并撞。
   所以"停车"这个结论是**稳健的**——它保守，而保守是对的；真正脆弱的是**结论与行动之间只差 1.36%**。
3. **两条边界**：`--adm-relax` 是**单参数扰动实验**，不是重新标定；10% 与 1.4% 两档都撞，
   再宽的档没有跑。V7 的 21/31 是同一批标定样本上的工作点，不是独立的泛化估计。

## 7 复现清单

| 命令 | 产物 |
| --- | --- |
| `python3 scripts/v8/v8_admission_report.py --run runs/v8/main --json /tmp/adm.json` | 逐候选归因表 + 敏感性 |
| `python3 scripts/v7/v7_gate_report.py --json /tmp/gate.json` | V7 工作点 + 留一检验 |
| `runs/v8/relax014/imagination/{summary.json,events.jsonl}` | 1.4% 放宽的真跑记录 |
| `runs/v8/relax10/imagination/{summary.json,events.jsonl}` | 10% 放宽的真跑记录 |
