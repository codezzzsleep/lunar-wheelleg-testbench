# 当前状态（唯一状态文档）

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

## 七、账本

| 项 | 值 |
| --- | --- |
| 本批新增付费 create | **0** |
| 历史 500 积分授权 | 不变 |
| 实际扣费 | **unknown**（外部对账项） |
