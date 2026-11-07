"""V8 视觉模型：沿用成片用的 VideoModel，换成南极低太阳、远处平面压到坑底以下、不加车道外的装饰碎石。"""
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v8_scene as S  # noqa: E402



def video_model(env, rock_bodies, holos=(), width=1920, height=1080, ambient=0.012, sun=2.7, off=None):
    import v7_visual as VV
    import vmodel
    orig = VV.visual_xml

    def patched(env_xml, rb, width=1600, height=1200, **kw):
        xml = orig(env_xml, rb, width=width, height=height, sun_dir=tuple(S.sun_dir()), deco=False)
        # 远处平面换成高度场外围的四块平板（高度场内部是月溪，不能被平面盖住）
        far = re.search(r'<geom name="v7_far_ground"[^>]*/>', xml).group(0)
        L, F = S.SPAN, 150.0
        boxes = ''.join(f'<geom name="v8_far{i}" type="box" size="{sx} {sy} 0.01" pos="{px} {py} -0.03" material="v7_reg" contype="0" conaffinity="0"/>'
                        for i, (sx, sy, px, py) in enumerate([((F - L) / 2, F, (F + L) / 2, 0), ((F - L) / 2, F, -(F + L) / 2, 0),
                                                              (L, (F - L) / 2, 0, (F + L) / 2), (L, (F - L) / 2, 0, -(F + L) / 2)]))
        terr = S.terrain_visual_obj(S.LW.CACHE / 'v8_terrain_vis.obj')
        xml = xml.replace(far, boxes + '<geom name="v8_ground" type="mesh" mesh="v8_ground" material="v8_reg" contype="0" conaffinity="0"/>')
        xml = xml.replace('<asset>', f'<asset><mesh name="v8_ground" file="{terr}"/>'
                          '<material name="v8_reg" texture="v7_reg" specular="0" shininess="0"/>', 1)
        xml = xml.replace('ambient="0.035 0.037 0.045"', f'ambient="{ambient} {ambient} {ambient * 1.2}"')
        xml = xml.replace('<headlight ambient="0.05 0.05 0.06" diffuse="0.05 0.05 0.05"',
                          '<headlight ambient="0.004 0.004 0.005" diffuse="0 0 0"')
        xml = xml.replace('shadowclip="6"', 'shadowclip="12"')
        ow, oh = off or (max(width, 1920), max(height, 1080))
        if off:
            xml = xml.replace('offsamples="8"', 'offsamples="2"')      # 高分辨率缓冲：少用多重采样，省内存
        xml = xml.replace('offwidth="4040" offheight="3030"', f'offheight="{oh}" offwidth="{ow}"')   # 换个顺序，免得 VideoModel 再把它改回 1920×1080
        xml = xml.replace('diffuse="1.75 1.72 1.66"', f'diffuse="{sun:.3f} {sun * 0.985:.3f} {sun * 0.95:.3f}"')
        return xml
    vmodel.VV.visual_xml = patched
    try:
        vm = vmodel.VideoModel(env, rock_bodies, holos=holos, width=width, height=height, shadowclip=12.0)
    finally:
        vmodel.VV.visual_xml = orig
    for gi in range(vm.m.ngeom):                 # 物理高度场不渲染，由细网格代替
        if vm.m.geom_type[gi] == vm.mj.mjtGeom.mjGEOM_HFIELD:
            vm.m.geom_group[gi] = 3
    return vm


HI = (4040, 3030)


def hi_renderer(vm):
    """高分辨率渲染器（每个渲染上下文都要复制全部贴图，约 1.4 GB；想象的车只建这一个）。"""
    import mujoco
    if getattr(vm, '_hi', None) is None:
        vm._hi = mujoco.Renderer(vm.m, HI[1], HI[0], max_geom=30000)
    return vm._hi


def release(vm):
    import gc
    for k in ('_hi', '_r'):
        r = getattr(vm, k, None)
        if r is not None:
            r.close(); setattr(vm, k, None)
    gc.collect()


def render_cam(vm, cam='front_cam', hi=False):
    vm.m.vis.global_.fovy = 45.0
    for g in range(6):
        vm.opt.geomgroup[g] = 1 if g in (0, 1, 2) else 0
    cid = vm.mj.mj_name2id(vm.m, vm.mj.mjtObj.mjOBJ_CAMERA, cam)
    r = hi_renderer(vm) if hi else vm.r
    r.update_scene(vm.d, camera=cid, scene_option=vm.opt)
    rgb = r.render().copy()
    r.enable_depth_rendering(); depth = r.render().copy(); r.disable_depth_rendering()
    return rgb, depth


def camera_rgbd(vm, cam='front_cam'):
    """机器人相机：RGB + 深度（米），分辨率 vm.W × vm.H。
    vm.hi_sensor 为真时（想象的车）只用一个高分辨率渲染器，再缩到传感器分辨率（同一相机、同一视场，内参按比例）。"""
    if not getattr(vm, 'hi_sensor', False):
        return render_cam(vm, cam)
    from PIL import Image
    rgb, depth = render_cam(vm, cam, hi=True)
    rgb_s = np.asarray(Image.fromarray(rgb).resize((vm.W, vm.H), Image.LANCZOS))
    depth_s = np.asarray(Image.fromarray(depth.astype(np.float32), mode='F').resize((vm.W, vm.H), Image.NEAREST))
    return rgb_s, depth_s


def dark_mask(rgb, thr=0.10):
    """被动相机在黑影里配不出深度：亮度低于门限的像素没有深度。"""
    lum = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0
    return lum < thr
