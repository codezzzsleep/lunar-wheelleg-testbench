# 第二轮执行清单

复核基线：`main = 39e3d94`　　工作分支：`fix/round2`

## 旧证据保全

`runs/canonical/` 保持不动（含 config/environment/results/summary/report）。
校验和存于 `runs/_archive_canonical_39e3d94/SHA256SUMS`：

```
4249151... config.json      01770a2... environment.json
1d74bb8... results.jsonl    b5ea748... summary.json      0c65769... report.md
```

旧批次的三项已知限制（不修补、不覆盖）：
1. 2520 条记录 `collision_sha` 全为 null；
2. `environment.json` 记录源码 `659c1c7` 且 `uncommitted_changes=true`；
3. `config.json` 的 `asset_count=49` 混淆了「可用资产」与「实际参与资产」。

## 六项修复与验收

| # | 任务 | 验收 | 状态 |
| --- | --- | --- | --- |
| 1 | 批次隔离与安全续跑 | 跨 suite 拒绝且原文件字节不变；续跑只补缺失；改动参数/资产/模型/源码逐项拒绝；脏记录拒绝；并发写互斥 | 待做 |
| 2 | 坏资产与 worker 异常留记录 | 缺 manifest / 坏 JSON / 结构错 / 缺 part / 无效尺寸 → precheck_failed 且不二次崩溃；单 worker 异常 → ERROR 且其余继续；加载异常不变成 completed | 待做 |
| 3 | 分析器严格校验 | 重复/缺失/计划外 ID、非法 JSON、全 ERROR、全预检失败 分别检测并非零退出；--allow-partial 显式且标注 | 待做 |
| 4 | 统一资产路径解析 | 仓库根与仓库外 cwd 结果一致；复制资产可用；缺 part 报出解析到的路径；空格路径可用 | 待做 |
| 5 | 运行来源证据 | 每个非平地 trial 有可重算的 collision_sha；改文件即拒；源码/模型身份可还原；清单无省略号 | 待做 |
| 6 | 安装流程接通 | 未激活 venv 的 shell 按文档命令可用；模型提交失败时 setup 非零退出；vendor 有修改时安全拒绝 | 待做 |

## 本轮不做

不改控制器策略、完成判据、障碍尺度、偏移网格；不加 GPU/RL/云/账户/新资产。

---

## 执行结果（2026-10-26）

| # | 任务 | 验收 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 批次隔离与安全续跑 | 跨 suite 拒绝、原文件字节不变 | 通过：exit=1，manifest/environment/results 校验和不变 | `tests/test_round2.py::TestBatchIsolation` |
| 1 | | 续跑只补缺失 | 通过：删到 1 条后 `--resume`，最终 3 条 / 3 唯一 ID | 同上 `test_resume_only_fills_missing` |
| 1 | | 参数/资产/模型/源码变化逐项拒绝 | 通过：改源码 → exit=1 且报"运行身份不一致" | `test_source_change_refused` |
| 1 | | 脏记录拒绝 | 通过：重复 ID → exit=1，不悄悄过滤 | `test_duplicate_id_in_results_refused` |
| 1 | | 并发写互斥 | 通过：存在 `.run.lock` → exit=1 | `test_lock_blocks_second_writer` |
| 2 | 坏资产留记录 | 缺 manifest/坏 JSON/非对象/缺 part/无效尺寸 | 通过：全部 `precheck_failed`，无二次崩溃 | `TestPrecheckRobustness`（6 项） |
| 2 | worker 异常 | 单任务异常 → ERROR 且整批继续 | 通过：未知控制器 → `status=ERROR` + traceback | `TestWorkerExceptionRecorded` |
| 3 | 分析器严格校验 | 重复/缺失/非法行/全 ERROR 非零退出 | 通过：重复 ID exit=2；全 ERROR exit=2 且只出 `diagnostics.json` | `TestAnalyzerValidation`（7 项） |
| 3 | | 探索性单条报告 | 通过：单条 hold → exit=0，标注"计划完整性未验证" | 同上 |
| 4 | 资产路径解析 | 跨 cwd 一致 / 复制资产 / 空格路径 / 缺件报路径 | 通过：`collision_sha` 与 `path_mode` 一致；空格目录可加载 | `TestAssetResolution`（6 项） |
| 5 | 来源证据 | 非平地 trial 均有非空 `collision_sha` | 通过：2520/2520，非平地缺 sha = 0 | `runs/canonical_r2/results.jsonl` |
| 5 | | 改引用文件 → 身份变化并拒绝；残留文件不影响 | 通过：追加 1 字节 → sha 变、replay exit=2；加 stray.stl → sha 不变 | `test_*_identity`，实机 replay 验证 |
| 5 | | 源码/模型身份可还原、无未记录修改 | 通过：`git_dirty=false`、模型 `dirty=false` | `runs/canonical_r2/environment.json` |
| 6 | 安装流程 | 未激活 venv 的 shell 按文档命令可跑 | 通过：`setup.sh` 全流程 exit=0；`.venv/bin/python scripts/demo.py --suite smoke` 成功 | 实机 |
| 6 | | 固定提交失败 → 非零退出 | 通过：伪造 commit → exit=1，未输出"安装完成" | 实机 |
| 6 | | vendor 有修改 → 安全拒绝 | 通过：植入文件 → exit=1 并保留现场 | 实机 |

## 过程记录（两次作废的运行，均未覆盖旧证据）

1. `runs/canonical_r2`（第一次）：因运行目录自身成为未跟踪文件，`git_dirty` 被污染为
   `true`，整批作废并删除。
2. `runs/canonical_r2`（第二次）：`git_dirty` 仍为 true，原因是上一步的作废目录留在
   工作区；清理后重跑。
3. 最终批次：工作区干净、`git_dirty=false`、`source_sha=05fd8807…`、commit `cb018a0`。

旧批次 `runs/canonical/`（`39e3d94`）原样保留，校验和在
`runs/_archive_canonical_39e3d94/SHA256SUMS`。

## 新测试

`tests/test_credibility.py`（8 项，第一轮）+ `tests/test_round2.py`（27 项）
= **35 项，全部通过**（约 20 秒）。

---

## 第三轮补充（2026-10-26）：训练器修复

基线 `e57d281` 的 `scripts/ppo.py` 有两处实现错误，已在 `fix/ppo` 分支修复并做数值验证：

1. `_adam` 调用在参数循环外 → 每个 minibatch 只更新 `bv1`，actor 从未被优化。
2. `act` 用未裁剪采样算 logp、返回裁剪后动作 → 未更新时 `ratio=1.015`。

验证：`scripts/check_ppo.py`（中心差分误差 ~1e-10）、`tests/test_trainer.py`（10 项）。
旧 150k 步与旧 checkpoint 保留在 `runs/train_P_150k`、`runs/train_G_40k` 等目录，
标注为"actor 未更新、动作概率不一致，不能用于判断 PPO 学习能力或 P/G 收益"。
结论见 [`TRAINER_REPORT.md`](TRAINER_REPORT.md)。
