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
