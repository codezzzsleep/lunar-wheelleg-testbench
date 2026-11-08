# V7 沙箱作业记录

| 沙箱 id | 开始时刻 | 结束时刻 | 命令 | 拉回的目录 | 文件数与总字节 | sha 校验 | 推送提交号 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T13:58+08:00 | 2026-11-07T14:04+08:00 | `python3 scripts/v4_regress.py`；`python3 scripts/v7/ka9_detour_wiring.py` | `runs/v4/regress/` | 2 个 JSON，约 1.6 KB | 本地复算一致 | 待提交 |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T14:06+08:00 | 2026-11-07T14:17+08:00 | `MUJOCO_GL=egl python3 scripts/v7/v7_route.py --arm obs --run runs/v7/route_obs` | `runs/v7/route_obs/` | 8568 个文件，189 MB | 与沙箱 sha256 清单逐文件一致 | 待提交 |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T14:30+08:00 | 2026-11-07T14:33+08:00 | `MUJOCO_GL=egl python3 scripts/v7/v7_shadow_exp.py --prepare --out runs/v7/shadow_exp` | `runs/v7/shadow_exp/` | 195 个文件，209 MB | 与沙箱 sha256 清单逐文件一致（195/195） | 待提交 |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T14:30+08:00 | 2026-11-07T14:33+08:00 | `v7_shadow_exp.py --prepare`（同上，补充 Lux3D 阶段说明） | `runs/v7/shadow_exp/` | 195 文件 / 209 MB | 逐文件一致 | 2eaf49a5a |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T17:05+08:00 | 2026-11-07T17:43+08:00 | `python3 scripts/v7/v7_shadow_exp.py --evaluate --out runs/v7/shadow_exp` | `runs/v7/shadow_exp/`（含 12 个 eval/rows.json、eval_rows.json、summary.json） | 72 行评估 + 12 条件汇总 | 与沙箱一致 | 待提交 |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T17:50+08:00 | 2026-11-07T19:03+08:00 | `MUJOCO_GL=egl python3 scripts/v7/v7_route.py --arm full --run runs/v7/route_full`（三次续跑，退出 10/10/0） | `runs/v7/route_full/` | 21365 个文件，424 MB | 逐文件一致 | 待提交 |
| cnb-cu4-1k6pbstk8-001 | 2026-11-07T19:46+08:00 | 2026-11-07T21:11+08:00 | `MUJOCO_GL=egl python3 scripts/v7/v7_route.py --arm full --run runs/v7/route_full_r2 --reuse-lux runs/v7/route_full`（三次续跑，退出 10/10/0） | `runs/v7/route_full_r2/` | 21498 个文件，592 MB | 逐文件一致 | edea14392 |
| cnb-lne-1k6r7ufaq-001 | 2026-11-07T23:32+08:00 | 2026-11-07T23:34+08:00 | `MUJOCO_GL=egl python3 scripts/v7/v7_scale_truth.py --run runs/v7/route_full_r2` | `runs/v7/route_full_r2/scale_truth_v72.json` | 1 个文件 | 逐字节一致 | 待提交 |
| cnb-lne-1k6r7ufaq-001 | 2026-11-07T23:34+08:00 | 2026-11-08T00:01+08:00 | `MUJOCO_GL=egl python3 scripts/v7/v7_redecide.py --run runs/v7/route_full_r2 --out runs/v7/route_full_r2_v72` | `runs/v7/route_full_r2_v72/` | 17644 文件，305 MB | 逐文件一致 | 待提交 |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T06:14+08:00 | 2026-11-08T06:22+08:00 | `v7_determinism.py --span 32/4 --repeat 2` | `runs/v7/determinism_e1_span{32,4}/` | 81 MB | 逐文件一致 | 0976b59d1 |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T06:30+08:00 | 2026-11-08T07:18+08:00 | `v7_redecide.py --run runs/v7/route_full_r2 --out runs/v7/route_full_r2_v73` | `runs/v7/route_full_r2_v73/` | 17497 文件 / 272 MB | 逐文件一致 | 84b212092 |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T08:05+08:00 | 2026-11-08T08:45+08:00 | `v7_shadow_exp.py --evaluate` | `runs/v7/shadow_exp/` | eval_rows 72 行 + summary | 逐文件一致 | 待提交 |
