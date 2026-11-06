# M3 连续任务路线（E1 已跑通，E0/E2 未做）

## 本步问题

以 WP8 v2 20 m 路线为骨架，做 E0 碎石、E1 想象被采纳、E2 全拒→第二眼三遭遇；
每个遭遇现场调用 Lux3D，按 V5 公共评估做决策与执行；FULL 与 OBS_CONS 各一次全程。

## 命令

- `python3 scripts/v6_m3_step2.py`（机头相机拍摄）
- `python3 scripts/v6_m3_e1_lux.py`（现场 6 个 Lux3D 任务）
- `python3 scripts/v6_m3_e1_admit_local.py`（本地配准/准入）
- `python3 scripts/v6_m3_e1_exec.py`（FULL 融合、3/3 预演、决策、执行、继续路线）

## 结果表

### E1 观测与想象

| 项 | 值 |
| --- | --- |
| 观测停车点 | x=7.82 |
| 岩石位置 | x=9.0（obstacle0） |
| 岩石掩码 | 23766 px |
| Lux3D 任务 | 6/6 下载 |
| 准入 | **1/6** |
| 通过候选 | rear −3.2 cm，path P95 120 mm，scale 1.05，contour 0.71，shell 0.61 |

### E1 FULL 决策与执行

| 项 | 结果 |
| --- | --- |
| 3/3 预演安全集 | R1、R2、L1、L2（BODY 失败） |
| 决策 | **R1**（最便宜的安全动作） |
| 执行 | **pass，52.48 s** |
| 路线终点 | **x=21.02，termination=success** |

### E1 OBS_CONS 对照

| 项 | 结果 |
| --- | --- |
| 3/3 安全集 | R1、R2、L1、L2（BODY 失败） |
| 决策 | **L2** |
| 执行 | **pass，52.44 s** |
| 路线终点 | **x=21.02，success** |

- 两臂都通过；FULL 选 R1、OBS 选 L2，动作不同但结局相同。
- 这说明 E1 这一遭遇没有产生“想象改变结局”，只是改变了动作。

- 这是真实连续执行：从 x=7.82 直接开到 x=21.02，中间没有再摆状态。
- E1 的想象只有 1 份通过，FULL 最终仍选直行 R1；没有发生“绕行”决策。

## 未做到

- **E0 碎石**：未做。
- **E2 全拒→第二眼 imgs**：未做。
- **OBS_CONS 全程**：未做。
- 路线执行没有逐帧记录（只有结果 JSON），M4 还不能打包。
- E1 的 KA6 只做了顶点落掩码比例 0.55，不是 §4 的 IoU ≥0.95 验收。

## 根因

- E1 已打通“现场拍照→Lux3D→本地配准→准入→融合→预演→决策→连续执行”；
  缺的是另外两个遭遇和 OBS 对照，以及执行轨迹记录。
- 不是配准或相机问题（机头相机位姿由 `cam_xpos/cam_xmat` 回读，岩石掩码正常）。

## 证据

- `runs/v6/m3/E1/observation2/`
- `runs/v6/m3/E1/admission_local.csv`
- `runs/v6/m3/E1/full/result.json`、`rehearsal/`、`execution/`
- `assets/v6/m3/E1/`（6 份 GLB）

## 下一步

补 OBS_CONS 全程、E0/E2，并在执行时录逐帧轨迹；然后按 §3 打包、过 §4 重放、上传。
