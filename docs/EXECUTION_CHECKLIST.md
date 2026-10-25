# 执行清单（2026-10-26）

审查基线：`e85813806912bf637b5ebdfc0a5e0f8ad9b1b509`
工作分支：`fix/credibility`

## 一、盘点结论

| 项 | 实际状态 |
| --- | --- |
| 原始生成资产 | **7 个 GLB 真实存在**于 `assets/raw/`（boulder / cargo_crate / lander_leg / flat_slab / fallen_panel / crate_lid / debris_plate） |
| 处理后资产 | 29 个目录，均带 `manifest.json` 与 CoACD 拆出的 `parts/*.stl` |
| 程序化资产 | 22 个（box 14 / cylinder 4 / ramp 4），**box 宽 0.30 m，ramp 宽 0.34 m** |
| 机器人模型 | `vendor/unitree_mujoco`（411 MB，未入库），go2w 16 执行器 |
| 历史实验记录 | 本机 `runs/` 有 `batch_all.jsonl`（1390 条）与两份旧归档；**`runs/` 被 .gitignore 排除，仓库内无任何原始记录** |
| 旧报告 | `docs/REPORT.md` 的数字来自本机 runs，**无法在仓库内复核** |

> **旧评估流程，待复核。** 上一轮所有百分比（5%→24%、86%、1135 次有效接触等）
> 均由被忽略的本机 `runs/` 生成，仓库内无法追溯。本轮不复刻这些数字，全部重跑。

## 二、六项确认缺陷与状态

| # | 缺陷 | 状态 |
| --- | --- | --- |
| 1 | `analyze.agg_pairs` 按 (controller, source, rel_h, stance) 分组，**不区分 shape**；方块/圆柱/斜坡合并成"程序化方块" | 待修 |
| 2 | `batch.summarize` 按 (source, layer, stance) 分组，**不含 controller** | 待修 |
| 3 | `gate1.py` 忽略子进程返回码、读固定路径旧 JSON、硬写 `PYTHONPATH=/tmp/robolib` | 待修 |
| 4 | `analyze.py` 结论段把"5%→24%""0.12 m""0 次抬腿"写死在代码里 | 待修 |
| 5 | `batch` 默认写 `runs/batch.jsonl`，`analyze` 默认 glob `runs/batch_*.jsonl` | 待修 |
| 6 | `analyze.py` 字体硬编码 `/tmp/sysroot/...` | 待修 |

## 三、验收方式

| 缺陷 | 验收 |
| --- | --- |
| 1 | 同高度构造 方块失败 / 圆柱成功 / 斜坡成功 三条记录 → 必须分开输出，方块曲线仍为 0%，不能变 67% |
| 2 | 同场景 hold 失败、step 成功 → 必须输出 0% 与 100%，不能输出 50% |
| 3 | 预置旧成功 JSON + 本次子进程失败 → 必须 FAIL 且退出码非零；空目录首次运行也能留下报告 |
| 4 | 只输入一条 hold 成功记录 → 只能描述这一条，不得出现 step/adapt 的数值 |
| 5 | 放入旧批次文件不应改变本次报告；默认演示后报告只读刚生成的数据 |
| 6 | 在无 `/tmp/sysroot`、`/tmp/robolib` 的环境下仍能生成完整报告 |

## 四、本轮不做

不扩资产、不消耗积分、不租 GPU、不接 Isaac、不训 RL、不做月壤、不建服务端。
