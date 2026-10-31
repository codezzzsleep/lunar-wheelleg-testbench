# 沙箱作业运维规则（踩过的坑，强制遵守）

## 1. 沙箱里的进程不会唤醒我

在 CNB 沙箱里 `setsid ... &` 起的任务，**不在 DSH 的后台作业列表里**，
它跑完不会产生任何通知。我如果只是"等下一回合再看"，就会一直空等。

**正确做法：把沙箱任务桥接成本地后台作业。**

```bash
# 本地用 DSH 的后台作业机制跑这个脚本（run_in_background），
# 它内部阻塞地等远端进程结束，结束时本地作业完成 -> 我才会被唤醒
bash scripts/cnb_wait.sh <remote-pgrep-pattern> <remote-output-path> <local-dest>
```

要点：
- 本地作业用 `run_in_background: true` 启动，**不要**裸 `setsid`；
- 脚本内部 `ssh` 前台轮询远端 `pgrep`/产物是否存在，结束后 `scp` 回传；
- 回传后打印 JSON 摘要，作为本地作业的输出。

## 2. 重计算只在沙箱跑

本机 8 GB，且与 `deepseek-harness.service` 同一个 cgroup：本地 python 冲到 7 GB 会触发
global OOM，把 worker 一起杀掉（dmesg 里 10/29–10/31 共 8 次）。
`collision_occupancy_metrics.py` / `v7_measure_candidate.py` 会在 `MemAvailable < 8 GB` 时
直接拒绝，除非加 `--allow-local`。

## 3. 沙箱会被回收（无活动连接约 10–12 分钟）

长任务必须持 SSH 会话保活；`scripts/cnb_run.sh` 已内建。

## 4. 一个回合只推进一件事

不要在一个回合里串多个小时的 `sleep` 轮询：回合被外部结束（OOM/关闭超时）时，
本地子进程全部丢失，之前所有等待作废。
