# 最终交付：整批 A–F 状态

**状态：未完成整批目标（部分交付）**

起点 `b1e1488`（feat/unseen-side 已快进合入 main）。本轮新增：可用的观测包、
修好的双胞胎几何、Gate P 见证矩阵、实测评测口径。**未完成**：动作库、Gate L
（真实图生）、单例闭环、固定评测、五步页面。

## 1. 本轮新增的用户操作能力

一条能跑的"看见"链路：给定案例，用真实 MuJoCo 相机渲染机器人的正面视角，
输出 RGB / 深度 / 掩码 / 可见点云和 x_front、W_vis、H_vis 四个可见量，
数值与真值几何吻合（见下）。

## 2. 可复制执行的命令与产物

```bash
export MUJOCO_GL=osmesa
.venv/bin/python scripts/measure_robot.py --out runs/unseen/prep/r1/robot_dims.json   # exit 0
.venv/bin/python scripts/twins.py       --out runs/unseen/gate_p/p1                    # exit 0，90 个水密双胞胎
.venv/bin/python scripts/gate_physics.py --twins runs/unseen/gate_p/p1 --out runs/unseen/gate_p/w2  # exit 0，810 回合
.venv/bin/python scripts/observe.py --case cases/unseen_v1/case_A.json --out runs/unseen/obs/o1     # exit 0
```

产物：`runs/unseen/prep/r1/robot_dims.json`、`runs/unseen/gate_p/p1/{mesh,twins_meta.json}`、
`runs/unseen/gate_p/w2/{results.jsonl,summary.json}`、`runs/unseen/obs/o1/`。

## 3. C1–C4 原始统计

| 命题 | 状态 | 分子/分母 |
| --- | --- | --- |
| C1 背面改变动作结果 | **部分成立** | P2 **9/18** 正面（R1 在一个背面全成功、另一个全失败）；C1 的"改变最优选项"口径 **1/18**，未达 4/18 |
| C2 Lux3D 候选有差异且可对齐 | **未成立** | 图生 3D 未接入，**0 个新任务** |
| C3 多假设预演相对基线的收益 | **未成立** | 未做（依赖 C2 与动作库） |
| C4 主动再观察的收益 | **未成立** | 未做 |

同观测检验（P3）：最好机位下 RGB MAE **3.23**，未达 2.0 阈值 → 目前**不能**声称
"双胞胎共用同一观测"，因此 C1 的判定只在"几何不同确实改变成败"这一层成立。

## 4. 预算

新增 Lux3D 任务 **0** 个；预估与核验积分均为 **0**；缓存复用 0。
旧账本 78 为历史提交额估算，**不是当前余额**，本轮未推测余额。
剩余已授权额度未知——需要用户确认后才能启用付费生成。

## 5. 未完成项、真实阻塞与建议

| 工作包 | 状态 | 缺口 |
| --- | --- | --- |
| A 合入+测量+观测 | **部分** | 深度精度验收、四联图、默认行为兼容检查未做 |
| B 双胞胎+物理化+动作库+Gate P | **部分** | 双胞胎已流形、P2 通过；**P1/P3 未通过**，P4 未做；**动作库只有 R1/R2/L1**，无跨骑/绕行/正式 A0 |
| C 图生客户端+Gate L | **未开始** | 图生 3D 路径、上传、预算锁、缓存身份、生成与配准、Gate L |
| D 单例闭环 | **未开始** | `unseen_pipeline.py` 未写 |
| E 固定评测 | **未开始** | 协议、`unseen_eval.py`、`analyze_unseen.py` |
| F 五步页面+视频+审查包 | **未开始** | `app_unseen.py`、演示视频、`verify_unseen.py` |

**真实阻塞（按优先级）**
1. **P3 不成立**是几何构造问题（背面未内缩），不是物理问题，可自行修复。
2. **P1 不成立**是动作库问题：现有三档动作同生同死，需要跨骑/绕行才有选项分歧。
3. **Gate L 需要付费额度确认**：图生 3D 单价与已授权批次未知，未擅自提交。

**建议的下一整批目标**：先修 P3（背面内缩）→ 补动作库（S1/D1–D4/A0）→ 重跑 Gate P
→ 再接图生 3D。在 P3 通过前，任何"双胞胎同观测"的结论都不成立。

## 附录：本批修掉的问题

- 双胞胎非流形（27–48 条边）→ 高度场棱柱，90/90 watertight、非流形 0。
- 相机绕 y 轴符号错误（朝后看）→ θ = −(90−|pitch|)。
- 相机装在机体内（射线 2 cm 处命中自身）→ 移到 (0.42, 0, 0.20)。
- MuJoCo segmentation 编码不可靠 → 改为逐像素射线掩码。
- `observe.py` 里 `out` 变量与输出目录同名导致类型错误。
- `a[2]=−1` 被误当停车 → 实测 0.32 m/s，改走显式刹车（0.679 m 刹停距离）。
