# V5 当前状态（2026-10-29，main）

> 本文件是 V5 批次的当前状态；`docs/UNSEEN_STATUS_CURRENT.md` 顶部指向本文件，
> 其下 V4 段落保留为历史。所有数字来自
> `runs/unseen/delivery_v5/v5_20261029/manifest.json` 及其子产物。

## 0. 四类状态

| 状态 | 值 | 说明 |
| --- | --- | --- |
| delivery_status | **COMPLETE** | P0–P7 均有产物；统一验收含负例 73/73；页面浏览器截图 11 张；全套测试 130 OK |
| evidence_status | **MIXED** | 批次身份链、同初态、负例已验证；旧 H5 init003(0.03)/six_v4(15 s)/pipeline_H5_R03(0.03) 被取代；R01 与 dev_narrow_tall 同网格 |
| capability_status | **PARTIAL** | 生成/清理/配准/资格/预演/真值执行可运行；整机几何下陷未实现；真实多假设观察未建立 |
| benefit_status | **NOT_ESTABLISHED** | R01 H5 2/3 低于 B3/U/宽度规则 3/3；R03 H5=盲走；R02/R04 无成功；无隐藏背面必要案例 |

## 1. 生成批次（3 任务 / 60 上界，累计 27 / 540）

| 计划项 | task_id | GLB 原始尺寸 (m) | 清理 | 配准 IoU | P95 mm | freespace | strict | planning eligible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C_R01_az25 | 4466035 | 0.0220 × 0.0162 × 0.0103 | ok | 0.5989 | 19.64 | 0.5113 | 否 | 否 |
| C_R01_az45 | 4466087 | 0.0165 × 0.0140 × 0.0063 | ok | 0.6907 | 12.47 | 0.4957 | 否 | 否 |
| **C_R01_face12k** | **4466144** | 0.0149 × 0.0220 × 0.0098 | ok | **0.8622** | 11.00 | 0.5106 | **否** | **是（仅 IoU 过政策）** |

- 3/3 生成并下载；3/3 clean/v4 通过；3/3 完成 1512 次搜索；0/3 strict；1/3 planning eligible。
- **原始 GLB 仍是 1–2 cm 量级**：偏航 +25°/+45° 与面数 12000 都没有修复尺度。
- face12k 的 IoU 过 `planning-eligible/v1` 的 0.85，但 P95 11.0 > 9.957、freespace 0.5106 > 0.05；
  CoACD 32 部件、`hit_part_cap=true`、concavity 0.53。**它不是 strict 通过，也不能写成几何合格。**
- 实际扣费 unknown；累计 27 任务 / 540 上界；本批未执行任何第四任务，不重提失败项。

## 2. 正式比较（30 s；同一真值、同一初态）

初始状态统一为 `configs/unseen_initial_state_v5.json`（lateral 0.05、yaw 0.05），
H5 与 six_R01 的 qpos+qvel 全量哈希 3/3 对齐（`evaluation/state_alignment_R01.json`）。

| 案例 | 方法 | 自选动作 | 执行 | 成功 | 均代价 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R01 | B0_blind | R1 | 3 | 0 | 60.0 | tipped 3/3 |
| R01 | B1_height | A0 | 3 | 0 | 40.0 | abort 3/3 |
| R01 | B2_box | A0 | 3 | 0 | 40.0 | 预演无稳健动作 |
| R01 | **B3_mirror** | **S1** | 3 | **3** | 6.593 | 与宽度规则/U_truth 同动作 |
| R01 | **H5_lux3d（C_R01_face12k）** | **L2** | 3 | **2** | 24.787 | seed0 L2 超时 30.02 s |
| R01 | U_truth | S1 | 3 | 3 | 6.593 | 真值上限 |
| R01 | 宽度规则（诊断） | S1 | 3 | 3 | 6.593 | W_vis 0.1558 < 0.1913 |
| R03 | B0_blind | R1 | 3 | 3 | 6.420 | — |
| R03 | **H5_lux3d（G_R03）** | **R1** | 3 | **3** | **6.420** | 与盲走/镜像同分 |
| R03 | B2_box / U_truth | D1 | 3 | 3 | 6.387 | 略便宜 0.033 s，非收益 |
| R02 | 全部非 A0 | — | 3 | 0 | 60/40 | 能力边界；H5 no_candidate |
| R04 | 全部非 A0 | — | 3 | 0 | 60/40 | 能力边界；H5 no_candidate |

**关键更正**：旧 `H5_R01_face12k_init003` 在 `gate_physics` yaw=0.03 初态下 L2 3/3；
六方法用 0.05。V5 统一为 0.05/0.05 后，H5 变成 **2/3**（seed0 超时）。
旧 3/3 保留为 superseded，不进入正式表。此前 H5 与六方法“同初态”的口径并不成立。

## 3. 案例覆盖（P2）

- 6 个独立完整形状：R01（r2_narrow_tall@1.15）、R02（s_round@1.1）、R03（s_flat@1.1）、
  R04（s_wide@1.0）、twin narrow、twin wide；3 个本批 API 任务；6 个观测方向；10 个 twin 背面变体。
