import hashlib,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parent.parent
units=[]; base=ROOT/'runs/v6/m4/units'
for u in sorted(base.iterdir()):
 if not u.is_dir() or u.name in ('M3_route_full','M3_route_obs'): continue
 chk=u/'check'/'replay_check.json'
 if not chk.exists(): continue
 ok=json.loads(chk.read_text()).get('ok')
 tg=ROOT/'dist/v6'/'units'/f'{u.name}.tar.gz'; tg.parent.mkdir(parents=True,exist_ok=True)
 subprocess.run(['tar','-czf',str(tg),'-C',str(base),u.name],check=True)
 h=hashlib.sha256(tg.read_bytes()).hexdigest()
 units.append({'unit':u.name,'package':str(u.relative_to(ROOT)),'tarball':str(tg.relative_to(ROOT)),'sha256':h,'bytes':tg.stat().st_size,'replay_ok':ok,'release_asset':f'v6/units/{u.name}.tar.gz','source':'scripts/v6_build_wp7_package.py + v6_replay_check.py'})
(ROOT/'dist/v6/showcase_manifest.json').write_text(json.dumps({'schema':'v6-showcase-manifest/v1','baseline':'7d0d3cd5c','units':units},indent=2))
print('units',len(units),'ok',sum(x['replay_ok'] for x in units))
