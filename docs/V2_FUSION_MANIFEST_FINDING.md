# 融合清单揭示：A1 的生成隐藏部分被 100% 清除

## 先修一个环境缺陷

沙箱缺 `networkx`，`fuse_observed.py` 在 `trimesh.fix_winding` 处崩溃，**但 `occ.npz` 已经写出**，
所以之前所有"配准后单/多候选"的运行用的都是**未经修复与验收的占据**，且从未生成 `fused/manifest.json`。
已安装 `networkx 3.7`，重跑融合才拿到清单。

## A1 的融合清单（P06·S1，H5_F）

| 字段 | 值 |
| --- | --- |
| `strict.pass` | **False** |
| `metrics.mask_iou` | 0.224 |
| `metrics.vis_pt_p95_mm` | 47.6 |
| `metrics.freespace_violation` | 0.632 |
| `retention.kept_voxels` | **0** |
| `retention.kept_ratio` | **0.0** |
| `retention.removed_ratio` | 1.0 |
| `no_generated_hidden_contribution` | **True** |

## 这意味着什么

1. **融合把候选的隐藏部分全部丢弃**（kept 0），只保留观测约束下的壳层与凹包；
2. 因此"配准后单候选 L2 通行、多候选 D2 通行"**不能归功于生成先验**——
   预演用的几何并不是 Lux3D 补出的那一面；
3. 六个候选在融合后可能退化成几乎相同的几何（都由观测 + 壳层决定），
   这解释了为什么多候选的安全集交集非空但差别不大；
4. 之前的"候选分歧是实质性的"结论需要复核：那批预演用的是**未修复占据**，不能作为分歧证据。

## 口径纠正

- 不再用"决策分歧"论证放宽阈值；
- 先按融合清单判定哪些候选进入正式集合：`strict.pass` 为 False 的候选，
  其预演结果只能作为诊断，不能作为"生成方法有效"的证据。

## 下一步

1. 对六个候选全部重跑融合（networkx 已装），提交六份 `fused/manifest.json`；
2. 按 `strict.pass`、`retention.kept_ratio`、`no_generated_hidden_contribution` 分类；
3. 若六个都 `kept_ratio≈0`，则本批 Lux3D 的隐藏面贡献为零，需要如实写成负结果，
   并把主表结论限定为"观测约束 + 壳层"的效果。
