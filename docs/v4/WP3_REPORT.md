# WP3 想象体检报告（首批）

- 执行基线：`8cfbc6c76`（V4.1 接收）；准入配置 `configs/v4_admission.json`。
- 本轮问题：首批 36 个任务能否真实提交并取回；输入/视角身份是否可追溯。
- 判定：任务提交、返回 GLB、ledger 记账齐全；准入评估在下一分片继续。

## 输入与任务

- 8 岩石 × 3 视角（偏航 0°、+25°、−25°）× 3 裁剪（raw/white/masked）× 2 采样 = 144 任务。
- 视角由真实扫描网格重新渲染（1600×1200，fovy 45°，相机高度/距离沿用），
  裁剪 512×512，原生目标高度 ≥512 px 后仅缩小、不放大。
- 首批优先 `moon_rock_05`（支撑 len_short/len_mid）与 `moon_rock_01` 全部 36 任务。

## 首批结果

- 提交 36；返回 34 GLB；9 个任务被服务端拒绝（重试后仍失败，`retry` 事件保留）。
- 任务号范围：4683782–4684297（34 个成功任务号见 ledger）。
- 原始 GLB 示例 sha256：`33dd7b7b…`、`bbd9cd0e…`（完整列表在 ledger）。
- 已评估/准入：0/34（本轮只完成取回；配准-融合-准入在下一分片执行）。

## 未做到

- 后 108 个任务（moon_rock_02/03/04/06/07、rock_07）尚未提交；
- 34 个 GLB 尚未过 §2.4 准入与体检测量。

## 证据

- `runs/v4/wp3/tasks.json`、`task_manifest.json`、`ledger_first36.jsonl`
- `runs/v4/wp3/wp3_batch1.tgz`（视角图与裁剪图，59 MB）
- `configs/v4_admission.json`、`docs/v4/WP3_ADMISSION.md`
