"""把一次路线运行里机器人拍到的每一张照片、送进 Lux3D 的每一张输入图拼成一张联系表，供人工逐张检查。

    python3 scripts/v7/v7_contact.py runs/v7/route_full docs/v7/contact_full.png
"""
import json
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

run, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
try:
    F = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 22, index=2)
except Exception:
    F = ImageFont.load_default()
rows = []
for look in sorted(run.glob('E*/look*')):
    st = json.loads((look / 'state.json').read_text())
    tiles = [(Image.open(look / 'rgb.png').convert('RGB').resize((480, 360)), f'{look.parent.name}/{look.name} rgb'),
             (Image.open(look / 'mask.png').convert('RGB').resize((480, 360)), f'mask {json.loads((look / "observation.json").read_text())["mask_px"]} px')]
    for k in sorted(st['crops']):
        tiles.append((Image.open(look / 'gen' / 'variants' / f'{k}.png').convert('RGB').resize((360, 360)), k))
    vis = st['visible']
    rows.append((tiles, f'x_front {vis["x_front"]:.3f}  W {vis["W_vis"]:.3f}  H {vis["H_vis"]:.3f}  native {st["crop_native_px"]} px'))
W = max(sum(t[0].width + 10 for t in r[0]) for r in rows) + 10 if rows else 400
Hh = sum(420 for _ in rows) + 10
sheet = Image.new('RGB', (W, max(Hh, 100)), (255, 255, 255)); d = ImageDraw.Draw(sheet)
y = 10
for tiles, info in rows:
    x = 10
    for im, lab in tiles:
        sheet.paste(im, (x, y + 30)); d.text((x, y), lab, font=F, fill=(20, 20, 20)); x += im.width + 10
    d.text((10, y + 392), info, font=F, fill=(60, 60, 60)); y += 420
out.parent.mkdir(parents=True, exist_ok=True); sheet.save(out); print(out)
