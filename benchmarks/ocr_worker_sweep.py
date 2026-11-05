"""Compare Windows OCR worker counts on the same synthetic image-only PDF."""
import hashlib,json,sys,tempfile,time,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmark_workflow import build_pdf,TaskMemory
from ocr_helper import ocr_pdf_pages
out={}
pages=int(sys.argv[2]) if len(sys.argv)>2 else 10
runs=int(sys.argv[3]) if len(sys.argv)>3 else 3
with tempfile.TemporaryDirectory(prefix='hmu_worker_') as td:
 p=Path(sys.argv[5]) if len(sys.argv)>5 else Path(td)/'scan.pdf'
 if len(sys.argv)<=5:build_pdf(p,pages,'scan')
 import fitz
 with fitz.open(p) as doc:assert len(doc)==pages,'Page count differs'
 pre_rendered=Path(sys.argv[6]) if len(sys.argv)>6 else None
 out['ocr_helper_sha256']=hashlib.sha256((Path(__file__).resolve().parents[1]/'ocr_helper.py').read_bytes()).hexdigest()
 out['corpus_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
 expected=None
 for count in ([int(n) for n in sys.argv[4].split(',')] if len(sys.argv)>4 else [1,2,4,6]):
  rows=[]
  for run in range(runs):
   with TaskMemory() as memory:
    start=time.perf_counter();maps=ocr_pdf_pages(p,list(range(1,pages+1)),max_workers=count,pre_rendered_dir=pre_rendered);duration=time.perf_counter()-start
   fingerprint=hashlib.sha256(json.dumps(maps,sort_keys=True).encode()).hexdigest()
   if expected is None:expected=fingerprint
   assert fingerprint==expected,'OCR maps changed with worker count'
   rows.append({'seconds':duration,'peak_task_sampled_rss_bytes':memory.peak})
  out[str(count)]={'runs':rows,'median_seconds':statistics.median(r['seconds'] for r in rows)}
  print(count,out[str(count)],flush=True)
  target=Path(sys.argv[1]);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(out,indent=2),encoding='utf-8')
