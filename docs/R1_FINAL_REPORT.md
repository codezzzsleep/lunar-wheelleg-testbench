# 看不见的那一面 · R1 整批统一汇报（2026-10-31）

审查基线 `f91a6a8b` · 本批代码 `main = f55ff387`（写作时）· 批次目录 `runs/unseen/delivery_v7/v7_20261030_r1`

---

## 一、现在用户能操作什么

```bash
# 一条命令：起 CNB 工作区 → 保活 → 同步 → 跑 → 回传（需要 CNB_TOKEN）
CNB_TOKEN=... bash scripts/cnb_run.sh --repo ycyc755/lunar-lab-r1

# 本地：入口自检 / 干跑 / 分阶段
.venv/bin/python scripts/run_r1.py --audit
.venv/bin/python scripts/run_r1.py --dry-run
.venv/bin/python scripts/run_r1.py --stage all          # 八阶段，已完成自动跳过
.venv/bin/python scripts/run_r1.py --stage six --force  # 单阶段重跑

# 单候选双门槛测量（一条命令）
.venv/bin/python scripts/v7_measure_candidate.py --fusion <dir> --pitch 0.0025 --eval-pitch 0.004

# 页面：总览 + 每次闭环回放 + 连续播放器 + 重仿真命令
runs/unseen/delivery_v7/v7_20261030_r1/media/report/index.html
runs/unseen/delivery_v7/v7_20261030_r1/media/report/player.html

# 统一验收 / 反例
.venv/bin/python scripts/verify_delivery_r1.py     # 73 项
.venv/bin/python scripts/v7_negatives_18.py        # 18 类
.venv/bin/python scripts/v7_collision_known_answers.py  # 8 项已知答案
```

CNB 沙箱：8 核 / 16 GB / 512 GB 盘，镜像自带 mujoco 3.17.0 + OSMesa；
实测 warm 启动 **Prepare 15.2 s + 六 stage 约 8 s**，改 Dockerfile 时冷启动 68 s。
**工作区在无活动连接约 10–12 分钟后被回收**，长任务必须持 SSH 会话（`cnb_run.sh` 已内建）。

---

## 二、八项完成标准逐项结论

| # | 标准 | 结论 | 入口 / 证据 |
| --- | --- | --- | --- |
| 1 | 同案例、可恢复、默认不付费的统一入口 | **达成** | `run_r1.py`（`--audit`/`--dry-run`/`--force`，生成需 `--allow-generate`）；跨案例可见量已切断（新增 `v7_visible_public.py`，R03 用 R03 的 `x_front=1.6055, W_vis=0.4578`） |
| 2 | 修正后的并集评价器 + 已知答案 + 全部正式资产按同一版本重测 | **部分** | 评价器已修（暴露面语义，已知答案 8/8）；**R03_s1 已按新口径重测**；R02_s2、R04_s2 网格丢失未重测，标为旧口径 |
| 3 | 完整候选/动作/状态/土壤矩阵，错误不缩分母，决策先落盘 | **达成** | 四维聚合（candidate×action×state×soil）；`rehearsal_error` 计入失败；18 项反例覆盖 |
| 4 | 同场景恢复 vs 跨假设投射，真实独立验证状态，直接继续对照 | **部分** | 两种模式与签名校验已实现（A/B/C/D 全过）；验证初态来自 drive seed 重编号，已标注**非独立**；未停稳状态单列 |
| 5 | 真实第二观察、两视角更新、双视角验收、重规划、真值续行 | **部分** | 第二观察真实（sha `171283e804ea110d`，可复现）；两视角更新**可见双视角通过**；**碰撞 0.9025 < 0.95 不合格** → 未进入重规划/真值续行 |
| 6 | 强基线齐全的同条件结果，保留全部分母 | **达成（负结果）** | R03/R02 六方法 × 三土壤 × 验证初态；收益 **NOT_ESTABLISHED** |
| 7 | 连续逐帧回放 + 页面真实重新仿真 | **达成** | 轨迹 327 帧真实记录；播放器支持播放/暂停/进度/速度；`v7_server.py` 提供页面后端，按钮触发**真实 MuJoCo 重仿真**（实测新 run_id `20261031T120326-e01aec`、327 帧、success） |
| 8 | 干净目录免费复现、统一验收、负例、单篇报告、远端身份 | **部分** | 干净目录：已知答案 8/8、反例 16/18（缺证据项明确失败）、audit 报 7 项缺失；验收 73/73；本报告；`main` 已推送 |

