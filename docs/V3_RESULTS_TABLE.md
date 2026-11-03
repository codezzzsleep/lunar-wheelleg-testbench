# v3 主结果（真实扫描岩石 · FULL vs OBS_ONLY）

## 1 筛选漏斗

| 项 | 值 |
| --- | --- |
| n_pool_rocks | 8 |
| n_states_captured | 48 |
| n_screened | 48 |
| n_complete_feasible | 44 |
| n_hidden_sensitive | 23 |
| n_selected | 22 |
| 分层（动作不同/结局不同） | {'action_only': 18, 'none': 25, 'action_and_outcome': 5} |

## 2 三结局（FULL vs OBS_ONLY，同一 S0）

- 执行状态数：13
- FULL：{'pass': 11, 'safe_stop': 1, 'physical_failure': 1}
- OBS_ONLY：{'pass': 10, 'safe_stop': 1, 'physical_failure': 2}
- 结局相同：12；FULL 更好：1；OBS_ONLY 更好：0
- 风险低估：0；过度保守：0

## 3 逐状态

| 状态 | H(m) | 真值选择 | OBS 选择 | FULL 执行 | OBS 执行 |
| --- | --- | --- | --- | --- | --- |
| moon_rock_01_h0v0 | 0.120 | R1 | D1 | pass | pass |
| moon_rock_01_h0v1 | 0.120 | R1 | D1 | pass | pass |
| moon_rock_01_h2v0 | 0.224 | L2 | A0 | safe_stop | safe_stop |
| moon_rock_02_h0v1 | 0.120 | R1 | D1 | pass | pass |
| moon_rock_02_h2v0 | 0.224 | R1 | L2 | pass | pass |
| moon_rock_02_h2v1 | 0.224 | L2 | D1 | pass | pass |
| moon_rock_03_h1v0 | 0.172 | R1 | L2 | pass | pass |
| moon_rock_03_h2v1 | 0.224 | D1 | R1 | pass | pass |
| moon_rock_04_h0v1 | 0.120 | D2 | L2 | pass | pass |
| moon_rock_04_h1v0 | 0.172 | R2 | L2 | pass | physical_failure |
| moon_rock_05_h1v0 | 0.172 | R1 | D1 | pass | pass |
| moon_rock_05_h1v1 | 0.172 | D1 | L2 | physical_failure | physical_failure |
| moon_rock_05_h2v0 | 0.224 | D1 | R1 | pass | pass |

## 4 隐藏区误差（候选分布，不是单个最好案例）

- 候选-状态行数：6
- A_iou: {'n': 6, 'mean': 0.0107, 'median': 0.0106, 'min': 0.0086, 'max': 0.0132}
- A_missing: {'n': 6, 'mean': 0.9892, 'median': 0.9893, 'min': 0.9867, 'max': 0.9913}
- A_overfill: {'n': 6, 'mean': 0.5521, 'median': 0.5624, 'min': 0.4359, 'max': 0.6167}
- B_mae: {'n': 6, 'mean': 36.3008, 'median': 35.732, 'min': 33.044, 'max': 40.073}
- B_p95: {'n': 6, 'mean': 217.0, 'median': 215.8, 'min': 198.6, 'max': 236.6}
- C_rear_abs: {'n': 6, 'mean': 48.0, 'median': 46.0, 'min': 46.0, 'max': 56.0}
- C_drop_abs: {'n': 6, 'mean': 3.3333, 'median': 4.0, 'min': 2.0, 'max': 4.0}
