# REVIEW_V7_R1：复核结论与补跑第二眼

- 下达：项目负责人
- 复核对象：`main` 提交 `5a3f2d581`
- 地位：SPEC_V7 的补充，冲突时以本文为准。
- 随本文附补丁包 `v7_1_patch.tar.gz`，只含 `scripts/v7/v7_route.py` 和本文。

---

## 0. 复核结论

### 0.1 通过的部分

- `scripts/v7/` 与代码包逐字节一致，没有被改动；回归、KA9、sha 校验、LFS 入库、沙箱日志都符合 SPEC。
- 三行观测照片正常：有贴图，没有空心或碎片，掩码正确。
- §3.1 只看正面一臂、§3.2 的 E1、§3.4 影子实验：数据成立，进入成片。

### 0.2 影子实验的结论（负责人根据 `eval_rows.json` 计算）

长影子条件（`low_side` 与 `low_front`）下，三种输入的对比：

| 输入 | 成功任务 | 准入 | 隐藏区 IoU 中位数 | 背面误差中位数 |
| --- | --- | --- | --- | --- |
| `B_naive` 亮度抠图（影子并进石头） | 10 | 0 | 0.18 | 14.8 cm |
| `A_naive` 原图裁剪 | 12 | 4 | 0.47 | 4.5 cm |
| `B_depth` 深度抠图（本项目） | 12 | 6 | 0.735 | 3.1 cm |

全部 64 个成功任务里，准入自检的表现：
- 想象错误的 32 个（隐藏区 IoU < 0.5）：准入 0 个；
- 想象正确的 31 个（IoU ≥ 0.6）：准入 28 个；
- 被准入的想象，背面误差最大 5.2 cm。

### 0.3 必须重做的一处：E2 的第二眼

1. **两视图被拼成一张组合图提交了。**
   - SPEC 的 `imgs` 模式是一个任务同时发送两张图。拼成一张图后，Lux3D 看到的是并排的两块石头，结论不能用。
   - `route_full` 的 E2 look2 作废；E1、E2 look1 不受影响。
2. **"仓库里没有多图接口"不成立。**
   - `scripts/lux3d_client.py` 的 `submit_img_to_3d_multi` 发送请求体字段 `imgs`（两张图的 URL，按顺序）。
   - `scripts/v7_generate.py` 在 10 月 30 日用它真实生成成功过：task 4486935、4489794，状态 3，GLB 已下载。
3. **结果记录有误导。**
   - look2 的 `lux_result.json` 在 `inputs` 里写了两张原图，实际上传的是 `look2/inputs/` 里的组合图。
   - 以后 `inputs` 一律写实际上传的文件。

接口不确定时，应当停下回报，而不是换一种做法提交。这一条补进 §5。

---

## 1. 安装补丁

1. 把 `v7_1_patch.tar.gz` 解到仓库根目录，按包内 `PATCH_SHA256.txt` 校验。
2. `python3 -m py_compile scripts/v7/v7_route.py`
3. 提交并推送：`v7.1: route --reuse-lux and real two-image check`。

`v7_route.py` 的改动：

| 改动 | 内容 |
| --- | --- |
| `--reuse-lux <旧运行目录>` | 单图请求的每张输入图与旧运行同一位置的输入图 sha256 完全相同、GLB 的 sha256 也对得上时，直接复用旧结果，不再退出等待。结果文件记 `reused_from`，`events.jsonl` 记 `look1_lux_reused`。两图请求从不复用。 |
| 两图结果检查 | `imgs` 模式的每个成功任务必须带 `api_field: "imgs"` 和 `n_images: 2`，否则报错停止。 |
| 两图请求说明 | `lux_request.json` 里新增 `imgs_rule`，写明调用方式。 |

观测、决策、执行的逻辑没有改动。负责人已验证：沙箱与负责人测试机渲染出的照片逐字节相同，复用会命中。

