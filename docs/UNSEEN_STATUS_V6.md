# V6 当前状态（2026-10-29，main，增量）

> 入口：`runs/unseen/delivery_v6/v6_20261029/manifest.json`；页面：
> `runs/unseen/delivery_v6/v6_20261029/media/replay/index.html`（截图 `media/page/v6_replay_page.png`）。
> 本批 **new create = 0**，只用 V5 已有真实资产。

## 0. 四类状态

| 状态 | 值 | 说明 |
| --- | --- | --- |
| execution_status | **PARTIAL** | A/B/C/E/G/H/I/J 有产物；D 的 F1/F3 未跑；F 只做单候选 |
| evidence_status | **MIXED** | 融合/比较/轨迹有实际记录；V6 验收 32/32；H5-F 的 CoACD 碰撞保真不合格；结论不能升级 |
| capability_status | **PARTIAL** | H5-F/B3-F 可见几何可运行并通过 strict；碰撞保真、隐藏先验作用、多候选/第二观察收益未建立 |
| benefit_status | **NOT_ESTABLISHED** | H5-F 的局部 S1 成功不能归因于隐藏几何：碰撞体占据 IoU 0.28 |

## 1. V5 预测误差（工作包 B）

R01 face12k，同候选/同初态：

- L2：候选预测 3/3、均值 6.10 s；真值 **2/3**，seed0 30.02 s `time_limit`；**1 个 false safe**。
- S1：候选预测 3/3、均值 6.407 s；真值 **3/3**（6.54/6.52/6.72 s）。
- 预测排序 L2 > S1（约 0.3 s），真值排序 S1 > L2。V5 因此选 L2 的预测优势不成立。
- 数据：`prediction_audit/prediction_audit.json`、`action_confusion.csv`、`summary.md`。

## 2. H5-F / B3-F（工作包 C）

融合器：`scripts/fuse_observed.py`，只读 observation + 已配准父候选 + 冻结参数；
体素占据 → 自由空间 carving → 观测壳 → 轮廓约束 → 深度 clamp → marching tetrahedra。

| 资产 | 分辨率 | IoU | P95 | freespace | watertight | hidden faces | strict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H5-F | 5 mm | 0.9475 | 2.82 mm | 0.0376 | true | 49k | **pass** |
| H5-F | 4 mm | 0.9425 | 1.74 mm | 0.0375 | true | 49k | **pass** |
| H5-F | 6 mm | 0.9362 | 1.93 mm | 0.0744 | true | — | fail（收敛检查） |
| B3-F | 5 mm | 0.9386 | 2.86 mm | 0.0463 | true | 50k | **pass** |
| raw H5 | — | 0.8622 | 11.0 mm | 0.5106 | — | — | fail |

- 可见几何由构造得到；**不能说“Lux3D 自己重建准确”**。
- B3-F 是镜像先验 + 同一融合器，不是 Lux3D。
- 详细：`fusion/validation_v6.json`。

## 3. 碰撞保真（工作包 E）

| 资产 | parts | 表面 P95 | 占据 IoU | 判定 |
| --- | --- | --- | --- | --- |
| H5-F | 32 | 8.05 mm | **0.284** | **COLLISION_UNRELIABLE** |
| H5-F | 64 | 7.63 mm | **0.286** | 仍不可靠；不是 32 上限单独造成 |
| B3-F | 16 | 8.72 mm | 0.906 | 近似，ATTENTION |
| raw H5 | 32 | 6.61 mm | 0.192 | 不可靠 |

H5-F 的融合表面高频、薄，CoACD 32/64 都没保住占据；因此由 H5-F 碰撞体得出的 S1 安全预演**不能当作隐藏几何结论**。数据：`collision/summary.json`。

## 4. 同条件比较（工作包 F，单候选）

同一真值 `ae1837cd…`、同一 30 s、同一初态 0/1/2；决策规则 `worst-case-risk/v2`（最坏代价、A0 不入安全集）。

| 方法 | 自选 | 真值 planning | 验证 3–7 | 均代价 | 说明 |
| --- | --- | --- | --- | --- | --- |
| H5_raw | L2 | 2/3 | 3/5 | 24.787 | 与 V5 一致 |
| H5_F_single | S1 | 3/3 | 5/5 | 6.593 | **但碰撞不可靠，仅诊断** |
| B3_F | A0 | 0/3 | 0/5 | 40.0 | 无稳健动作，A0 |
| B0_blind | R1 | 0/3 | 0/5 | 60.0 | 翻覆 |
| U_truth | S1 | 3/3 | 5/5 | 6.593 | 上限参考 |

H5-F 的 S1 成功与 U_truth 相同，且优于 raw/B0；但 H5-F 的碰撞近似不合格，B3-F 又全无稳健动作。
因此不能把这解释为“生成隐藏先验已被证明有用”。多候选 H5_F_multi 未跑。

## 5. 第二观察（工作包 G）

- 真实候选对：H5_F_single（S1） vs B3_F（A0）→ `triggered=true`（动作分歧）。
- 机器人实际移动/制动/观察：基线 0.529 m、bearing 11.67°，观察可用；第二视角 H5-F IoU 0.8813、B3-F 0.874，**两者都保留（no_rejection）**。
- 从观察后状态重新预演，worst-case 决策 **A0**；真值 A0 abort、R1 tipped。
- 第二观察没有把候选分开，也没有改善决定；真实信息作用未建立。数据：`observation/summary.json`。

## 6. 月壤（工作包 H）

- V5 的“静态”`env.step(零)`仍按 v_ref 驱动车轮；V6 改为 `brake_step` 显式零轮速/制动保持。
- 稳定窗口 50 步：max wheel qvel 0.00116、base vx 5.6e-5、tilt range 0.0033°、min ncon 12 → `MEASURED`。
- 公式下陷 **9.75 mm**；同一时刻轮底实测 **−0.893 mm**（轮底在地面上方/接触间隙）→ 整机几何下陷仍未实现。
- V5 1000 回合稳定性可复用（物理未改）；0.655/1.172 s 是 wall time，不是通行时间；1.768 是土壤/刚性 wall-time 比，等价吞吐约 0.566，不是“提高 1.768 倍”。

## 7. 连续回放与页面（工作包 I）

- 真实轨迹（qpos/qvel/action/contacts）：候选 L2 成功 6.10 s、真值 L2 30.02 s 超时、真值 S1 6.54 s 成功。
- GIF：`media/replay/H5_raw_L2_seed0.gif`、`truth_L2_seed0.gif`（301 帧）、`truth_S1_seed0.gif`。
- 页面：`media/replay/index.html`（五段：看见/融合/试走/决定/月壤）；真实 Chromium 截图 `media/page/v6_replay_page.png`。
- 页面明确：输入仿真 RGB-D、执行独立仿真、H5-F 可见面由构造得到、B3-F 镜像不是 Lux3D、fixture 不是真实收益。

## 8. 仍未完成

- F1/F3 fixture（可见面扰动、单位缩放链）；
- H5_F_multi 多候选消融；
- 逐接触点到融合区域映射（不声称接触 generated_hidden）；
- 64 部件之外更细的碰撞分解/关键结构保持；
- 真实第二观察的收益（本轮 A0，未建立）；
- V6 统一验收 **33/33**（含实际真值文件 SHA 与负例）；Git 提交推送待做。
- 全套测试：`Ran 130 tests in 777.748s`，`OK (skipped=1)`；日志 `verify/unit_v6.log`。
