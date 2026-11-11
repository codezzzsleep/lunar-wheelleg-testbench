# V8 状态

- 安装：`c3bb5848f`（`v8: polar corridor, three robots, dark-aware self-check`）；V8 与 V7.3 的补丁清单分别校验通过（根 `PATCH_SHA256.txt` 为 V8，V7.3 在 `docs/v7/PATCH_SHA256_v73.txt`）。
- 沙箱：`cnb-0fp-1k6rn0am3-001`，8 核，`mujoco==3.17.0`，另需 `matplotlib`（V8 真值占地检查用）。
- §2 第 1 次（conservative，`--max-looks 5`）：`result=stuck`、`looks=5`、`sim_time_s=142.2`、`wall_s=32.5`，与预期一致。
- §2 第 2 次（optimistic）：`result=collision`、`looks=1`、`drive_margin_m=-0.23`、`sim_time_s=83.44`，与预期一致（撞上 B 藏在黑影里的一截，重叠 23 cm）。
- §2 第 3 次（conservative_seedark）：`result=arrived`、`looks=3`、`sim_time_s=147.26`，与预期一致（黑影里能测深度时 3 眼通过）。
- §2 第 4 次（imagination_truth）：`result=arrived`、`looks=1`、`drive_margin_m=0.117`、`sim_time_s=115.88`，与预期一致。
- §2 四次运行全部与 SPEC §2 预期表一致。
- §3.1 想象的车第一眼：退出码 **10**，`NEED_LUX3D.json` 列出 `look1/T1/lux_request.json` 与 `look1/T2/lux_request.json`。
- §3.2 第一眼 Lux3D（本机）：
  - T1：6/6 成功（A1、A2、B1、B2、C1、C2）；
  - T2：4/6 成功（A1、A2、C1、C2）；B1、B2 重提一次仍失败，记 `status=failed`；
  - GLB：`assets/v8/lux/main/look1/<T>/<id>/tex_mesh.glb`（10 个，82 MB）。
- §3.1 第二眼：第一眼决策 `imagined_blocked` → 第二眼（`look2/T2`，imgs 3 个任务，真实两图）。
- §3.2 第二眼 Lux3D（本机）：M1/M2/M3 **3/3 成功**，均 `api_field=imgs`、`n_images=2`；GLB 在 `assets/v8/lux/main/look2/T2/`。
- §3.3 第二次退出码 **10**：第二眼（look2/T2）决策仍 `imagined_blocked`，脚本继续要求 **look3/T2**。
  - 这与 SPEC §0.4“两眼之后还不行，就停车”不一致（脚本 `--max-looks` 默认 1+MAX_EXTRA_LOOKS，允许继续看第三眼）。
  - 按“遇到与文档不一致停下回报”，未调用 look3 的 Lux3D，未删目录；look3 请求已拉回并推送。

## 2026-11-11 眼数与规范对齐

- SPEC 原文（`docs/v8/SPEC_V8.md:64`，§0.4）：「留不出余量、预演碰撞、或某块石头的想象全被拒绝，都去看第二眼。**两眼之后还不行，就停车。**」
- 代码原状：`scripts/v8/v8_run.py` 里 `MAX_EXTRA_LOOKS = 2`，`--max-looks` 默认 `1 + MAX_EXTRA_LOOKS = 3`；只有 `len(looks) >= a.max_looks` 才停车，所以 `imagined_blocked` 之后默认还会看第三眼（§3.3 的 `look3/T2/lux_request.json` 即由此产生）。
- 本次改动：新增 `MAX_LOOKS_BY_SPEC = 2`（注释写明来源 SPEC §0.4:64「两眼之后还不行，就停车」），`MAX_EXTRA_LOOKS = MAX_LOOKS_BY_SPEC - 1 = 1`，`--max-looks` 默认改取 `MAX_LOOKS_BY_SPEC`（= 2 眼）。
- 停车语义已核对：`scripts/v8/v8_run.py:369` 的 `if len(looks) >= a.max_looks or trust:` 之后是 `result='stuck'` + `rec.hold(env, 'stuck', 2.0)` + `break`，不看下一眼、也不再发 Lux3D 请求；全文件 `look()` 只有两处调用（第一眼、循环末尾），没有别的入口或 while/for 能绕过。
- 显式超规范：`--max-looks` 大于 2 时往 stderr 打警告，并在 `summary.json` 与 `events.jsonl` 的 `result` 事件里写 `looks_exceed_spec: true`（默认两眼看时为 `false`）。即第三眼只能人为显式要求，不会默认发生。
- `PATCH_SHA256.txt`：只更新 `scripts/v8/v8_run.py` 一行（`8f2c7353…` → `d866cf93…`），其余 10 行未动；`sha256sum -c PATCH_SHA256.txt` 11/11 OK，`docs/v8/SPEC_V8.md` 哈希未变（SPEC 未改）。
- 测试：新增 `tests/test_v8_looks.py`（8 项：解析 SPEC 文本取「两」并与脚本默认值比对、断言 `--max-looks 3`/`5` 带出 `looks_exceed_spec`）；新增 `tests/_gl.py`（子进程探测 GL，避免主进程 SIGABRT），`tests/test_camera.py`、`tests/test_freespace.py` 在无 GL 时优雅跳过（`OK (skipped=6)` / `OK (skipped=5)`），不再 core dump。
- 遗留：`runs/v8/main/imagination/looks/look3/T2/lux_request.json` 是旧默认值（3 眼）下的产物，Lux3D 未调用（`look3/T2` 无 `lux_result.json`，`assets/v8/lux/main/` 下也无 `look3`）。要不要删由负责人决定，本次未删；新默认值下重跑不会再生成第三眼。

