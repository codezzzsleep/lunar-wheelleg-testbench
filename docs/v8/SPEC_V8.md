# SPEC_V8：南极窄道里的三台机器人

- 下达：项目负责人
- 地位：V8 的执行规范。V7 的规则（密钥、数据保管、提交方式）继续有效，本文只写 V8 新增与变化的部分。
- 随本文附代码包 `v8_bundle.tar.gz`。

---

## 0. V8 要证明什么

### 0.1 场景

月球南极附近，太阳高度角 10°，从左后方照来。

- 窄道左边是月溪，右边是大石堆，两边在轨道图上都标为禁行；
- 窄道里有两块轨道图分辨不出的石头（< 1 m）：
  - **石块 A** 横在右车道上，比机身还高。机器人只看得到它亮着的长边，看不到它有多厚；
  - **石块 B** 挡住左边，后半截斜着向右凸，凸出的那截落在黑影里。
- 机器人只有一台被动相机。黑影里太暗，测不出深度。

### 0.2 两种影子

| 影子 | 由什么造成 | 换个位置再看一眼能不能解决 |
| --- | --- | --- |
| 视线的影子（盲区） | 被更近的东西挡住 | 能缩小 |
| 太阳的影子（黑影） | 太阳照不到，相机测不出深度 | 不能：从哪里看都是黑的 |

A 背后要换道的那片地，同时落在两种影子里。

### 0.3 三台车

三台车的观测、规划器、执行器完全相同，只在"看不见的地方怎么算"上不同：

| 车 | 看不见的格子 | 负责人本机测试的结果 |
| --- | --- | --- |
| 保守 | 当障碍；规划不出路线就换位置再看（最多 5 眼） | 5 眼后仍规划不出，停车 |
| 乐观 | 当空地 | 撞上 B 藏在黑影里的一截（路线与真实石块重叠 23 cm） |
| 想象 | Lux3D 想象出的石块当障碍，其余当空地 | 见下 |

- 对照实验：同一台保守车，如果相机在黑影里也能测出深度，看 3 眼就能过去。这说明它卡住的原因就是黑影。
- 想象的车，负责人做了两种替身测试：
  - 直接把真实石块形状当"完美想象"：看 1 眼，到达；
  - 走完整条 Lux3D 链路（请求 → 退出 10 → 结果 → 重放 → 配准自检 → 第二眼 → 预演），只是"Lux3D 的结果"换成替身 GLB（真形状、变薄一半、换一块石头，放进 Lux3D 惯例的任意正立坐标系）：
    - 第一眼：A 的 6 份采纳 5 份（换石头那份被拒绝）；B 大半被 A 挡住，6 份全被拒绝；
    - 第二眼走到 A 的左前方，只为 B 调两图：3 份采纳 2 份（变薄那份被拒绝）；
    - 留 5 cm 余量规划，5 格预演都没碰，到达；离真实石块最近 12 cm；
    - 反事实：信了第一眼被拒绝的 B，撞上 B。
- **正式运行用 Lux3D 的真实想象**，这是本规范要你完成的部分。结果可能与替身不同，如实记录。

### 0.4 想象的车怎么决策

每一眼：

1. 每块目标石头单独调用 Lux3D：
   - 第一眼单图，六份（A1 A2 B1 B2 C1 C2）；
   - 第二眼两图，三份（M1–M3），两张图是同一块石头的第一眼和第二眼。
2. 每份候选配准到观测上，用 V7 冻结的门槛自检：尺寸比、隐藏比例、贴合、侵入空地、轮廓。
   - 唯一的改动：轮廓只在"看得清"的像素上比。两种影子同一个道理：
     - 候选投到黑影里的部分不算对也不算错，因为黑影里可能就是石头的背光面；
     - 候选被更近的东西挡住的部分（观测深度比候选近 5 cm 以上）也不算。
