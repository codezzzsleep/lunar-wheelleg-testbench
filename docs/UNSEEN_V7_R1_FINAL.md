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

## 1b. 一条命令的用户入口

```bash
.venv/bin/python scripts/run_r1.py --dry-run      # 只打印将执行的命令（可复制）
.venv/bin/python scripts/run_r1.py --stage all    # 全流程；已有产物的阶段自动跳过
.venv/bin/python scripts/run_r1.py --stage six --force   # 只重跑某阶段
```

八个阶段固定顺序：`observe → candidate → fuse → measure → closed_loop → six → page → verify`。
两条硬约束：**云端生成必须显式 `--allow-generate`**（默认不花钱）；**产物存在即跳过、不覆盖**
（`--force` 才重跑），避免静默替换证据。

入口自带**输入审计**：`.venv/bin/python scripts/run_r1.py --audit` 会逐条检查每个阶段声明的输入
是否存在（本轮就是靠这个发现闭环阶段还指着已不存在的 `drive_R03`）。

## 1c. 多土壤决策聚合（已修）

原实现只按 `(候选, 状态)` 聚合，同一候选同一状态在不同土壤下的行会**互相覆盖**——
多土壤跑出来的证据被静默丢弃。

现在 `decision.evaluate(extra_keys=('soil_config',))` 按 **(候选 × 动作 × 状态 × 土壤)** 聚合：

- 同一格在不同土壤下是**不同格**，缺失任何一格 → `insufficient` → **不安全**（保守）；
- 单元验证：2 候选 × 2 状态 × 3 土壤 = 12 格，两个候选各 2 次失败 → `risk = 0.333`；
  删掉任一土壤格 → `insufficient=True, safe=False`。

## 1d. 验证状态续接合同（已修）

`eval_six` 的验证初态此前是**按 seed 重置**再跑一遍，冒充"续接"。现在：

- 协议可给 `validation_state_snapshots`（R03 已导出 3/4/5 三条行驶后快照）；
- 验证行必须带 `validation_continuation` 与 `state_mode`（`same_scene`，签名不符则 `project` 并记录）；
- 没给快照时如实标 `seed_reset`——**不允许**重置后跑一遍算作续接。

**实测（R03 nominal，`six_R03_nominal_v2`）**：验证行 **18 条全部 `validation_continuation=true`**，
`state_mode` 全为 **`project`**（快照来自观测场景，与真值碰撞场景签名不同 → 显式投影并记录）。
规划结果与旧口径一致：B2_box 仍 A0 0/3（验证 0/3），其余 5 个方法 3/3（验证 3/3）。
即：**续接没有改变结论，但现在有据可查**，不再用"重置后跑一遍"顶着续接的名义。

## 1e. 多土壤聚合改变决策（实测）

R03 双合格假设、三土壤（nominal / low_traction / high_drag）、1 个真实初态：
**2 候选 × 7 动作 × 1 状态 × 3 土壤 = 42 格**（只有 seed 0 通过停稳判据，所以不是 126 格）。

| 口径 | 安全集大小 | 选择 | 真值执行 |
| --- | --- | --- | --- |
| 只看 nominal | 7 | **R1** | 成功，3.1915 m |
| **三土壤聚合** | **5（R1 掉出）** | **D1** | **成功，3.0895 m**，`t_start` 11.94 s，`project` |

**结论**：土壤不确定性进入聚合后，R1 因在某种土壤下失败而**不再安全**，规则改选 D1 仍能完成。
这说明多土壤聚合**真的改变了决策**，不是换个口径记同一件事。

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
| V7_R04_s2（2.5 mm, offset 1.0） | **0.9654 / 1.979 / 0.0339** | 0.9776 / 1.357 / **37.626** | **不合格（碰撞 c2s 37.6 mm）** |
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

- 第二个独立对象已合格（R02）；R03 有两个合格假设。
- **R04_s2 已测完并判不合格**：可见门槛过（0.9654/1.979/0.0339），但 3 mm 体素下的盒并集
  碰撞保真为 **IoU 0.9776 / s2c 1.357 mm / c2s 37.626 mm** —— 反向距离远超 5 mm。
  原因：3 mm 体素**漏掉薄/凹结构**，源表面大片区域离最近盒面 37 mm；2.5 mm 体素则跑不完内存。
  这是**碰撞表示的分辨率限制**，不是评分错误，也不拿"可见通过"顶替。
