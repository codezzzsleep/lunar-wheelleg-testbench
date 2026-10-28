# 最终交付：看不见的那一面 V1

## 用户现在能操作什么

本地页面（`scripts/app_unseen.py`，127.0.0.1:8090）可看一个完整案例：
机器人正面观测 → 3 个几何候选的三维侧视 → 候选×动作预演矩阵 →
稳健决策（含平局与停车说明）→ 真值执行与揭晓、动作回放。
**用真实 Lux3D 生成的候选目前没有**：执行环境缺 `AHOLO_API_KEY`。

## 三个状态（分开判定）

| 项 | 状态 | 依据 |
| --- | --- | --- |
| delivery_status | **PARTIAL** | 真实图生链路已跑通：上传、create、轮询、ZIP→GLB 下载均成功，已得 2 个真实候选；但配准未验证、正式评测未做 |
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

## 相机缺陷与观测重渲（2026-10-28）

前视相机此前只做了绕 y 轴转向，图像 up 落在世界 +y 上 → **地平线竖立 90°**，
planA/planB/CAL1 的输入图都是横的。已改为显式相机基（视线 +x 下俯 12°、图像 up 取世界 +z 投影），
验证：相机 right=[0,−1,0]、up=[0.206,0,0.979]、视线=[0.979,0,−0.206]，渲染地平线水平、障碍贴地。

同时把输入图改为**白底合成**（掩码外涂白，去掉了掠射角地形噪点），裁剪留白 15%→35%，
统一输出 1024²。两份观测与标定图已全部重渲。

已付费的两个候选（`4416952`/`4418107`）来自滚转输入，**已标注为不可用于当前观测的配准**，
保留在账本与 `by_tasks/` 里不删除；按你的要求暂停所有新的生成提交。

重渲后重跑残差诊断（`runs/unseen/align/diag_A2/diag.json`）：
S1 网格往返 RMS **0.0 mm**；S2 手工位姿 @原生 RMS **0.45 mm**（边缘 0.19 / 内部 0.47）；
S3 降到 640×480 RMS **3.8 mm**（此前为 42.29 mm）——滚转相机的错误也在放大这个残差。

## 生成与预算

- 本轮新增 Lux3D 图生任务 **2** 个：`4416952`、`4418107`，状态均为 succeeded + downloaded。
- 预留上界 **40 积分**（2×20），剩余授权 260；任务数 2 ≤ 15。**未超限**。
- 实际扣费：API 未返回 charge 字段 → `actual_charge=null`、`verified=unknown`，
  不把预留写成实扣。
- 两个候选几何确实不同：`4416952` extents 0.200×0.191×0.124 m；`4418107` 0.250×0.246×0.156 m。
  同一输入产生不同几何，这对"重复输入是否给相同形状"是一个正面观察（样本量 2）。
- **一次重复创建事故**：首个 create 成功后客户端误读响应（`TypeError`），修好后 resume 时
  因身份被截断成 16 位导致缓存未命中，又创建了第二个任务。已修正身份截断与响应解析，
  两个任务都保留在账本里（不删除负面记录），并从两者各下载了一个 GLB。
- 输入图上传：`GET /asset/v1/token` → OUS `single/upload`（multipart，带 md5 与 `ous-token-v2`）
  → 轮询 `upload/status` 直到 status=5 → 得到 URL。已实测成功。

## 主要对照结果（完整分母）

| 任务 | 方法 | 成功/总 |
| --- | --- | --- |
| Gate P（810 回合） | R1/R2/L1 × 5 背面 × 3 初态 | P1 4/18、P2 1/18、P4 30/30 |
| E2E case_A | H3 三候选 × 4 动作 × 3 初态 | 决策 L2；真值 3/3；盲走 R1 3/3（**无收益**） |

## 未完成项与真实阻塞

1. **图生 create 与上传**：链路已打通（上传 → create → 轮询 → ZIP 解 GLB）。
   密钥只从环境变量 `AHOLO_API_KEY` 读取，不在仓库、不在文档、不打印。
   仍需按计划补齐其余候选；当前**暂停**新提交（等 CAL1 技术放行）。
2. **可见面配准（测量已可信，候选未过）**：
   受控诊断（`runs/unseen/align/diag_A/diag.json`）把误差来源逐项隔离：

   | 组 | 只改了什么 | 内部 RMS | 边缘 RMS | 整体 RMS |
   | --- | --- | --- | --- | --- |
   | S0 同场景同路径 @1280×960 | — | **0.0 mm** | 0.0 | **0.0** |
   | S1 网格导出重载 | 网格往返 | 0.0 | 0.0 | **0.0** |
   | S2 手工世界位姿 | 放置路径 | **0.49 mm** | 22.2 | 6.77 |
   | S3 降到 640×480 | 分辨率 | 2.21 | **99.8** | **42.29** |

   结论：43 mm 来自**分辨率降到 640×480 后的边缘像素**（0.58% 像素 >100 mm），
   不是整体放错。指标已按原定义重写：原生分辨率、内部/边缘分离、中位与 P95、
   观测可见点到候选表面的最近距离（`vis_pt_*`）、以及真正的自由空间侵入。
   已知变换恢复（fixture：真网格经 1.15× 缩放 + 12° yaw）：IoU **0.9859**、
   可见点距离中位 **3.57 mm**、P95 **5.55 mm**（阈值 5.74 mm 边缘附近），
   说明求解器精度已接近其台阶下限。
   两个真实候选：`4418107` IoU 0.7832 / vis_pt P95 **57.9 mm**；
   `4416952` IoU 0.7804 / vis_pt P95 **58.3 mm** —— **均未通过**。
3. **C2/C3 未成立**：没有真实候选，多假设收益未评估。
4. **正式评测协议与 `unseen_eval.py`/`analyze_unseen.py` 未实现**（H3 冒烟也未跑）。
5. **视频未做**；页面为静态侧视 + 回放帧，不是连续视频。
6. **P2/P3 未过**：P3 需背面内缩 2 cm；P2 需更极端背面落差。

## 能力边界

不承诺猜出真实背面；不宣称月面真实可用；不做真实机器人迁移；
页面不开放付费 create；密钥不落盘、不进前端。
