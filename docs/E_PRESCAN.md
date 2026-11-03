# E 预扫：现有 FULL / OBS_ONLY 案例

数据：`runs/v3/states/*/decision/` 中同时有 decision 与 execution 的 14 个状态。

- `both_success` = 12，`full_only` = 0，`obs_only` = 0；
- **两臂选择的动作完全一致（differ_action = 0）**；
- 结论：现有案例里没有“背面影响落点/后坡/绕行”的差异，FULL/OBS_ONLY 退化为同一决策。
  E 需要新的案例或更敏感的决策规则，不能拿这 14 个状态冒充三案例对照。
- 下一步：从这 14 个里先选“轮式更便宜、系统应当用轮”的 1 例（双方 R1/R2 成功），
  再构造/寻找“背面影响”的 1 例与“边界”1 例；没有正例就按 SPEC 如实结束研究尝试。
