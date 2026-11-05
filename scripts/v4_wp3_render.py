"""Render 3 yaw views per rock for WP3 (RGB-D + mask + crop variants)."""
import json,pathlib,sys,hashlib
import numpy as np, mujoco, trimesh
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent
ROCKS={'moon_rock_01':'moon_rock_01_h1v0','moon_rock_02':'moon_rock_02_h1v0','moon_rock_03':'moon_rock_03_h1v0',
       'moon_rock_04':'moon_rock_04_h1v0','moon_rock_05':'moon_rock_05_h1v0','moon_rock_06':'moon_rock_06_h1v0',
       'moon_rock_07':'moon_rock_07_h0v0','rock_07':'rock_07_h2v1'}

def pick_level(rock):
    if rock=='moon_rock_05': return 'h2'
    man=json.loads((ROOT/f'runs/v3/states/{ROCKS[rock]}/truth/manifest.json').read_text())
    target=float(man.get('height_m') or 0.0)
    best=None
    for lev in ('h0','h1','h2'):
        p=ROOT/f'assets/v3/rocks/{rock}/{lev}/body.stl'
        if not p.exists(): continue
        m=trimesh.load(str(p),force='mesh',process=False); h=float(m.bounds[1][2]-m.bounds[0][2])
        score=abs(h-target)
        if best is None or score<best[0]: best=(score,lev)
    return best[1] if best else 'h1'

def xml_for(rock,level,yaw_deg,out):
    obj=ROOT/f'assets/v3/rocks/{rock}/{level}/body_vis.obj'
    tex=ROOT/f'assets/v3/rocks/{rock}/texture.png'
    man=json.loads((ROOT/f'runs/v3/states/{ROCKS[rock]}/truth/manifest.json').read_text())
    pl=man['placement']; x,y,yaw=pl['x'],pl['y'],pl.get('yaw_deg',0.0)
    if rock=='moon_rock_05':
        t=trimesh.load(str(ROOT/'runs/v3/stage008/truth_v2/truth/body_world.stl'),force='mesh',process=False)
        x=float((t.bounds[0][0]+t.bounds[1][0])/2); y=float((t.bounds[0][1]+t.bounds[1][1])/2)
    # mesh yaw is part of placement: rotate mesh via body quat
    q=[np.cos(np.deg2rad(yaw)/2),0,0,np.sin(np.deg2rad(yaw)/2)]
    xml=f'''<mujoco><compiler angle="degree"/><option timestep="0.002" gravity="0 0 -1.62"/>
<visual><global fovy="45" offwidth="1600" offheight="1200"/><headlight ambient="0.18 0.18 0.18" diffuse="0.45 0.45 0.45" specular="0.02 0.02 0.02"/><quality shadowsize="4096"/></visual>
<asset><mesh name="rock" file="{obj}"/><texture name="tex" type="2d" file="{tex}"/><material name="mat" texture="tex" specular="0.1" shininess="0.1"/></asset>
<worldbody><camera name="obs" pos="0 0 0" quat="1 0 0 0" fovy="45"/><light pos="2 -1 3" dir="-0.5 0.3 -1" directional="true"/>
<geom name="ground" type="plane" size="8 8 0.1" rgba="0.55 0.52 0.46 1"/>
<body name="rock" pos="{x} {y} 0" quat="{q[0]} {q[1]} {q[2]} {q[3]}"><geom name="rockg" type="mesh" mesh="rock" material="mat"/></body></worldbody></mujoco>'''
    return xml

def look_camera(pos,target,up=(0,0,1)):
    pos=np.asarray(pos,float); target=np.asarray(target,float)
    f=target-pos; f/=np.linalg.norm(f); up=np.asarray(up,float)
    r=np.cross(f,up); r/=np.linalg.norm(r); u=np.cross(r,f)
    R=np.stack([r,u,-f],axis=1)
    return pos,R

def render(rock,level,yaw,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    xml=xml_for(rock,level,yaw,outdir); mp=outdir/'scene.xml'; mp.write_text(xml)
    model=mujoco.MjModel.from_xml_path(str(mp)); data=mujoco.MjData(model)
    mujoco.mj_forward(model,data)
    # rock center from body
    bid=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'rock'); center=np.array(data.xpos[bid],float)+np.array([0,0,0.02])
    pos=center+np.array([-0.95*np.cos(np.deg2rad(yaw)),-0.95*np.sin(np.deg2rad(yaw)),0.45])
    _,R=look_camera(pos,center)
    from scipy.spatial.transform import Rotation
    quat=Rotation.from_matrix(R).as_quat()  # x,y,z,w
    qw=[quat[3],quat[0],quat[1],quat[2]]
    cid=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_CAMERA,'obs')
    model.cam_pos[cid]=pos; model.cam_quat[cid]=qw
    mujoco.mj_forward(model,data)
    r=mujoco.Renderer(model,1200,1600)
    r.update_scene(data,camera=cid); rgb=r.render().copy()
    r.enable_depth_rendering(); dep=r.render().copy(); r.disable_depth_rendering()
    r.enable_segmentation_rendering(); seg=r.render().copy(); r.disable_segmentation_rendering(); r.close()
    R_actual=np.array(data.cam_xmat[cid],float).reshape(3,3); pos_actual=np.array(data.cam_xpos[cid],float)
    mask=(seg[:,:,0]==bid).astype(np.uint8)*255 if seg.ndim==3 else np.zeros((1200,1600),np.uint8)
    # try geom id if body id not present
    if mask.sum()==0 and seg.ndim==3:
        gid=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'rockg'); mask=(seg[:,:,0]==gid).astype(np.uint8)*255
    Image.fromarray(rgb).save(outdir/'rgb.png'); Image.fromarray(mask).save(outdir/'mask.png')
    np.save(outdir/'depth.npy',dep.astype(np.float32))
    fovy=45.0; f=0.5*1200/np.tan(np.deg2rad(fovy)/2)
    camj={'camera_schema':'camera-snapshot/v2','world_pos':pos_actual.tolist(),'R_world_from_camera':R_actual.tolist(),
          'fovy_deg':fovy,'image_width':1600,'image_height':1200,
          'intrinsics':{'fx':float(f),'fy':float(f),'cx':799.5,'cy':599.5,'width':1600,'height':1200},
          'depth_convention':'positive_camera_minus_z','view_yaw_deg':yaw,'source_rock':rock,'level':level}
    (outdir/'camera.json').write_text(json.dumps(camj,ensure_ascii=False,indent=2))
    return outdir,mask

if __name__=='__main__':
    rock=sys.argv[1] if len(sys.argv)>1 else 'moon_rock_05'
    yaws=[float(x) for x in (sys.argv[2].split(',') if len(sys.argv)>2 else ['0','25','-25'])]
    base=ROOT/'runs/v4/wp3/views'/rock
    for y in yaws:
        d=base/f'yaw{int(y):+d}'
        d,mask=render(rock,pick_level(rock),y,d)
        print(d,'mask_px',int((mask>0).sum()))
