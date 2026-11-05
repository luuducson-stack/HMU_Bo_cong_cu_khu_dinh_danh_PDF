"""Separate true-outline corpus; never changes the historical benchmark corpus."""
import argparse
import cProfile
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

import fitz


def build_dense_pdf(path, pages=2):
    output=fitz.open()
    for pn in range(pages):
        native=fitz.open();page=native.new_page(width=600,height=800)
        page.insert_text((30,55),'Ho ten: TRAN THI MAI',fontsize=12)
        for row in range(36):
            for x in (30,310):
                page.insert_text((x,100+row*18),f'Clinical row {row:02}: pressure 120/80; glucose 5.2; stable.',fontsize=8)
        for y in (80,755):page.draw_line((25,y),(575,y))
        svg=page.get_svg_image(text_as_path=True)
        with fitz.open(stream=svg.encode(),filetype='svg') as image:
            with fitz.open(stream=image.convert_to_pdf(),filetype='pdf') as outlined:
                assert not outlined[0].get_text().strip()
                assert len(outlined[0].get_drawings())>2000
                output.insert_pdf(outlined)
        native.close()
    output.set_metadata({'creationDate':'D:20261028000000','modDate':'D:20261028000000'})
    output.save(path,no_new_id=True);output.close()
    return {'pages':pages,'kind':'glyph_outline','clinical_rect':[25,80,575,756],'name_rect':[72,43,161,58]}


def check_pixels(source,product,review):
    with fitz.open(source) as before,fitz.open(product) as after:
        assert len(before)==len(after)
        for original,result,page in zip(before,after,review['pages']):
            assert not original.get_text().strip() and len(original.get_drawings())>2000
            assert not [q for q in page['proposals'] if q['selected'] and q['kind'] in {'QR_VECTOR_CANDIDATE','SIGNATURE_IMAGE','SIGNATURE_REGION'}], 'Glyph outlines misclassified as QR/signature'
            area=fitz.Rect(25,80,575,756)
            expected=original.get_pixmap(dpi=200,clip=area,alpha=False).samples
            actual=result.get_pixmap(dpi=200,clip=area,alpha=False).samples
            assert expected==actual, 'Protected clinical outline pixels changed'
            name=result.get_pixmap(dpi=200,clip=fitz.Rect(73,44,158,56),alpha=False).samples
            assert sum(name)/len(name)>254, 'Patient-name outline ink remains'
    return {'textless_and_dense':True,'clinical_pixels_exact':True,'name_region_white':True,'no_false_qr_or_signature':True}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-dir');ap.add_argument('--output',required=True)
    ap.add_argument('--runs',type=int,default=3);ap.add_argument('--warmup',type=int,default=1)
    ap.add_argument('--profile',action='store_true');args=ap.parse_args()
    if args.runs<1 or args.warmup<0:ap.error('runs must be positive; warmup must be nonnegative')
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(Path(args.source_dir).resolve() if args.source_dir else root))
    import engine
    from benchmark_workflow import TaskMemory
    output={'python':platform.python_version(),'pymupdf':fitz.VersionBind,'source_dir':str(Path(engine.__file__).parent),
            'source_hashes':{n:engine.sha(Path(engine.__file__).parent/n) for n in ('engine.py','hmu_recognizers.py','ocr_helper.py')},
            'profiled':args.profile,'warmup_runs':args.warmup,'runs':args.runs,'measurements':[]}
    profiler=cProfile.Profile() if args.profile else None
    with tempfile.TemporaryDirectory(prefix='hmu_dense_') as td:
        base=Path(td);source=base/'input.pdf';output['fixture']=build_dense_pdf(source)
        output['corpus_sha256']=engine.sha(source)
        for index in range(-args.warmup,args.runs):
            job=base/f'job_{index}'
            if profiler:profiler.enable()
            with TaskMemory() as memory:
                start=time.perf_counter();review=engine.prepare(source,job,'DENSE_VECTOR',case_xml_index=[]);prepared=time.perf_counter()
                product,qc=engine.export(job,draft=True);exported=time.perf_counter()
            if profiler:profiler.disable()
            output['ground_truth_checks']=check_pixels(source,product,review)
            if index>=0:output['measurements'].append(dict(prepare_seconds=prepared-start,export_seconds=exported-prepared,total_seconds=exported-start,
                                                        peak_task_sampled_rss_bytes=memory.peak,output_bytes=product.stat().st_size))
    for phase in ('prepare','export','total'):
        values=[r[phase+'_seconds'] for r in output['measurements']]
        output['median_'+phase+'_seconds']=statistics.median(values);output['range_'+phase+'_seconds']=[min(values),max(values)]
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(output,indent=2),encoding='utf8')
    if profiler:profiler.dump_stats(str(target.with_suffix('.prof')))
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
