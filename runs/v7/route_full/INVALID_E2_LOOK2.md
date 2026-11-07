# E2 look2 作废声明

- 本运行 `runs/v7/route_full` 的 E2 look2 提交的是**拼接组合图**（`look2/inputs/M1.png` 等由第一眼与第二眼观测横向拼成），不是一次发送两张图的 `imgs` 调用。
- Lux3D 看到的是并排的两块石头，因此该 3 个任务的结论**作废**；E1 与 E2 look1 不受影响。
- 本运行由 `runs/v7/route_full_r2` 取代；`route_full_r2` 的 E2 look2 使用 `scripts/lux3d_client.submit_img_to_3d_multi` 真实发送两张有序图片。
- 不删除任何数据；原文件保留用于追溯。