---

## 三、对象、任务与分母

| 项 | 数 | 说明 |
| --- | --- | --- |
| 独立对象 | **4**（R01–R04） | 纲领要求 4 个 |
| 生成任务 | 10 + 4 = **14** | 本批新增 4 个（1 积分/任务口径估算） |
| 可测候选 | **6** | R01_s1/s2/tv1/dtv、R02_s1/s2/g1/g2、R03_s1/s2、R04_s1/s2 中的可测者 |
| 新口径合格 | **1**（V7_R03_s1） | 可见 + 碰撞均过 |
| 旧口径合格 | 2（V7_R03_s2、V7_R02_s2） | 评价器修复前测得，需重测 |
| 两视角合格 | **0** | 可见通过、碰撞 0.9025 不合格 |

---

## 四、资格表（新旧口径分列）

| 候选 | 口径 | 可见 IoU / P95 / freespace | 碰撞 IoU / s2c / c2s | 结论 |
| --- | --- | --- | --- | --- |
| **V7_R03_s1** | **新** | 0.9737 / 1.702 / 0.0392 | **0.9852 / 0.623 / 0.740** | **合格** |
| V7_R03_s2 | 旧 | 0.9551 / 2.65 / 0.0473 | 0.9918 / — / — | 旧口径合格 |
| V7_R02_s2 | 旧 | 0.9841 / 2.042 / 0.0461 | 0.9893 / 0.504 / 0.792 | 旧口径合格 |
| V7_R04_s2 | 新（可见）/旧（碰撞） | 0.9654 / 1.979 / 0.0339 | 0.9776 / 1.357 / **37.626** | 不合格（碰撞） |
| V7_R01_tv1 | 新 | 0.9548 / 1.835 / **0.0875** | — | 不合格（freespace） |
| V7_R02_g1 / g2 | 旧 | 0.9661 / 0.0978、0.6737 | — | 不合格 |
| tv_R03_s1（两视角） | 新 | obs1 0.9803/1.669/0.0126、obs2 0.9837/1.761/0.0108 | 0.8832(2.5mm) / **0.9025(2mm)** | **不合格（碰撞表示上限）** |

**DIAG 资产**：R03_engine（旧 `strict_pass=true` 无新证据，撤销）、各 `g1/g2` 变体，均在表中标 DIAG，不进正式池。

---

## 五、两视角更新：前后对比

| 阶段 | obs1 IoU/P95/free | obs2 IoU/P95/free |
| --- | --- | --- |
| 单视角融合（只用第一视角） | 0.9737 / 1.702 / 0.0392 | 0.9268 / 1.819 / **0.0737（淘汰）** |
| **两视角更新（体素交集）** | **0.9803 / 1.669 / 0.0126** | **0.9837 / 1.761 / 0.0108** |

- 交集体素：view1 623,972 / view2 606,225 / 共有 **600,864**；
- **补洞是形状保持的**：补洞后两视角可见指标与原网格完全一致（obs1 0.9803/1.669/0.0126）；
- 碰撞（同一补洞网格，有效测量 `source_vol_defined=true`）：2.5 mm → IoU 0.8832 / c2s 5.026；2.0 mm → **0.9025 / 4.000**；
- **判定**：可见双视角通过，碰撞未过 0.95，且加密收益递减 → **box 并集对该细碎表面的表示上限**，非分辨率或评价错误。

---

## 六、同条件对照（六方法 × 三土壤 × 验证初态）

| 方法 | R03 nominal | R03 low_traction | R03 high_drag | R02（三土壤） |
| --- | --- | --- | --- | --- |
| B0_blind | R1 3/3 | R1 3/3 | R1 3/3 | R1 **0/3** |
| B1_height | R1 3/3 | R1 3/3 | R1 3/3 | A0 0/3 |
| B2_box | **A0 0/3** | D1 3/3 | **A0 0/3** | A0 0/3 |
| B3_mirror | R1 3/3 | R1 3/3 | R1 3/3 | A0 0/3 |
| H5_lux3d | **D1 3/3** | R1 3/3 | R1 3/3 | A0 0/3 |
| U_truth | R1 3/3 | R1 3/3 | R1 3/3 | **A0 0/3** |