- **有效隐藏背面取舍 0 个**：R01 是唯一有动作取舍的真实石头（R1 0/3、S1 3/3），
  但 W_vis 0.1558 < 净空 0.1913，宽度规则直接选 S1 3/3；R03 除 A0 外全 3/3；
  R02/R04 全 0/3；az25/az45 是同一石头转角度；twin 的 ledge 使 S1 降到 2/3，但没有替代稳健动作。
- R01 与 `dev_narrow_tall` 同网格（SHA `be4375…`，truth world SHA `5b2242…`），不是独立留出案例。
- 结论：当前案例集只能支持“动作取舍存在/链路可运行”，不能支持“必须推断隐藏背面”。

## 4. 主动观察（P4）

- 真实 face12k 单候选：`trigger/v1` 判定一致（chosen L2，safe L2/R2/S1），**not_triggered**；
  没有为了演示强行观察。
- 可控 fixture（truth-shaped vs box prior）：**triggered**（S1 vs A0）；观察可用
  （baseline 0.529 m、bearing 11.67°、state_hash `a3405a02…`）；第二视角筛掉 box（IoU 0.4853），
  truth-shaped 保留（IoU 0.998）；从观察后状态预演并选 S1；真值续行 S1 success、R1 tipped。
- fixture 全链路只验证触发/筛选/续行接口，**不计 Lux3D 收益**；真实多假设观察收益 NOT_ESTABLISHED。

## 5. 月壤（P5）

| 项 | 结果 |
| --- | --- |
| A 单轮 | 标定 5 档误差 0.36–2.72%；验证 4 档 3.12–5.24%；单轮装置 0.09/0.10，不是整机轮 |
| B 平地 | 刚性 3.6727 m / 0.655 s；土壤 3.612 m / 1.172 s；土壤阻力功 −58.88 J |
| C 坡面 | 0/5° 通过；10/15° 土壤 time_limit；20° 刚性 tipped vs 土壤 time_limit |
| D 零牵引 | H=0 时 p95 0.0003 N、dx 0.0002 m |
| E 稳定性 | 1000 回合（平地/坡10/坡15/障碍 × 5 参数 × 10 初态 × 5 动作）；0 NaN/Inf/异常；792 timeout、200 abort、8 tipped；max final_x 3.047 m、max tilt 61.42° |
| F 吞吐 | 土壤/刚性墙钟比 1.768（同控制步；未下降超过一半） |
| G 几何下陷 | **PARTIAL_NOT_IMPLEMENTED**：公式 26.5 mm vs 静态轮底约 −0.97 mm；整机刚性接触未映射垂直下陷 |

## 6. 页面与验收（P6/P7）

- 页面：`scripts/app_unseen.py` 已改为读 `runs/unseen/page_registry.json` + V5 manifest；
  新增 batch 入口 `?run=batch:v5_20261029`；浏览器验证用 Playwright 缓存的 headless Chromium，
  截图在 `runs/unseen/delivery_v5/v5_20261029/media/page/`。
- `scripts/verify_delivery_v5.py` 绑定本批 manifest，含真实负例（重复初态、坏 SHA、伪造成功、
  真假同 SHA、no_candidate）；当前 **73/73**。
- 全套单元测试在最终代码上重跑：`Ran 130 tests in 777.529s`，`OK (skipped=1)`；日志 `verify/unit_v5.log`。
- `verify_delivery_v5.py --self-test` 73/73；负例实际调用同一校验函数。

## 7. 复现入口

```bash
# 预检（不联网、不 create）
.venv/bin/python scripts/preflight_delivery_v5.py --plan plans/unseen_delivery_v5.json \
  --budget configs/unseen_v5_budget.json --ledger runs/unseen/generation/ledger.jsonl \
  --cache runs/unseen/generation/cache --out runs/unseen/delivery_v5/v5_20261029/verify/preflight.json

# dry-run / resume（resume 不 create）
.venv/bin/python scripts/imagine.py --plan plans/unseen_delivery_v5.json --dry-run
.venv/bin/python scripts/imagine.py --plan plans/unseen_delivery_v5.json --resume \
  --budget configs/unseen_v5_budget.json

# 统一验收（含负例）
.venv/bin/python scripts/verify_delivery_v5.py \
  --manifest runs/unseen/delivery_v5/v5_20261029/manifest.json \
  --out runs/unseen/delivery_v5/v5_20261029/verify/report.json --self-test

# 页面
.venv/bin/python scripts/app_unseen.py --port 8091
# http://127.0.0.1:8091/?run=batch:v5_20261029
```

## 8. 仍未完成 / 需用户决定

1. **隐藏背面必要案例**：需要新造“可见宽度不足/误导、隐藏背面使 S1 必败、另有 3/3 稳健动作”的几何。
   建议先用 twins/程序化几何做免费真值扫描，再决定付费生成；不再在现有四块石头上重复付费。
2. **真实多假设第二观察收益**：真实候选没有分歧；fixture 只验证接口。
3. **整机几何下陷**：未实现；坡面滑转/参数随机化仍有限。
4. **R01 的独立性**：与开发案例同网格，不能用于泛化主张。
5. **实际扣费**：unknown；累计 27/540 上界，不再新增 create。
