# V6.1 续批状态（2026-10-29，main，进度快照）

> 入口：`runs/unseen/delivery_v6_1/v6_1_20261029/manifest.json`
> 计划：`plans/unseen_delivery_v6_1.json`；融合配置：`configs/unseen_v6_1_fusion.json`
> 本批 **new_create = 0**；V6 目录未改动。

**这份文件是进度快照，不是最终交付。** B/D/E/F/G/H 未完成时不得报 COMPLETE。

## 0. 四类状态（当前）

| 状态 | 值 |
| --- | --- |
| execution_status | **PARTIAL**（A done；C partial；B/D/E/F/G/H 未完成） |
| evidence_status | **MIXED** |
| capability_status | **PARTIAL** |
| benefit_status | **NOT_ESTABLISHED** |

## 1. 工作包 A：融合物理语义（DONE）

`scripts/fuse_observed.py` 重写为 `fuse-observed/v2`：

- **三类空间**：已知自由 / 测量带 / 未知，逐体素判定并写入 `space` 统计；
- **深度约定**：相机轴向深度 `positive_camera_minus_z`，与 align/freespace 度量一致；斜视 fixture 检出混用；
- **视野**：先判原始 u/v 是否在有效图像范围，clip 只防越界；视野外/无效深度/NaN/相机后方一律未知；
- **非周期边界**：`dilate6/erode6/dilate2` 全部零填充，边界外按未知/空；
- **网格语义**：cell-center（体素中心 = origin+(i+0.5)·pitch），等值面在相邻中心之间插值；
- **不挪顶点**：约束只在占据层施加，导出后不移动任何顶点（v1 的 `_clamp_visible` 已删除）；
- **有效配置**：命令行覆盖与基准配置合并写 `effective_config.json`，哈希进入运行身份；`band_m + free_epsilon_m < pitch_m` 直接报错。

已知答案回归 `verify/space_tests.json`：**12/12 通过**（平面自由、后 3 mm 非自由、视野外、相机后方、倾斜平面、周期边界 ×3、底面不绕回、可重复、配置身份、band<pitch 拒绝）。

试过但**更差**的方案（如实记录，已禁用）：把深度不连续像素排除在自由空间与壳约束之外，freespace 违例 0.1213 → 0.3714，因此 `use_depth_edge_exclusion=false`。

## 2. 融合几何（H5-F，冻结配置）

| 资产 | 网格 | IoU | 可见点 P95 | freespace | depth P95 | 水密 | strict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C_R01_face12k_H5F_formal | 5 mm | 0.9538 | 3.38 mm | **0.1220** | 11.57 mm | true | **fail** |
| C_R01_face12k_H5F_p004 | 4 mm | 0.9551 | 1.94 mm | **0.1104** | 6.99 mm | true | **fail** |

- 可见面精度已到 1.9 mm（4 mm），但 **freespace 违例不随分辨率下降**（0.122 → 0.110），说明它不是离散化造成，而是真实存在的前向突出（约 7–11 mm 的局部区域）。
- 因此 H5-F 的可见几何**本批仍未过 strict**；不得把它当合格资产使用。
- 父先验实体化：face12k 非水密，走 `shell_floodfill` 回退（已标 `solid_method`）；H5-F 输出水密，走射线奇偶。

## 3. 工作包 C：源实体 → 实际碰撞（PARTIAL）

### 3.1 评价器自检（DONE）

`scripts/collision_occupancy_metrics.py` 重写为 `collision-metrics/v2`：

- 占据并集按逐 part 求并（box 直接涂单元；凸 part 用半空间），**不加各 part 体积**；
- 双向表面距离用**并集外边界**：box 采样只在暴露面上（相邻单元为空），排除埋藏内面；
- 过填/漏填样本与体积分数、关键净空、评价分辨率/采样数/种子、源实体是否定义。

已知答案自检 `collision/selftest/selftest.json`：**3/3 通过**

| 实体 | 自身 | box 并集 | 凸包（填凹） | 错位 |
| --- | --- | --- | --- | --- |
| 立方体 | PASS IoU 1.0 | PASS IoU 1.0 | PASS（hull=self，N/A） | 检出 12.0 mm |
| 带凹槽 | PASS IoU 1.0 | PASS IoU 1.0 | **检出** IoU 0.940 / s2c 32.98 mm | 检出 12.0 mm |
| 带通道 | PASS IoU 1.0 | PASS IoU 1.0 / s2c 2.0 mm | **检出** IoU 0.934 / s2c 44.11 mm | 检出 12.0 mm |

### 3.2 两条碰撞路线（同一评价器）

源：`fusion/C_R01_face12k_H5F_p004/body.stl`（4 mm，水密）

| 路线 | 表示 | 数量 | 占据 IoU | 源→碰撞 P95 | 碰撞→源 P95 |
| --- | --- | --- | --- | --- | --- |
| CoACD | 32 凸部件 | 32 | **0.287** | 9.98 mm | **25.47 mm** |
| **box 并集** | 2780 轴对齐盒 | 2780 | **0.937** | **0.85 mm** | **1.29 mm** |

- CoACD 的填凹在更严的评价器下依然严重（碰撞表面离源 25 mm），与 V6 结论一致。
- box 并集把双向偏差压到 ~1 mm；唯一未达项是 **IoU 0.937 < 0.95**，差距来自 4 mm 构建 vs 2.5 mm 评价（过填 3.4%、漏填 3.1%）。
- MuJoCo 直接加载 2780 个原生 `box` geom：加载+reset 0.63 s，100 控制步 0.46 s，接触正常；不做凸包、不再缩放/贴地。
- **未完成**：2.5 mm 构建以满足字面 IoU、探针/接触验证（C5）、性能对照（C6）、缓存身份（C3）。

## 4. 工作包 B：已知答案 fixture（PARTIAL）

F0/F1 已跑出可核对结果；F2–F5 被 harness 路径缺陷挡住，**未跑，不伪造**。

| fixture | 设置 | IoU | 可见点 P95 | freespace | 隐藏保留 | 判读 |
| --- | --- | --- | --- | --- | --- | --- |
| **F0** | 父候选 = 观测真值实体本身 | 0.9676 | 2.18 mm | **0.1105** | 1.000 | 仍不过 strict |
| **F1** | 可见面外推 8 mm、隐藏不变 | 0.9678 | 2.13 mm | **0.1096** | 1.000 | 可见面被拉回、隐藏全保留 |

### 关键结论（F0）

**在“父候选完全正确”的已知答案下，融合仍然得到 freespace 0.1105。** 这证明 H5-F 的
0.11 违例来自我方的占据/提取阶段（壳厚、掩码膨胀 1 px、体素量化），**不是 Lux3D 父候选造成的**。
这把 V6 的“生成几何导致误差”解释进一步收窄：可见面一致性首先是我们的融合器问题。

F1 同时说明：可见面被观测约束拉回（IoU 0.9678、P95 2.13 mm），隐藏部分 100% 保留
（`hidden_kept_ratio=1.0`，被自由空间切掉 1206 个体素），即“保留生成隐藏几何”这一层是成立的，
不成立的是可见面的最后 1 个体素。

## 5. 未完成（本轮继续）

- B：F2–F5 未跑（harness 路径缺陷）+ F0/F1 的 freespace 0.11 需要在壳厚/掩码层修掉；
- D：R01 四父候选 + R03 资格、H5_F_multi、决策完整性合同、决策先落盘；
- E：同条件比较、预测误差、接触来源、rigid/soil 接线；
- F：真实多候选第二观察；
- G：页面与回放更新；
- H：三层验收与 12 条实际反例。
