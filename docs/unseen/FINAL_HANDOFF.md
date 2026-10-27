# 最终交付：整批 A–F 状态

**状态：外部依赖交付中的「基础假设未完全成立」** —— A/B 部分完成，C/D/E 部分完成，
F 部分完成。**不能称为整批正常完成。**

判定依据：`scripts/verify_unseen.py` 输出 **NOT_PASS**（4 项必需项未通过），
见 `runs/unseen/verify/v1/verify.json`。

## 1. 本轮新增的用户操作能力

一条可在本地页面走完的**「先想后走」闭环**：机器人只看到障碍正面 →
系统用几何先验生成 3 个背面候选 → 在每个候选里预演 4 种走法 × 3 个初态 →
按最坏假设风险选出稳健动作 → 在真值场景执行 → 揭晓与盲走对照。

入口：`.venv/bin/python scripts/app_unseen.py --port 8090` → http://127.0.0.1:8090

## 2. 可复制执行的命令与产物

```bash
export MUJOCO_GL=osmesa
.venv/bin/python scripts/measure_robot.py  --out runs/unseen/prep/r1/robot_dims.json
.venv/bin/python scripts/twins.py          --out runs/unseen/gate_p/p3
.venv/bin/python scripts/physicalize.py    --mesh <stl> --out assets/posed/<id>   # 逐个
.venv/bin/python scripts/gate_physics.py   --posed assets/posed --out runs/unseen/gate_p/w4
.venv/bin/python scripts/calibrate_observe.py --out runs/unseen/obs/cal
.venv/bin/python scripts/observe.py        --case cases/unseen_v1/case_A.json --out runs/unseen/e2e/e1
.venv/bin/python scripts/unseen_pipeline.py --case cases/unseen_v1/case_A.json \
    --hyp-source H3 --cached-only --out runs/unseen/e2e/e1
.venv/bin/python scripts/app_unseen.py --port 8090
.venv/bin/python scripts/verify_unseen.py --out runs/unseen/verify/v1
```

## 3. C1–C4 原始统计

| 命题 | 状态 | 分子/分母 |
| --- | --- | --- |
| C1 背面改变动作结果 | **部分成立** | 统一执行器后 810 回合：**P1 4/18 通过**（最优选项确实随背面变）、P2 1/18 未过、P3 未过、P4 30/30 过。上一版 9/18 因"同初态+单凸包"作废 |
| C2 Lux3D 候选可对齐有差异 | **未成立** | 图生 3D 未接入，**0 个任务**；本轮假设是几何先验（H3） |
| C3 多假设预演相对基线收益 | **未成立** | case_A 上系统选 L1，真值 3/3；盲走 R1 也 3/3，**无差异** |
| C4 主动再观察 | **未成立** | 未做 |

支撑性验收（`runs/unseen/verify/v3/verify.json`，从原始记录重算）：
观测反投影横向误差 5.2 mm；双胞胎 5 个背面正面指纹唯一；Gate P 无重复回合；
**状态机动作 L1 触发 270/270**；**L1 与 R1 动作指纹交集 0**；
**A0 刹车 150 步、终态 x=−0.003、不翻**；成功记录 0 条越界；
决策可复算；缺记录→insufficient_evidence；无安全动作→A0；
页面有候选三维视图 3 张、回放 6 帧、真值揭晓 1 张。

## 4. 预算

新增 Lux3D 任务 **0**；预估与核验积分 **0**；缓存复用 0。旧账本 78 是历史提交额估算，
不是当前余额。**剩余已授权额度未知**，付费图生需要用户确认后才能启用。

## 5. 未完成项与真实阻塞

| 包 | 状态 | 缺口 |
| --- | --- | --- |
| A 观测与动作 | **部分** | 观测/标定完成；`nq` 兼容检查未做 |
| B Gate P | **未通过** | P1 2/18、P2 1/18、P3 MAE 3.23；P4 通过 |
| C Gate L | **未开始** | 图生客户端、上传、预算锁、配准、Gate L 全部未做 |
| D 单例闭环 | **完成（几何先验版）** | `unseen_pipeline.py` 与 Gate P 共用 `runner.py`；假设来自 H3 而非 Lux3D；三动作同分时如实标注 tie-break |
| E 固定评测 | **未开始** | 协议、`unseen_eval.py`、`analyze_unseen.py` 未写 |
| F 页面与审查包 | **部分** | 五步页面含候选三维、回放、揭晓（`runs/unseen/ui_five.png`）；无视频 |

**真实阻塞**
1. **Gate P 未通过**（P1/P2/P3）：P3 需背面内缩 2 cm；P1/P2 需更丰富的动作差异与
   更敏感的几何档。已用掉一轮物理调整，还有一轮。
2. **Gate L 需付费授权**：图生 3D 单价与批次额度未核定，未擅自提交。
3. **E 未开始**：需要先有通过的 Gate P 与 Gate L 才能冻结协议。

## 附录：本批修掉的问题

- 正面采样随背深变化（drop 36 排 / ramp_l 16 排）→ 正面由 `front_rings` 独立生成，
  5 种背面正面顶点逐顶点一致。
- 障碍放在 x=0 与出生点重合 → 移到 x=1.8。
- 三个 seed 初态相同 → 真实扰动 ±0.05 m / ±0.03 rad。
- 单凸包碰撞 → `physicalize.py` 保姿态 CoACD，90/90 成功。
- `gate_physics` 恒返回 0 → P1/P2/P4 自动判定，必需项不过则非 0。
- 观测图像 y 向下被当作相机 +Y → 取负；新增非对称标定物验证（误差 5.2 mm）。
- 相机朝向符号错误、相机装在机体内、segmentation 编码不可靠、变量同名。
- `a[2]=−1` 被误当停车 → A0 走显式刹车（0.679 m 刹停距离）。
