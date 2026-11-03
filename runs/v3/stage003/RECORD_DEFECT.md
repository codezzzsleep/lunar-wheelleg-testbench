# 受记录器别名缺陷影响的旧记录（不覆盖）

缺陷：`frame_from_env` 把 `d.qpos/d.qvel/d.actuator_force` 的 **view** 入队，flush 前
仿真步会原地改写这些数组，导致同一 chunk 内多帧显示同一（最后一个）状态。

受影响目录（保留原样，仅标注）：
- `runs/v3/route/nominal_r1/record`（50 Hz 路线记录，10 Hz 子采样由它派生）
- `runs/v3/stage003/s2_full_nominal_r1/record`
- `runs/v3/stage003/s4_state1f|s4_state2e|s4_state3/record`（旧 S4 三次）
- `runs/v3/stage003/s5_wheel_rec/record_*`（旧轮式 6 次）
- `runs/v3/stage003/wheel_state1_r1/record`（旧轮式 state1 拷贝）

替代：`fix_leg_state1|2|3`、`fix_s5_wheel`（新目录，修复后重新采集）。
