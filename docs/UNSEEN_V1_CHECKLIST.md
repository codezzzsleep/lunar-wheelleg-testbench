# V1 检查表（S01–S26）

更新：2026-10-28　基线：`271235a` → 后续提交见 `git log`

| 步骤 | 状态 | 证据 / 说明 |
| --- | --- | --- |
| S01 核对开工状态 | DONE | `git log`；工作区干净 |
| S02 复现审查发现 | DONE | 五项 before/after 见 `docs/UNSEEN_REVIEW_REPORT.md` §2 |
| S03 预算账本 | DONE | `scripts/budget.py`、`tests/test_budget.py`(16) |
| S04 客户端模式/缓存/恢复 | DONE | `tests/test_budget.py::TestModes`（7 项） |
| S05 低置相机与观测包 | DONE | `scripts/observe.py`；相机位姿由 reset 后实测；`runs/unseen/obs/final_{cal,planA,planB}` |
| S06 标定件与 CAL1 放行 | DONE | `runs/unseen/preflight/cal1_preflight.json` 全 PASS；`runs/unseen/prep/cal_object.json` |
| S07 提交 CAL1 | DONE | task **4431907**；朝向结论 uncertain → `configs/lux3d_frame.json` |
| S08 固定 A/B 计划 | DONE | `plans/unseen_v2_generation.json`（11 active + 2 disabled） |
| S09 执行 A/B 生成 | **DONE（11/11 下载）** | task 4432000…4432278；`runs/unseen/generation/generation_table.json` |
| S10 配准新候选 | RUNNING | 见 §候选质量 |
| S11 候选验收与物理化 | BLOCKED_INTERNAL | 候选比例与观测不符，需先判定坐标/形状 |
| S11-F 观测一致化 H5-F | TODO | 若 E3 判定为形状限制则启用 |
| S12 统一原始记录 | 部分 | `results.jsonl` + 动作指纹已实现 |
| S13 决策器预期键/隔离 | 部分 | 期望键校验有；真值替换测试无 |
| S14 动作与 Gate P 复验 | 部分 | 动作接线完成；P1/P2 未按 v2 重跑 |
| S15 H5 单例端到端 | TODO | 依赖合格候选 |
| S16 可操作页面 | 部分 | 旧 `app_unseen.py` 未接新候选 |
| S17 分析器严格校验 | DONE | `scripts/analyze_unseen.py` |
| S18 评测器方法决策 | 部分 | 评测器已通；Oracle 未做 |
| S19 八种方法 | 部分 | H3/B0/B1 已接；H1/H2/H4/H5/Oracle 未接 |
| S20 冻结协议 | TODO | 仅有 smoke 协议 |
| S21 正式矩阵 | TODO | — |
| S22 自动分析 | 部分 | 分析器可跑 |
| S23 演示素材 | TODO | — |
| S24 统一自验 | TODO | 旧 `verify_unseen.py` 未接新口径 |
| S25 复现与证据索引 | 部分 | `runs/unseen/delivery_v2/review_index.json` |
| S26 提交与汇报 | RUNNING | 本文档 |

## 候选质量（S10/S11 关键事实）

观测与候选的尺度/比例对照（extents 单位 m）：

| 观测 | W_vis | H_vis | H/W |
| --- | --- | --- | --- |
| A（planA） | 0.340 | 0.189 | 0.56 |
| B（planB） | 0.620 | 0.140 | 0.23 |

| 候选 | extents | 说明 |
| --- | --- | --- |
| A1 | 0.100 × 0.035 × 0.062 | 宽仅观测的 29% |
| A2 | 0.100 × 0.056 × 0.032 | 极扁 |
| A3 | 0.080 × 0.043 × 0.134 | 偏高 |
| A4 | 0.120 × 0.055 × 0.069 | — |
| A5 | 0.120 × 0.083 × 0.002 | 2 mm 薄片 |
| B1–B5 | 0.120 × 0.029–0.037 × 0.001–0.015 | 全部 <15 mm 薄片 |
| CAL1 | 0.110 × 0.062 × 0.033 | 标定件被压扁 |

**A1 的实际配准结果**（`runs/unseen/align_v2/A1.json`）：

| 指标 | 值 | 阈值 | 判定 |
| --- | --- | --- | --- |
| 尺度 | 3.4347（= H_vis / 候选高度 ×1.15） | — | — |
| mask IoU | **0.0077** | ≥0.85 | 失败 |
| 精确 vis_pt 中位 / P95 | 32.5 / **103.0 mm** | P95 ≤5.7 mm | 失败 |
| 自由空间侵入 | 0.0 | ≤0.05 | 通过（因为几乎不重叠） |

等高缩放后候选宽度 = 0.0351 × 3.43 = 0.120 m，观测可见宽 0.340 m，
只有 35%；IoU 0.0077 说明它甚至没落在观测轮廓上。

**判读（未定论，需 E1/E3 后才能归因）**：
所有 11 个候选的横向尺寸都停在 0.08–0.12 m，而观测可见宽是 0.34 / 0.62 m；
等高缩放后必然偏窄。可能是 (a) 生成模型对白底剪影输出了扁片、
(b) 局部观测本身信息不足、(c) 配准需要各向异性。当前证据不支持任何单一归因。
