# V7-R1 统一交付（2026-10-30）

审查基线 `4fe5281f` · 批次目录 `runs/unseen/delivery_v7/v7_20261030_r1/`

## 0. 一句话结论

系统**能跑通**：观察 → 生成候选 → 观测约束物理化 → 逐候选/逐动作/逐状态预演 → 决策先落盘 →
真值续行 → 揭晓；**无候选时安全刹停**、**有合格候选时真的通行（3/3 成功）**都已在真实数据上跑过。
**研究收益仍不成立**：六个方法在 R03 上除盒先验外全部成功，成功数无法区分方法优劣。

## 1. 用户可操作的完整流程

```bash
cd /var/lib/deepseek-harness/lunar-lab
export LD_LIBRARY_PATH=/tmp/sysroot/usr/lib/x86_64-linux-gnu:/tmp/sysroot/lib/x86_64-linux-gnu
export MUJOCO_GL=osmesa

# ① 观察（一次驾驶 + 第二视角；含状态快照）
.venv/bin/python scripts/observe.py --case R03 --out runs/unseen/obs_R03
.venv/bin/python scripts/drive_observe.py --case R03 --out runs/unseen/.../observation/drive_R03

# ② 生成候选（1 积分/任务口径；只在实际提交时花钱）
.venv/bin/python scripts/v7_generate.py --batch-dir runs/unseen/delivery_v7/v7_20261030_r1 \
    --object R03 --images <输入图> --sample s1 --credit-upper 1.0 --scope v7_r1
.venv/bin/python scripts/v7_generate.py --batch-dir runs/unseen/delivery_v7/v7_20261030_r1 --download --scope v7_r1

# ③ 清洗 → 配准 → 观测约束融合（含自由空间雕刻与观测壳）
.venv/bin/python scripts/clean_candidate.py --candidate <glb> --out <cand>/clean --id V7_R03_s1
.venv/bin/python scripts/align24.py --candidate <cand>/clean/body.stl --obs runs/unseen/recovery_r3/obs_R03 \
    --out <cand>/align --top-k 4
.venv/bin/python scripts/fuse_observed.py --observation runs/unseen/recovery_r3/obs_R03 \
    --parent-world <cand>/world/align --parent-id V7_R03_s1 --method H5_F \
    --out <out>/fusion --pitch 0.0025 --config configs/unseen_v7_r1_fusion_offset1.json

# ④ 双门槛测量（可见 + 碰撞）
.venv/bin/python scripts/collision_box_union.py --mesh <out>/fusion/body.stl --out <out>/collision --pitch 0.0025
.venv/bin/python scripts/collision_occupancy_metrics.py --mesh <out>/fusion/body.stl \
    --collision <out>/collision --out <out>/collision/metrics.json --eval-pitch 0.004 --parity full

# ⑤ 观察后状态 → 逐动作预演 → 决策先落盘 → 真值续行
.venv/bin/python scripts/v7_closed_loop.py --drive <drive_observe.json> \
    --hypotheses <cases/*.json> --truth-collision <truth> --truth-world <truth_world> \
    --soil-configs nominal --out <out>/closed_loop

# ⑥ 六方法对照（三种真实土壤 + 验证初态）
.venv/bin/python scripts/eval_six.py --protocol plans/unseen_v7_protocol_six_nominal.json --out <out>/six

# ⑦ 页面（回放 + 用缓存资产重新仿真）
.venv/bin/python scripts/v7_page_r1.py
.venv/bin/python scripts/v7_rerun.py --case R03 --hypothesis <collision> --action R1 --seed 0

# ⑧ 统一验收
.venv/bin/python scripts/verify_delivery_r1.py
```

## 2. 已验证的能力

| 能力 | 证据 | 结论 |
| --- | --- | --- |
| 无候选 → 安全刹停 | `closed_loop_R01_a0`：0 格 → A0，3 状态续行位移 ≈0 | ✅ |
| 有合格候选 → 通行 | `closed_loop_R03_scene2`：42 格 → R1，**3/3 成功**，位移 3.19 m | ✅ |
| 决策先落盘 | `decision_events.jsonl` 中 `decisions_written` 早于 `execution_started` | ✅ |
| 观察后真值续行 | `t_start` 9.84/10.88/10.32 s（不是 0） | ✅ |
| 跨候选状态投射 | 同场景恢复拒绝、投射不搬材质（跳过 54 条摩擦） | ✅ |
| 双合格假设 | V7_R03_s1（2.5 mm）+ V7_R03_s2（4 mm）→ 42 格，R1，3/3 成功 | ✅ |
| **第二个独立对象合格** | **V7_R02_s2**：可见 0.9841/2.042/0.0461，碰撞 0.9893/0.504/0.792 | ✅ |

