# DEMO_V5 · 看不见的那一面（2–3 分钟）

可录制的演示脚本。所有数字、图、字幕都来自本批已落盘产物；录制不需要改 JSON、
不需要 trial_id，也不触发任何生成 API。

## 录制前（一次性）

```bash
cd /var/lib/deepseek-harness/lunar-lab
.venv/bin/python scripts/app_unseen.py --port 8091
# 浏览器打开 http://127.0.0.1:8091/
```

页面只读 `runs/`、`cases/` 下的缓存产物。截图在
`runs/unseen/delivery_v5/v5_20261029/media/page/`；数据入口是
`runs/unseen/delivery_v5/v5_20261029/manifest.json`，正式表是
`runs/unseen/delivery_v5/v5_20261029/evaluation/formal_table_v5.json`。

**统一字幕口径（录制时不要改）**

- 输入是**仿真 RGB-D**，不是真实相机。
- 执行是**独立仿真**，不是真实机器人。
- 月壤是半经验近似，**几何下陷未实现**。
- strict 几何诊断与 planning eligibility 分列。
- benefit 当前是 **NOT_ESTABLISHED**。
- fixture 不是 Lux3D；预演不是执行回放。

---

## 0:00–0:15 开场：这批到底有什么

**画面**：`http://127.0.0.1:8091/?run=batch:v5_20261029`
（截图：`media/page/06_v5_batch_status.png`）

**字幕/口播**：

> 机器人只看得到障碍正面。我们让 Lux3D 生成背面候选，先在候选上预演动作，
> 再在独立真值上执行。V5 批次有 3 个真实生成候选、3 个清理通过、3 个配准完成，
> **0 个 strict 通过、1 个 IoU-only planning eligible、2 个 ineligible**。

**指一下正式表**：R01 的 `C_R01_face12k` 是唯一 planning eligible，但它只是 IoU 过：
IoU 0.8622、P95 11.0 mm > 9.957、freespace 0.5106、`hit_part_cap=true`。
页面上 strict 和 planning 是两列，不能合并成“通过”。

---

## 0:15–1:00 （a）一个完整真实生成候选闭环：R03 / G_R03

**画面**：`http://127.0.0.1:8091/?run=pipeline_H5_R03`
（截图：`media/page/01_pipeline_H5_R03.png`）

**数据来源**：

- `runs/unseen/recovery_r3/pipeline_H5_R03/summary.json`
- `runs/unseen/recovery_r3/pipeline_H5_R03/decision.json`
- `runs/unseen/recovery_r3/pipeline_H5_R03/rehearsal.jsonl`
- `runs/unseen/recovery_r3/pipeline_H5_R03/execution.jsonl`
- 候选状态：`runs/unseen/recovery_r3/v4_status.json` 的 `G_R03` 行

**口播（按画面顺序）**：

1. **看见**：机器人真实观测的 RGB、可见面 mask、送生成的 1024² 白底图；深度只用于
   可见面分割和 `x_front / W_vis / H_vis`，不读背面。
2. **想象**：候选 `G_R03`，task `4463082`，候选 world `9ba49243…`；侧视/后侧视/俯视
   是同一候选的三视图。清理通过；strict 失败（IoU 0.8847、P95 7.94 mm、freespace
   0.1818）；planning eligibility **通过**。两列分开读。
3. **试走**：7 个动作 × 3 个初态；`S1` 在该候选上失败，其余通过；失败阶段是
   `not_applicable`，不是“没跑”。
4. **决定**：冻结规则 `worst-case-risk/v1`；安全集去掉 `S1` 后，`R1` 的 worst-case R=0，
   mean cost 6.267，低于 `D1` 的 6.373，所以选 `R1`。
5. **执行与揭晓**：在独立真值 `436b75d2…` 上，H5 选定 `R1` **3/3**；盲走 B0 也是
   **3/3**；A0 0/3（abort）。真值与候选不是同一资产。

**收句**：

> 这是完整闭环，但没有证明收益：H5 与盲走同分。页面把这一点写在“收益判读”里。

---

## 1:00–1:40 （b）一个有信息量的动作选择案例：R01 正式 H5 vs 镜像/宽度规则

**画面 A**：`http://127.0.0.1:8091/?run=H5_R01_face12k`
（截图：`media/page/04_H5_R01_face12k.png`）

**画面 B**：`http://127.0.0.1:8091/?run=six_R01_v5`
（截图：`media/page/07_six_R01_v5.png`）

**数据来源**：

- `evaluation/H5_R01_face12k/summary.json`、`execution.jsonl`
- `evaluation/six_R01_v5/summary.json`、`records.jsonl`
- `evaluation/formal_table_v5.json`、`evaluation/benefit_summary.json`
- `evaluation/state_alignment_R01.json`（H5 与 six 的初态哈希 `all_match=true`）

**口播**：

