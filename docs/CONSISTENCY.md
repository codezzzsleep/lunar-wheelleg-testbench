# 交付一致性检查

> **范围（2026-11-11 标注）**：本检查是 **v3 批次**的一致性口径，不覆盖 v4–v8。全项目当前的边界与证据等级见 `docs/DELIVERY.md`。

| 检查 | 结果 | 实际值 |
| --- | --- | --- |
| route rigid final_x | 通过 | 23.5482 |
| route rigid passed | 通过 | True |
| route nominal final_x | 通过 | 23.5375 |
| route nominal passed | 通过 | True |
| basic_cycle >= 8 runs | 通过 | 8 |
| basic_cycle all_ok | 通过 | 8 |
| climb failure status | 通过 | not_passed |
| e cases n=14 | 通过 | 14 |
| e both_success=12 | 通过 | 12 |
| e full_only=0 | 通过 | 0 |
| e differ_action=1 | 通过 | 1 |
| perturbed S1 n=3 | 通过 | 3 |
| perturbed S1 unified=2 | 通过 | 2 |
| perturbed hashes distinct | 通过 | 3 |
| evidence index present | 通过 | 143 |

总计：15/15 通过。
