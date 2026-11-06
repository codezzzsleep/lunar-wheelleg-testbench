"""Build WP3 crop variants and 144-task manifest from rendered views."""
import json,pathlib,sys,hashlib
import numpy as np
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parent.parent
ROCKS=['moon_rock_05','moon_rock_01','moon_rock_02','moon_rock_03','moon_rock_04','moon_rock_06','moon_rock_07','rock_07']
YAWS=['+0','+25','-25']
CROPS=['raw','white','masked']
def sha(p):
 h=hashlib.sha256(); h.update(pathlib.Path(p).read_bytes()); return h.hexdigest()
def crop(img,mask,pad=1.15,size=512):
 ys,xs=np.where(mask>0); y0,y1,x0,x1=ys.min(),ys.max(),xs.min(),xs.max()
 cx,cy=(x0+x1)//2,(y0+y1)//2; side=int(max(y1-y0,x1-x0)*pad); half=side//2
 a=max(0,cy-half); b=min(img.shape[0],cy+half); c=max(0,cx-half); d=min(img.shape[1],cx+half)
 sub=img[a:b,c:d]; m=mask[a:b,c:d]>0
 out=Image.new('RGB',(side,side),(255,255,255)); 
 im=Image.fromarray(sub); out.paste(im,(max(0,(side-im.width)//2),max(0,(side-im.height)//2)))
 crop=np.asarray(out)
 if side>=size:
  crop=np.asarray(Image.fromarray(crop).resize((size,size),Image.LANCZOS)); m=np.asarray(Image.fromarray(m.astype(np.uint8)*255).resize((size,size),Image.NEAREST))>0
 else:
  canvas=np.full((size,size,3),255,np.uint8); mm=np.zeros((size,size),bool)
  hh=min(crop.shape[0],m.shape[0],size); ww=min(crop.shape[1],m.shape[1],size)
  oy=(size-hh)//2; ox=(size-ww)//2
  canvas[oy:oy+hh,ox:ox+ww]=crop[:hh,:ww]; mm[oy:oy+hh,ox:ox+ww]=m[:hh,:ww]; crop=canvas; m=mm
 return crop,m
def main():
    out=ROOT/'runs/v4/wp3'; out.mkdir(parents=True,exist_ok=True)
    tasks=[]; order=0; meta=[]
    for rock in ROCKS:
        for yaw in YAWS:
            d=out/'views'/rock/f'yaw{yaw}'
            rgb=np.asarray(Image.open(d/'rgb.png').convert('RGB')); mask=np.asarray(Image.open(d/'mask.png').convert('L'))
            base,m=crop(rgb,mask)
            variants={'raw':base,
                      'white':np.where(m[...,None],base,np.uint8(255)),
                      'masked':np.where(m[...,None],base,np.uint8(112))}
            for cname,arr in variants.items():
                vd=out/'crops'/rock/f'yaw{yaw}'/cname; vd.mkdir(parents=True,exist_ok=True)
                for rep in (0,1):
                    p=vd/f'rep{rep}.png'; Image.fromarray(arr).save(p)
                    order+=1
                    tasks.append({'id':f'v4_{rock}_yaw{yaw}_{cname}_r{rep}','state_id':f'v4_wp3_{rock}','rock':rock,
                                  'view_yaw_deg':int(yaw),'crop':cname,'variant':cname,'repeat_idx':rep,'image':str(p),
                                  'image_sha256':sha(p),'model':{'version':'G1-Turbo','face_count':30000},
                                  'create_order':order,'estimated_credits':20.0})
                    meta.append({'task':tasks[-1]['id'],'path':str(p),'sha256':tasks[-1]['image_sha256'],'rock':rock,'yaw_deg':int(yaw),'crop':cname,'repeat':rep})
    doc={'schema':'v3-generation-tasks/v1','wp':'WP3','n':len(tasks),'rocks':ROCKS,'views':YAWS,'crops':CROPS,
         'note':'144 tasks: 8 rocks x 3 yaw views x 3 crops x 2 repeats; G1-Turbo 30000 faces; no upscaling (512px canvas)',
         'tasks':tasks}
    (out/'tasks.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2))
    (out/'task_manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    print(json.dumps({'tasks':len(tasks),'out':str(out/'tasks.json')},ensure_ascii=False))
if __name__=='__main__': main()
