# 证据索引（自动生成）

> 本文件由 `scripts/v3_evidence_index.py` 生成，**只覆盖 v3 批次**（`runs/v3/*`）。v4–v8 的证据与结论矩阵见 `docs/DELIVERY.md`；本文件不要当全项目证据索引引用。

| run | schema | 结果 | 关键指标 |
| --- | --- | --- | --- |
| `runs/v3/basic_cycle/nominal_FL_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/nominal_RL_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/nominal_RR_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/nominal_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/nominal_seed0_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/nominal_seed1_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/nominal_seed2_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/basic_cycle/rigid_r1` | v3-basic-cycle/v1 | 通过 / passed |  |
| `runs/v3/climb/front12_rigid_r1` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=13, ok_phases=13 |
| `runs/v3/climb/front18_rigid_r1` | v3-climb-front2/v2 | 失败 | blocked_at=FR_lift, phases=4, ok_phases=3 |
| `runs/v3/climb/front2_nominal_r1` | v3-climb-front2/v1 | 通过 / passed | phases=13, ok_phases=13 |
| `runs/v3/climb/front2_nominal_r2` | v3-climb-front2/v1 | 通过 / passed | phases=13, ok_phases=13 |
| `runs/v3/climb/front2_rigid_r1` | v3-climb-front2/v1 | 通过 / passed | phases=13, ok_phases=13 |
| `runs/v3/climb/front3_nominal_r1` | v3-climb-front2/v2 | 通过 / passed | blocked_at=None, phases=13, ok_phases=13 |
| `runs/v3/climb/front3_nominal_r2` | v3-climb-front2/v2 | 通过 / passed | blocked_at=None, phases=13, ok_phases=13 |
| `runs/v3/climb/front3_rigid_r1` | v3-climb-front2/v2 | 通过 / passed | blocked_at=None, phases=13, ok_phases=13 |
| `runs/v3/climb/front_nominal_r1` | v3-climb-front/v1 | 通过 / passed | phases=7, ok_phases=7 |
| `runs/v3/climb/front_nominal_r2` | v3-climb-front/v1 | 通过 / passed | phases=7, ok_phases=7 |
| `runs/v3/climb/front_rigid_r1` | v3-climb-front/v1 | 通过 / passed | phases=7, ok_phases=7 |
| `runs/v3/climb/rear_attempt_r1` | v3-climb-front2/v1 | 失败 / partial | phases=21, ok_phases=16 |
| `runs/v3/climb/rear_attempt_r2` | v3-climb-front2/v1 | 失败 / partial | phases=22, ok_phases=18 |
| `runs/v3/climb/rear_center_partial_r1` | v3-climb-front2/v2 | 失败 | blocked_at=RL_shift, phases=20, ok_phases=19 |
| `runs/v3/climb/rear_easy3_partial_r1` | v3-climb-front2/v2 | 失败 | blocked_at=RL_shift, phases=19, ok_phases=18 |
| `runs/v3/climb/rear_gated_r1` | v3-climb-front2/v2 | 失败 / partial | blocked_at=RR_shift, phases=16, ok_phases=15 |
| `runs/v3/climb/rear_loop_partial_r1` | v3-climb-front2/v2 | 失败 | blocked_at=RR_hold, phases=20, ok_phases=19 |
| `runs/v3/climb/rear_partial_r1` | v3-climb-front2/v2 | 失败 / partial | blocked_at=RL_shift, phases=19, ok_phases=18 |
| `runs/v3/climb/rear_wheelassist_partial_r1` | v3-climb-front2/v2 | 失败 | blocked_at=hold_all, phases=23, ok_phases=22 |
| `runs/v3/control/legtest` | v3-v1-legtest/v1 | 失败 | phases=4, ok_phases=0 |
| `runs/v3/rock_actions/contact_04_h2v0_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=1, unified_actions=1 |
| `runs/v3/rock_actions/contact_04_h2v1_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=0, unified_actions=0 |
| `runs/v3/rock_actions/leg2_04_h2v1` | v3-rock-actions/v2 | — | actions=2, ok_actions=0, unified_actions=0 |
| `runs/v3/rock_actions/leg_04_h2v0` | v3-rock-actions/v1 | — | actions=3, ok_actions=1, unified_actions=0 |
| `runs/v3/rock_actions/moon_rock_01_h2v0` | v3-rock-actions/v1 | — | actions=4, ok_actions=2, unified_actions=0 |
| `runs/v3/rock_actions/moon_rock_02_h0v0` | v3-rock-actions/v1 | — | actions=5, ok_actions=4, unified_actions=0 |
| `runs/v3/rock_actions/moon_rock_03_h0v0` | v3-rock-actions/v1 | — | actions=5, ok_actions=4, unified_actions=0 |
| `runs/v3/rock_actions/moon_rock_04_h1v0` | v3-rock-actions/v1 | — | actions=7, ok_actions=1, unified_actions=0 |
| `runs/v3/rock_actions/moon_rock_04_h2v0` | v3-rock-actions/v1 | — | actions=4, ok_actions=0, unified_actions=0 |
| `runs/v3/rock_actions/moon_rock_05_h1v0` | v3-rock-actions/v1 | — | actions=7, ok_actions=6, unified_actions=0 |
| `runs/v3/rock_actions/pp_-0.02_0.01_-1.5_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=0, unified_actions=0 |
| `runs/v3/rock_actions/pp_0.02_0_0_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=1, unified_actions=1 |
| `runs/v3/rock_actions/pp_0_0.02_1.5_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=1, unified_actions=1 |
| `runs/v3/rock_actions/unified_04_h2v0_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=1, unified_actions=1 |
| `runs/v3/rock_actions/unified_04_h2v0_wheel` | v3-rock-actions/v2 | — | actions=5, ok_actions=0, unified_actions=0 |
| `runs/v3/rock_actions/unified_04_h2v1` | v3-rock-actions/v2 | — | actions=5, ok_actions=0, unified_actions=0 |
| `runs/v3/rock_actions/unified_moon_rock_06_h2v0` | v3-rock-actions/v2 | — | actions=5, ok_actions=4, unified_actions=4 |
| `runs/v3/rock_actions/unified_moon_rock_07_h2v0` | v3-rock-actions/v2 | — | actions=5, ok_actions=5, unified_actions=5 |
| `runs/v3/rock_actions/z_moon_rock_04_h2v0_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=1, unified_actions=1 |
| `runs/v3/rock_actions/z_moon_rock_04_h2v1_s1` | v3-rock-actions/v2 | — | actions=1, ok_actions=0, unified_actions=0 |
| `runs/v3/route/nominal_r1` | v3-route/v1 | 通过 | final_x=23.5375, tilt_max_deg=8.286 |
| `runs/v3/route/rigid_r1` | v3-route/v1 | 失败 | final_x=12.7655, tilt_max_deg=60.502 |
| `runs/v3/route/rigid_r2` | v3-route/v1 | 通过 | final_x=23.5482, tilt_max_deg=8.912 |
| `runs/v3/route/rigid_s035` | v3-route/v1 | 失败 | final_x=23.5649, tilt_max_deg=10.518 |
| `runs/v3/stage003/fix_leg_state1` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/fix_leg_state2` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/fix_leg_state3` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/fix_s5_wheel` | v3-wheel-compare/v1 | — | actions=6, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/fix_s5_wheel2` | v3-wheel-compare/v1 | — | actions=6, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s1_rigid` | v3-endgame-diag/v1 | — |  |
| `runs/v3/stage003/s2_descent` | v3-descent/v1 | — | final_x=2.5182 |
| `runs/v3/stage003/s2_full_nominal_r1` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/s2_full_rigid_r1` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/s2_stable` | v3-stable-window/v1 | — | actions=50, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s2a_r1` | v3-endgame-recover/v1 | — | actions=125, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s2a_r2` | v3-endgame-recover/v1 | — | actions=200, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s2a_r3` | v3-endgame-recover/v1 | — | actions=125, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s2a_r4` | v3-endgame-recover/v1 | — | actions=75, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s2a_r5` | v3-endgame-recover/v1 | — | actions=75, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s2a_r6` | v3-endgame-recover/v1 | — | actions=75, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s4_state1` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/s4_state1f` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/s4_state2` | v3-climb-front2/v2 | 失败 | blocked_at=body_down, phases=23, ok_phases=22 |
| `runs/v3/stage003/s4_state2b` | v3-climb-front2/v2 | 失败 | blocked_at=descent, phases=26, ok_phases=25 |
| `runs/v3/stage003/s4_state2c` | v3-climb-front2/v2 | 失败 | blocked_at=descent, phases=26, ok_phases=25 |
| `runs/v3/stage003/s4_state2d` | v3-climb-front2/v2 | 失败 | blocked_at=descent, phases=26, ok_phases=25 |
| `runs/v3/stage003/s4_state2e` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/s4_state3` | v3-climb-front2/v2 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage003/s5_wheel` | v3-wheel-compare/v1 | — | actions=6, ok_actions=0, unified_actions=0 |
| `runs/v3/stage003/s5_wheel_rigid` | v3-wheel-compare/v1 | — | actions=6, ok_actions=0, unified_actions=0 |
| `runs/v3/stage004/dev_regression1` | v3-climb-front2/v3 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage004/e2e_04_h1v0_v2` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_04_p1` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_04_p2` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_04_p2_fix` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_04_p3` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_04_p3_fix` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_moon_rock_01_h2v0` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/e2e_moon_rock_05_h1v1` | stage4-full-obs/v1 | — |  |
| `runs/v3/stage004/g1_dev5` | stage4-g1/v1 | — |  |
| `runs/v3/stage004/g1b_climb_only` | stage4-g1/v1 | — |  |
| `runs/v3/stage004/geom_h04_1` | v3-climb-front2/v3 | 通过 | blocked_at=None, phases=26, ok_phases=26 |
| `runs/v3/stage004/geom_shift1` | v3-climb-front2/v3 | 失败 | blocked_at=descent, phases=26, ok_phases=25 |
| `runs/v3/stage004/geom_shift_pos1` | v3-climb-front2/v3 | 失败 | blocked_at=descent, phases=26, ok_phases=25 |
| `runs/v3/stage004/geom_unknown_far1` | v3-climb-front2/v3 | 失败 | blocked_at=descent, phases=26, ok_phases=25 |
| `runs/v3/stage004/truth_moon_rock_01_h2v0` | stage4-truth-arm/v1 | — |  |
| `runs/v3/stage004/truth_moon_rock_04_h1v0` | stage4-truth-arm/v1 | — |  |
| `runs/v3/stage004/truth_moon_rock_05_h1v1` | stage4-truth-arm/v1 | — |  |
| `runs/v3/stage005/comp_main` | stage5-composite-check/v1 | — |  |
| `runs/v3/stage005/comp_main2` | stage5-composite-check/v1 | — |  |
| `runs/v3/stage005/comp_main4` | stage5-composite-check/v1 | — |  |
| `runs/v3/stage005/comp_main5` | stage5-composite-check/v1 | — |  |
| `runs/v3/stage005/diag2` | None | — |  |
| `runs/v3/stage005/smoke` | stage5-smoke/v1 | — |  |
| `runs/v3/stage005/smoke6` | stage5-smoke/v1 | — |  |
| `runs/v3/stage006/calib` | stage6-calib/v1 | — |  |
| `runs/v3/stage006/fix` | stage6-fix/v1 | — |  |
| `runs/v3/stage006/matrix2` | stage6-matrix/v1 | — | actions=8, ok_actions=3, unified_actions=0 |
| `runs/v3/stage006/matrix_030_obs` | stage6-matrix/v1 | — | actions=8, ok_actions=3, unified_actions=0 |
| `runs/v3/stage006/matrix_032` | stage6-matrix/v1 | — | actions=8, ok_actions=0, unified_actions=0 |
| `runs/v3/stage006/rock5` | stage6-rock/v1 | — |  |
| `runs/v3/stage007/layout2` | stage7-layout/v1 | — | actions=8, ok_actions=1, unified_actions=0 |
| `runs/v3/stage008/case_4632564_full` | stage8-case/v1 | — | actions=8, ok_actions=1, unified_actions=0 |
| `runs/v3/stage008/case_4632564_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632564_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632603_full` | stage8-case/v1 | — | actions=8, ok_actions=1, unified_actions=0 |
| `runs/v3/stage008/case_4632603_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632603_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632618_full` | stage8-case/v1 | — | actions=8, ok_actions=1, unified_actions=0 |
| `runs/v3/stage008/case_4632618_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632618_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632621_full` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632621_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632621_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632624_full` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632624_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632624_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632627_full` | stage8-case/v1 | — | actions=8, ok_actions=1, unified_actions=0 |
| `runs/v3/stage008/case_4632627_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_4632627_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_ref_full` | stage8-case/v1 | — | actions=8, ok_actions=1, unified_actions=0 |
| `runs/v3/stage008/case_ref_obs` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/case_ref_obs_truth` | stage8-case/v1 | — | actions=8, ok_actions=2, unified_actions=0 |
| `runs/v3/stage008/formal_v2` | stage8-formal-v2/v1 | — |  |
| `runs/v3/stage008/ref_repro` | stage6-fix/v1 | — |  |
| `runs/v3/wheel_probe/full_h0.05_v0.30` | v3-wheel-probe/v2 | 通过 / passed | final_x=2.8453, tilt_max_deg=0.31 |
| `runs/v3/wheel_probe/full_h0.12_v0.30` | v3-wheel-probe/v2 | 失败 / failed | final_x=0.6984, tilt_max_deg=60.388 |
| `runs/v3/wheel_probe/h0.12_v0.30` | v3-wheel-probe/v1 | 通过 | final_x=1.55, tilt_max_deg=19.69 |
| `runs/v3/wheel_probe/h0.12_v0.50` | v3-wheel-probe/v1 | 通过 | final_x=1.5505, tilt_max_deg=21.361 |
| `runs/v3/wheel_probe/h0.18_v0.30` | v3-wheel-probe/v1 | 失败 | final_x=0.8373, tilt_max_deg=60.042 |
| `runs/v3/wheel_probe/h0.18_v0.50` | v3-wheel-probe/v1 | 失败 | final_x=0.7904, tilt_max_deg=60.079 |
| `runs/v3/wheel_probe/h0.24_v0.30` | v3-wheel-probe/v1 | 失败 | final_x=0.7056, tilt_max_deg=60.03 |
| `runs/v3/wheel_probe/h0.24_v0.50` | v3-wheel-probe/v1 | 失败 | final_x=0.6978, tilt_max_deg=60.076 |
| `runs/v3/wheel_probe/rigid_v0.10` | v3-wheel-probe/v1 | 失败 / failed | final_x=0.754, tilt_max_deg=7.26 |
| `runs/v3/wheel_probe/rigid_v0.30` | v3-wheel-probe/v1 | 通过 / passed | final_x=1.5516, tilt_max_deg=11.414 |