3. 被采纳的候选取并集，作为"想象出的石头"。一块石头的候选全被拒绝时，它周围看不见的格子按保守处理。
4. 给想象留 5 cm 余量规划路线。5 cm 来自 V7 影子实验：被采纳的想象，背面误差最大 5.0 cm。
5. **在想象里预演：** 把路线放进只有想象石块的场景里（每份被采纳的候选一格），任何一格碰到就不执行。
6. 留不出余量、预演碰撞、或某块石头的想象全被拒绝，都去看第二眼。两眼之后还不行，就停车。
   - 第二眼站在哪：在看得见、开过的地方里选一个能原地转向的点，朝向"还看不见、又要用到"的格子；某块石头的想象全被拒绝时，就对准那块石头。
   - 第二眼为谁调 Lux3D：因"想象全被拒绝"而看第二眼时，只为那块石头调（两图）；已经有被采纳想象的石头沿用原结论。因留不出余量或预演碰撞而看第二眼时，拍到的石头都重新想象。

替身测试里观察到：第一眼时 B 大半被 A 挡住、离得也远，B 的想象（哪怕用真实形状当替身）配准不上、被自检拒绝。这正是第二眼要做的事：换个位置，把被挡住的部分看出来。

机器人在路上从不使用真实形状。真实形状只在跑完后的复盘（`v8_eval.py`）里出现。

---

## 1. 安装

1. 把 `v8_bundle.tar.gz` 解到仓库根目录，按包内 `PATCH_SHA256.txt` 校验。包内文件：

   ```
   scripts/v8/v8_scene.py      场景（地形、石块、太阳）
   scripts/v8/v8_vis.py        视觉模型与机器人相机（黑影门限）
   scripts/v8/vmodel.py        成片用的视觉模型（从负责人的渲染代码移入仓库）
   scripts/v8/v8_nav.py        地图、三种策略的占据图、规划、第二眼选点、碰撞判定
   scripts/v8/follow.py        原地转向 + 直行的路点执行
   scripts/v8/v8_obs.py        每块目标石头的观测目录与 Lux3D 输入图
   scripts/v8/v8_imagine.py    配准与自检（轮廓只在亮处比），在想象里预演
   scripts/v8/v8_lux.py        Lux3D 请求与结果（格式沿用 V7），重放核对
   scripts/v8/v8_run.py        三台车的完整流程
   scripts/v8/v8_eval.py       赛后复盘
   docs/v8/SPEC_V8.md          本文
   ```

2. `python3 -m py_compile scripts/v8/*.py`
3. 提交并推送：`v8: polar corridor, three robots, dark-aware self-check`。

依赖与 V7 相同：岩石资产 `assets/v3/rocks`，缓存 `runs/v7/cache`，`plans/v3_protocol.json`，`configs/v5_admission.json`。

---

## 2. 沙箱：不需要 Lux3D 的四次运行

一个一个跑，每跑完一个就拉回、校验、推送，`docs/v8/SANDBOX_LOG.md` 各记一行。每个约 2–4 分钟。

```
MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy conservative --max-looks 5 --out runs/v8/main
MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy optimistic --out runs/v8/main
MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy conservative --see-dark --max-looks 5 --tag conservative_seedark --out runs/v8/main
MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy imagination --imagine truth --tag imagination_truth --out runs/v8/main
```

预期（`runs/v8/main/<tag>/summary.json` 的 `result`）：

| tag | result | looks |
| --- | --- | --- |
| conservative | stuck | 5 |
| optimistic | collision | 1 |
| conservative_seedark | arrived | 3 |
| imagination_truth | arrived | 1 |

与预期不同时，停下回报，附 `events.jsonl`。

---

## 3. 想象的车：沙箱与本机交替

### 3.1 沙箱：跑到第一眼

```
MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy imagination --imagine lux --out runs/v8/main
```

- 预期退出码 **10**，`runs/v8/main/imagination/NEED_LUX3D.json` 列出请求文件。每块目标石头一份，通常两份：`looks/look1/T1/lux_request.json`、`looks/look1/T2/lux_request.json`。
- **立即**把 `runs/v8/main/imagination/` 整个拉回本机，校验，推送。

### 3.2 本机：调用 Lux3D

- 对每份请求，按 `items` 逐项调用 Lux3D，规则与 V7 相同：
  - `mode: img`：每项一个任务，上传 `path` 那张图；
  - `mode: imgs`：每项一个任务，请求体字段 `imgs = [paths[0], paths[1]]`，按顺序；**不得拼成一张图**；同样输入的三项是独立样本，各自给样本编号，避免命中缓存；
  - `version: G1-Turbo`，`faceCount: 30000`。
