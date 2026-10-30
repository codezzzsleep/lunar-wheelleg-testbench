"""
V7：从**真实第二观测**生成上传图（白底隔离 + 1024 正方裁剪）。

第二张输入必须是机器人实际移动到新位置后拍到的图，不是生成视图，也不是真值背面。
本脚本只做编码：把该观测的 RGB 按同一 mask 置白底、按同一裁剪规则放大到 1024。

  .venv/bin/python scripts/v7_make_second_view_pkg.py \
      --observation runs/unseen/delivery_v6_1/v6_1_20261029/observation/R01_lat30 \
      --out runs/unseen/delivery_v7/v7_20261030/generation/two_view_R01/upload2_1024.png
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from make_upload_package import crop_to_fraction  # 同一裁剪规则


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--observation', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    obs = ROOT / a.observation
    rgb = np.array(Image.open(obs / 'rgb.png').convert('RGB'))
    mask = np.array(Image.open(obs / 'mask.png').convert('L')) > 127
    iso = rgb.copy()
    iso[~mask] = 255
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = crop_to_fraction(iso, mask, out)
    Image.fromarray(iso).save(out.parent / 'isolated_white.png')
    rec = {'schema': 'v7-second-view-upload/v1', 'observation': a.observation,
           'source_rgb_sha': __import__('hashlib').sha256((obs / 'rgb.png').read_bytes()).hexdigest(),
           'n_mask_px': int(mask.sum()), 'crop': meta,
           'note': ('第二视角来自真实相机横向位移渲染（observe.py --cam-lateral），'
                    '不是生成视图；只做白底与同一裁剪编码。'),
           'out_sha': __import__('hashlib').sha256(out.read_bytes()).hexdigest()}
    (out.parent / 'second_view_manifest.json').write_text(
        json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps({k: rec[k] for k in ('n_mask_px', 'out_sha')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