---

## 2. 标记作废、更新调用规程

1. 新建 `runs/v7/route_full/INVALID_E2_LOOK2.md`，写明：
   - E2 look2 的 3 个任务提交的是拼接组合图，不是两图调用，结论作废；
   - 该运行由 `runs/v7/route_full_r2` 取代；
   - 不删除任何数据。
2. 更新 `docs/v6/LUX3D_CALL.md` §6：
   - `imgs` 模式：一个 item 是一个任务，请求体字段 `imgs` = [paths[0] 的 URL, paths[1] 的 URL]，顺序不能换，不带 `img`；用 `scripts/lux3d_client.submit_img_to_3d_multi`，做法同 `scripts/v7_generate.py`；
   - 禁止把两张图拼成一张；
   - 同一请求里路径相同的 item（M1–M3）是独立采样，各用一个 sample id，避免命中缓存；
   - 两图任务的结果必须写 `api_field: "imgs"`、`n_images: 2`；
   - `inputs` 写实际上传的文件。

---

## 3. 补跑有想象的一臂

沙箱上需要 `runs/v7/route_full/`（含照片与 `lux_result.json`）和 `assets/v7/lux/` 的 GLB，从 git/LFS 拉取。根路径仍用 `/workspace/lunar-lab`。

1. **沙箱：**

   ```
   MUJOCO_GL=egl python3 scripts/v7/v7_route.py --arm full --run runs/v7/route_full_r2 --reuse-lux runs/v7/route_full
   ```

   - 预期：E1 和 E2 look1 复用旧结果（`events.jsonl` 里有两行 `look1_lux_reused`），E1 照旧采纳并执行；E2 look1 照旧全部拒绝，机器人去看第二眼，在 E2 look2 以退出码 10 停下。
   - 如果在 E1 就以退出码 10 停下，说明复用没命中：在 STATUS 记一行，照常提交 6 个任务继续，不用等负责人。
2. **退出码 10：** 拉回 `runs/v7/route_full_r2/`，校验，推送。
3. **本地：** 读 `E2/look2/lux_request.json`，按 `imgs_rule` 提交 3 个真实两图任务（M1–M3），照常记账。
   - 写 `lux_result.json`，每个任务带 `api_field`、`n_images`，`inputs` 写两张实际上传的图；推送。
   - 服务端失败重提一次，仍失败记 `status=failed`，流程继续。
   - 如果两图接口直接返回参数错误：停下回报，附服务端返回的错误码和信息（不含密钥），不要换别的做法提交。
4. **沙箱：** 拉取，运行同一条命令续跑，直到退出码 0。拉回、校验、推送。
5. 生成联系表：`python3 scripts/v7/v7_contact.py runs/v7/route_full_r2 docs/v7/contact_full_r2.png`。

数据保管照 SPEC §1：每次退出都要拉回、校验、推送后才继续，`SANDBOX_LOG.md` 每次追加一行。

---

## 4. 其他事项

- **REVIEW_R3 的 gallery 修正、RESULTS 重写：取消。** V6 的展示与结论由 V7 取代，V7 的结果文档由负责人根据数据撰写。
- **mujoco 固定为 3.17.0：** 确认。写进 `docs/v7/ENV.md`，注明 4.0 不兼容（机器人签名）。
- **8 个失败的影子任务：** 不补跑，照现在的结果使用。

---

## 5. 回报

在 `docs/v7/STATUS.md` 追加：

- 补丁安装、作废标记、规程更新的提交号；
- `route_full_r2`：复用是否命中；E2 look2 的 3 个任务的 task_id、状态、准入数；E2 的分支与执行动作、真值结局；终点 x、全程用时、是否到达；
- 联系表路径。

立即停下并回报的情况，在 SPEC §5 之外再加一条：
- **接口或做法与文档不一致时**（例如找不到文档要求的接口），停下回报，不要自行换一种做法。
