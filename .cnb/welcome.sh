#!/bin/sh
cd /workspace/lunar-lab 2>/dev/null || exit 0
echo "lunar-lab sandbox"
echo "  repo:   $(git rev-parse --short HEAD 2>/dev/null)"
echo "  python: $(.venv/bin/python -V 2>/dev/null || python3 -V)"
echo "  入口:   .venv/bin/python scripts/run_r1.py --audit"
echo "  验收:   .venv/bin/python scripts/verify_delivery_r1.py"
echo "  页面:   runs/unseen/delivery_v7/v7_20261030_r1/media/report/index.html"
