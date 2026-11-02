# 当前状态（唯一入口）

最后更新：2026-11-02 深夜 · v2 批次进行中 · 代码起点 `84a3c33b8`

## 本批已确立的实质结论

1. **融合入口缺陷已定位并修复（fuse-observed/v3）**：v2 用
   `shell & ~dilate6(parent_inside)` 在观测壳层与父先验之间人为挖出 1 体素空隙，
   再用 `largest_component` 二选一。P06·S1 上 B1 的父先验 3,569 体素被整块删除
   （kept_ratio=0），C1 的观测壳层 4,927 体素被整块删除（可见面 IoU 0.806）。
   v3 改成“只按像素抑制壳层、不删父先验”，并按“含父先验的连通块无条件保留、
   纯壳层碎屑才按体积清理”做组件整理。修复后 B1/C1 的 kept_ratio 均为 1.0，
   壳层保留，fused strict 通过（P06·S1 B1 IoU 0.932 / P95 4.21 mm）。
2. **已知答案核查的是体素去向，不是 fused strict**：用真值网格 P06 走 align24
   后作父先验，父先验 451,068/451,068 体素保留（kept_ratio=1.0）；壳层 6,089 体素、
   无壳层对照的 freespace 分别为 0.0668 / 0.0666——**freespace 超限来自 2.5 mm
   体素化+等值面提取，不是壳层造成的**，不能靠放宽阈值掩盖。
3. **B3_F 改标“镜像补全”**：既有 B3_F 结果是镜像先验+观测约束，不是壳层对照，
   也不是生成贡献消融。主表 B3_F 行标 `comparison_label=mirror_completion`。
   真正的生成消融是 `fuse_observed --ablate-generated-unknown`：同一候选、同一
   parent、同一栅格、同一状态与预算，只删除未知区父先验体素。
4. **规划土壤口径改为冻结 5 点集**（区间四角+中心，标签 p0..p4），与 20 状态
   筛选所用的 C 扫描一致；nominal 单点只作诊断，三档 `low_traction/high_drag`
   只作敏感性，不混入主比较。
5. **筛选口径存在一处必须报告的不一致**：C 扫描（`v2_soil_c.py`）用 `visible={}`
   跑真值动作，而正式规划器用真实可见量；两者会改变 D1/D2 等动作的触发参数。
   用真实可见量复算时，已发现部分入选状态的真值参考为 A0（如 P01·S1、P01·S3）。
   因此 20 状态主表的 U_truth 行以**正式可见量**为准，真值无动作的状态记
   `no_reference_action`，不能算“过度保守”。

## 工程收紧

- 融合产物准入：`manifest.json` + `artifact_status=complete` + `content_sha` +
  观测/父网格/代码 SHA 全部匹配；`partial.json` 或 `failed.json` 存在即拒绝。
  下游不再仅凭 `occ.npz` 存在就继续碰撞/预演。
- 依赖锁定：`requirements-lock.txt`（Python 3.12.16 / mujoco 3.17.0 / numpy 2.5.4 /
  scipy 1.18.1 / trimesh 5.2.0 / manifold3d 3.5.4 / pillow 13.0.0），
  每个融合清单写 `environment` 块。
- 生成记账：`v2_gen_six.py` 逐任务写 `runs/lux3d/ledger.jsonl`（submitted/completed、
  estimated_credits=1、实际 consumed_credits 若接口返回）；已提交失败不重复付费，
  只补从未提交的并发失败。

## 进行中（沙箱后台）

- Phase C：20 状态 × 六候选 → 融合/碰撞/5 点规划 + A1 生成消融（`v3batch/`）。
- Phase D：20 状态 × 非 Lux 六行的 5 点规划（`v3batch/<state>/nonlux.json`）。
- P58·S2 三关键状态完整消融（`v3batch/P58_S2/`）。
- 旧 v3 结果已移至 `v3batch_pre_final/`，不参与主表。

## 协议与归档

- v2 协议：`plans/v2_protocol.json`（修订 A1 已更名为
  `mirror_completion` + `generation_ablation`）；v1 归档 `plans/archive/`。
- 新的状态选择清单：`runs/.../v2_main_states.json`（20 状态，8 块石头）。
- 详细证据：`docs/V2_*.md`（融合清单、雕刻机制、壳层对照、C1 单独结果、配准记录）。

---

# 归档：v1 及更早过程


最后更新：2026-11-01 · 基线 `3280c741` · 本批按《下一批执行任务书》推进 ·
其他 `docs/*.md` 为归档，保留过程与更正，不再逐份更新。

## 一、结论四栏

| 栏位 | 状态 | 依据 |
| --- | --- | --- |
| 工程执行 | **PARTIAL→推进中** | 共同规划已统一并实跑；预检、第二观察、2.5D、七行比较、碰撞等价均已落地；页面与打包在建 |
| 证据 | **PARTIAL** | R01/R02/R03 各至少一个状态有完整 21 格预演与真实执行轨迹；新留出集尚未生成 |
| 能力 | **PARTIAL** | R02 上 2.5D 补平策略真实通行（x=3.561），与真值参考（L2，x=3.606）同级；R01 全部家族不通行 |
| 收益 | **NOT_ESTABLISHED** | 唯一有合格候选的 R03 无区分度；2.5D 在 R02 上有效但仅一个状态，不能外推 |

