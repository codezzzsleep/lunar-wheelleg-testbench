# v2 交接文档（2026-11-03 02:40，给新会话）

## 0. 一句话状态

融合缺陷已修（`fuse-observed/v3`，提交 `d1f384fe7`），三关键状态的 nominal 结果已出；
20 状态八行主表还差 **P22/P76/P29/P37 的尾段**，正在沙箱 B 上接着跑。
**沙箱 A 可以关闭**；它的关键小结果已复制到本地 `reports/v2/`。

## 0.5 先读评审（很重要）

`docs/REVIEW_2026-11-03.md` 对本批给出了严格判定：**八行主表目前不能作为研究证据**。
新会话必须先读完它，尤其 P0-1..P0-6。与本交接直接相关的结论：

- **5 点表是附录，不是主表**：16/20 状态连真值参考 U_truth 都是 A0；已把
  `reports/v2/appendix_5pt/` 明确标成“附录：5 点退化口径”，不要再叫主表。
- **主比较用 nominal**：同一候选 A1 在 5 点下 A0、在 nominal 下 D2 通行；
  土壤口径必须写在结论旁边。
- **`strict.pass` 测的是观测壳层，不是生成几何**：56 个候选配准 0 通过，
  融合后 47 通过；融合 IoU 与配准 IoU 的相关只有 0.15。主表的 strict 列
  不能当作“Lux3D 生成正确”的证据。
- **真值对照不通过 strict**：truth_parent 的 freespace 0.069 > 0.05；
  阈值硬编码、未按 2.5 mm 重新标定。标定完成前，strict 只能当诊断量。
- **first/multi 组成不一致**：P16·S1 的 first 实际是 B2，multi 只有 2 个候选；
  `fusion_invalid` 被旧聚合器当成“过度保守”。新的 `v2_main_table.py` 已把
  `fusion_invalid` 归为 `pipeline_failure`，并增加 `n_candidates` /
  `first_candidate_id` / `candidate_failures`；旧表需重算。
- **真值对照的“有壳”臂来自未入库代码**（`e5abe66e…`），不能作为受控对比；
  需要用同一个提交重跑。

因此，本批的定位应写成：**融合入口缺陷已修、工具链已收紧；20 状态主表尚未达到
可发表证据标准**。不要用 strict 通过或 5 点表去声称方法优劣。

## 1. 沙箱与依赖

- A：`cnb-ii9-1k6d6hcl1-001.978e12c8-f1ec-4c9a-861b-f4f79713b3f9-8kf@cnb.space`
  —— 可释放。A 上未完成的 P22/P76 融合资产已迁到 B。
- B：`cnb-qho-1k6ejq77c-001.fa1c5fae-c337-45ca-b20a-42aa3dd84a75-sa6@cnb.space`
  —— 正在跑。B 的 `/opt/lunar` 原先缺 `rtree`、`scipy`、`networkx`，已装：
  `rtree 1.4.1`、`scipy 1.18.1`、`networkx 3.7`；`requirements-lock.txt`/`requirements.txt` 已补。
- 新沙箱必须先确认 `python -c "import rtree, scipy, networkx, manifold3d"`，否则
  `fuse_observed` 会在 1 秒内失败并留下 `failed.json`。
- 运行环境：`export PATH=/opt/lunar/bin:$PATH MUJOCO_GL=osmesa`。

## 2. 已完成、可直接引用

### 2.1 融合修复（已定稿）

v2 的 `shell & ~dilate6(parent_inside)` 在壳层与父先验之间挖出 1 体素空隙，再用
`largest_component` 二选一。P06·S1：B1 父先验 3,569 体素被整块删、C1 壳层 4,927
体素被整块删。v3 改为按像素抑制壳层、含父先验组件无条件保留。修复后 A1/B1/C1
`kept_ratio=1.0`、strict 通过（A1 0.9236 / B1 0.9300 / C1 0.9252）。

已知答案：真值网格经 align24 后作父先验，451,068/451,068 保留；壳层与无壳层
freespace 0.0668/0.0666 → 超限来自 2.5 mm 体素化，不是壳层，未放宽阈值。
逐体素见 `reports/v2/voxel_fate.json`。

### 2.2 对照命名与消融

- B3_F = **镜像补全**（`mirror_completion`），不是壳层对照。
- 生成消融 = `fuse_observed --ablate-generated-unknown`：同候选/同 parent/同栅格，
  只删未知区父先验。
- 协议 A1 rev2 已写入 `plans/v2_protocol.json`。

### 2.3 三关键状态（nominal，已出）

| 状态 | first | multi | first 消融 | 说明 |
| --- | --- | --- | --- | --- |
| P06·S1 | D2 通行 | A0 | D2 通行 | 6 候选；multi 因跨候选最坏而放弃 |
| P06·S3 | R2 通行 | A0 | D2 通行 | 6 候选；multi 同样过保守 |
| P58·S2 | D2 通行 | **D2 通行** | 未跑 | 6 候选；唯一 first/multi 都通行的关键状态 |

