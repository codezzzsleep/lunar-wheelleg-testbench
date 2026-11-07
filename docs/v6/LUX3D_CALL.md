# Lux3D 调用规程（REVIEW_R3 §2 收尾项）

本文件规定本项目所有 Lux3D 调用的提交、轮询、下载、记账与结果落盘方式。密钥只从环境变量读取，不写入任何文件。

## 1. 环境

- `AHOLO_API_KEY`：唯一密钥来源，仅进程环境；
- 默认模型：`G1-Turbo`，`faceCount=30000`；
- 所有调用在本地执行（负责人 4 核 8G 机器），沙箱不做 Lux3D 调用；
- 每次调用必须进账本 `runs/v3/generation/ledger.jsonl`。

## 2. 任务文件

```json
{
  "schema": "v3-generation-tasks/v1",
  "n": 6,
  "tasks": [
    {
      "id": "v7_route_E1_A1",
      "state_id": "v7_route_E1",
      "variant": "A1",
      "repeat_idx": 0,
      "image": "runs/v7/route_full/E1/look1/inputs/A1.png",
      "image_sha256": "...",
      "model": {"version": "G1-Turbo", "face_count": 30000},
      "create_order": 1,
      "estimated_credits": 20.0
    }
  ]
}
```

- `id` 必须唯一；身份 = `sha256(variant\nversion\nface_count\nrepeat_idx\nimage_sha256)`；
- 同一图像重复提交会命中缓存，不再创建新任务；需要新调用时换 `id`/`variant`，不得改输入图。

## 3. 提交与轮询

```bash
AHOLO_API_KEY=... python3 scripts/v3_generate.py \
  --tasks <tasks.json> --submit --workers 3
```

- `--submit`：创建缺失任务并下载；
- `--resume`：只对已创建未取回的任务轮询；
- 服务端 `GENERATION_CONCURRENCY_LIMIT_EXCEEDED` 时降低并发或等待后重试；
- 状态码：3 = 成功，4 = 服务端失败；
- 服务端失败允许重提一次，`retry_of` 指向原任务；仍失败在结果中记 `status=failed`，流程继续；
- 不得替换输入图、不得挑选候选。

## 4. 下载与存储

- 缓存：`runs/v3/generation/cache/<identity>/model.glb` 与 `meta.json`；
- V7 正式资产：`assets/v7/lux/<task_id>/tex_mesh.glb`（LFS）；
- 每次下载写 ledger：`event=downloaded`，含 `identity`、`task_id`、`glb_sha256`、`total_seconds`、`consumed_credits`；
- 拉回本地后按 sha256 校验，再提交并推送。

## 5. 曝光规则

- 沿用 V5：输入图均值 < 100 才提亮（`v3_obs` 规则）；
- 影子实验的输入一律**不**提亮，暗是实验条件本身。

## 6. V7 路线请求与结果

路线遇到需要 Lux3D 时写出 `lux_request.json`（`schema=v7-lux-request/v1`），字段：

- `mode`：`img`（每个 item 一张图，6 个任务）或 `imgs`（每个 item 两张图，3 个任务）；
- `items`：`[{id, path}]` 或 `[{id, paths:[p1,p2]}]`；
- `result_file`：结果 JSON 的仓库相对路径；
- `result_schema`：本节末的结果格式。

### 6.1 `imgs` 模式（真实两图）

- 一个 item = **一个 Lux3D 任务**；
- 请求体字段 `imgs` = `[paths[0] 的 URL, paths[1] 的 URL]`，**顺序不能换**，且**不带** `img` 字段；
- 调用 `scripts/lux3d_client.submit_img_to_3d_multi(img_urls, version='G1-Turbo', face_count=30000)`，做法同 `scripts/v7_generate.py`；
- **禁止**把两张图拼成一张组合图提交；
- 同一请求里路径相同的 item（如 M1–M3）是独立采样，必须各用一个 sample id，避免命中文件缓存；
- 每张图先走 `upload_image` 拿 URL，再按顺序传入。

### 6.2 结果格式

```json
{
  "tasks": [
    {
      "id": "A1",
      "task_id": 123456,
      "status": "ok",
      "submitted_at": "2026-11-07T10:00:00+08:00",
      "finished_at": "2026-11-07T10:06:00+08:00",
      "fetched_at": "2026-11-07T10:06:10+08:00",
      "glb": "assets/v7/lux/123456/tex_mesh.glb",
      "glb_sha256": "...",
      "inputs": ["runs/v7/route_full/E2/look1/gen/variants/A1.png", "runs/v7/route_full/E2/look2/gen/variants/A1.png"],
      "api_field": "imgs",
      "n_images": 2
    }
  ]
}
```

- `status` 只允许 `ok` / `failed`；
- 路径一律仓库相对路径，不得写绝对路径；
- `inputs` 写**实际上传**的文件路径与顺序；
- 两图任务必须写 `api_field: "imgs"`、`n_images: 2`，否则 `v7_route.py` 会报错停止；
- 失败任务也写入结果，`status=failed`，不生成 `glb`。

## 7. 影子实验

- 12 个条件 × 6 个任务 = 72 个任务一次性提交（负责人 R3 补充）；
- 每个条件 `lux_request.json` 在 `runs/v7/shadow_exp/<rock>/<sun>/`；
- 结果写各自 `result_file`；
- 评估统一由 `v7_shadow_exp.py --evaluate` 完成，不手工改结果。

## 8. 记账与回报

- 每次提交/下载后，把任务数、成功数、失败数、平均耗时写入 `docs/v7/STATUS.md`；
- 账本异常（缺 `task_id`、重复 identity、未记账）必须先修复再继续；
- 不在沙箱保存唯一 Lux3D 副本。
