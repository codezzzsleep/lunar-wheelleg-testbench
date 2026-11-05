# M0 找回并持久化全部 Lux3D 结果

## 本步问题

按 ledger 枚举全部 Lux3D 任务，校验 sha256，取回或重生成，并把结果与输入图上传 Release `v6-showcase`。

## 命令

- `python3 scripts/v6_m0_audit.py`
- `python3 scripts/v6_m0_manifest.py`
- `python3 scripts/v6_upload.py`

## 结果表

| 来源 | 任务数 | 已恢复 | 失联 |
| --- | --- | --- | --- |
| v3 生成缓存 | 84 | **75** | 9 |
| WP3 | 144 | 0 | 144 |
| V5 C2（rock_07 曝光） | 6 | 0 | 6 |
| 合计 | **234** | **75** | **159** |

- 75 份恢复的 GLB 已逐个校验 `sha256` 与缓存 `meta.json` 一致；正在上传 `v6-showcase`（资产名 `v6__lux3d__<id>.glb`）。
- 原输入图：234 个任务全部找不到本地输入（路径原为旧沙箱 `/workspace/work/lunar-lab/runs/...`），`input_sha_ok` 全为 false。
- 任务号：只有 `runs/v4/wp3/ledger_first36.jsonl` 的 34 个 WP3 任务与主机 ledger 的 5 个任务保留 `task_id`；其余 195 个连任务号也没有。
- 旧沙箱已回收，`/tmp/aholo.env` 与新沙箱均无 API 密钥，无法用任务号 `fetch_result`，也无法用原图重新提交。

## 未做到

- 159 个任务未恢复：144 WP3 + 6 C2 + 9 v3。
- 输入图一份都没有。
- Release 上传只覆盖 75 份 GLB；`assets/v3/rocks` 原始网格/贴图尚未上传。

## 根因（§6.1 触发）

- 任务的输入图、GLB、任务号都只存在于旧沙箱；旧沙箱在 M0 之前被自动回收。
- 恢复需要 Lux3D API 密钥，但密钥只在旧沙箱的 `/tmp/aholo.env`，主机与新沙箱都没有；没有密钥既不能按 task_id 取回，也不能重提。
- 这是**存储与凭据**问题，不是生成或校验代码问题。

## 证据

- `dist/v6/m0_audit.csv`（234 行，逐任务状态）
- `dist/v6/lux3d_manifest.json`（234 条，含 task_id/来源/rock/view/crop/输入 sha/GLB sha/Release 名/状态）
- `/tmp/v6upload.log`（上传记录，进行中）

## 下一步

按 §6.1 停下回报。要完成 M0 需要其一：
1. 提供可用 Lux3D API 密钥（可放环境变量），我用保留的 34+5 个 task_id 先取回，再用 ledger 原图重提其余任务；
2. 或恢复旧沙箱的 `runs/v3/generation/cache`、`runs/v4/wp3/crops`、`/tmp/aholo.env`；
3. 否则 M0 只能保留 75 份恢复结果，后续 M1–M3 无法按全集执行。
