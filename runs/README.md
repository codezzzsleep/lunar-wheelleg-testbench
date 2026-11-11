# 批次索引

`runs/` 共 58 个批次目录：下面 8 个是主要批次，其余 50 个是第二轮一次性批次（`R_*`、`train_*`、`smoke_*`、`skill_*`、`pg_v2` 等），基本 0 引用，可以整批忽略（这 50 个里还夹着 `archive*`、`_archive_canonical_*` 这类本地归档目录）。

| 批次 | 首提交日期 | 磁盘占用 | 一句话内容 | 被交付文档引用 |
|---|---|---|---|---|
| `runs/lux3d/` | 2026-10-26 | 见实测 | Lux3D 生成账本 `ledger.jsonl` | 否（供资产溯源） |
| `runs/unseen/` | 2026-10-27 | 5.5 GB | 盲测 delivery v1–v7 | 是，引用最多 |
| `runs/v3/` | 2026-11-03 | 28 GB（含 20 GB ignored 缓存） | v3 单状态岩石与 G6 交付证据 | 是，仅历史口径 |
| `runs/v4/` | 2026-11-05 | 0.3 GB | V4 展示场景 WP 产物 | 否 |
| `runs/v5/` | 2026-11-05 | 见实测 | V5 核心规范批次 | 否 |
| `runs/v6/` | 2026-11-06 | 0.9 GB | V6 Lux3D 与碰撞保真 | 否 |
| `runs/v7/` | 2026-11-07 | 2.2 GB | V7 路线、遭遇、shadow 实验 | 是 |
| `runs/v8/` | 2026-11-08 | 0.7 GB | 当前主线：三车对照 + 想象眼 | 是 |

「首提交日期」是目录第一次进 Git 的日期，不是实验日期。引用口径 = 根 `README.md` 与 `docs/v7/STATUS.md`、`docs/v8/STATUS.md`。

## 产物不入库

新产物按 `.gitignore` 规则拦截；**历史已入库的不动**（它们在 `git status` 里显示为正常跟踪文件，不是垃圾，别手删）。

## 不要清理历史

**不要**用 `git lfs migrate` 清历史：仓库文档引用了 240 个不同的短提交哈希，重写历史会让它们全部失效。

## 删不得的 Key 产物（证据）

| 产物 | 是什么证据 |
|---|---|
| `runs/v7/shadow_exp/eval_rows.json` | V7.3 shadow 重评估逐行数据 |
| `runs/v8/main/*/` 下 `summary.json`、`events.jsonl`、`traj.npz` | 每台车的结论、事件流、轨迹 |
| `runs/v8/main/imagination/looks/look*/T*/` 下 `state.json`、`lux_result.json`、`decide/target_decision.json` | 每一眼的观测、Lux3D 结果、决策 |
| `runs/v8/main/eval.json` | V8 复盘汇总 |
