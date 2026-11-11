# E4 整批接续（a9910fa 之后）· 最终状态

main = 见 `git log`；已推送。工作区干净。

## 1. 新增可操作能力

| 能力 | 入口 |
| --- | --- |
| 真实 Lux3D 候选进正式 H5 链路（含 CoACD 保姿态碰撞） | `scripts/unseen_pipeline.py --hyp-source H5 --candidates <json>` |
| 六方法在同一真值上对照 | `scripts/eval_six.py --protocol plans/unseen_v2_protocol.json` |
| 月壤单轮标定 + 整机阻力接入 | `scripts/soil_single_wheel.py --fit`；`spec.soil={mode:'soil'}` |
| 实际上传包（UV 贴图 + 白底裁剪 + 哈希） | `scripts/make_upload_package.py` |
| 主动观察（真实抬高机身 + 第二视角筛除） | `scripts/look_again.py` |
| 页面看本批记录 | `scripts/app_unseen.py --port 8090`（注册表 `runs/unseen/recovery_r3/page_runs.json`） |
| 统一自验（从原始记录重算） | `scripts/verify_r3.py --run runs/unseen/recovery_r3` |

## 2. 主链路各阶段状态

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| 观测 | 完成 | `runs/unseen/recovery_r3/observations/{A,B,CAL}`，camera-snapshot/v2 |
| 候选生成（真实 Lux3D） | 完成（历史批次 15 任务） | `runs/unseen/generation/generation_table.json` |
| 清理/预检 | 完成 | `clean_table_v3.json`；A2 厚度比 0.09426 判薄片 |
| 配准 | 完成（严格诊断未过） | A1 0.670 / A3 0.773 / A4 **0.881** IoU；P95 15.4/56.4/12.8 mm |
| 工程资格 | **A4 唯一 planning_eligible** | `configs/unseen_planning_policy.json` |
| 保姿态物理化 | 完成 | A4 → CoACD 6 部件，collision_sha `23d0025b…` |
| 预演/决策 | 完成 | `records.jsonl` + `decision.json`（冻结 SHA） |
| 独立真值执行 | 完成 | truth `2afba6f8…` ≠ 候选 `7646be25…` |
| 六方法对照 | 完成（小矩阵） | `runs/unseen/recovery_r3/six/` |
| 页面 | 接入完成（无浏览器截图验证） | `/api/cases` 返回 5 个运行 |
| 月壤 | 单轮标定通过；整机阻力接入 | `soil/single_wheel.json` |
| 主动观察 | 完成（无候选被淘汰） | `look_again/look_again.json` |

## 3. 主表（共同真值 `2afba6f8…`，初态 0/1/2）

| 方法 | 自选动作 | 执行 | 成功 | 刹停 | 失败 | 均代价 |
| --- | --- | --- | --- | --- | --- | --- |
| B0_blind | R1 | 3 | 3 | 0 | 0 | 5.653 |
| B1_height | A0 | 3 | 0 | 3 | 0 | 40.0 |
| B2_box | A0 | 3 | 0 | 3 | 0 | 40.0 |
| B3_mirror | R1 | 3 | 3 | 0 | 0 | 5.653 |
| H5_lux3d | R1 | 3 | 3 | 0 | 0 | 5.653 |
| U_truth | R1 | 3 | 3 | 0 | 0 | 5.653 |

**如实结论**：该案例上高度规则过度保守（可见高度比 2.19 > 冻结阈值 1.6 → 刹停）；
Lux3D/镜像/真值上限与盲走结果完全相同，**没有收益证据**。

## 4. 月壤

单轮软接触标定：一个全局系数 c=0.00151，5 档载荷（20/40/60/80/100 N）
下陷误差 0.36%/1.34%/1.95%/2.40%/2.72%，**5/5 在 ±30% 内**，全部稳定。

整机接入：`_soil_step()` 覆盖 reset 稳定化 / step / brake 三处；按轮载估算下陷、
施加压实阻力与牵引上限。同控制器 200 控制步：rigid x=2.372 → soil x=2.230（少走 0.142 m）。
**局限已写死**：整机刚性接触本身不产生几何穿透，下陷是按轮载的估计量。

## 5. 上传包（待确认，未提交 create）

| 项 | P1 | P2 |
| --- | --- | --- |
| 形状 | planA 穹顶 | planB 宽低 |
| 目标占画面 | 78.01% | 77.99% |
| 目标亮度 | 164.7 | 172.4 |
| 上传字节 SHA | `c3f014e7…` | `71980740…` |

P3 = P1 同字节第二采样（`sample_id`/`nonce` 区分身份）。批次上界 60、最多 3 任务。
**关键修复**：无 UV 的 STL 直接贴 2D 贴图会退化成条带（球/立方体已复现），
改用三平面 UV OBJ 后纹理正常。

## 6. 自验

`scripts/verify_r3.py`：**35/35 通过**（exit 0）。
注入失败路径：缺目录 exit 2；篡改 A2 判为 ok 后 exit 1。
全套单元测试：**112 项通过**。

## 7. 仍未完成

| 项 | 真实依赖 |
| --- | --- |
| B 组正式 H5 | B1–B5 全为薄片，无合格候选；A 组候选被组匹配正确拒绝 |
| 六方法扩展到 4 块独立石头 | 需新的合格候选（新付费批次，待确认） |
| 页面像素级验证 | 环境无浏览器，只验证了数据接口 |
| 月壤滑转/坡面/1000 回合/吞吐 | 需完整整机月壤实验 |
| 再观察后的重新预演 | 接口已支持保存 qpos/qvel，但未接成完整第二次决策 |

## 8. 预算

历史 15 任务 / 300 积分上界 / 剩余 0 / 核验扣费 unknown。
本批**未新增任何付费任务**；试点计划停在 `PREPARED_NOT_SUBMITTED`。