- 观察能力边界：R03 驾驶基线 0.424–0.427 m < 0.45 m 门槛 → 第二观察标 `not_evaluated`（不据此淘汰候选）。
- 执行是仿真，不是实物；月壤只进阻力/牵引参数。
- 生成价格按 1 积分/任务估计（**未与 API 账单核对**），实际扣费 `unknown`。
- 推送：`main` 领先远端若干提交（仓库 2.6 GB，链路慢）；已加 `.gitignore` 阻止大网格入库。

## 7b. 最终验收口径

`verify_delivery_r1.py`：**73 项全通过**（完整性 13 / 功能 55 / 目标 5），包括：

- 每个阶段输入存在的审计（`run_r1.py --audit` 返回 0）；
- 决策矩阵四维合同（候选 × 动作 × 状态 × 土壤）、A0 不入安全集、无候选必写原因；
- 多土壤聚合单元检查（缺格即不安全）；
- 验证续接合同（18/18 行 `validation_continuation=true`，模式有记录）；
- 决策先落盘（事件时间序）、续行非重置（`t_start > 1 s`）、位移=终值−初值；
- 真值对照（第二观察上 `freespace 0.0199`）；
- 碰撞测量口径（full parity、未抽样、峰值 RSS 记录）；
- 页面双模式与 6 个闭环回放页。

## 8. 状态

```json
{"execution_status":"PARTIAL","evidence_status":"PARTIAL","capability_status":"PARTIAL",
 "benefit_status":"NOT_ESTABLISHED","claim_level":"NOT_REACHED"}
```

## 9. CNB 打开即用沙箱

仓库根目录已含沙箱配置，点开「云原生开发」即得可用环境：

| 文件 | 作用 |
| --- | --- |
| `.ide/Dockerfile` | 基于 `cnbcool/default-dev-env`，装 OSMesa/GL 与锁定依赖（mujoco 3.17.0、numpy 2.5.4、trimesh 5.2.0、coacd、manifold3d、pillow、pyyaml）；**无任何 COPY**（构建上下文只有 Dockerfile 本身） |
| `.cnb.yml` | `vscode` 事件，8 vCPU；六个 stage：镜像自检 → 拉项目 → bootstrap → 烟测 → 统一验收 → 判定快照；带 `endStages` 留档 |
| `.cnb/bootstrap.sh` | 建 venv、装锁定依赖、用 `importlib.metadata` 逐项核对版本（不一致即失败） |
| `.cnb/smoke.sh` | MuJoCo 建模 + **OSMesa 出图断言**（64×64 非空）+ 仓库模块可导入 |
| `.cnb/welcome.sh` | 打开终端打印入口/验收/页面命令 |

**本地已验证**：`sh .cnb/smoke.sh` → `render (64,64,3) uint8 159486`、`imports ok`、`smoke ok`；
`bootstrap.sh` 的版本核对 → `{"checked": 6, "mismatch": []}`。

**未验证（缺外部资源）**：镜像构建与真实启动需要 CNB 项目与令牌
（`repo-cnb-trigger:rw` 用于 start、`account-engage:r` 用于 list、`repo-cnb-detail:r` 用于 detail）。
拿到令牌后：

```bash
export CNB_TOKEN=...
bash <skill>/scripts/cnb_api.sh start  --repo <org>/<repo> --branch main
bash <skill>/scripts/cnb_api.sh wait   --repo <org>/<repo> --branch main --timeout 900
bash <skill>/scripts/cnb_api.sh stages --repo <org>/<repo> --sn <sn>
```

## 10. 沙箱实测（CNB，2026-10-31）

仓库 `ycyc755/lunar-lab-r1`（源码快照）已跑通，六个 stage 全绿：

| 阶段 | 耗时 |
| --- | --- |
| Prepare（镜像，缓存命中） | **15.2 s** |
| 1. 镜像自检 | 1.3 s |
| 2. 就位（复用工作区，不 clone GitHub） | 3.0 s |
| 3. bootstrap | 0.8 s |
| 4. MuJoCo + OSMesa 烟测 | 1.2 s |
| 5. 结构验收 | 0.8 s |
| 6. 判定快照 | 0.9 s |

快照断言（写进构建日志，无需 SSH）：`Python 3.12.16 / mujoco 3.17.0 / numpy 2.5.4 / trimesh 5.2.0`。

