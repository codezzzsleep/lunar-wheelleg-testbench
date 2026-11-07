# REVIEW_V7_R2：修正尺寸比、重算决策与影子实验

- 下达：项目负责人
- 复核对象：`main` 提交 `37928fcf7`
- 地位：SPEC_V7 与 REVIEW_V7_R1 的补充，冲突时以本文为准。
- 随本文附补丁包 `v7_2_patch.tar.gz`。

---

## 0. 复核结论

### 0.1 通过的部分

- 补丁安装、作废标记、LUX3D_CALL §6、ENV、SANDBOX_LOG：符合要求。
- `scripts/v7/` 与 v7.1 补丁逐字节一致。
- E2 第二眼是真实两图调用：
  - 结果字段齐全；
  - 三个模型的尺寸、比例相互一致，M1 收养可信；
  - 负责人在本地重做配准，得到的数值与你的结果逐位相同。
- E2 第一眼没有命中复用，原因成立：原运行在 E1 处中断后续跑，补跑一路没有中断；续跑不是逐位相同的，所以到 E2 时位姿有毫米级差异。你按规程提交了新任务，处理正确。

### 0.2 负责人发现并修正的错误（v7.2）

**自检的"尺寸比"在 V7 深度掩码下有系统偏差。错误由负责人的改动引入，与你的执行无关。**

- **定义：** 尺寸比 = 候选在可见列里的高度 ÷ 观测正面的高度。
- **为什么偏：** 候选按"从地面往上填满"计算，高度从地面算起。V7 的深度掩码只保留离地 1.5 cm 以上的像素，观测正面从约 1.3 cm 才开始，观测高度被低估，比值被抬高。
  - 门槛 0.889–1.09 是在分割掩码下标定的。那时正面一直延伸到地面，没有这个偏差。
- **证据：** 把场景里真实石头的网格当作候选打分（`scripts/v7/v7_scale_truth.py`）：

  | 遭遇 | v5 定义 | v7.2（从地面量起） |
  | --- | --- | --- |
  | E1（22 cm） | 1.057 | 1.000 |
  | E2（12 cm） | 1.113（超过上限，真石头会被拒绝） | 1.000 |

- **修正：** `v7_encounter.scale_ratio_ground`，观测高度也从地面量起。
  - 门槛数值不变，其他四项指标不变；
  - v5 原值另存为 `scale_ratio_v5`，便于对照；
  - `decision.json` 与影子实验的 `rows.json` 标 `metric_version: 2`。

### 0.3 修正后的结论（负责人本地计算，需你在沙箱上正式复现）

| 遭遇 | 原结论 | v7.2 结论 | 选中动作 | 实际执行 |
| --- | --- | --- | --- | --- |
| E1 第一眼 | 采纳 5/6，直行 | 采纳 3/6（B1、B2、C1），直行在 2/3 份里安全，代价最低 | 直行 R1 | R1 |
| E2 第一眼 | 拒绝 0/4 | 拒绝 0/4（轮廓或伸进空地不合格，与尺寸比无关） | 去看第二眼 | 第二眼 |
| E2 第二眼 | 拒绝 0/3 → 回退 | **采纳 1/3（M2）**，用 M2 预演：除"放弃"外都安全 | 直行 R1 | R1 |

- 两个遭遇最终选中的动作都与 `route_full_r2` 实际执行的相同。
- 同样的起始状态、同样的动作，物理过程完全相同，所以 `route_full_r2` 的执行轨迹就是 v7.2 决策会产生的轨迹，**不需要重跑路线**。

影子实验（64 个成功任务）按 v7.2 重算：

- 有 7 份从采纳变为拒绝。它们都是高度偏矮、原来被偏差抬进门槛的。
- 长影子条件下：

  | 输入 | 采纳 |
  | --- | --- |
  | 亮度抠图 | 0/10 |
  | 原图裁剪 | 3/12 |
  | 深度抠图 | 5/12 |

- 自检：
  - 想象错的 32 份（隐藏区 IoU < 0.5）采纳 0 份；
  - 想象对的 31 份（≥ 0.6）采纳 21 份（原来是 28 份）；
  - 被采纳的想象背面误差最大 5.0 cm。

---

## 1. 安装补丁

1. 把 `v7_2_patch.tar.gz` 解到仓库根目录，按包内 `PATCH_SHA256.txt` 校验。包内文件：

   ```
   scripts/v7/v7_encounter.py     尺寸比从地面量起（scale_ratio_ground）；decision 标 metric_version 2
   scripts/v7/v7_shadow_exp.py    评估使用修正后的尺寸比；rows 标 metric_version 2，旧缓存自动作废
   scripts/v7/v7_redecide.py      新增：同一观测、同一批 Lux3D 结果重新决策，并与实际执行对比
   scripts/v7/v7_scale_truth.py   新增：用真实石头检查尺寸比
   docs/v7/REVIEW_V7_R2.md        本文
   ```

2. `python3 -m py_compile scripts/v7/*.py`
3. 提交并推送：`v7.2: size ratio measured from the ground (fix depth-mask bias)`。

---

## 2. 在沙箱上运行（不调用 Lux3D）

一个一个跑，每跑完一步就拉回、校验、推送，`SANDBOX_LOG.md` 各记一行。

1. **真值检查：**

   ```
   MUJOCO_GL=egl python3 scripts/v7/v7_scale_truth.py --run runs/v7/route_full_r2
   ```

   预期每一行的 `v72_scale_ratio` 都在 1.00 ± 0.01，`v5_scale_ratio` 为 E1 约 1.057、E2 约 1.113。结果写在 `runs/v7/route_full_r2/scale_truth_v72.json`。

2. **重新决策：**

   ```
   MUJOCO_GL=egl python3 scripts/v7/v7_redecide.py --run runs/v7/route_full_r2 --out runs/v7/route_full_r2_v72
   ```

   - 预期退出码 0，`summary.json` 的结论与 §0.3 的表一致（`all_same: true`）。
   - 耗时参考：约 1–1.5 小时（E1 三份采纳候选、E2 第二眼一份，加上只看正面的两种极端几何）。
   - **退出码 3**（选中动作与实际执行不同）：停下回报，附 `summary.json`，不要重跑路线。

3. **影子实验重新评估：**

   ```
   python3 scripts/v7/v7_shadow_exp.py --evaluate --out runs/v7/shadow_exp
   ```

   旧的 `rows.json` 没有 `metric_version: 2`，会自动重算。把新的 `summary.json` 原文写进 STATUS。

---

## 3. 回报

在 `docs/v7/STATUS.md` 追加：

- 补丁提交号；
- 真值检查的输出；
- `route_full_r2_v72/summary.json` 的 `compare` 部分；
- 影子实验新的 `summary.json`；
- 与 §0.3 的数字是否一致。不一致时如实写出，不要改代码。

---

## 4. 成片

成片由负责人渲染，用的正是 v7.2 的结论。负责人会另外交付视频文件和渲染代码包；你收到后放进 `docs/v7/video/`（mp4 走 LFS），提交并推送。

---

## 5. 规则

- 不改 `scripts/v7/`、不改门槛；
- 不重跑路线，不调用 Lux3D；
- 遇到与本文不一致的情况，停下回报。
