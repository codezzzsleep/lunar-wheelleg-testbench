# 先想后走 V1 · 审查报告

## 0. 现状

- **main commit**：`29734ac`（已推送 origin/main），工作区干净。
- **delivery_status = PARTIAL**：A/B/E(部分) 完成，C/D/F/G 未完成。
- **evidence_integrity = PASS（含未验证项）**：94 项回归通过；标定/自由空间/配准都有可重算证据；
  但真值替换隔离测试、完整矩阵、统一自验入口未完成。
- **research_gate = NOT_PASS**：C1 部分（P1/P2 未按 v2 重跑）、C2 未成立（无合格真实候选）、
  C3 未评估、C4 未做。
- **用户现在能新增完成**：跑通"观测→H3 候选→物理化→预演→决策→真值执行"的**H3 版**闭环，
  并用评测器/分析器得到一张完整分母的主表；真实 Lux3D 侧只有 2 个旧输入诊断候选。

## 1. 交付清单（A–G）

| 包 | 状态 | 源码 / 证据 |
| --- | --- | --- |
| A 预算与恢复 | **完成** | `scripts/budget.py`、`tests/test_budget.py`(16)、`runs/unseen/generation/MIGRATION.md` |
| B1 真实深度标定 | **完成** | `scripts/calibrate_observe.py`、`runs/unseen/obs/cal_v2/calibration.json` |
| B2 自由空间 v2.1 | **完成** | `scripts/align.py`、`tests/test_freespace.py`(5)、`runs/unseen/align_v2/diag/freespace_counterexample/` |
| B3 标定件窄底 | **完成** | `scripts/make_calibration_object.py`、`runs/unseen/prep/cal_object.json` |
| B 相机 xyaxes | **完成** | `scripts/wheelleg_env.py`、`tests/test_camera.py`(5) |
| C E0 配准回归 | **完成** | `runs/unseen/align_v2/fixture_A_v2.json` |
| C E1/E2/E3 | **未做** | — |
| P3 同观测 | **完成** | 相机 0.16 m/0°；IoU 1.0000、深度差 0.001–0.003 mm、MAE<0.001 |
| D1 CAL1 放行 | **未提交** | 技术条件 (3)(4)(2) 已满足；等 E1 |
| D2 生成清单 | **未开始**（暂停） | — |
| D3 候选物理化 | **部分** | `scripts/physicalize.py`；真实候选未按新口径重评 |
| D4 H5 闭环 | **未开始** | 无合格候选 |
| E1 动作接线 | **完成** | `nav_target_y`、`Detour`、`tests/test_detour.py`(6) |
| E2 假设/评测/分析 | **完成（H3 冒烟）** | `scripts/hypotheses.py`、`unseen_eval.py`、`analyze_unseen.py`、`runs/unseen/eval/smoke1/` |
| E3 决策完整性 | **部分** | 期望键校验有；真值替换测试无 |
| E4 可复现性 | **完成** | cases 相对路径、文档去本机路径 |
| F 冻结协议/主表 | **未开始** | 只有 `plans/unseen_v2_protocol_smoke.json` |
| G 页面/视频/自验 | **未开始** | 旧 `app_unseen.py` 未接新口径 |

## 2. 五项复核问题 before / after

| # | before | after | 回归 |
| --- | --- | --- | --- |
| 1 预算只算 HELD | 两条 downloaded -> 0 积分 0 任务；上限 20/1 时两次 reserve 都成功 | 占用=除"证明未发出"外全部状态；上限 20/1 时第二次失败 | `test_budget` 16 项 |
| 2 resume 落入 create | 仅 --resume 时 create 被调用 1 次 | resume 只查询下载，create 0 次 | `test_7_resume_never_creates` |
| 3 自由空间只看 obs_mask | 轮廓外侵入漏检 | 已知空域=全部有效观测像素；反例检出 28.49% | `test_freespace` 5 项 |
| 4 标定件 taper 不收缩底面 | 底面 0.024 m² > 其他 0.0236 m² | 底面 0.003 m²、最大侧面 0.0232 m²（7.75 倍） | `make_calibration_object --report` |
| 5 标定不用渲染深度 | 点云来自 mj_ray，空点云也可能 pass | 点云来自渲染深度反投影；平面误差 0.0 mm、横向 5.2 mm；空数据 FAIL | `calibrate_observe.py` exit 0/1 |

