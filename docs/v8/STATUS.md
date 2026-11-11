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

## 2026-11-11 复盘产物 eval.json（本机生成，**不完整**，须按本节阅读）

- 命令：`python3 scripts/v8/v8_eval.py --run runs/v8/main`（本机）；产物 `runs/v8/main/eval.json`（1.1 KB，`schema: v8-eval/v1`）。
- 环境：不需要 GL（只用 numpy/scipy/matplotlib 算真值占地）；本机没装 matplotlib，本次装 3.11.2 后跑通。它不在 `requirements.txt` 的 9 个校验包内，故只在注释里登记。
- `robots` 四台，数值与 §2 一致：`conservative` stuck/5 眼/142.2 s、`conservative_seedark` arrived/3 眼/147.26 s、`imagination_truth` arrived/1 眼/115.88 s、`optimistic` collision/1 眼/83.44 s（撞击 t=80.94 s）。
- **缺口（必读）**：`imagination` 那次运行按 §3.3 停在第三眼、退出码 10，因此**没有** `summary.json` / `events.jsonl` / `traj.npz`；`v8_eval.py` 只遍历含 `summary.json` 的目录，于是想象车整段被**静默跳过**：
  - `imagination` 车没有出现在 `robots` 里；
  - `imagination` 列表为空 → `summary.admitted = 0`、`rejected = 0`、`admitted_back_err_range_m = null`。
  - 读法：`admitted = 0` 表示"没有可评估的想象行"，**不是**"没有候选被采纳"。§3.2 的自检结论（T1 的候选、T2 的两眼结果）仍只能到 `looks/*/decide/target_decision.json` 与 §3.2 记录里去看。
- 因此当前 `eval.json` 只满足 §4.1 的"三台车并列"中的四台，**不满足**"想象的车每份候选与真实形状的比较"。要补齐：先在沙箱按两眼重跑想象车拿到 `summary.json`，再跑一次本命令；`v8_eval.py` 的静默跳过行为建议在 V9 一并修（跳过时应显式写出 `incomplete_runs`）。