## 3. 候选与门槛（本批口径）

| 候选 | 可见 IoU / P95 / freespace | 碰撞 IoU / s2c / c2s | 结论 |
| --- | --- | --- | --- |
| **V7_R03_s1**（2.5 mm, offset 1.0） | **0.9737 / 1.702 / 0.0392** | **0.9852 / 0.492 / 0.774** | **合格** |
| V7_R03_s2（4 mm, offset 0.5） | 0.9551 / 2.65 / 0.0473 | 0.9918 / — / — | 合格（父批次） |
| V7_R01_tv1（2.5 mm, offset 1.0） | 0.9548 / 1.835 / **0.0875** | — | 不合格（freespace） |
| **V7_R02_s2**（2.5 mm, offset 1.0） | **0.9841 / 2.042 / 0.0461** | **0.9893 / 0.504 / 0.792** | **合格** |
| V7_R02_g1（4 mm） | 0.9661 / 1.907 / 0.0978 | — | 不合格 |
| V7_R02_g2（4 mm） | 0.6737 / — / — | — | 不合格（配准失败） |

**误差归因**：已知答案（父=真值）在同一表示下的 freespace 下限是 **0.0399**；
R03_s1 达 0.0392（贴住下限），R01_tv1 停在 0.0875（超出下限约 0.048）→
**过不过门槛取决于父形状是否贴合观测**，不是管线还在丢东西。

## 4. 六方法对照（R03，三种真实土壤 + 验证初态 3/4/5）

| 方法 | nominal | low_traction | high_drag |
| --- | --- | --- | --- |
| B0_blind | R1 3/3（3/3） | R1 3/3 | R1 3/3 |
| B1_height | R1 3/3 | R1 3/3 | R1 3/3 |
| B2_box | **A0 0/3** | D1 3/3 | **A0 0/3** |
| B3_mirror | R1 3/3 | R1 3/3 | R1 3/3 |
| H5_lux3d | **D1 3/3** | R1 3/3 | R1 3/3 |
| U_truth | R1 3/3 | R1 3/3 | R1 3/3 |

土壤参数真进环境（三个哈希互异）；验证初态在决策冻结后执行。
**收益未建立**：除盒先验外全部成功，无法据此说生成假设带来收益。

## 4b. 第二对象 R02 的结果：合格重建 ≠ 可通行

| 方法 | nominal 结果 |
| --- | --- |
| B0_blind | R1 0/3 |
| B1_height | A0 0/3 |
| B2_box | A0 0/3 |
| B3_mirror | A0 0/3 |
| H5_lux3d | A0 0/3 |
| **U_truth（真值上限）** | **A0 0/3** |

low_traction 与 high_drag 下同样六方法全部 0/3（B0 选 R1、其余选 A0），三种土壤一致。

**机制**：R02 障碍高 **0.1695 m**（R03 为 0.0965 m）；U_truth 的三次预演结果都是 `abort`
（不是 `time_limit`），即平台**翻不过这个高度**。所以这是**几何能力边界**，与重建质量无关——
V7_R02_s2 仍是合格重建，但该障碍不可通行。

**连真值上限都是 0/3**：从冻结初态、30 s 预算，在 R02 这个对象上任务本身不可达（选择 A0 即
"没有安全动作"）。所以 R02 是**能力边界**案例，不是方法差异案例。

结论：**重建资格（V7_R02_s2 双门槛合格）与任务可通行必须分列**；
六方法在 R02 上不能用来判断收益。

## 4c. 第二观察：不是做不到，是停得太远

| 停距 | 基线 | 视线角 | 可用 |
| --- | --- | --- | --- |
| 0.78 m（原） | 0.424–0.427 m（<0.45） | 8.5–8.97° | **0/3** |
| **0.68 m（新策略）** | **0.496–0.525 m** | **11.3–12.0°** | **1/3**（seed 0） |

判据一个都没改（基线 ≥0.45 m、视线角 ≥8°、稳定判据原样），只把**停距**从 0.78 m 改到 0.68 m：
基线达标、视线角达标、取景仍充足（3.8–4.3 万像素、深度有效率 1.0）。
2/3 判 `unstable` 属于停稳判据，不是视差不足。

**影响**：R03 的第二观察由 `not_evaluated` 变为真实可用 → 可以真正执行"再观察后保留/淘汰候选"。

## 4d. 再观察确实会淘汰候选（首次真实发生）

用行驶后状态生成第二观察（`obs_R03_at_driven`），固定几何/位姿、只移动相机、不做二次配准：