> R01 的候选 `C_R01_face12k` 是唯一 IoU-only planning eligible。正式 H5 在统一初态
> 0.05/0.05 下选 `L2`：seed0 在 30.02 s 超时，seed1/2 成功，合计 **2/3**；盲走 R1
> **0/3**。所以 H5 优于盲走、B1、B2——这是真的。
>
> 但它没有优于镜像/真值/宽度规则：`B3_mirror`、`U_truth` 和宽度规则诊断都选 `S1`，
> 都是 **3/3**（mean 6.593）。因此 H5 的 2/3 **低于**这三个 3/3，benefit 仍是
> `NOT_ESTABLISHED`。

**指一下页面**：

- 候选页：strict `fail`，planning `IoU-only`，P95/freespace/part cap 都列出；
- 六方法页：H5 行 `no_candidate`（six_R01_v5 没有 H5 候选），B3/U 选 S1 3/3；
- 正式表：R01 一行把 H5、B0、B3、U 放在一起。

**必须说的初态更正**：

> 旧的 `H5_R01_face12k_init003` 在 yaw=0.03 下是 L2 3/3，已标 **SUPERSEDED**；
> 它没有和 six 的 0.05/0.05 配对，所以不用于正式表、不作为当前结果。

---

## 1:40–2:10 （c）一个诚实边界：R02 / R04 全部动作失败

**画面**：`http://127.0.0.1:8091/?run=six_R02_v5`
和 `http://127.0.0.1:8091/?run=six_R04_v5`
（截图：`media/page/09_six_R02_v5.png`、`media/page/10_six_R04_v5.png`）

**数据来源**：

- `evaluation/six_R02_v5/summary.json`
- `evaluation/six_R04_v5/summary.json`
- `cases/R02/summary.json`、`cases/R04/summary.json`

**口播**：

> R02 和 R04：H5 都是 `no_candidate`；B0 R1 0/3；B1/B2/B3/U 都退到 A0，0/3 abort；
> 真值扫描里 7 个非 A0 动作也全部 0/3。当前动作库在这两个案例上没有安全通行动作。
> 页面写“可通行动作：无”，不写成“H5 失败”，因为这里没有候选决策。

---

## 2:10–2:35 （d）“再看一眼”：真实候选未触发；fixture 只验证接口

**画面**：`http://127.0.0.1:8091/?run=trigger_face12k`
（截图：`media/page/05_trigger_face12k.png`）

**数据来源**：

- `observation/trigger_face12k/look_loop.json`、`trigger.json`

**口播**：

> 真实候选 `C_R01_face12k` 的 trigger 判定是“候选一致，不触发观察”，所以没有第二
> 观察、没有 decision、没有执行。这不是失败，是**未触发**。页面不会为了演示编一段
> “再看一眼改善决定”的动画。

**如果一定要看第二观察链路**：

`http://127.0.0.1:8091/?run=look_loop_R01_v3`（截图：`media/page/03_look_loop_R01_v3.png`）

> 这是 **FIXTURE** 链，不是真实 Lux3D：它验证了“抬高 → 第二视角 → 筛选 kept →
> 8 个动作全部失败 → A0 回退”的接口和格式。fixture 不计真实成绩，也不证明真实候选
> 会从“再看一眼”受益。

---

## 2:35–2:45 收尾

**画面**：回到 `batch:v5_20261029` 页面底部“土壤 / 预检 / 计时”。

**字幕/口播**：

> 当前证据支持的：真实生成候选能进入清理、配准、CoACD、预演、独立真值执行；
> 页面能区分 strict、planning、fixture、cache、无候选、观察不可用和计时缺失；
> 本批统一验收 **73/73**。
>
> 当前证据不支持的：H5 相对镜像/宽度规则/真值的收益（NOT_ESTABLISHED）；真实月壤
> 几何下陷；真实机器人迁移；真实候选“再看一眼改善决定”。
>
> 下一步是把缺的批次数据补齐，并继续用同一套页面复核，而不是把结论写成 PASS。

---

## 录制检查清单

- [ ] 页面在 8091 端口启动，`?run=` 直达能打开。
- [ ] 批次页显示：3 生成 / 3 清理 / 3 配准完成 / 0 strict / **1 IoU-only planning** / 2 ineligible。
- [ ] R03 截图里 H5 与 B0 都是 3/3，收益字幕是 NOT_ESTABLISHED。
- [ ] R01 正式 H5 截图里 L2 2/3、B0 0/3；B3/U/宽度规则 3/3 写在正式表。
- [ ] 旧 init003 只以 SUPERSEDED 出现，不写成当前结果。
- [ ] R02/R04 截图里 H5 是 `no_candidate`，非 A0 全 0/3。
- [ ] trigger 截图里是“未触发”，fixture 页顶部有 FIXTURE 标签。
- [ ] 没有“真实机器人”“真实月面”“统计显著”“H5 全面更优”的字幕。
- [ ] 所有截图来自 `runs/unseen/delivery_v5/v5_20261029/media/page/`。