- 结果写进请求里 `result_file` 指定的位置，字段按 `result_schema`：
  - `inputs` 必须与请求里的路径**逐字相同**（仓库相对路径）；
  - `glb` 是仓库相对路径，`glb_sha256` 必须与文件一致；
  - 两图任务必须带 `api_field: "imgs"`、`n_images: 2`。
- GLB 放在 `assets/v8/lux/main/<look>/<target>/<id>/`（走 LFS）。
- 密钥只从环境变量读，不写进任何文件、日志或命令行。`LUX3D_CALL.md` 按 V7 的格式追加记录。
- 提交并推送。

### 3.3 沙箱：继续

拉取最新提交后，**运行同一条命令**：

- 脚本从头确定性地重放到第一眼，核对重新拍到的输入图与请求时逐字节相同，然后用你的结果决策；
- 退出码与处理：

| 退出码 | 含义 | 你要做的 |
| --- | --- | --- |
| 0 | 跑完（到达或停车） | 拉回、校验、推送，进入 §4 |
| 10 | 需要第二眼的 Lux3D | 回到 §3.2，处理 `NEED_LUX3D.json` 列出的新请求（`look2`，两图） |
| 11 | 重放与上次拍到的不一致 | **停下回报**，不要删任何目录 |

- 每次退出后都立即拉回、校验、推送。

### 3.4 耗时参考

- 每份候选配准约 1–2 分钟（单线程）；第一眼两块石头共 12 份，约 20–30 分钟；
- 在想象里预演每格约 1 分钟；
- 负责人本机（2 核）整条替身链路三个阶段共约 40 分钟。

---

## 4. 复盘与反事实

### 4.1 复盘

```
python3 scripts/v8/v8_eval.py --run runs/v8/main
```

输出 `runs/v8/main/eval.json`，内容：

- 三台车并列；
- 想象的车每份候选与真实形状的比较：占地 IoU、背面误差、侧面误差、自检结论。

### 4.2 反事实：如果信了被自检拒绝的想象

- 看 `eval.json` 的 `imagination` 列表，在**被拒绝**的候选里，找 `back_err_m` 最小（想得最短）的那一份，记下它的 `look`、`target` 和 `candidate`。
- `--trust` 只作用于第一眼的结论：如果你选的那份来自 `look2`，改选 `look1` 里被拒绝、`back_err_m` 最小的一份。
- 运行（例子：T1 的 A2）：

  ```
  MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy imagination --imagine lux --trust T1=A2 --tag counterfactual_T1_A2 --out runs/v8/main
  ```

- 它会先把 `imagination/looks/` 里已有的观测、Lux3D 结果与自检结果复制过来，不产生新的 Lux3D 调用；
- 这台车只用指定的那份想象，不看第二眼，也不在想象里预演；
- 如果它退出码是 10 或 11，停下回报。
- 被拒绝的候选里没有想得太短的（`rejected_too_short` 为 0），跳过这一步，并在 STATUS 里写明。

---

## 5. 数据保管

沙箱随时可能被销毁，不能让沙箱成为任何数据的唯一副本：

- 每一步跑完立即拉回本机，按文件 sha256 与沙箱逐一核对，再推送；
- 拉回的范围是整个 `runs/v8/main/`：轨迹 `traj.npz`、`looks/`、`decide/`、`rehearsal/`、`events.jsonl`、`summary.json`；
- `npz` `npy` `png` `glb` `obj` 走 LFS。

---

## 6. 回报

在 `docs/v8/STATUS.md` 追加：

- 安装提交号；
- §2 四次运行的 `summary.json`；
- 想象的车每次退出的退出码、`NEED_LUX3D.json`；
- 每份 Lux3D 结果的 `task_id` 与状态；
- 想象的车最终的 `summary.json`、`events.jsonl` 里的 `imagination` 与 `rehearsal` 两类事件；
- `eval.json` 的 `robots` 与 `summary`；
- 反事实运行的 `summary.json`，或跳过的原因。

数字与预期不一致时如实写出，不要改代码。

---

## 7. 规则

- 不改 `scripts/v8/`、不改门槛、不改场景；
- Lux3D 只在本机调用；密钥只从环境变量读；
- 同一个进程里只跑一个场景，不要在 V8 脚本之前先跑别的场景（V7 的教训：模块全局设置会泄漏）；
- 遇到与本文不一致的情况，停下回报。
