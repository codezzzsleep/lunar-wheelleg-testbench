#!/bin/bash
# 14 状态重跑完成后的一步收口：重出唯一源表 + 三份文档 + 回传
set -e
cd /workspace/lunar-lab
/opt/lunar/bin/python scripts/v3_report.py
/opt/lunar/bin/python scripts/v3_docs.py
echo "--- done: runs/v3/report/v3_results.json + docs/*"