## 2026-11-11 复盘产物 eval.json（首版已作废，见下文 §4.1）

- 首版 `eval.json`（1.1 KB）只含 4 台车、`imagination` 列表为空、`summary.admitted = 0`：
  原因是 `v8_eval.py` 当时只遍历含 `summary.json` 的目录，而想象车按 §3.3 停在第三眼、没有 summary。
  **该读数不能理解为"没有候选被采纳"。**
- 同日修好脚本并重新生成（候选比较改为独立扫描 `looks/`，并显式写 `incomplete_runs`），
  见下文 §4.1；现文件为 6.8 KB、13 行候选比较。本节保留只为记录这次踩坑。

## 2026-11-11 本机补跑（无 GPU，OSMesa 软件渲染）

- 环境：本机没有 `DISPLAY`/EGL。用 `apt-get download` + `dpkg -x` 把 `libosmesa6`、`libglvnd0`、
  `libglapi-mesa`、`libglx-mesa0`、`libgl1-mesa-dri`、`libllvm20` 解到 `/tmp/glroot`，
  再以 `LD_LIBRARY_PATH=/tmp/glroot/usr/lib/x86_64-linux-gnu MUJOCO_GL=osmesa` 跑通 MuJoCo 渲染
  （venv 内 `mujoco 3.17.0` / `numpy 2.5.4` 与沙箱一致）。这是"没有 GPU 也能跑"的可行路径，
  但它渲染出的像素与 EGL 后端**不保证逐位相同**（见 §3.3）。
- 过程中修掉两个移植性缺陷（都属"换机器就断"的坑）：
  1. `target_decision.json` 里 `glb`/`obs` 记的是沙箱绝对路径 `/workspace/lunar-lab/…`，换机器后
     `trimesh.load` 直接 `ValueError: string is not a file`。新增 `v8_imagine.resolve_path()`
     （依次试：原样 → 仓库根拼接 → 从已知顶层目录截断后拼接），新写入的 `glb` 改记仓库相对路径；
  2. `v8_eval.py` 只遍历有 `summary.json` 的目录，跑到一半退出的车会被**静默跳过** →
     候选比较改为独立扫描 `looks/`，并把这类运行显式记进 `incomplete_runs`。
- 补丁清单：`PATCH_SHA256.txt` 更新了 `v8_imagine.py`、`v8_eval.py` 两行，仍 **11/11 OK**；
  新增的 `scripts/v8/v8_replay_diff.py`（重放差异取证工具）不属原补丁包，未入清单。

### §3.3 结论：两眼停车成立；但本机跑不成一次完整物理运行

- 重跑 `--policy imagination --imagine lux`（默认两眼）：
  - look1 **逐字节复现成功**（`same_inputs` 命中，直接复用沙箱的 6 份 Lux3D 结果，**没有产生任何 API 调用**）；
    决策 `imagined_blocked` → 按 §0.4 侧移看第二眼；
  - look2 重放**不逐字节相同** → `replay_mismatch` → 按设计退出码 **11**（拒绝拿旧结果冒充，行为正确）。
