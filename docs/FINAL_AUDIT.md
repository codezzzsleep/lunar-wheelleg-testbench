# 交付终审（第 30 轮）

## 文档清单

| 文件 | 作用 | 状态 |
| --- | --- | --- |
| `docs/G6_DELIVERY.md` | 最小可复现交付页 | 存在 |
| `docs/G6_STATUS.md` | 状态矩阵 | 存在 |
| `docs/BOUNDARY.md` | D/E 能力边界 | 存在 |
| `docs/EVIDENCE_INDEX.md` | 57 run 自动索引 | 存在 |
| `docs/CONSISTENCY.md` | 15 项一致性检查 | 存在 |
| `docs/D_FAILURE_REPORT.md` | CLIMB 最小失败报告 | 存在 |
| `docs/E_CASES.md` | E 三案例 | 存在 |
| `docs/D2_ROCK_SUMMARY.md` | 真实岩石动作矩阵 | 存在 |
| `docs/CURRENT_STATUS.md` | 交接/状态页 | 存在 |

## 自动核对

- `scripts/v3_consistency.py`：**15/15 通过**。
- git 工作区：tracked-dirty **0**；HEAD `452b78fcfff65844768a13374828d388bceff7b3`。

## 链接检查

- `scripts/v3_link_check.py`：docs 中 6 个相对链接，缺失 0（`docs/LINK_CHECK.md`）。

## 仍成立的外部阻塞

- `dist/v3_bundle` 旧批次；`plans/unseen_delivery_v5.json` 与 `build_delivery_v5.py`
  的 `work_packages` 格式不兼容，无法直接重建。
- 发布通道缺 git-lfs/gh/token；`dist/publish/PUBLISH_STATUS.json` 仍为
  `blocked_on_release_channel`（code_sha 为旧值，原因仍成立）。

## 不应被误读的结论

- A/B/F 通过；C 部分；D 未通过；E 无正例。
- S1 原始 1/2、扰动 2/3；CLIMB 未完成；20 m 路线为纯轮式。