## 二、本批已修的真实缺陷（都是实现问题）

1. `U_truth` 返回固定 `R2` → 改为真值几何真实预演，R02 上会自己选 **L2**；
2. 空可见量 `visible=None` → 缺 `x_front/W_vis/H_vis` 直接报输入错误；
3. 成本恒 `9e9` → 用真实模拟时间（成功=完成时刻，放弃/失败=冻结代价）；
4. 土壤集合与宽度规则各自定义 → 显式 `planning_soils` 全集枚举 + `eval_six.plan_width_rule`；
5. 无候选只写决策 → 改为**真实执行 A0**。

统一实现：`scripts/common_planner.py::plan_action`。

## 三、目前的方法实现与结果

**七行主比较（同一状态、同一可见量、同一预算）**

| 家族 | R01@1.0 | R02@0.9 |
| --- | --- | --- |
| 高度规则 | A0 | A0 |
| 方盒子 B2_F | A0 | A0 |
| 镜像 B3_F | A0 | A0 |
| 2.5D 挡未知 | D1 失败 | D1 失败 |
| **2.5D 补平** | R1 失败 | **R1 通行（3.561）** |
| Lux3D H5_F | A0 | A0 |
| 真值参考 | A0 | **L2 通行（3.606）** |

**第二观察（公平三臂）**：R01/R02 上 A 与 B 决策、结果完全一致 → 信息价值为 0；
R02 的差距不在第二张图，而在候选几何过于悲观（真值能过、候选不能）。

**碰撞决策等价**：R02 的 Lux3D/方盒/镜像与 R01 的 s2 候选对表示敏感（变粗后决策改变），
标 `representation_sensitive` 并用参考表示；R01 的两个先验不敏感，可用粗表示。

**新留出筛选**：规则已冻结（`plans/holdout_protocol.json`）；现有 12 个配置按规则选出 6 个。
池只有 17 个对象（13 GLB + 4 石头），未达 48，原因是新增真实几何需付费生成，本批未授权。

## 四、输入、状态与土壤

- 观测：`runs/unseen/delivery_v7/v7_20261030_r1/scan_obs2/`（4 配置）+ `runs/unseen/recovery_r3/obs_R03`；
- 共同状态：`common_states/<config>/<soil>/seed<7|11|13>/`，含 S0 与 S1 快照、采集记录；
- 土壤：`planning_soils=[nominal,low_traction,high_drag]`，执行土壤 `nominal`，
  全部经 `v7_soil.resolve()` 注入真实参数（nominal 不再退化成 rigid）。

## 五、作品入口与复现

```bash
# 五画面作品页（同一运行的数据）
.venv/bin/python scripts/v7_story_page.py \
  --run runs/unseen/delivery_v7/v7_20261030_r1/family_compare/R02_s0.9_nominal_seed7 \
  --out runs/unseen/delivery_v7/v7_20261030_r1/story/R02.html
# 浏览器直接打开该 html；播放/暂停/拖动/揭晓都在同一页

# 七行主比较（重跑）
.venv/bin/python scripts/v7_family_compare.py --config R02_s0.9 \
  --out runs/unseen/delivery_v7/v7_20261030_r1/family_compare/R02_s0.9_nominal_seed7

# 2.5D 资产与评估
.venv/bin/python scripts/v7_elev25d.py --observation runs/.../scan_obs2/R02_s0.9 \
  --case cases/unseen_v1/R02.json --out runs/.../elev25d/R02_s0.9
.venv/bin/python scripts/v7_elev25d_eval.py --config R02_s0.9 --out runs/.../elev25d_eval/R02_s0.9_nominal_seed7

# 共同规划预检
.venv/bin/python scripts/v7_precheck_next.py --config R02_s0.9 --out runs/.../precheck_next/R02_s0.9_nominal_seed7

# 演示包（新目录完整运行，缺项非零退出）
bash demo/r1_r03_two_view/run_demo.sh /tmp/demo_new
```

## 六、仍然缺什么

1. 新留出集需要真实新几何：**一次性生成申请草案**见 `docs/GENERATION_REQUEST_DRAFT.md`，
   单价与费用上界待填，本批未授权；
2. 2.5D 补平目前只在一个状态上验证，未随新留出集统一运行；
3. R01 无任何家族通行，是动作库边界，不是表示问题；
4. 页面尚未接入"新仿真"按钮（当前由脚本生成页面）。


## 更正：碰撞资产加载（2026-11-01 晚）

**根因**：旧入口把资产根目录直接交给环境。

- 普通融合资产的碰撞体在 `<root>/collision/manifest.json`，根目录 manifest 只列了 `body.stl`；
- 两视角资产的根目录**没有 manifest.json**，加载直接抛异常；
- 异常被吞成"没有安全动作"，于是输出 A0，被读成"候选认为过不去"。

