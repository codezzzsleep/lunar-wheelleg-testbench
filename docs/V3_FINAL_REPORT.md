# v3 最终报告：真实扫描岩石上，Lux3D 隐藏几何是否改善隐藏区理解与行动

> 单篇报告。当前状态只看 `docs/CURRENT_STATUS.md`；本文件是结果与解释，不是状态文档。

## 0 主问题的回答

- 完成双枪执行的状态：**13** 个（FULL 与 OBS_ONLY 从同一个 S0 各执行一次）。
- 三结局：FULL {'pass': 11, 'safe_stop': 1, 'physical_failure': 1}；OBS_ONLY {'pass': 10, 'safe_stop': 1, 'physical_failure': 2}。
- FULL 更好 1 个；OBS_ONLY 更好 0 个；结局相同 12 个。
- 风险低估（FULL 预演安全、真值失败）0；过度保守（FULL 安全停下、OBS 能通行）0。

## 1 口径（先冻结，再看结果）

- 主比较：同一状态、同一公共观测几何、同一栅格与配置，FULL = V ∪ (生成父候选 ∩ 未知区)，OBS_ONLY = V（逐体素同一个数组）。
- 取消旧形状关：IoU≥0.85 / P95≤8% / 融合 strict 不再是准入条件；只检查数据有效、放置正确、观测不被覆盖、自由区不被占据、消融只删未知区。
- 隐藏敏感筛选只用完整真值：真值规划与观测规划动作不同，或两者在真值上的三结局不同；且完整真值至少有一条实测通行动作。
- 决策：候选级预演矩阵 → 多数票（≥⌊n/2⌋+1）→ 预登记代价最低；附加最坏规则（n/n）与固定首候选 A1。
- 执行：FULL/OBS_ONLY 各自从同一个 S0 恢复到同一真值场景、独立执行，不 reset、不多给时间。

## 2 数据与方法

- 来源池：Poly Haven CC0 真实摄影测量扫描件，池上限 48 状态网格，主网格 8 块石头 × 3 个 H/r 档 × 2 个首视角。
- 高度档 H/r = [1.4, 2.0, 2.6]（轮半径 0.086 m）。初始 0.6/1.0/1.4 档实测对现有轮式平台不产生接触，按 §4.4 的能力标定改档，改动发生在任何生成之前。
- 配准：24 朝向粗搜索 + 投影式多尺度鲁棒 ICP + 局部坐标下降；输出唯一矩阵，评估/导出/融合/碰撞共用。已知答案：未运行。
- 融合：栅格只由公共观测决定（pitch 0.002 m），V 与候选无关、一次落盘并哈希绑定；消融只删 U∩P，之后不做任何清理/补洞。
- 碰撞：占据按 2× 降采样到 0.004 m 后做 box union；不以 IoU 0.95 作准入。

## 3 筛选漏斗（真实规模）

| 项 | 值 |
| --- | --- |
| n_pool_rocks | 8 |
| n_states_planned | 48 |
| n_states_captured | 48 |
| n_complete_feasible | 44 |
| n_hidden_sensitive | 23 |
| n_selected | 22 |
| 选中岩石 | moon_rock_01, moon_rock_02, moon_rock_03, moon_rock_04, moon_rock_05, moon_rock_06, moon_rock_07, rock_07 |
| 分层 | {'action_only': 18, 'none': 25, 'action_and_outcome': 5} |
| 排除原因 | {'not_hidden_sensitive': 22, 'no_feasible_traversal': 4} |

## 4 主结果：FULL vs OBS_ONLY

