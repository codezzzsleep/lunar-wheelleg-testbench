"""
批量资产入库：每个原始 GLB 在 4 个高度上各生成一份处理后资产。

为什么要多高度：考场按"相对高度"分层，Lux3D 组和程序化组必须在同一层里可比，
所以同一个物体要能以不同尺寸出现。旋转/缩放的同源版本算同一个形状家族。
"""
import json, pathlib, sys
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

sys.path.insert(0, str(pathlib.Path(__file__).parent))
# 只归一化一个轴：侧向宽度。0.30 m 与程序化方块完全一致（rel_width 0.79）。
# 高度不再预设，而是量出来——形状的真实长宽比必须保留，否则就不叫"形状细节"了。
TARGET_WIDTH = 0.30


def job(args):
    glb, w = args
    from process_asset import process
    stem = pathlib.Path(glb).stem
    out = pathlib.Path('assets/processed') / f'{stem}_w{int(round(w*1000)):03d}'
    # 可重入：已经处理过就跳过，重跑只补缺的（上一轮进程中途被杀过）
    if (out / 'manifest.json').exists():
        return f'SKIP {out.name}'
    try:
        man = process(glb, None, out, target_width=w)
        man['source_kind'] = 'lux3d'
        man['asset_id'] = stem
        man['family'] = stem          # 同一 GLB 的所有尺寸属于同一形状家族
        (out / 'manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
        return f'OK   {out.name}  rel_h={man["rel_height"]:.2f} rel_w={man["rel_width"]:.2f} parts={man["coacd_parts"]} conc={man["concavity"]}'
    except Exception as e:
        return f'FAIL {stem}: {repr(e)[:120]}'


if __name__ == '__main__':
    raws = sorted(pathlib.Path('assets/raw').glob('*.glb'))
    tasks = [(str(g), TARGET_WIDTH) for g in raws]
    print(f'{len(raws)} raw glb, width-normalised to {TARGET_WIDTH} m = {len(tasks)} assets')
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('fork')) as ex:
        for msg in ex.map(job, tasks):
            print(msg, flush=True)