**修复**：`scripts/collision_asset.py::resolve()` 统一解析（先 `collision/`，再根目录，逐个校验 boxes/parts 可用），
所有实验入口复用；`common_planner` 把加载失败记为 `rehearsal_error`，与物理失败分开，
整轮若全是 `rehearsal_error`，决策理由记 `inconclusive_rehearsal_errors`，不再写 `no_safe_traversal`。

**实跑证据**（R02、nominal、seed7，四类资产）：

| 资产 | 解析 | R1 | L2 |
| --- | --- | --- | --- |
| 方盒 B2_F | boxes 3900 | tipped | **success** |
| 镜像 B3_F | boxes 3560 | tipped | tipped |
| Lux3D H5_F | boxes 6595 | tipped | **success** |
| 双视角 | boxes 6742 | tipped | **success** |

`rehearsal_error = 0`，8 次全部是真实物理结果。见 `runs/.../collision_smoke/summary.json`。

**暂时撤回的解释**（原始记录与文件保留）：

- "第二观察价值为零"——B 臂双视角资产根目录无 manifest，属加载失败；
- "候选过于悲观"——同上；
- "碰撞表示敏感"——参考表示跑在 mesh、粗表示跑在 box，口径不一致；
- 旧七行表中方盒/镜像/Lux3D 行加载的是重建 mesh，不是 canonical box 并集，结论待重跑。

**不受影响**：2.5D 两行与真值参考行（根目录即 boxes）。


## 更正二：2.5D 网格坐标（同日）

**根因**：网格原点 `x0 = x_front − 0.6 = 1.0537892` 未落在 1 cm 格点上，但 box 索引按
`round(x0/cell)` 计算，于是整张高程图沿 +x 平移约 **1.05 m**。

| | 旧（错位） | 修正后 |
| --- | --- | --- |
| 石头 x 范围 | 2.704–2.914 m | **1.650–1.860 m**（真值石头在 1.8） |
| 盒子数（fill） | 536 | 546 |
| 挡未知 | D1 → 失败 | **A0（无安全通行动作）** |
| 补平 | R1 → 成功 3.561 | **L2 → 成功 3.606** |

修正后 2.5D 补平**仍然通行**，但动作由 R1 变为 **L2**，与真值参考选的 L2 一致；
挡未知由"撞车"变为"直接放弃"。旧的两个数值作废。

修复方式：原点向下取整到格点（`floor(x0/cell)*cell`），x/y 索引改为纯偏移，
z 用 `floor/ceil` 取整，避免再出现隐式平移。


## 更正三：修复后统一重跑（作废旧表）

碰撞加载与 2.5D 坐标修好后，三张表全部重跑。原始旧表保留，但结论以本节为准。

**七行主比较**

| 家族 | R01@1.0 | R02@0.9 |
| --- | --- | --- |
| 高度规则 | A0 | A0 |
| 方盒子 | A0 | **L2 通行 3.606** |
| 镜像 | A0 | A0 |
| 2.5D 挡未知 | A0 | A0 |
| 2.5D 补平 | A0 | **L2 通行 3.606** |
| Lux3D | R2 失败 1.513 | **L2 通行 3.606** |
| 真值参考 | A0 | **L2 通行 3.606** |

**公平三臂（R02）**：A（第一图）L2 成功 27.7 s；B（第二图）L2 成功 27.7 s；C（S0 直接）D2 成功 7.46 s。

**碰撞决策等价（R02）**：Lux3D L2→L2 不敏感、方盒 L2→L2 不敏感、镜像 A0→R2 敏感。

**由此更正的解释**

- "第二观察价值为零"的**依据不成立**（旧 A/B 是加载失败），但结论仍成立：A 与 B 决策与结果完全一致；
- "候选过于悲观"**不成立**：方盒子与 Lux3D 在正确加载后都能找到 L2 并通行；
- "碰撞表示敏感"**不成立**：3 个资产里只有镜像 1 个敏感；
- 新增观察：S0 直接行动也能通行且便宜（7.46 s vs 27.7 s），观察的净价值需要重新论证。


## 九、新留出集（2026-11-02）

- 生成 7/7 成功（Lux3D g1-turbo，image-to-3d，1 积分/任务，上界 140 计入既有 500）；
- 评估在沙箱完成（8 核/16 GB，7 路并行），**168/168 行**，无 asset_missing、无 rehearsal_error；
- 21 个状态分类：**参考无解 15 / 候选通行 3 / 过度保守 3**；
- 过度保守三例：P06·S1、P06·S3、P58·S2，逐格确认非计算错误；
- 详情见 `docs/ROCK_GRID_REPORT.md`，页面 `runs/.../story/story_P06_S1.html`、`story_P29_S2.html`。

## 七、账本

| 项 | 值 |
| --- | --- |
| 本批新增付费 create | **0** |
| 历史 500 积分授权 | 不变 |
| 实际扣费 | **unknown**（外部对账项） |
