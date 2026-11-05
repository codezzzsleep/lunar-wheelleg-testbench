# WP7 展示墙素材报告（4/6）

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

## A4 同段 5 m：轮式 vs 抬身通过

- 场景：`runs/v4/wp7/A4_scene.json`，目标 5 m。
- 轮式 R1：**8.82 s**，success。
- 抬身 BODY（抬 0.08 m，轮速 4.65 rad/s）：**21.12 s**，success。
- 结论：同段平地上轮式比抬身快约 2.4×，可用于展示墙“平时用轮子更省”。
- 注：BODY 是连续抬身，不是离散轮步；不冒充 SPEC 的“轮式与抬轮步进”离散对比。

## B2 一侧坑：被地形坑符号 bug 阻塞

- 用 `terrain.make_spec(pits=1, pit_depth=0.30)` 建场，`build_heightfield` 返回
  `actual_min_m=0.0, actual_max_m=0.297`，即“坑”被归一化成了 **0.30 m 的凸包**；
  物理地面没有坑，D2 只是从平地上绕过。
- 若把这次运行当 B2 通过，就是拿凸包冒充坑；已停止，不计入。
- 需要先修 `terrain.build_heightfield` 的坑编码（当前 `h -= h.min()` 把负高度翻成正值），
  再重做 B2。
- 因此 WP7 仍为 4/6。
