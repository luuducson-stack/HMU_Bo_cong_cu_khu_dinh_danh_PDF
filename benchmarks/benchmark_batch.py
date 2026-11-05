"""Fresh independent cases, wall time includes enqueue, export and actual-PDF QC."""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import batch
import batch_runtime
import engine


def summarize(rows,seconds):
    unique={r['source_sha256']:r for r in rows if r['state']!='DUPLICATE'}
    exported=[r for r in unique.values() if r['state'] in {'NEEDS_REVIEW','READY'}]
    clear=[r for r in exported if r['result'].get('verification',{}).get('status')=='PASS']
    ready=[r for r in exported if r['state']=='READY']
    times=sorted(r['result']['machine_seconds'] for r in exported)
    return dict(window_seconds=seconds,unique_files=len(unique),exported_files=len(exported),
        machine_clear_files=len(clear),ready_files=len(ready),
        exported_files_per_hour=len(exported)*3600/seconds,
        machine_clear_files_per_hour=len(clear)*3600/seconds,ready_files_per_hour=len(ready)*3600/seconds,
        worst_seconds=max(times,default=None),median_seconds=statistics.median(times) if times else None,
        p95_seconds=times[max(0,math.ceil(len(times)*.95)-1)] if times else None)


def run_batch_benchmark(manifest: Path,destination: Path,*,jobs:int,ocr_workers:int,render_workers:int) -> dict:
    start=time.perf_counter();destination=Path(destination).resolve()
    destination.mkdir(parents=True,exist_ok=False)
    cases=json.loads(Path(manifest).read_text(encoding='utf8'))['cases']
    if not cases:raise ValueError('Empty corpus')
    if len({c['case_id'] for c in cases})!=len(cases):raise ValueError('Duplicate case IDs')
    sources=[Path(c['source_path_private']) for c in cases]
    for c,p in zip(cases,sources):
        if engine.sha(p)!=c['source_sha256']:raise ValueError('Corpus hash changed')
    db=destination/'queue.sqlite3';ids=batch.enqueue(db,sources)
    if len(set(ids))!=len(ids):raise ValueError('Corpus repeats an input path')
    samples=[];stop=threading.Event()
    def sample():
        while not stop.is_set():
            samples.append(dict(seconds=time.perf_counter()-start,**batch_runtime.resources(destination)))
            stop.wait(.1)
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    try:coordinator=batch.run_queue(db,jobs=jobs,ocr_workers=ocr_workers,render_workers=render_workers)
    finally:stop.set();thread.join()
    elapsed=time.perf_counter()-start;rows=[batch.get_job(db,i) for i in ids]
    result={**summarize(rows,elapsed),'configuration':dict(jobs=jobs,ocr_workers=ocr_workers,render_workers=render_workers),
        'coordinator':coordinator,'peak_tree_rss_bytes':max(s['batch_rss'] for s in samples),
        'minimum_available_ram_bytes':min(s['available_ram'] for s in samples),'sample_count':len(samples),
        'max_sample_gap_seconds':max((b['seconds']-a['seconds'] for a,b in zip(samples,samples[1:])),default=0),
        'disk_bytes':sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()),
        'policy':engine.POLICY,'code_hashes':{p.name:engine.sha(p) for p in [Path(batch.__file__),Path(engine.__file__),
            Path(__file__).parents[1]/'batch_worker.py',Path(__file__).parents[1]/'output_qc.py',
            Path(__file__).parents[1]/'ocr_helper.py',Path(__file__).parents[1]/'hmu_recognizers.py']},
        'cases':[dict(case_id=c['case_id'],source_sha256=r['source_sha256'],pages=r['pages'],state=r['state'],
            attempts=r['attempts'],machine_seconds=r['result'].get('machine_seconds'),timings=r['result'].get('timings'),
            qc_status=r['result'].get('verification',{}).get('status'),
            findings=len(r['result'].get('verification',{}).get('findings',[])),
            unreadable_pages=r['result'].get('verification',{}).get('unreadable_pages',[])) for c,r in zip(cases,rows)],
        'scope':'Fresh job cache; OS cache uncontrolled. Machine PASS is not independent ground truth or human release.'}
    engine.save_json(destination/'ram_samples.json',samples)
    engine.save_json(destination/'measurement.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--jobs',type=int,default=2);p.add_argument('--ocr-workers',type=int,default=1);p.add_argument('--render-workers',type=int,default=1)
    a=p.parse_args();print(json.dumps(run_batch_benchmark(a.manifest,a.destination,jobs=a.jobs,ocr_workers=a.ocr_workers,render_workers=a.render_workers),ensure_ascii=False,indent=2))
