# 最终交付：看不见的那一面 V1

## 用户现在能操作什么

本地页面（`scripts/app_unseen.py`，127.0.0.1:8090）可看一个完整案例：
机器人正面观测 → 3 个几何候选的三维侧视 → 候选×动作预演矩阵 →
稳健决策（含平局与停车说明）→ 真值执行与揭晓、动作回放。
**用真实 Lux3D 生成的候选目前没有**：执行环境缺 `AHOLO_API_KEY`。

## 三个状态（分开判定）

| 项 | 状态 | 依据 |
| --- | --- | --- |
| delivery_status | **EXTERNAL_BLOCKED** | 两份正式输入的观测、计划、预算、账本、上传路径均已就绪；`--submit` 因缺密钥返回 exit 3；`align.py` 已实现但 fixture 未达标 |
| evidence_integrity | **PASS（含未验证项）** | 自验从原始 JSONL 重算：动作真触发、A0 真停、无越界成功、无重复记录、缺记录→insufficient_evidence；但**配准链未通过 fixture**，不能算已验证 |
| research_gate | **NOT_PASS** | P1 4/18 通过、**P2 1/18 未过**、**P3 未过**、P4 30/30 过；C2/C3 未成立 |

## 本轮 commit 与工作区

`main = 22e8f80` 起，本批新增提交见 `git log`；工作区干净。
审查索引：`runs/unseen/delivery_v1/review_manifest.json`（含文件 SHA、命令与退出码、外部阻塞）。

## 最短复现命令

```bash
export MUJOCO_GL=osmesa
.venv/bin/python scripts/imagine.py --plan plans/unseen_v1_generation.json --dry-run      # exit 0
.venv/bin/python scripts/imagine.py --plan plans/unseen_v1_generation.json --submit \
    --budget configs/unseen_v1_budget.json                                               # exit 3（缺密钥）
.venv/bin/python scripts/gate_physics.py --posed assets/posed --out runs/unseen/gate_p/w6
.venv/bin/python scripts/unseen_pipeline.py --case cases/unseen_v1/case_A.json \
    --hyp-source H3 --cached-only --out runs/unseen/e2e/e2
.venv/bin/python scripts/app_unseen.py --port 8090
.venv/bin/python scripts/verify_unseen.py --out runs/unseen/verify/v3
```

## 生成与预算

- 本轮新增 Lux3D 任务 **0** 个；预估积分 **0**；核验积分 **0**（无实际扣费）。
- 授权额度：300 积分 / 单任务 ≤20 / ≤15 任务；计划 13 个输入（A 组 6、B 组 6、标定 1），
  预留上界 260 ≤ 300，任务数 13 ≤ 15，**未超限**。
- 历史账本 78 是提交额估算，不是余额；本轮不推测余额。

## 主要对照结果（完整分母）

| 任务 | 方法 | 成功/总 |
| --- | --- | --- |
| Gate P（810 回合） | R1/R2/L1 × 5 背面 × 3 初态 | P1 4/18、P2 1/18、P4 30/30 |
| E2E case_A | H3 三候选 × 4 动作 × 3 初态 | 决策 L2；真值 3/3；盲走 R1 3/3（**无收益**） |

## 未完成项与真实阻塞

1. **图生 create 与上传**：缺 `AHOLO_API_KEY`。计划、预算锁、账本、缓存校验、下载、
   状态机均已实现；设置密钥后可直接 `--submit`。
2. **可见面配准未验证**：`align.py` 已实现（可见面约束、yaw±25°/尺度 5 档、IoU/RMS/自由空间），
   但 fixture 测试 cand 56 px vs obs 914 px，IoU 0，**未达标**，不作为可用能力。
3. **C2/C3 未成立**：没有真实候选，多假设收益未评估。
4. **正式评测协议与 `unseen_eval.py`/`analyze_unseen.py` 未实现**（H3 冒烟也未跑）。
5. **视频未做**；页面为静态侧视 + 回放帧，不是连续视频。
6. **P2/P3 未过**：P3 需背面内缩 2 cm；P2 需更极端背面落差。

## 能力边界

不承诺猜出真实背面；不宣称月面真实可用；不做真实机器人迁移；
页面不开放付费 create；密钥不落盘、不进前端。
