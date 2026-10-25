# 已归档脚本

这些脚本已被取代，保留仅供追溯，**不要在新流程里使用**。

| 文件 | 取代者 | 说明 |
| --- | --- | --- |
| `batch.py` | `scripts/demo.py` | 旧批跑：默认写死 `runs/batch.jsonl`，分组键缺 controller 与 shape |
| `report.py` | `scripts/analyze.py` | 早期出图脚本，结论写死在代码里 |
| `render_exam.py` | `scripts/replay.py` | 旧渲染：自带一套近似控制循环，与考试不同源 |
| `probe_go2w.py` | — | 早期一次性探针（读模型自由度与执行器） |

`scripts/drive_test.py` **没有归档**：它的 `ids()` 与站姿常量仍被 `exam.py` 使用，
属于当前代码路径。