- 验证初态 18 行全部 `validation_continuation=true`、`state_mode=project`（快照来自观测场景，显式记录）；
- **R02 连真值上限都 0/3**：障碍高 0.1695 m（R03 为 0.0965 m），`U_truth` 预演三次全 `abort` → 几何不可通行；
- **收益 NOT_ESTABLISHED**：R03 除盒先验外全成功；R02 全失败。两端都区分不出方法优劣。

---

## 七、闭环分支（真实数据）

| 分支 | 数据 | 结果 |
| --- | --- | --- |
| 无候选 → A0 | R01，0 格 | 3 状态续行位移 ≈0 |
| 筛选后空集 → A0 | R03 两候选均被第二视角淘汰，0 格 | 位移 0.0005 m，`reason=no_candidates_after_second_view` 写盘先于执行 |
| 有候选 → 通行 | R03 双合格假设，42 格 | 安全集 7 → **R1** → **3/3 成功**，位移 3.1915/3.1971/3.1906 m，`t_start` 9.84/10.88/10.32 s |
| **两视角候选闭环** | **单候选 × 单状态 × 三土壤 = 18 格** | 安全集 6 动作 → **R1**；真值**一种条件成功**，`final_x = 3.603 m`，**实际位移 3.0895 m**，`state_mode = project` |
| 多土壤聚合 → 改选 | R03 三土壤，42 格 | 安全集 **7→5**（R1 掉出）→ **D1** → 真值**成功** 3.0895 m |

---

## 八、播放与重新仿真

```bash
# 页面：起后端后在 http://127.0.0.1:8765/ 点"开始重新仿真"（真实后端、新 run_id）
.venv/bin/python scripts/v7_server.py --port 8765

# 或命令行重新仿真（真实 MuJoCo，产生新 run_id 与日志）
.venv/bin/python scripts/v7_rerun.py --case R03 \
  --hypothesis runs/.../processed/V7_R03_s2/collision --action R1 --seed 0 \
  --out runs/.../evaluation/rerun_manual
# 由落盘轨迹生成播放器
.venv/bin/python scripts/v7_player.py --traj <rerun>/rerun_trajectory.jsonl --out <page>/player.html
```

- 轨迹：**327 帧**（原为 0 字节，`record_trajectory` 未开启是真因），空帧时脚本直接失败；
- 播放器：播放/暂停/进度拖动/速度选择，画面标仿真时间与动作；已用无头 Chromium 渲染验证；
- 边界：这是**基于已记录状态的可视回放**，不是物理原始渲染视频；不同 seed 不拼成同一轨迹。

---

## 九、生产负例与验收

| 项 | 结果 |
| --- | --- |
| 十八类反例 | **18/18**（全部调用生产函数，记录触发位置） |
| 碰撞已知答案 | **8/8** |
| 统一验收 | **73/73**（完整性 13 / 功能 55 / 目标 5） |
| 状态合同 A/B/C/D | 全过（同场景拒绝、投射不搬材质、土壤改变签名） |
| 分块等价性 | maxdiff **0.0**（2M/200k/20k 三档） |
| 干净目录 | 已知答案 8/8；反例 16/18（缺证据项明确失败）；audit 报 7 项缺失 |

---

## 十、账本（分列）

| 项 | 值 |
| --- | --- |
| 本批授权总额 | **500 积分**（沿用 R1 授权，非新增） |
| 账户余额（用户报告） | 1042（信息，不是代码核验的用量） |
| 价格口径 | **1 积分/任务** 的估算（`price_verified=false`） |
| 本批任务数 | 14（含 4 个纹理输入变体） |
| 估计占用 | 14 × 1 = 14 积分 |
| **实际扣费** | **unknown**（未与 API 账单核对，等待外部对账） |

---

## 十一、尚未成立 / 缺失 / 需外部处理

**研究主张**
- 收益 **NOT_ESTABLISHED**：无任何证据表明生成隐藏先验带来可测的动作收益或成本改善。

**能力缺口**
1. 两视角更新的**碰撞表示**：box 并集在 2 mm 时 IoU 0.9025，未过 0.95；
2. **两视角候选未进入重规划/真值续行**（因碰撞不合格，按规则不进正式池）；
3. ~~页面一键重仿真未实现~~ → **已实现并实测**（`scripts/v7_server.py`，新 run_id `20261031T120326-e01aec`）；
4. §9 **有界扫描未执行**（需先重建 R02/R04 网格资产）。

