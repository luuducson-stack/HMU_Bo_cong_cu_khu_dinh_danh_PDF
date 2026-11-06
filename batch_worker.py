"""One owned process prepares, exports and verifies one independent PDF."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import batch


def processing_fingerprint(row):
    import engine
    return dict(source_sha256=row['source_sha256'],policy=engine.POLICY,
        code_hashes={name:engine.sha(Path(__file__).with_name(name)) for name in
            ('engine.py','hmu_recognizers.py','ocr_helper.py','output_qc.py','batch_worker.py')})


def process_job(row, *, ocr_workers, render_workers):
    with batch.queue_lock(Path(row['job_dir'])/'review_operation'):
        return _process_job(row,ocr_workers=ocr_workers,render_workers=render_workers)


def _process_job(row, *, ocr_workers, render_workers):
    import engine
    from output_qc import verify_output,content_digest
    root=Path(row['job_dir']);root.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();timings={};job=root/'review'
    fingerprint=processing_fingerprint(row);code_hashes=fingerprint['code_hashes']
    source=batch.snapshot_source(row)
    checkpoint=root/'prepare_checkpoint.json'
    def progress(stage,message=''):
        engine.save_json(root/'progress.json',{'stage':stage,'message':message,'updated':time.time(),'attempt_id':row.get('attempt_id')})
    progress('PREPARING')
    if checkpoint.exists():
        stored=json.loads(checkpoint.read_text(encoding='utf8'))
        if stored!=fingerprint:raise ValueError('Processing version changed; enqueue a new generation from the original')
        review=engine.ensure_job(job)
    else:
        # Preserve a partial attempt for diagnosis; prepare always owns a new directory.
        if job.exists():job.rename(root/f'incomplete_{time.time_ns()}')
        review=engine.prepare(source,job,study_id='CASE_'+row['id'][:16],case_xml_index=[],
            source_name=row['source_name'],ocr_workers=ocr_workers,render_workers=render_workers,
            progress_cb=lambda msg:progress('PREPARING',msg))
        engine.save_json(checkpoint,fingerprint)
    timings['prepare']=time.perf_counter()-start
    progress('EXPORTING');phase=time.perf_counter();pdf=None
    pointer=job/'last_export.json'
    if pointer.exists():
        previous=json.loads(pointer.read_text(encoding='utf8'))
        records=previous.get('files',[])
        cache=job/'output_verification_private.json'
        same_content=False
        if cache.exists():
            old_qc=json.loads(cache.read_text(encoding='utf8'))
            same_content=old_qc.get('content_sha256')==content_digest(review) and len(records)==1 and old_qc.get('pdf_sha256')==records[0].get('output_sha256')
        if len(records)==1 and (records[0].get('revision')==review['revision'] or same_content) and records[0].get('job_id')==review['job_id']:
            generation=(job/'exports'/previous['export_id']).resolve()
            candidate=(generation/records[0]['pdf']).resolve()
            if (generation.is_relative_to((job/'exports').resolve()) and candidate.parent==generation
                    and candidate.is_file() and engine.sha(candidate)==records[0].get('output_sha256')):pdf=candidate
    if pdf is None:
        pdf,_=engine.export(job,draft=True,progress_cb=lambda msg:progress('EXPORTING',msg))
    timings['export']=time.perf_counter()-phase
    progress('VERIFYING');phase=time.perf_counter()
    verification=verify_output(job,pdf,expected_revision=review['revision'],ocr_workers=ocr_workers,
        render_workers=render_workers,progress_cb=lambda msg:progress('VERIFYING',msg))
    timings['verify']=time.perf_counter()-phase
    if any(engine.sha(Path(__file__).with_name(n))!=h for n,h in code_hashes.items()):
        raise ValueError('Processing code changed during this job; result requires a fresh run')
    result=dict(state='NEEDS_REVIEW',revision=review['revision'],engine_job_id=review['job_id'],output=str(pdf.resolve()),
        verification=verification,pages=len(review['pages']),timings=timings,machine_seconds=time.perf_counter()-start,
        source_sha256=row['source_sha256'],code_hashes=code_hashes,attempt_id=row.get('attempt_id'))
    engine.save_json(root/(f"result_{row['attempt_id']}.json" if row.get('attempt_id') else 'worker_result.json'),result)
    progress('NEEDS_REVIEW')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True);args=parser.parse_args()
    if sys.stdin.readline().strip()!='START':raise SystemExit('Worker ownership handshake missing')
    request=json.loads(Path(args.request).read_text(encoding='utf8'))
    try:
        process_job(request['job'],ocr_workers=request['ocr_workers'],render_workers=request['render_workers'])
    except Exception as exc:
        import engine
        from error_pipeline import record_error_event
        row=request['job']
        job_dir=Path(row['job_dir'])
        job_dir.mkdir(parents=True,exist_ok=True)
        batch_dir=job_dir.parent.parent
        root_dir=batch_dir.parent if batch_dir.name in {'batch','queue'} else batch_dir
        err=record_error_event(
            root_dir,
            exc,
            stage='BATCH_WORKER',
            source_file=row.get('source_name'),
            job_id=row.get('id'),
            queue_id=row.get('id'),
        )
        engine.save_json(job_dir/f"error_{row['attempt_id']}.json",{
            **err,
            'type':type(exc).__name__,
            'message':err.get('message') or str(exc),
            'retryable':isinstance(exc,TimeoutError) or getattr(exc,'winerror',None) in {32,33,1450},
        })
        raise


if __name__=='__main__':main()
