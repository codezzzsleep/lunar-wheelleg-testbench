# V7 当前状态（唯一入口）

**批次**：`v7_20261030`｜**基线**：`fdd2a27b`｜**方向**：项目纲领 v2.1
**批次入口**：`runs/unseen/delivery_v7/v7_20261030/manifest.json`（生成中）
**预算**：`configs/unseen_v7_budget.json`（本批新增 500，独立账本）｜**协议**：`configs/unseen_v7_protocol.json`
**计划**：`plans/unseen_v7_delivery.json`

> 本文件是 V7 的唯一当前状态入口。历史状态见 `docs/UNSEEN_STATUS_V6_1.md`（已归档为上一批）。

## 0. 四类状态

| 状态 | 值 |
| --- | --- |
| execution_status | **IN_PROGRESS**（生成与处理链在跑） |
| evidence_status | **PENDING**（须等正式表与验收器） |
| capability_status | **PENDING** |
| benefit_status | **NOT_ESTABLISHED**（尚未比较，不预设） |

## 1. 已完成（可复核）

### 1.1 预算与账本（独立核算）

- 本批新增授权 **500 积分**，写入 `configs/unseen_v7_budget.json`；
- 本批账本 `runs/unseen/delivery_v7/v7_20261030/generation/ledger.jsonl`（独立文件，历史账本只读保留）；
- 单价口径：**每任务上界 20 积分**（本仓库历史账本 27 条记录全部按此上界，非模型猜测）；
- 已用：**80 / 500**（4 个单图任务）；实际扣费一律 `unknown`。

### 1.2 真实生成（第一批，4 任务）

| 对象 | 采样 | 任务 ID | 模式 | GLB SHA256（前 10） | ZIP |
| --- | --- | --- | --- | --- | --- |
| R02 | s1 | 4484069 | single_image | `dbe440554b` | 71.4 MB |
| R02 | s2 | 4484076 | single_image | `750132e7d7` | 42.8 MB |
| R04 | s1 | 4484079 | single_image | `ac904b61e7` | 71.9 MB |
| R04 | s2 | 4484082 | single_image | `a2509285c8` | 75.3 MB |

- 输入图：`runs/unseen/recovery_r3/upload_pkg/<对象>/upload_1024.png`（机器人首视角实测图，1024 白底隔离版）；
- 每条任务记录含：输入字节 SHA、上传 URL、请求身份（模式+有序图字节+版本+faceCount+sample）、
  任务 ID、ZIP SHA、GLB SHA、时间戳；
- `resume` 只查询、`--download` 只下载，均不触发创建（接口回归 11/11 通过）。

### 1.3 生成接口回归（11/11）

`scripts/v7_gen_interface_test.py` → `generation/interface_test.json`：
两图确实序列化为 `imgs` 两元素且不带 `img`；调换顺序身份变化；改第二张图身份变化；
单图仍用 `img`；resume 只查不建；多图少于两张被拒；**同一 attempt_id 重复预留被拒**（本轮修的真实缺陷）。

### 1.4 独立对象清单（4 个）

`runs/unseen/delivery_v7/v7_20261030/cases/independence.json`：
R01/R02/R03/R04 来自四块不同源石（`r2_narrow_tall` / `s_round` / `s_flat` / `s_wide`），
缩放归一后两两占据 IoU 最大 **0.7163**（R02|R04），全部 < 0.90 → **4 个独立对象**。
同一网格的缩放/旋转/多初态不计为新对象。

## 2. 进行中

- 四个新候选的 清理 → 24 朝向配准 → 观测融合 → box 碰撞 → 保真测量；
- 配准结果（align24/v3，1512 次粗评）：R02_s1 iou 0.8712 / p95 18.6 mm、R02_s2 0.7817 / 13.4 mm、
  R04_s1 0.8410 / 25.6 mm、R04_s2 0.8281 / 24.0 mm —— **四个都未过配准门槛**，
  是否可用要看融合后的可见面指标（融合会用观测约束修正表面）。

## 3. 未开始（本批必做）

- 第二批生成（补足覆盖，目标每对象 3 个有效假设）；
- 真实两图生成（需先做出真实第二视角）；
- 主动观察闭环（行驶→第二观测→重规划→续行）；
- 主比较（六方法 + 真值上限）、月壤 rigid/soil 对照；
- 页面适配视图与回放；
- 验收器 V7 版（12 类真实错误）与最终报告。

## 4. 限制（现在就写明）

- 实际扣费 `unknown`；本批只保证「预留上界 20/任务」。
- 4 个新候选的配准均未过门槛，若融合后仍不合格，它们只进 DIAG，不进正式表。
- R01 仍是开发诊断，不计作留出对象。
