# V8 状态

- 安装：`c3bb5848f`（`v8: polar corridor, three robots, dark-aware self-check`）；V8 与 V7.3 的补丁清单分别校验通过（根 `PATCH_SHA256.txt` 为 V8，V7.3 在 `docs/v7/PATCH_SHA256_v73.txt`）。
- 沙箱：`cnb-0fp-1k6rn0am3-001`，8 核，`mujoco==3.17.0`，另需 `matplotlib`（V8 真值占地检查用）。
- §2 第 1 次（conservative，`--max-looks 5`）：`result=stuck`、`looks=5`、`sim_time_s=142.2`、`wall_s=32.5`，与预期一致。
- §2 第 2 次（optimistic）：`result=collision`、`looks=1`、`drive_margin_m=-0.23`、`sim_time_s=83.44`，与预期一致（撞上 B 藏在黑影里的一截，重叠 23 cm）。
- §2 第 3 次（conservative_seedark）：`result=arrived`、`looks=3`、`sim_time_s=147.26`，与预期一致（黑影里能测深度时 3 眼通过）。
- §2 第 4 次（imagination_truth）：`result=arrived`、`looks=1`、`drive_margin_m=0.117`、`sim_time_s=115.88`，与预期一致。
- §2 四次运行全部与 SPEC §2 预期表一致。
- §3.1 想象的车第一眼：退出码 **10**，`NEED_LUX3D.json` 列出 `look1/T1/lux_request.json` 与 `look1/T2/lux_request.json`。
