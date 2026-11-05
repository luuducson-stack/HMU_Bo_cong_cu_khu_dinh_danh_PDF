"""Compare two completed measurements only when their synthetic corpus hashes match."""
import argparse,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('before');p.add_argument('after');p.add_argument('output');a=p.parse_args()
before=json.loads(Path(a.before).read_text(encoding='utf-8'));after=json.loads(Path(a.after).read_text(encoding='utf-8'))
assert set(before['cases'])==set(after['cases']),'Incomplete or different corpus groups'
rows=[]
for name,old in before['cases'].items():
 new=after['cases'][name]
 assert old['corpus_sha256']==new['corpus_sha256'],f'Non-matching corpus: {name}'
 row={'case':name,'corpus_sha256':old['corpus_sha256']}
 for field in ['prepare','export','total']:
  key=f'median_{field}_seconds';b=old[key];n=new[key]
  row[field]={'before_seconds':b,'after_seconds':n,'change_percent':(n/b-1)*100}
 for label,data in [('before',old),('after',new)]:
  row[f'{label}_sampled_task_rss_bytes']=statistics.median(r['peak_task_sampled_rss_bytes'] for r in data['measurements'])
 row['memory_change_percent']=(row['after_sampled_task_rss_bytes']/row['before_sampled_task_rss_bytes']-1)*100
 rows.append(row)
output=Path(a.output);output.write_text(json.dumps({'before':str(a.before),'after':str(a.after),'comparison':'matching corpus; negative change means improvement; includes correctness overhead','rows':rows},indent=2),encoding='utf-8')
for r in rows: print(r['case'],f"total {r['total']['before_seconds']:.3f} -> {r['total']['after_seconds']:.3f}s ({r['total']['change_percent']:+.1f}%), sampled task memory {r['memory_change_percent']:+.1f}%")
