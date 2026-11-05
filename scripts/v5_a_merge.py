"""Merge A-line shard tables into one report table."""
import csv,glob,pathlib,statistics
ROOT=pathlib.Path(__file__).resolve().parent.parent
rows=[]
for p in sorted((ROOT/'runs/v5/a_r3').glob('shard*/a_table.csv')):
 rows+=list(csv.DictReader(open(p)))
out=ROOT/'runs/v5/a_r3/a_table.csv'; out.parent.mkdir(parents=True,exist_ok=True)
if rows:
 with out.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
I=[r for r in rows if r['type']=='I']; II=[r for r in rows if r['type']=='II']
print('combos',len(rows),'I',len(I),'II',len(II))
for r in I+II: print(r['state'],r['channel'],r['type'],r['perfect'],r['perfect_out'],r['obs'],r['obs_out'],'off_gap',r['off_gap'],'rear_gap',r['rear_gap'])
