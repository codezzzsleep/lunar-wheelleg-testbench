# 文档地图

刚拿到仓库，按顺序只读这三份：

1. `docs/DELIVERY.md` —— 交付说明与结论矩阵（证据分 A/B/C 级），正式结论 **benefit = NOT_ESTABLISHED**
2. `docs/v8/STATUS.md` —— 最新状态，当前主线 V8
3. `docs/v7/STATUS.md` —— V7 收尾

另外两份导航：`scripts/README.md`（脚本代次与坑）、`runs/README.md`（批次索引与证据）。

| 路径 | 是什么 | 现行/归档 | 该先读吗 |
|---|---|---|---|
| `docs/DELIVERY.md` | 交付说明、结论矩阵 | 现行 | 必读 1 |
| `docs/v8/` | 主线 V8 的 SPEC 与状态 | 现行 | 必读 2 |
| `docs/v7/` | V7 规范、状态、三轮复核 | 现行（已收尾） | 必读 3 |
| `docs/v6/`、`docs/v5/`、`docs/v4/` | 各代 SPEC 与 WP 报告 | 归档 | 否 |
| `docs/unseen/` | 盲测交付交接 | 归档 | 否 |
| `docs/archive/{v2,rounds,unseen,reports}/` | v2 批、轮次报告、unseen 各版状态、过期报告 | 归档（迁入中） | **否，不要当现行结论引用** |
| `docs/REVIEW_2026-11-11.md` | 2026-11-11 复核，最新一次 | 现行 | 读前三份后再查 |
| `docs/evidence/`、`figures/`、`research/`、`sources/` | 证据 JSON、图、调研、来源 | 存档 | 否 |
| 其余平铺 `docs/*.md` | 历史散文档 | 归档 | 否 |

## 三件容易踩的事

**① 8 份文档是脚本生成物**，手改会被下次运行覆盖，要改就改脚本再重跑：

| 生成物 | 生成脚本 |
|---|---|
| `CURRENT_STATUS.md`、`V3_FINAL_REPORT.md`、`V3_RESULTS_TABLE.md` | `scripts/v3_docs.py` |
| `EVIDENCE_INDEX.md` | `scripts/v3_evidence_index.py` |
| `LINK_CHECK.md` | `scripts/v3_link_check.py` |
| `CONSISTENCY.md` | `scripts/v3_consistency.py` |
| `G6_DELIVERY.md`、`G6_STATUS.md` | `scripts/v3_minimal_site.py` |

**② 三个"v7"不是一个东西**：

| 名字 | 指什么 |
|---|---|
| `runs/unseen/delivery_v7/` | 2026-10-30 起的盲测批次产物 |
| `docs/UNSEEN_STATUS_V7.md` | 那个批次的状态记录 |
| `docs/v7/` | 2026-11-07 起的 V7 规范、状态与复核 |

**③ 代次链**：v3 已收口 → v4/v5 多数结论缺产物、**不可引用** → v6 部分 → v7 基本闭环 → v8 主线。

## 文档链接自检

`python3 scripts/check_docs_links.py` 扫描所有 md 里的路径引用（反引号路径与 Markdown 链接），
报出目标不存在的条目。**当前基线：27 个不同的悬空目标 / 28 处引用**（迁移前后一致、无新增），主要是：

<!-- link-check:ignore-start -->
- **真正缺失的产物**（文档宣称有、仓库里没有）：`runs/v3/report/v3_table.csv`、
  `runs/v3/stage013/input_batch/registration.json`、`runs/v4/wp2/value_scenes.json`、
  `runs/v5/ka8/ka8.json`、`cases/R02|R04/summary.json`、`assets/body_world.stl` 等 ——
  这与 `docs/DELIVERY.md` 里"V4/V5 多数结论缺产物、不可引用"的判定是同一件事。
- **规格模板里的占位名**：`Cx_REPORT.md`、`Mx_REPORT.md`、`WPx_REPORT.md`（模板本来就没有对应文件）。
- **从未提交的脚本**：`scripts/v7_contact_sheet.py`、`scripts/align_orient.py`、`scripts/h5_fixture_loop.py`。
<!-- link-check:ignore-end -->

门禁用法：`python3 scripts/check_docs_links.py --baseline 27`（现有悬空不阻断，新增一条就失败）。
