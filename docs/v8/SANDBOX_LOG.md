# V8 沙箱作业记录

“推送提交号”列按 `git log` 回填（2026-11-11 核对）；本次本机补跑见文末两行。

| 沙箱 id | 开始 | 结束 | 命令 | 拉回目录 | 文件数/总字节 | sha 校验 | 推送提交号 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:26+08:00 | 2026-11-08T03:28+08:00 | `v8_run.py --policy conservative --max-looks 5` | `runs/v8/main/` | 26 文件 / 57 MB | 逐文件一致 | `af7f3ecd2` |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:30+08:00 | 2026-11-08T03:31+08:00 | `v8_run.py --policy optimistic` | `runs/v8/main/` | 68 MB | 逐文件一致 | `b4c6e6aaf` |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:46+08:00 | 2026-11-08T03:47+08:00 | `v8_run.py --policy conservative --see-dark --max-looks 5 --tag conservative_seedark` | `runs/v8/main/` | — | 逐文件一致 | `a8c634d3c` |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:50+08:00 | 2026-11-08T03:51+08:00 | `v8_run.py --policy imagination --imagine truth --tag imagination_truth` | `runs/v8/main/` | — | 逐文件一致 | `b107d3a42` |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:53+08:00 | 2026-11-08T03:54+08:00 | `v8_run.py --policy imagination --imagine lux`（退出 10，请求 look1 两块的 6 份） | `runs/v8/main/`（imagination 67 MB，41 文件） | — | 逐文件一致 | `1f4aa61df` |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T05:59+08:00 | 2026-11-08T06:06+08:00 | `v8_run.py --policy imagination --imagine lux`（第二次退出 10，停在 look3） | `runs/v8/main/`（612 MB） | — | 逐文件一致（不含 lux_cache） | `13cf2fbd8` |

## 2026-11-11 本机补跑（无 GPU，OSMesa 软件渲染）

本机没有 GL，用 `apt-get download` + `dpkg -x` 解出 Mesa 到 `/tmp/glroot`，
`LD_LIBRARY_PATH=/tmp/glroot/usr/lib/x86_64-linux-gnu MUJOCO_GL=osmesa`。

| 机器 | 开始 | 结束 | 命令 | 退出码 | 结果 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| 本机 | 2026-11-11T20:36+08:00 | 20:39 | `v8_run.py --policy imagination --imagine lux` | **11** | look1 逐字节复现、复用沙箱 Lux3D；look2 重放差 0.19 mm → `replay_mismatch` | 见 `imagination/looks/look2/REPLAY_DIFF.json` |
| 本机 | 2026-11-11T20:41+08:00 | 20:42 | `v8_run.py --policy imagination --imagine lux --trust T2=C1 --tag counterfactual_T2_C1` | **0** | `result=collision`、撞 `obstacle1`（t=89.18 s）、规划期 `drive_margin_m=-0.23` | `counterfactual_T2_C1/` |
| 本机 | 2026-11-11T21:30+08:00 | 21:31 | `v8_run.py --policy imagination --imagine lux --accept-replay-drift` | **0** | `result=stuck`、`looks=2`、52.72 s、无碰撞；look2 决策仍 `imagined_blocked`（T2 三份候选 0/3 准入）→ 按 SPEC §0.4 停车 | `imagination/`（含 `summary.replay_drift_accepted` 与 `looks/look2_replay/`） |

两次本机运行都**没有调用 Lux3D**（`AHOLO_API_KEY` 未设置；复用判定命中即用已有结果）。