5 点口径下这三状态 first/multi/消融全部 A0（见 `reports/v2/key_states/`）。

### 2.4 20 状态主表进度

- 5 点 Lux：A 13 个 + B 的 P29/P37 重融中；非 Lux 5 点 20/20（A）。
- nominal Lux：A 13 个（P01×3、P04×3、P06×2、P16×3、P22·S1、P58·S2）；
  B 的 P29/P37、P22·S2/S3、P76×3 待补。
- nominal 非 Lux：B 19/20（缺 P22·S3，资产刚补传）。

## 3. 正在跑（B）

1. 重融 P29·S1/S3、P37·S3（`--force`，rtree/scipy/networkx 已装）；
2. 已接收 A 迁移的 `v3batch/P22_S1/S2/S3`、`P76_S1/S2`（fused/coll/parent/multi.json）；
3. 正在补传 `v3extra/P22/S3`、`v3gen/P22_S3`、`v3gen/P76_S3`；
4. P76·S3 需要 B 用已有候选新融；
5. nominal 非 Lux 已 19/20。

## 4. 新会话接续步骤

```bash
# 1) 确认 B 上没有残留旧任务
ssh B 'pgrep -af "v2_multi|fuse_observed|v2_nonlux"'

# 2) 补完 P22/P76（会复用已迁移的 fused/coll，只补缺失候选）
cd /workspace/lunar-lab
R=runs/unseen/delivery_v7/v7_20261030_r1
for spec in "P22 S1" "P22 S2" "P22 S3" "P76 S1" "P76 S2" "P76 S3"; do
  set -- $spec; ROCK=$1; ST=$2
  OBS=$R/v3extra/$ROCK/$ST/obs; [ -d "$OBS" ] || OBS=$R/grid/$ROCK/$ROCK/$ST/obs
  CANDS=$R/v3gen/${ROCK}_${ST}
  python3 scripts/v2_multi.py --rock $ROCK --state $ST --obs $OBS \
    --cands $CANDS --out $R/v3batch/${ROCK}_${ST} --soils points \
    --jobs 2 --ablate --ablate-first-only
done

# 3) nominal 规划（复用 v3batch 资产；只对仍是 5 点或缺失的状态）
python3 scripts/v2_nominal_table.py --only multi,nonlux --workers 2

# 4) 把 B 的结果 JSON 拉回本地，与 reports/v2 的 A 结果合并
#    需要合并成一个 root 再跑 v2_main_table；或直接在新会话里按状态覆盖复制。
python3 scripts/v2_main_table.py --states $R/v2_main_states.json \
  --root <merged_root> --out $R/v3table_nominal
```

注意：

- `v2_multi` 只在 fused 资产通过 manifest/content/观测/父网格/代码 SHA 校验时复用；
  失败会写 `prep_error.json`，`failed.json`/`partial.json` 必须删掉或用 `--force` 才会重做。
- `v2_nominal_table.py` 用 `v3batch/<state>/<tag>` 的符号链接复用资产，不重融。
- 合并时**不要**使用 B 上 `v3batch_invalid_B/` 里的 P76 旧结果（全部 `fusion_invalid`）。
- 5 点表已证明退化（16/20 连 U_truth 都 A0），主表用 nominal；5 点只作敏感性。
- 20 状态筛选的 C 扫描用了 `visible={}`，正式规划用真实可见量；P01 等状态真值参考
  在正式口径下为 A0，主表记 `safe_stop_no_reference`，不能算过度保守。

## 5. 文件位置

- 代码：`scripts/fuse_observed.py`（v3）、`scripts/v2_multi.py`、
  `scripts/v2_nonlux_rows.py`、`scripts/v2_nominal_table.py`、
  `scripts/v2_main_table.py`、`scripts/v2_batch20.py`
- 协议：`plans/v2_protocol.json`（A1 rev2）
- 状态清单：`runs/unseen/delivery_v7/v7_20261030_r1/v2_main_states.json`
- 审阅包：`reports/v2/`（`5pt/`、`nominal/`、`key_states/`、`voxel_fate.json`、`README.md`）
- 依赖锁：`requirements-lock.txt`
- 旧结果：`runs/.../v3batch_pre_final/`（不参与主表）

## 6. 已提交 / 待提交

- `d1f384fe7`：融合修复 + 消融 + 5 点规划 + 工具链。
- `e73e84609`：`reports/v2` 首批审阅包。
- 新会话应把 B 的 P22/P76/P29/P37 结果、最终 nominal 表、更新后的
  `CURRENT_STATUS.md` 与本文档一起提交并推送。
