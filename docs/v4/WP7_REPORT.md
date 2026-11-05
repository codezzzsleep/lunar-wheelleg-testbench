# WP7 展示墙素材报告（3/6）

| 场景 | 动作 | 结果 | 用时 | 记录 |
| --- | --- | --- | --- | --- |
| A1 平地巡航 10 m | R1 | pass | 15.12 s | `runs/v4/wp7/A1_cruise_10m` |
| A3 8° 缓坡 5 m | R1 | pass，最大倾角 2.87° | 8.98 s | `runs/v4/wp7/A3_slope8` |
| B1 开阔巨石绕行 | D2 | pass | 7.14 s | `runs/v4/wp7/B1_boulder_detour` |
| A2 碎石区 | R1 | **failed：tipped 60°** | 7.08 s | `runs/v4/wp7/A2_gravel`（未计入完成） |

- 修复：`runner.py` 的 `FIELD_X_MAX=3.95` 硬编码导致 10 m 巡航在 x=3.97 被误判 `out_of_field`；
  改为读取 `env.field_x_max` 后 A1 通过。
- 碎石场景两次尝试（岩块高度 0.10/0.05 m）均在 x≈4.73、t=7.08 s 翻车 60°，说明碰撞体
  与视觉碎石不一致或过陡；暂不计入 6 场景，下一轮重做。
- 未完成：A4 轮式/抬轮对比、B2 一侧坑绕行；共 3/6 完成。
