# 先想后走 V1 · 最终审查报告

- **main commit**：`57412b1`，已推送 origin/main，工作区干净。
- **delivery_status = PARTIAL**
- **evidence_integrity = PASS（含未验证项）**
- **research_gate = NOT_ESTABLISHED**（C1 未受控、C2 未成立、C3 未评估、C4 未做）
- **用户现在能新增完成**：看到 11 个真实 Lux3D 图生候选及其哈希与预算记录；
  能跑通"观测→H3 候选→预演→决策→真值执行"的 H3 版闭环与评测/分析。

## 1. 交付清单

| 包 | 状态 | 源码 / 证据 |
| --- | --- | --- |
| S01–S04 预算与恢复 | **DONE** | `scripts/budget.py`、`tests/test_budget.py`(16) |
| S05 低置相机与观测包 | **DONE** | `scripts/observe.py`（相机位姿 reset 后实测）、`runs/unseen/obs/final_*` |
| S06 标定件与 preflight | **DONE** | `runs/unseen/preflight/cal1_preflight.json`（全 PASS） |
| S07 CAL1 | **DONE** | task **4431907**、`configs/lux3d_frame.json`（结论 uncertain） |
| S08 A/B 计划 | **DONE** | `plans/unseen_v2_generation.json`（11 active + 2 disabled） |
| S09 生成执行 | **DONE** | 11/11 downloaded、`runs/unseen/generation/generation_table.json` |
| S10 配准新候选 | **RUNNING（A1 失败）** | `runs/unseen/align_v2/A1.json` |
| S11 候选验收/物理化 | BLOCKED_INTERNAL | 候选比例与观测不符 |
| S11-F H5-F | TODO | 待 E1/E3 判定 |
| S12–S14 | 部分 | 动作接线完成；P1/P2 未按 v2 重跑 |
| S15 H5 闭环 | TODO | 无合格候选 |
| S16 页面 | 部分 | 旧页面未接新候选 |
| S17–S19 评测/分析/方法 | 部分 | 评测器与分析器可用（H3 冒烟）；H1/H2/H4/H5/Oracle 未接 |
| S20–S22 协议/矩阵/结论 | TODO | — |
| S23 演示 | TODO | — |
| S24 统一自验 | TODO | — |
| S25–S26 索引与汇报 | 部分 | `runs/unseen/delivery_v3/review_index.json`、本文件 |

## 2. 五项复核问题 before / after

| # | before | after | 回归 |
| --- | --- | --- | --- |
| 1 预算只算 HELD | downloaded 记 0 积分；上限 20/1 两次 reserve 都成功 | 占用含全部状态；第二次失败 | `test_budget` 16 项 |
| 2 resume 落入 create | create 被调用 1 次 | create 0 次 | `test_7_resume_never_creates` |
| 3 自由空间只看掩码内 | 轮廓外侵入漏检 | 反例检出 **28.49%**（13367 px 全在掩码外） | `test_freespace` 5 项 |
| 4 标定件底面未收缩 | 底面 0.024 m² > 最大侧面 0.0236 m² | 底面 0.003、最大侧面 0.0232（7.75 倍） | `cal_object.json` |
| 5 标定不用渲染深度 | 点云来自 mj_ray | 渲染深度反投影；平面误差 0.0 mm、横向 5.2 mm | `cal_v2/calibration.json` |

另修：**MuJoCo 按文件名缓存网格**（曾使自由空间从 28.49% 变 0）、相机 90° 滚转、
`nav_target_y` 接线（D1 +0.496 m / D2 −0.492 m）。

## 3. 真实生成表

