"""Fresh-job localhost benchmark. Real records remain private; exports are DRAFT."""
import argparse
import copy
import hashlib
import http.client
import json
import sys
import threading
import time
import urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
PRODUCT_ROOT=Path(__file__).resolve().parents[1]
PRODUCT_HASHES={n:hashlib.sha256((PRODUCT_ROOT/n).read_bytes()).hexdigest() for n in ('engine.py','app.py','ocr_helper.py','hmu_recognizers.py','benchmarks/benchmark_real_workflow.py')}
import app
import engine
from benchmark_workflow import TaskMemory


def machine_seconds(prepare, export):
    return prepare + export


def mask_sha(data):
    masks = [(p['page'], p['width'], p['height'],
              [(q['kind'], q['rects'], q.get('method'), q.get('stream_xrefs'))
               for q in p['proposals'] if q['selected']], p['manual_rects']) for p in data['pages']]
    return hashlib.sha256(json.dumps([data['dpi'], masks], sort_keys=True).encode()).hexdigest()


def run(source, root, review_job=None):
    source, root = Path(source), Path(root)
    if root.exists(): raise ValueError('Use a new benchmark root')
    source_hash = engine.sha(source)
    hashes=dict(PRODUCT_HASHES)
    if hashes != {n:engine.sha(PRODUCT_ROOT/n) for n in hashes}: raise ValueError('Product changed since benchmark import')
    reference = json.loads((Path(review_job)/'review.json').read_text(encoding='utf8')) if review_job else None
    if reference and reference['source_sha256'] != source_hash: raise ValueError('Reference source differs')
    if reference and reference.get('policy') != engine.POLICY: raise ValueError('Reference policy differs')
    if reference and reference.get('dpi') != 200: raise ValueError('Reference DPI must be200')
    server = app.create_server(root)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=1800)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse(); raw = response.read()
            if response.status != 200: raise RuntimeError(f'HTTP {response.status}: {raw[:200]!r}')
            return raw
        finally: conn.close()
    try:
        token = json.loads(request('GET','/state'))['token']
        with TaskMemory() as memory:
            start = time.perf_counter()
            state = json.loads(request('POST','/upload', source.read_bytes(),
                {'X-HMU-Token':token,'X-Original-Filename':urllib.parse.quote(source.name),'X-Study-ID':'SPEED_REAL'}))
            data = state['review']
            job = next(root.glob('*/review'))
            engine.save_json(job/'automatic_review_private.json',data)
            prepared = time.perf_counter()
            if reference:
                if [(p['width'],p['height']) for p in data['pages']] != [(p['width'],p['height']) for p in reference['pages']]:
                    raise ValueError('Reference page geometry differs')
                data['pages'] = copy.deepcopy(reference['pages'])
                for p in data['pages']: p['reviewed'] = False
                data['revision'] += 1
                engine.save_json(job/'review.json', data)
            # Applying a frozen reference stands in for human review and is outside both intervals.
            export_start = time.perf_counter()
            result = json.loads(request('POST','/export', json.dumps({'job_id':data['job_id'],'revision':data['revision'],'draft':True}), {'X-HMU-Token':token}))
            pdf = request('GET','/download?job_id='+data['job_id'])
            end = time.perf_counter()
        assert engine.sha(source) == source_hash
        assert hashes == {n:engine.sha(PRODUCT_ROOT/n) for n in hashes}, 'Product changed during benchmark'
        assert hashlib.sha256(pdf).hexdigest() == result['qc']['output_sha256']
        total = machine_seconds(prepared-start, end-export_start)
        return {'pages':len(data['pages']), 'input_sha256':source_hash,'mask_sha256':mask_sha(data),
                'ingest_prepare_seconds':prepared-start,'export_download_seconds':end-export_start,
                'machine_seconds':total,'equivalent_100_seconds':total*100/len(data['pages']),
                'meets_proportional_240s':total*100/len(data['pages'])<=240,
                'peak_task_sampled_rss_bytes':memory.peak,'human_seconds_excluded':True,
                'source_hashes':hashes,
                'output':str(Path(result['directory'])/result['file']),'output_bytes':len(pdf),'status':'DRAFT_NEEDS_QC'}
    finally:
        server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source');parser.add_argument('--root',required=True)
    parser.add_argument('--review-job');parser.add_argument('--output',required=True);parser.add_argument('--runs',type=int,default=3)
    args=parser.parse_args()
    if args.runs<1:parser.error('runs must be positive')
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    records=[]
    for i in range(args.runs):
        records.append(run(args.source,Path(args.root)/f'run_{i+1}',args.review_job))
        output.write_text(json.dumps({'scope':'Fresh OCR + HTTP upload/export/download, DRAFT; proportional 71-page acceptance authorized by user, not a real 100-page measurement','measurements':records},indent=2),encoding='utf8')
        print(json.dumps({k:v for k,v in records[-1].items() if k.endswith('seconds') or k=='meets_proportional_240s'}),flush=True)
