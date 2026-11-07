# V8 沙箱作业记录

| 沙箱 id | 开始 | 结束 | 命令 | 拉回目录 | 文件数/总字节 | sha 校验 | 推送提交号 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:26+08:00 | 2026-11-08T03:28+08:00 | `v8_run.py --policy conservative --max-looks 5` | `runs/v8/main/` | 26 文件 / 57 MB | 逐文件一致 | 待提交 |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:30+08:00 | 2026-11-08T03:31+08:00 | `v8_run.py --policy optimistic` | `runs/v8/main/` | 68 MB | 逐文件一致 | 待提交 |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:46+08:00 | 2026-11-08T03:47+08:00 | `v8_run.py --policy conservative --see-dark --max-looks 5 --tag conservative_seedark` | `runs/v8/main/` | 逐文件一致 | 待提交 |
| cnb-0fp-1k6rn0am3-001 | 2026-11-08T03:50+08:00 | 2026-11-08T03:51+08:00 | `v8_run.py --policy imagination --imagine truth --tag imagination_truth` | `runs/v8/main/` | 逐文件一致 | 待提交 |
