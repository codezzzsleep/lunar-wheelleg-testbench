# 账本迁移说明（2026-10-28）

- 原件：`ledger_v1_original.jsonl`（未改动）
- 新格式：`ledger.jsonl`，增加 `attempt_id`（单次尝试唯一键）与 `run_scope`
- 历史两条任务 identity 相同（同一输入图），但 task_id 不同（4416952 / 4418107），
  各自保留一条记录、各自占用 20 积分上界：**两条都计入本轮 300/15 的额度**。
- 这两条来自滚转相机的旧输入，`usable_for_current_observation=false`，
  只作诊断，不进入正式 H5。
- 旧的文生 78 积分不属于本轮 scope，不在此账本内。
