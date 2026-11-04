# WP0 数据可取回报告

- 基线：`a00fce37b`
- Release：https://github.com/codezzzsleep/lunar-wheelleg-testbench/releases/tag/v4-data
- 清单：`dist/v4/glb_manifest.json`（172 项：86 GLB + 86 results.zip，共 5,544,326,480 字节）
- 覆盖：v3 全部候选 75×2、stage007 6 GLB、stage013 输入批次 5×2、gen_v2/P58_S2 6 results.zip

## 验收

- 全量核对：逐个比较 GitHub Release asset 的 `digest` 与清单 `sha256`，**172/172 一致**；
  文件大小全部一致；`dist/v4/verify.json`。
- 抽样下载覆盖四类来源：v3、stage007、stage013_input、gen_v2，下载后 sha256 均一致。
- 新目录 clone（稀疏、仅清单）：`git clone --filter=blob:none --no-checkout --depth 1`，
  sparse-checkout `dist/v4`，读取清单后再全量核验 Release。
- 未使用 Git LFS（环境无 git-lfs）；采用 Release 附件方案，符合 SPEC 的“或 Release 附件”。

## 说明

- stage007 只有 GLB（原始 results.zip 未落盘），清单如实标 `kind=glb`。
- P58_S2 的 6 个 results.zip 由 Lux3D 任务号重新取回，sha 与 tasks.json 原记录一致。
- 所有资产保持原始字节；未重新编码、未放大。
