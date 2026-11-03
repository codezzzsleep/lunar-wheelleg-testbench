# STAGE003 通过终点逐条核对

动作名称：**CLIMB + 末段恢复（含 RL 轮式助爬）**；不把它改名为 BODY_CLEARANCE，
也不把 RL 的轮式助爬说成准静态抬腿。

| 终点项 | 状态 | 证据 |
| --- | --- | --- |
| 1. nominal 下三个真实初态 3/3 | **通过** | `s4_state1f/2e/3`，24/24 × 3；qpos dfea15f0 / 264be46e / 7e321110 |
| 2. 共同终态与预算下的完整轮式对照 | **通过** | `s5_wheel` 6/6（R1 0.30 / R2 0.15 × 三初态），同一终态函数 |
| 3a. 全轨迹（≥50 Hz） | **通过** | `s4_state1f/record` 2929 帧；字段见 `record_check.json` |
| 3b. 关键快照 | **通过** | `support4/state.json`（四轮支撑）、`s1_rigid/endgame_state.json` |
| 3c. 三维回放 | **通过** | `replay/leg_state1.mp4`、`wheel_state1_r1.mp4`、`side_by_side_state1.mp4` |
| 3d. 新目录可复现离线包 | **通过（wheel）/待确认（all）** | `dist/stage003_bundle.tar.gz`；wheel exit 0；all 测试进行中 |
| 4. 代码与小证据已推送，包 SHA 明确 | **通过** | commit 见各段；tar sha256 3347bf9b… |
| 5. 不宣称腿式/Lux3D 增量价值 | **遵守** | 本场景轮式 6/6 且更便宜（14.6–28.3 s vs 56.8–58.7 s） |

## 失败与缺口（不隐藏）

- RL 是轮式助爬上台，不是准静态抬腿；动作名称已如实标注。
- 末段恢复（level_roll/body_down/preload）是结构 A 的开发实现，参数为开发几何下调出。
- 记录缺口：相位仅 result.json 边界、轮模式只有 brake 标志、逐轮载荷需反推。
- 未做：BODY_CLEARANCE、SIDE_LEVEL（不属本批必需），20 m 路线，软土脱困，Lux3D。
