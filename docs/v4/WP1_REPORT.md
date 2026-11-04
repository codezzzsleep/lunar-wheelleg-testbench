# WP1 回归测试报告

- 基线：`a00fce37b`
- 命令：`python3 scripts/v4_regress.py`
- 结果文件：`runs/v4/regress/20261105T025035.json`
- 结论：**T1–T6 全部通过**

| 项 | 结果 | 关键数值 |
| --- | --- | --- |
| T1 真值当先验 | pass | 隐藏区 IoU=1.0，diff 出 U=0 |
| T2 配准已知答案 | pass | IoU 0.9609，深度 P95 19.874 mm |
| T3 统一终点 | pass | len_short：D2 success 7.28 s（末帧 7.28）；BODY success 116.86 s（末帧 116.86） |
| T4 步数上限 | pass | 10 步截断，reason=None，不记 fail |
| T5 预演/执行一致 | pass | 前 50 步 qpos 最大差 3.7e-9 |
| T6 记录完整 | pass | 50 Hz（dt=0.02），qpos/qvel/动作/关节目标/接触 sidecar/下陷/滑移齐全 |

代码改动：`v3_record.py` 增加轮下陷与滑移率字段（平地近似，缺失写 None 并登记）；
`v4_regress.py` 为唯一入口。回归文件仅写 `runs/v4/regress/`，未改冻结产物。
