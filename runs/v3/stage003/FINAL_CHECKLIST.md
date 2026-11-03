# STAGE003 通过终点逐条核对

动作名称：**CLIMB + 末段恢复（含 RL 轮式助爬）**；不把它改名为 BODY_CLEARANCE，
也不把 RL 的轮式助爬说成准静态抬腿。

| 终点项 | 状态 | 证据 |
| --- | --- | --- |
| 1. nominal 下三个真实初态 3/3 | **通过** | `s4_state1f/2e/3`，24/24 × 3；qpos dfea15f0 / 264be46e / 7e321110 |
| 2. 共同终态与预算下的完整轮式对照 | **通过** | `s5_wheel` 6/6（R1 0.30 / R2 0.15 × 三初态），同一终态函数 |
| 3a. 全轨迹（≥50 Hz） | **通过（修复后重采）** | `fix_leg_state1|2|3` 2929/2936/2838 帧，last_t 与执行结束一致；轮式 `fix_s5_wheel2` 6/6 record_consistent；旧记录已标 `RECORD_DEFECT` |
| 3b. 关键快照 | **通过** | `support4/state.json`（四轮支撑）、`s1_rigid/endgame_state.json` |
| 3c. 三维回放 | **通过（按时间戳重渲）** | `replay_fix/leg.mp4` 58.57 s、`wheel.mp4` 14.70 s（真实执行全程）、`side_by_side.mp4` 1920×1080/58.57 s |
| 3d. 新目录可复现离线包 | **通过（修复后重建）** | `dist/stage003_bundle.tar.gz` sha256 `355f3627…`；新目录 MANIFEST 277/277、`all` exit 0；leg/wheel/side 均 1920×1080 |
| 4. 代码与小证据已推送，包 SHA 明确 | **通过** | commit 见各段；tar sha256 3347bf9b… |
| 5. 不宣称腿式/Lux3D 增量价值 | **遵守** | 本场景轮式 6/6 且更便宜（14.6–28.3 s vs 56.8–58.7 s） |

## 失败与缺口（不隐藏）

- RL 是轮式助爬上台，不是准静态抬腿；动作名称已如实标注。
- 末段恢复（level_roll/body_down/preload）是结构 A 的开发实现，参数为开发几何下调出。
- 记录缺口：相位仅 result.json 边界、轮模式只有 brake 标志、逐轮载荷需反推。
- 未做：BODY_CLEARANCE、SIDE_LEVEL（不属本批必需），20 m 路线，软土脱困，Lux3D。


## 记录器修复（2026-11-03 晚）

- 缺陷：`frame_from_env` 把 `d.qpos/d.qvel/d.actuator_force` 的 view 入队，flush 前被仿真步改写。
- 修复：采样时 `copy=True`，`Recorder.add` 入队再深拷贝 ndarray/contacts。
- 生产入口自测 `v3_record_selftest`：每帧采样后原地改 qpos/qvel/actuator_force，
  落盘 qpos 与采样快照 **diff = 0.0**。
- 重采：腿式 `fix_leg_state1|2|3`（3/3，24/24）；轮式 `fix_s5_wheel2`（6/6，
  6/6 record_consistent，last_t == time_s）。
- 旧记录不覆盖，全部标 `RECORD_DEFECT.json`；清单见 `RECORD_DEFECT.md`。
