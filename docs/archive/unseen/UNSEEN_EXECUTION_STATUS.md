# 执行状态（唯一事实来源）

更新：2026-10-28　基线：`1e362ed` → 本文档对应提交见 `git log`

| 包 | 状态 | 证据 |
| --- | --- | --- |
| A 预算与恢复 | **完成** | `scripts/budget.py`、`tests/test_budget.py`（16 项） |
| B1 真实深度标定 | **完成** | `scripts/calibrate_observe.py`、`runs/unseen/obs/cal_v2/calibration.json` |
| B2 自由空间 v2.1 | **完成** | `scripts/align.py`、`tests/test_freespace.py`（5 项）、`runs/unseen/align_v2/diag/freespace_counterexample/` |
| B3 标定件窄底 | **完成** | `scripts/make_calibration_object.py`、`runs/unseen/prep/cal_object.json` |
| C E0–E3 | **部分** | E0 已完成（`runs/unseen/align_v2/fixture_A_v2.json`）；E1/E2/E3 未做 |
| D1 CAL1 放行 | **未提交** | 技术条件中 (3) 自由空间、(4) 标定件、(2) 深度标定已满足；E1 未做 |
| D2 生成清单 | **未开始**（暂停） | `plans/unseen_v2_generation.json` 未建 |
| D3 候选物理化 | **部分** | `scripts/physicalize.py` 可用；真实候选尚未在新口径下重评 |
| D4 H5 闭环 | **未开始** | 无合格候选 |
| E1 动作接线 | **完成** | `nav_target_y` + `Detour` 真正生效；`tests/test_detour.py`（6 项） |
| E2 假设接口/评测/分析 | **完成（H3 冒烟）** | `scripts/hypotheses.py`、`unseen_eval.py`、`analyze_unseen.py`、`runs/unseen/eval/smoke1/` |
| E3 决策完整性 | **部分** | 期望键校验已实现；真值替换测试未做 |
| E4 可复现性 | **完成** | cases 改相对路径；文档去除本机路径；渲染后端按 `MUJOCO_GL` |
| F 冻结协议与主表 | **未开始** | 仅有 `plans/unseen_v2_protocol_smoke.json`（非冻结） |
| G 页面/视频/自验 | **未开始** | 旧的 `app_unseen.py` 仍在，未接入新口径 |

## 关键数字（都可从已提交文件重算）

- 全套回归：**94 项通过**（`python -m unittest discover -s tests`，约 745 s）
- 预算账本：已创建 **2** 个任务、占用上界 **40** 积分、核验扣费 **unknown**、剩余 **260 / 13 任务**
- 标定：平面误差 **0.0 mm**、横向 **5.2 mm**、轴向/欧氏比 **1.0097**
- 自由空间反例：新口径 **28.49%** 侵入（13367 px 全在原掩码外）
- 配准回归（E0）：尺度 **0.8726**（误差 0.35%）、yaw **−11.85°**（误差 0.15°）、
  精确 vis_pt P95 **0.797 mm**
- 冒烟矩阵：9 期望键全完成；B0 3/3 成功（均代价 5.7）、H3 3/3、B1 3/3 刹停（均代价 40）

## 已知缺陷与限制

1. **MuJoCo 网格资产缓存**：同一路径写不同网格会复用旧几何；已改为唯一目录。
   任何新代码都不得复用固定 `posed_tmp/mesh.stl`。
2. **绕行回位不彻底**：D1 峰值 |y| 0.587 → 终值 0.496（目标点约束），只回落约 85%。
3. **真实候选未在新口径下重评**：两个旧候选来自滚转相机输入，仅作诊断。
4. **P1/P2/P3 未重跑 v2 口径**：等待 E1 完成后统一重跑。