| 候选 | 首视角 IoU | 第二视角 IoU / P95 / freespace | 判定 |
| --- | --- | --- | --- |
| V7_R03_s1_2p5 | 0.9737（合格） | **0.9268 / 1.819 mm / 0.0737** | **淘汰（第二视角）** |
| **V7_R03_s2** | 0.9551（合格） | **0.9193 / 2.405 mm / 0.0739** | **淘汰（第二视角）** |

**真值对照（决定性）**：真值网格在**同一第二观察**上 IoU **0.9997** / P95 **0.645 mm** /
freespace **0.0199**（通过）。

| 对象 | 首视角 | 第二视角 freespace |
| --- | --- | --- |
| 真值网格 | 0.0321 | **0.0199（通过）** |
| V7_R03_s1 | — | 0.0737 |
| V7_R03_s2 | — | 0.0739 |

**结论修正**：第二观察的帧/配准**没有问题**；两个候选的 0.0737/0.0739 是**真实的形状误差**。
我先前"第二观察系统性偏差"的假设被该对照**否定**。

仍然成立的限制：第二视角把**两个候选都淘汰**，所以它能区分"候选 vs 真值"，
但**不能**区分这两个候选谁更好。

同批的 V7_R03_s1 首轮因 50.9 万面超过 MuJoCo 单 mesh 上限而 `not_evaluated`（**失败原因，不是判定**）；
改为同场景多视觉 mesh 后重跑，截稿时仍在执行 → **判定记为 `pending`**。

为拿到快速信号，另做了一张 5 mm 顶点聚类**代理网格**（36,398 面）跑同一筛选：
首视角 IoU **0.9366**、第二视角 0.9074 / 2.76 mm / 0.1434 → `rejected(first_view)`。
但**代理网格不能当作 s1 的判定**：降采样本身就把首视角 IoU 从 0.9737 压到 0.9366，
它只能说明渲染通路可用。因此该行标注 `usable_as_verdict = false`，不顶替真实候选的结论。

## 4e. 筛选后的闭环：空集合 → A0 安全刹停

两个候选都被第二视角淘汰后，按**筛选后集合（空）**重跑闭环：

| 项 | 值 |
| --- | --- |
| 分支 | `a0_fallback_no_candidate` |
| 矩阵格 | 0 |
| 决策 | **A0**，原因 `no_candidates_after_second_view`（**写盘前**写入） |
| 真值续行 | 从行驶后状态开始（`t_start` 11.94 s），`state_mode=project`（已记录：快照来自观测场景） |
| 结果 | `abort`，位移 0.0005 m（安全停止；A0 不计成功） |

过程中修掉两个真实缺陷：
① 无候选时 `reason` 未在写盘前写入 → 决策合同**正确拒绝**了该决策；
② 真值续行此前一律用 `same_scene`，与"状态来自观测场景"矛盾 → 改为**先同场景、失败则投影并记录原因**。

## 5. 测量口径修正（影响结论的部分）

| 问题 | 处理 |
| --- | --- |
| 2.5 mm 层化被 20 万面上限挡住 | 同场景多视觉 mesh 分块，单/多 mesh 指标一致（IoU 0.9551 相同） |
| 边距侵入过高 | 定位到**观测壳偏移方向**：offset 1.0 体素使已知答案 0.0510 → **0.0399**；带宽不是杠杆 |
| 碰撞测量 OOM | **我的实现问题**：内层 128×509k 点×面矩阵；改两级分块后峰值 RSS **756.7 MB**，全网格 parity，未抽样 |
| 粗网格 parity 曾给 0.8691 | 作废；该值是 16.6 mm 顶点聚类近似的产物，不是门槛口径 |

**等价性验证**：20,480 面 / 3,000 点，2M、200k、20k 三档分块 **maxdiff = 0.0**。

## 6. 生产路径验收

`verify_delivery_r1.py`：**44 项检查**，覆盖完整性/功能/目标三层，调用生产决策合同，
并核对闭环**实际引用**的候选资格。反例注入 **12/12**（N01–N18，全部调用生产函数）。

## 7. 剩余限制与阻塞

- 第二个独立对象已合格（R02）；R04 的采样仍卡在 freespace / 配准，保留完整分母。
- 观察能力边界：R03 驾驶基线 0.424–0.427 m < 0.45 m 门槛 → 第二观察标 `not_evaluated`（不据此淘汰候选）。
- 执行是仿真，不是实物；月壤只进阻力/牵引参数。
- 生成价格按 1 积分/任务估计（**未与 API 账单核对**），实际扣费 `unknown`。
- 推送：`main` 领先远端若干提交（仓库 2.6 GB，链路慢）；已加 `.gitignore` 阻止大网格入库。

## 8. 状态

```json
{"execution_status":"PARTIAL","evidence_status":"PARTIAL","capability_status":"PARTIAL",
 "benefit_status":"NOT_ESTABLISHED","claim_level":"NOT_REACHED"}
```