**复用规律（实测）**：镜像按 Dockerfile 内容 hash 缓存 —— 改 Dockerfile 的冷启动 **68 s**，
不改则 **15 s**；改 `.cnb/*.sh` 或 `.cnb.yml` 不触发镜像重建。工作区不必反复重启，
闲置约 10–12 分钟才回收。

**踩过的坑（都已修）**：
1. 基础镜像 PEP 668 禁 pip → 依赖装进 `/opt/lunar` venv；
2. 仓库 `.venv` 用系统 python 建 → 看不到镜像依赖 → 不再建仓库 venv，直接用镜像解释器；
3. stage 写死 `.venv/bin/python` → 改 `python3`；
4. stage 2 从 GitHub clone（慢/可能失败）→ 改为复用工作区 checkout，缺失才从 cnb.cool 拉。

**口径说明**：CNB 里跑的是**源码快照**的结构性验收；完整 73 项验收需要 `runs/` 证据包，
仍在证据所在机器上执行。

## 11. 用 CNB 沙箱当算力（SSH）

CNB 云原生开发环境可以直接 SSH 进去当 8 核 16 GB 的算力机用：

```bash
# 启动（API）→ 取详情 → SSH
curl -s -X POST -H "Authorization: Bearer $CNB_TOKEN" -H 'Accept: application/vnd.cnb.api+json' \
  -H 'Content-Type: application/json' -d '{"branch":"main"}' \
  https://api.cnb.cool/ycyc755/lunar-lab-r1/-/workspace/start
curl -s -H "Authorization: Bearer $CNB_TOKEN" -H 'Accept: application/vnd.cnb.api+json' \
  https://api.cnb.cool/ycyc755/lunar-lab-r1/-/workspace/detail/<sn>   # remoteSsh 字段
ssh <remoteSsh> 'nproc; /opt/lunar/bin/python -c "import mujoco;print(mujoco.__version__)"'
```

实测：8 核 / 16 GB / 512 GB 盘；`/opt/lunar/bin/python` 里已有 mujoco 3.17.0、numpy 2.5.4、
trimesh 5.2.0；代码用 `tar | ssh` 同步（源 385 MB，几分钟）。

一条命令跑完整沙箱任务（起环境 → 保活 → 同步 → 跑两视角更新 → 回传）：

```bash
CNB_TOKEN=... bash scripts/cnb_run.sh --repo ycyc755/lunar-lab-r1
```

**限制（踩过）**：
- 工作区在**无活动连接**约 10–12 分钟后被回收，后台任务会随之消失；
  要长时间跑必须保持 SSH 会话（`ssh -o ServerAliveInterval=30 ... 'while true; do sleep 60; done'`）。
- 镜像缺 `rtree`（trimesh 布尔求交需要）→ 已在 `.ide/Dockerfile` 里补装。
- 令牌偶发 401（`errcode 16`），短时间高频调用容易触发；拉开间隔即可恢复。

## 12. 轨迹记录修复（§11.2）

审查基线里 `rerun_trajectory.jsonl` 是 0 字节——`v7_rerun.py` 建 `EpisodeRunner` 时没开
`record_trajectory`。已修：开记录、把帧写进 jsonl，并在**帧为空时直接失败**（不谎称有轨迹）。

实测（R03 / V7_R03_s2 / R1 / seed 0）：`{"success": true, "n_frames": 327}`。

## 13. 评价器口径切换（2026-10-31）

**旧口径**：`box_surface_distance` 对**所有 box 表面**取最小值 —— 相邻盒之间的内部接缝被当成实体外表面。
任务书 §5.2 的已知答案（两个相邻单位盒，点 `(1,0.5,0.5)` 应为 **0.5**）在旧实现下读出 **0.0**。

**新口径**：先求并集**暴露面**（某侧邻格为空才算外表面），再算点到矩形的精确距离。
`sample_box_surfaces` 同步改用暴露面规则，部分暴露面保留暴露部分，不再整面删除。
已知答案回归 `verify/collision_known_answers.json`：**8/8 通过**（单盒、接缝、L 形部分暴露、凹槽、通道、平移、缩放、分块等价）。

**已按新口径重测**：V7_R03_s1 → IoU 0.9852 / s2c **0.623 mm** / c2s 0.740 mm，**仍合格**（峰值 731 MB）。