| plan | task_id | 输入 sha256 | GLB extents (m) | 费用上界 | 核验 |
| --- | --- | --- | --- | --- | --- |
| 4416952 | 4416952 | 旧滚转输入 | 0.200×0.191×0.124 | 20 | unknown |
| 4418107 | 4418107 | 同上 | 0.250×0.246×0.156 | 20 | unknown |
| CAL1 | **4431907** | c1617f0b… | 0.110×0.062×0.033 | 20 | unknown |
| A1 | **4432000** | 见 table | 0.100×0.035×0.062 | 20 | unknown |
| A2–A5 | 4432xxx | 见 table | 0.08–0.12 × 0.03–0.08 × 0.002–0.134 | 80 | unknown |
| B1–B5 | 4432026…4432278 | 见 table | 0.12 × 0.029–0.037 × 0.001–0.015 | 100 | unknown |

**预算：13 任务 / 260 积分上界 / 剩余 40 积分与 2 槽位**。核验扣费全部 unknown（API 不返回 charge）。
完整逐项哈希见 `runs/unseen/generation/generation_table.json`。

## 4. 固定矩阵主表

**仅 H3 冒烟，不是正式对照**（`runs/unseen/eval/smoke1/`，1 观测、1 候选、3 初态）：

| 方法 | n | 成功 | 刹停 | 成功率 | 均代价 |
| --- | --- | --- | --- | --- | --- |
| B0 盲走 | 3 | 3 | 0 | 1.000 | 5.7 |
| B1 保守停车 | 3 | 0 | 3 | 0.000 | 40.0 |
| H3 程序化 | 3 | 3 | 0 | 1.000 | 5.7 |

H3 与 B0 用同一几何，相同是预期的。正式 288/480 回合矩阵**未运行**。

## 5. 复制即跑

```bash
export MUJOCO_GL=osmesa
.venv/bin/python -m unittest discover -s tests            # 94 项，约 745 s
.venv/bin/python scripts/imagine.py --plan plans/unseen_v2_generation.json --dry-run
.venv/bin/python scripts/observe.py --case cases/unseen_v1/planA.json \
    --out runs/unseen/obs/final_planA --cam-height 0.16 --pitch 0
.venv/bin/python scripts/align.py --candidate <glb> --obs runs/unseen/obs/final_planA \
    --out runs/unseen/align_v2/<id>.json
.venv/bin/python scripts/unseen_eval.py --protocol plans/unseen_v2_protocol_smoke.json \
    --out runs/unseen/eval/smoke1
.venv/bin/python scripts/analyze_unseen.py --input runs/unseen/eval/smoke1/results.jsonl \
    --protocol plans/unseen_v2_protocol_smoke.json --out runs/unseen/eval/smoke1
```

## 6. 未完成项与原因

| 缺失 | 已排查 | 外部阻塞 | 下一条命令 |
| --- | --- | --- | --- |
| 候选配准合格 | A1 实测 IoU 0.0077、P95 103 mm | 否 | 实现 E1（24 朝向）/E3（有界比例）后重评 |
| H5 闭环与页面 | 依赖合格候选 | 否 | 有合格候选后 `unseen_pipeline.py --hyp-source H5` |
| 正式协议与 8 方法矩阵 | 评测器/分析器已通 | 否 | 写 `plans/unseen_v2_protocol.json` |
| P1/P2 v2 重跑 | 动作已接线 | 否 | 重跑 `gate_physics.py` |
| 演示视频、统一自验 | — | 否 | `verify_unseen.py` + 录屏 |

**为什么候选不合格**：11 个候选横向尺寸都停在 0.08–0.12 m，观测可见宽为 0.34 / 0.62 m；
B 组全部 <15 mm 厚。等高等比缩放后必然偏窄。可能是生成模型对白底剪影输出扁片、
也可能是局部观测信息不足或需各向异性配准——**当前证据不支持单一归因**，
需 E1/E3 受控对照后才能判定。

## 7. 能力边界

- 不声称机器人能猜出真实背面；不声称 H5 已可用。
- 页面展示的仍是 H3 记录，不是新候选。
- 相机为离地 0.16 m 的低置虚拟机载相机，不是真的"蹲下观察"动作。