- 量化差异（`runs/v8/main/imagination/looks/look2/REPLAY_DIFF.json`，工具 `scripts/v8/v8_replay_diff.py`）：
  - 位姿：dx = **0.1902 mm**、dy = 0.0923 mm、dyaw = **0.008483°**；
  - RGB：平均绝对差 1.5608（/255），192 万像素里 28,438 个像素差 > 8；
  - 深度：共同有限像素 142.9 万，中位数差 0.83 mm、p90 8.93 mm、p99 351 mm（差异集中在岩石轮廓边缘）。
- 判读：这不是渲染坏了，而是**跨机器的浮点漂移在接触丰富的机动之后被放大**——同机逐位可复现
  （V7 §2.1 已证），换机器后第二眼停车位姿差 0.19 mm，就足以让"逐字节复用"判据失效。因此：
  - 协议结论（由已记录的决策推导，**不是**一次完整物理运行）：两眼上限下想象车在 look2 之后停车，
    不会再要第三眼；它与 `conservative` 的差别只是"停在第几眼"。
  - 想变成真实运行只有两条路：回原沙箱跑，或把复用判据从"逐字节"改成"位姿 + 像素容差"
    （后者削弱证据强度，需负责人决策，本次**未改**）。

### §4.1 复盘：eval.json 现在含候选比较

- `python3 scripts/v8/v8_eval.py --run runs/v8/main` → `runs/v8/main/eval.json`。
- `imagination` **13 行**（look1 T1 6 份 + look1 T2 4 份 + look2 T2 3 份）；`admitted=2`（仅 T1 的 B2、C2）、
  `rejected=11`、`rejected_too_short=10`；`incomplete_runs=["imagination"]`（该车无 `summary.json`）。
- 被采纳：背面误差 0.00–0.35 m、占地 IoU 0.60–0.714；被拒绝里 10 份"想短了"（back_err < −0.05 m），
  最极端 **−0.9 m**（T2 的 C1、C2）。
- 机器人成绩 4 台（`imagination` 因退出码 10/11 无 `summary.json`，故不在 `robots` 里，已由
  `incomplete_runs` 显式标注，避免再被读成"没有候选被采纳"）。

### §4.2 反事实：信了被拒绝的想象会撞

- 依据 §4.1：被拒绝里 `back_err_m` 最小（想得最短）= `look1/T2/C1`（−0.9 m；C2 同为 −0.9，按 id 取 C1）。
- 运行：`--policy imagination --imagine lux --trust T2=C1 --tag counterfactual_T2_C1`
  （复用 `imagination/looks` 的观测与 Lux3D 结果，无新 API 调用；look1 逐字节复现成功，所以这是一次**真实物理运行**）。
- 结果：规划期 `drive_margin_m = **-0.23**`（与真值重叠 23 cm）→ 执行 → **t = 89.18 s 撞上 obstacle1**，
  `result=collision`、`looks=1`、`sim_time_s=91.68`。产物 `runs/v8/main/counterfactual_T2_C1/`。
- 判读：把自检拒绝的候选强行采纳后，规划器就在真值里"看不见的那 0.9 m"上看见了空路，直接撞进去。
  **自检的拒绝是 load-bearing 的**；同时说明"想象不足"比"没有想象"更危险。
- 附一条口径更正：早期 STATUS 把 `drive_margin_m=-0.23` 写在 `optimistic` 名下的 summary 字段，
  实际它只出现在 `plan` 事件的 `margin_vs_truth` 里，`optimistic/summary.json` 无此键。上文不改，此处理清。

### 本版收口状态

| 条目 | 状态 | 说明 |
| --- | --- | --- |
| §0.4 两眼上限 | DONE | `MAX_LOOKS_BY_SPEC = 2`，显式超规范才警告并记 `looks_exceed_spec` |
| §3.1 首眼请求 | DONE | 沙箱退出码 10，两份 `lux_request.json` |
| §3.2 首眼/第二眼 Lux3D | DONE | 首眼 T1 6/6、T2 4/6；第二眼 3/3（`imgs`，n_images=2）；准入 2/6、0/4、0/3 |
| §3.3 两眼停车 | **BLOCKED** | 跨机重放差 0.19 mm → 退出码 11；协议结论可推导，但缺一次完整运行 |
| §4.1 复盘 | DONE | `eval.json` 含 13 行候选比较 + `incomplete_runs` |
| §4.2 反事实 | DONE | `--trust T2=C1` 真实运行 → 撞车（t=89.18 s） |
| §5 数据保管 | DONE | 本文件 + `PATCH_SHA256.txt`（11/11）+ 产物路径；`SANDBOX_LOG.md` 的"待提交"列已由提交号补齐 |