**尚未按新口径重测**：V7_R02_s2、V7_R04_s2 —— 它们的 `body.stl` 不在本机（`.gitignore` 排除了
`*.stl`，原远端主机已回收），因此资格表里这两行标注为**旧口径**，不能与新口径混报。
重测需要先由父候选 + 观测重新融合生成网格。

## 14. 两视角更新：可见通过、碰撞待定的真实状态

| 版本 | 面数 | 水密 | 可见 obs1 | 可见 obs2 | 碰撞 |
| --- | --- | --- | --- | --- | --- |
| 交集原网格 | 509,408 | ✗ | 0.9803/1.669/**0.0126** | 0.9836/1.761/**0.0108** | 不可测（非水密） |
| 体素填充闭合 | 148,430 | ✓ | 0.9599/2.305/**0.3988** | 0.9626/2.308/**0.2199** | **0.9684/1.25/1.299 通过** |
| 仅补洞（fill_holes） | 310,156 | ✓ | 待测（面数超 20 万，需多 mesh 路径） | 待测 | 待测 |

**结论**：同一网格上"可见合格"与"碰撞合格"尚未同时取得。
- 不闭合 → 碰撞不可测；
- 体素填充闭合 → 凹处被填平，可见 freespace 0.40/0.22，形状已变；
- 仅补洞 → 形状基本不变且水密，但 31 万面需要多视觉 mesh 渲染路径才能评价（本批已具备该路径）。

**这不是判定失败，是测量路径问题**；下一步固定为：用多视觉 mesh 路径评价 fill_holes 版本 → 若可见通过再测碰撞。

### 14b. 结论修正：补洞版本才是可判定的网格

| 版本 | 水密 | 形状是否保持 | 可见 obs1/obs2 | 碰撞 |
| --- | --- | --- | --- | --- |
| 交集原网格 | ✗ | — | 0.9803/1.669/0.0126、0.9836/1.761/0.0108 | 不可测 |
| 体素填充闭合 | ✓ | **否**（凹处填平） | 0.9599/…/**0.3988**、0.9626/…/**0.2199** | 0.9684 通过（**作废**，形状已变） |
| **仅补洞（PLY）** | ✓ | **是**（可见指标与原网格一致） | **0.9803/1.669/0.0126、0.9837/1.761/0.0108** | **0.8832 / 1.123 / 5.026 → 不合格** |

**最终判定**：两视角更新在**可见**上成功（双视角通过且形状保持），在**碰撞**上不合格
（IoU 0.8832 < 0.95，c2s 5.026 mm 刚越线）。先前"0.9684 通过"来自形状被改变的闭合网格，已作废。

**收敛对照（§5.4）**：同一补洞网格，仅改碰撞体素与评价网格：

| 并集体素 | 评价网格 | box 数 | IoU | s2c | c2s | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 2.5 mm | 4.0 mm | 5,383 | 0.8832 | 1.123 | **5.026** | 不合格 |
| 2.0 mm | 3.0 mm | 8,687 | **0.9025** | 1.000 | **4.000** | 不合格 |

加密把 c2s 从 5.03 拉到 4.0（过门槛）、IoU 0.8832→0.9025，但**仍 < 0.95 且收益递减** →
是 box 并集对这张细碎表面的**表示上限**，不是分辨率或评价错误。
要过 0.95 需要换碰撞表示（自适应 box / 多层并集），本批记录为表示能力边界。


## 15. 干净目录复现（§12）

在一个**全新目录**里只用仓库内容（`git archive HEAD`，不含 `runs/`）验证：

| 检查 | 结果 |
| --- | --- |
| `scripts/v7_collision_known_answers.py` | **8/8 PASS**（评价器已知答案，纯代码可复现） |
| `scripts/run_r1.py --audit` | 正确报告 **7 个输入缺失**（证据/网格不在仓库里）—— 这是任务书要求的"缺原始输入必须明确失败"，不是静默通过 |
| `scripts/v7_negatives_18.py` | 缺证据路径的条目按规则失败（不伪装通过） |

**结论**：代码层可复现（评价器与反例可独立运行）；**数据层不可复现**，因为
`runs/` 下的网格与证据被 `.gitignore` 排除且原主机已回收。这是本批的真实复现边界：
重建需要从父候选 + 观测重新融合，而那批中间 STL 也不在仓库里。