| 状态 | H(m) | 真值选择 | 观测选择 | FULL 动作 | FULL 结局 | OBS 动作 | OBS 结局 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | 0.120 | R1 | D1 | D1 | pass | D1 | pass |
| moon_rock_01_h0v1 | 0.120 | R1 | D1 | D1 | pass | D1 | pass |
| moon_rock_01_h2v0 | 0.224 | L2 | A0 | A0 | safe_stop | A0 | safe_stop |
| moon_rock_02_h0v1 | 0.120 | R1 | D1 | D1 | pass | D1 | pass |
| moon_rock_02_h2v0 | 0.224 | R1 | L2 | L2 | pass | L2 | pass |
| moon_rock_02_h2v1 | 0.224 | L2 | D1 | D1 | pass | D1 | pass |
| moon_rock_03_h1v0 | 0.172 | R1 | L2 | L2 | pass | L2 | pass |
| moon_rock_03_h2v1 | 0.224 | D1 | R1 | R1 | pass | R1 | pass |
| moon_rock_04_h0v1 | 0.120 | D2 | L2 | L2 | pass | L2 | pass |
| moon_rock_04_h1v0 | 0.172 | R2 | L2 | R2 | pass | L2 | physical_failure |
| moon_rock_05_h1v0 | 0.172 | R1 | D1 | D1 | pass | D1 | pass |
| moon_rock_05_h1v1 | 0.172 | D1 | L2 | L2 | physical_failure | L2 | physical_failure |
| moon_rock_05_h2v0 | 0.224 | D1 | R1 | R1 | pass | R1 | pass |

### 4.1 多数 / 最坏 / 首候选

- 多数：上表 FULL/OBS_ONLY 列即多数规则（阈值 ⌊n/2⌋+1）。
- 最坏与首候选复用同一候选级矩阵；对应汇总在 `runs/v3/report/v3_results.json` 的每状态 `arms` 与 `decision/matrix_*.jsonl`。
- n_tasks / n_unique_geometries 逐状态记录在决策记录里；相同几何只算一票，任务分母保留。

## 5 隐藏区误差（候选分布）

- 候选-状态行数：6
- A_iou: {'n': 6, 'mean': 0.0107, 'median': 0.0106, 'min': 0.0086, 'max': 0.0132}
- A_missing: {'n': 6, 'mean': 0.9892, 'median': 0.9893, 'min': 0.9867, 'max': 0.9913}
- A_overfill: {'n': 6, 'mean': 0.5521, 'median': 0.5624, 'min': 0.4359, 'max': 0.6167}
- B_mae: {'n': 6, 'mean': 36.3008, 'median': 35.732, 'min': 33.044, 'max': 40.073}
- B_p95: {'n': 6, 'mean': 217.0, 'median': 215.8, 'min': 198.6, 'max': 236.6}
- C_rear_abs: {'n': 6, 'mean': 48.0, 'median': 46.0, 'min': 46.0, 'max': 56.0}
- C_drop_abs: {'n': 6, 'mean': 3.3333, 'median': 4.0, 'min': 2.0, 'max': 4.0}

OBS_ONLY 没有物体的格在物理规划中等同可通行地面；顶面计分按公共地面高处理，并另报"无隐藏表面"比例。空预测仍承担遗漏误差。

## 6 再看一眼（诊断子集）

- 本批未执行（记录为 observation_failure 或未运行，不伪造信息收益）。

## 7 作品与复现

- 五画面页面：`media/v3/page/index.html`；素材 12 个 mp4，[1920, 1080]@30 fps。
- 轻量包：`dist/v3_bundle/`（≤300 MiB，含离线演示与缓存重仿真入口；默认不联网）。
- 复现步骤见 `dist/v3_bundle/README.md` 与根目录 `README.md` 的 v3 一节。

## 8 错误分层与局限

- 管线错误（加载/渲染/度量）与机器人物理失败分开记；未完成不缩分母。
- 已知局限：单视角 + 光滑正面的配准存在沿面滑动歧义（见已知答案记录）；Lux3D 图像到 3D 的隐藏面是先验而非测量；月壤是半经验/受限模型，不是真实月壤。
- 生成过程没有界面录屏（无头 API）：以真实 task_id/时间线/上传图与返回资产为证，不伪造实时录屏。

## 9 结论

在已完成的 13 个隐藏敏感状态上，加入生成隐藏几何的 FULL 臂结局更好 1 次、更差 0 次。方向上支持"补上隐藏几何有助于行动选择"，但样本规模不足以声称统计显著，且必须与逐候选的隐藏误差分布一起读。
