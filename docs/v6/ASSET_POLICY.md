# V6 资产保存规则（修正）

- **本地优先**：所有生成物（GLB、输入图、渲染图、轨迹、场景资产）先落本机 `assets/v6/` 或 `runs/v6/`，
  再同步到沙箱；沙箱只做计算，不作为唯一存储。
- **立即上传**：本地落盘后立刻上传 Release `v6-showcase`，并在 `dist/v6/` 清单登记 sha256。
- **沙箱用后即弃**：不在沙箱保留唯一副本；任何只在沙箱存在的文件都视为可丢失。
- **失败教训**：M0 的 159 个 Lux3D 任务、WP3 crops、逐动作预演记录都只存在于旧沙箱，回收后无法恢复。

## 当前本地资产

- `assets/v6/lux3d/`：80 份 GLB（`model.glb` + `meta.json`），619 MB；清单 `dist/v6/local_lux3d_store.json`。
- `assets/v6/assets_v3_rocks.tar.gz`：v3 岩石网格/贴图（如已转存）。
- Release `v6-showcase`：`v6__lux3d__<identity>.glb`、`v6__assets__v3_rocks.tar.gz`、`v6__wp7__scenes.tar.gz`。