**我实际运行的**：上述 5 组回归 + `tests.test_camera` + `tests.test_detour` + 全套 94 项 + 标定 +
自由空间反例 + H3 冒烟矩阵。**没运行**：正式 8 方法矩阵（协议未冻结）、真实候选新口径重评、
P1/P2 的 v2 重跑、页面与视频。

## 3. 生成表

| task_id | 输入 | 状态 | 合格 | 重复分组 | 费用上界 | 核验 |
| --- | --- | --- | --- | --- | --- | --- |
| 4416952 | planA v1（滚转相机） | downloaded | 否（旧输入，仅诊断） | 与 4418107 同 identity | 20 | unknown |
| 4418107 | planA v1（滚转相机） | downloaded | 否（同上） | 同上 | 20 | unknown |

预算：已创建 **2**、占用 **40**、核验 **unknown**、剩余 **260 积分 / 13 任务**。
CAL1 与 A/B 清单**未提交**（按指令暂停）。

## 4. 主表（H3 冒烟，分母明确）

| 方法 | n | 成功 | 刹停 | 翻覆 | 越界 | 成功率 | 均代价 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B0 盲走 | 3 | 3 | 0 | 0 | 0 | 1.000 | 5.7 |
| B1 保守停车 | 3 | 0 | 3 | 0 | 0 | 0.000 | 40.0 |
| H3 程序化 | 3 | 3 | 0 | 0 | 0 | 1.000 | 5.7 |

**这是接线冒烟，不是正式对照**：只有 1 个观测、1 个候选、3 初态；H3 与 B0 用的是同一个
`h3_ramp25` 几何，所以两者相同是预期的。正式 288/480 回合矩阵未运行。

## 5. 复制即跑的命令

```bash
export MUJOCO_GL=osmesa
.venv/bin/python -m unittest discover -s tests          # 94 项，约 745 s
.venv/bin/python scripts/calibrate_observe.py --out runs/unseen/obs/cal_v2
.venv/bin/python scripts/test_freespace_counterexample.py
.venv/bin/python scripts/observe.py --case cases/unseen_v1/planA.json \
    --out runs/unseen/obs/planA_v3 --cam-height 0.16 --pitch 0
.venv/bin/python scripts/unseen_eval.py --protocol plans/unseen_v2_protocol_smoke.json \
    --out runs/unseen/eval/smoke1
.venv/bin/python scripts/analyze_unseen.py --input runs/unseen/eval/smoke1/results.jsonl \
    --protocol plans/unseen_v2_protocol_smoke.json --out runs/unseen/eval/smoke1
.venv/bin/python scripts/imagine.py --plan plans/unseen_v1_generation.json --dry-run
```
离线所需文件与哈希见 `runs/unseen/delivery_v2/review_index.json`。

## 6. 未完成项

| 缺失 | 已排查 | 是否外部阻塞 | 解除后下一条命令 |
| --- | --- | --- | --- |
| E1 24 朝向搜索、E2 俯仰、E3 有界比例 | 评估核与搜索已 v2 化，fixture 通过 | 否 | `scripts/align_orient.py`（待写）后重评两候选 |
| 真实候选新口径重评 | 旧候选来自滚转输入 | 否 | 用 v3 观测重跑 `align.py` |
| D2 生成清单 13 项 | 预算与上传链路已验证 | **是**（按指令暂停） | 用户放行后 `imagine.py --submit` |
| D4 H5 闭环 | 依赖合格候选 | 是 | 有合格候选后跑 `unseen_pipeline.py --hyp-source H5` |
| F 冻结协议 + 8 方法矩阵 | 评测器/分析器已通 | 否 | 写 `plans/unseen_v2_protocol.json` 后 `unseen_eval.py` |
| G 页面/视频/`verify_unseen.py` | 旧页面仍可看 H3 记录 | 否 | 接新口径 + 录屏 |

## 7. 已知缺陷

1. **MuJoCo 按文件名缓存网格**：同一路径写不同网格会复用旧几何（曾使自由空间从 28.49% 变 0）。
   已改唯一目录；新代码不得复用固定路径。
2. **绕行回位不彻底**：|y| 峰值 0.587 → 终值 0.496。
3. **P3 依赖平视相机**：相机高于障碍顶部时无法同观测（实测 MAE 0.245 vs 0.003）。
   因此 v3 观测把相机放到离地 0.16 m，这改变了"机器人视角"的物理含义，需在正式报告中说明。