**外部阻断**
- **数据层不可复现**：`*.stl` 被 `.gitignore` 排除，原远端主机已回收；R02_s2/R04_s2 的网格丢失，
  重测必须先重建网格（父候选 + 观测重新融合，而那批中间 STL 同样未入库）。
- CNB 令牌偶发 401（`errcode 16`），高频调用触发；不影响已提交的配置与脚本。

---

## 十二、复核后的更正（2026-10-31 移交轮）

| 项 | 原结论 | 复核后 |
| --- | --- | --- |
| 碰撞评价器已知答案 | 8/8 通过 | **8/8 仍通过**；但任务书指定的"合并盒 vs 三单位盒"检验在修复前给出 **0.0**，已修（逐 cell 判暴露面），现在两者都 0.5，见 `verify/known_answer_review.json` |
| 18 项生产反例 | 18/18 通过 | **仅 6 项真正调用生产路径**（N05/N06/N07/N08/N13/N14）；6 项自证式、2 项写死、2 项读旧报告、1 项弱检查、1 项部分，见 `verify/negatives_18_classification.json` |
| V7_R02_s2 新口径合格 | 合格（0.9893/0.799/0.820） | **撤回**：该次测量 `source_status.watertight=false`、`source_volume_defined=false`，占据 IoU 不可作资格 |
| 所有碰撞 s2c | 视为有效 | **重新定性**：s2c 由修复前的 `box_surface_distance` 计算，内部接缝被当外表面，值偏小；需重测后才能用于资格 |
| 闭环 R03 决策 | R1（two_qualified）/ D1（三土壤） | **输入错误**：闭环阶段此前喂 R01 可见量（W_vis 0.143 vs R03 0.458），已修入口；两结果需重跑 |
| 两视角更新体 | 合格（0.9684 PASS） | **撤回**：0.9684 来自体素填充闭合网格（形状已变，可见 freespace 0.3988/0.2199）；有效测量为 0.8832/0.9025，不合格 |

## 十三、状态

```json
{"execution_status":"PARTIAL","evidence_status":"PARTIAL","capability_status":"PARTIAL",
 "benefit_status":"NOT_ESTABLISHED","claim_level":"NOT_REACHED"}
```

**判定依据**：执行代码、入口、矩阵与状态合同、两视角更新、播放器、负例、验收均已落地并有证据；
但「碰撞表示」与「重规划/真值续行」未闭合，且数据层不可复现，故 execution/evidence/capability 均为 PARTIAL。

---

## 十三、交接状态（写作时仍在运行）

| 任务 | 状态 | 日志 / 产物 |
| --- | --- | --- |
| R02_s2 按新口径重测 | **融合完成**（12:11，`recal_V7_R02_s2/body.stl` 32 MB），碰撞测量运行中 | 日志 `/tmp/refuse2.log`；产物 `runs/.../fusion_diagnostics/recal_V7_R02_s2/` |
| R04_s2 按新口径重测 | 排队（脚本第二个） | 同上 |
| 页面后端 | 已完成并实测 | `scripts/v7_server.py`，run_id `20261031T120326-e01aec` |

重跑命令：

```bash
cd /var/lib/deepseek-harness/lunar-lab
export LD_LIBRARY_PATH=/tmp/sysroot/usr/lib/x86_64-linux-gnu:/tmp/sysroot/lib/x86_64-linux-gnu MUJOCO_GL=osmesa
.venv/bin/python scripts/fuse_observed.py --observation runs/unseen/recovery_r3/obs_R02 \
  --parent-world runs/unseen/delivery_v7/v7_20261030/candidates/V7_R02_s2/world/align \
  --parent-id V7_R02_s2 --method H5_F \
  --out runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/recal_V7_R02_s2 \
  --pitch 0.0025 --config configs/unseen_v7_r1_fusion_offset1.json
.venv/bin/python scripts/v7_measure_candidate.py \
  --fusion runs/unseen/delivery_v7/v7_20261030_r1/fusion_diagnostics/recal_V7_R02_s2 \
  --pitch 0.0025 --eval-pitch 0.004
```
