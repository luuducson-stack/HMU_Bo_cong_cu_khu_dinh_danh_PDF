"""Verify the visible exported PDF; a machine PASS never approves a human review."""
import hashlib
import copy
import json
from pathlib import Path
import re
import tempfile
import time

import fitz
import engine
import hmu_recognizers as recognizers
from ocr_helper import ocr_pdf_pages, ocr_settings_fingerprint

PII_TYPES={'PATIENT_NAME','PATIENT_NAME_REVIEW','RELATIVE_NAME','HEALTHCARE_STAFF_NAME',
           'PERSON_NAME','PERSON_NAME_UNCLASSIFIED','DATE_OF_BIRTH','YEAR_OF_BIRTH',
           'ADDRESS_VN','PHONE_NUMBER_VN','CONTACT_PHONE','NATIONAL_ID','HEALTH_INSURANCE_ID',
           'EMAIL','ACCESS_CREDENTIAL'}


def verifier_fingerprint():
    digest=hashlib.sha256()
    for name in ('output_qc.py','engine.py','hmu_recognizers.py','ocr_helper.py'):
        digest.update(Path(__file__).with_name(name).read_bytes())
    digest.update(json.dumps(ocr_settings_fingerprint(),sort_keys=True).encode())
    return digest.hexdigest()


def _review_digest(review):
    return hashlib.sha256(json.dumps(review,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def content_digest(review):
    content=copy.deepcopy(review)
    content.pop('revision',None)
    for page in content['pages']:
        page.pop('reviewed',None);page.pop('note',None)
    return _review_digest(content)


def _seeds(review):
    seeds={}
    patterns={'DATE_OF_BIRTH':recognizers.DATE,'YEAR_OF_BIRTH':recognizers.YEAR,'PHONE_NUMBER_VN':recognizers.PHONE}
    for page in review['pages']:
        for q in page['proposals']:
            kind=q['kind'];value=q.get('text','')
            if q['selected'] and kind in PII_TYPES and recognizers._valid(kind,value):
                if kind in patterns and not re.fullmatch(patterns[kind],value):continue
                seeds.setdefault(kind,set()).add(value)
    return {k:sorted(v) for k,v in seeds.items()}


def _covered(rect, masks):
    remaining=[tuple(rect)]
    for mask in masks:
        parts=[]
        for r in remaining:
            a,b,c,d=max(r[0],mask[0]),max(r[1],mask[1]),min(r[2],mask[2]),min(r[3],mask[3])
            if a>=c or b>=d:parts.append(r);continue
            parts.extend(x for x in ((r[0],r[1],r[2],b),(r[0],d,r[2],r[3]),
                (r[0],b,a,d),(c,b,r[2],d)) if x[0]<x[2] and x[1]<x[3])
        remaining=parts
    return not remaining


def _has_ink(pix,rects,threshold):
    samples=pix.samples_mv;stride=pix.stride;n=pix.n;bounds=fitz.IRect(pix.irect)
    for r in rects:
        box=(fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect
        if box.is_empty or not bounds.contains(box):return True
        if any(min(samples[y*stride+box.x0*n:y*stride+box.x1*n],default=255)<threshold for y in range(box.y0,box.y1)):
            return True
    return False


def verify_output(job: Path, pdf: Path, *, expected_revision: int, ocr_workers: int,
                  render_workers: int=1, progress_cb=None) -> dict:
    job=Path(job);pdf=Path(pdf);start=time.perf_counter()
    review=engine.ensure_job(job)
    if type(expected_revision) is not int or review['revision']!=expected_revision:
        raise ValueError('Review revision changed before verification')
    digest=engine.sha(pdf);fingerprint=verifier_fingerprint();review_hash=_review_digest(review)
    cache=job/'output_verification_private.json'
    identity=dict(pdf_sha256=digest,job_id=review['job_id'],revision=expected_revision,
                  policy=review['policy'],verifier_fingerprint=fingerprint,review_sha256=review_hash,
                  content_sha256=content_digest(review))
    if cache.exists():
        old=json.loads(cache.read_text(encoding='utf8'))
        if all(old.get(k)==v for k,v in identity.items()):return old
        if all(old.get(k)==v for k,v in identity.items() if k not in {'revision','review_sha256'}):
            current=json.loads((job/'review.json').read_text(encoding='utf8'))
            if _review_digest(current)!=review_hash or engine.sha(pdf)!=digest:raise ValueError('PDF or review changed')
            rebound={**old,**identity,'reused_ocr':True}
            engine.save_json(cache,rebound)
            return rebound
    expected=len(review['pages']);findings=[];unreadable=[];nonblank=set();erased_source=set()
    with fitz.open(pdf) as doc:
        structural=(len(doc)==expected and doc.embfile_count()==0)
        for pn,page in enumerate(doc,1):
            structural=structural and not page.get_text().strip() and not list(page.annots() or []) and not list(page.widgets() or [])
            if pn<=expected:
                ref=review['pages'][pn-1]
                structural=structural and abs(page.rect.width-ref['width'])<.02 and abs(page.rect.height-ref['height'])<.02
        pages=list(range(1,len(doc)+1))
    maps={}
    if structural:
        with tempfile.TemporaryDirectory(prefix='verify_',dir=job) as temporary:
            engine._render_scan_pages(pdf,pages,200,temporary,max_workers=render_workers)
            maps=ocr_pdf_pages(pdf,pages,dpi=200,pre_rendered_dir=Path(temporary),max_workers=ocr_workers,
                progress_cb=(lambda done,total:progress_cb(f'Kiểm PDF {done}/{total} trang')) if progress_cb else None)
            for ref in review['pages']:
                cells=[q for q in ref['proposals'] if q['selected'] and q.get('rule')=='explicit_identity_column_cell']
                masks=[r for q in ref['proposals'] if q['selected'] and q['kind']!='WATERMARK_TEXT' for r in q['rects']]+ref['manual_rects']
                near=[]
                for q in ref['proposals']:
                    if q['kind'] not in PII_TYPES or q['selected'] or not q['rects']:continue
                    if all(_covered(r,masks) for r in q['rects']):continue
                    # OCR boxes can overshoot a selected field by a fraction of a point; pixels must prove the whole box blank.
                    if all(r[2]-r[0]>1 and r[3]-r[1]>1 and _covered([r[0]+.5,r[1]+.5,r[2]-.5,r[3]-.5],masks) for r in q['rects']):near.append(q)
                if not cells and not near:continue
                pix=fitz.Pixmap(str(Path(temporary)/f"{ref['page']}.png"))
                for q in near:
                    if not _has_ink(pix,q['rects'],250):erased_source.add((ref['page'],q['id']))
                for q in cells:
                    if _has_ink(pix,q['rects'],220):findings.append(dict(page=ref['page'],kind='SIGNATURE_REGION',text='Ô định danh còn nét trên PDF xuất',
                        rects=q['rects'],score=1,rule=q['rule'],reason='identity_cell_not_blank',review_status='PENDING_REVIEW'))
        # Only OCR-empty pages need a blankness proof; do not rasterize every page twice.
        column_findings={}
        with fitz.open(pdf) as doc:
            for pn in pages:
                if pn in maps and not maps[pn][0].strip():
                    pixels=doc[pn-1].get_pixmap(dpi=200,colorspace=fitz.csRGB,alpha=False).samples
                    if pixels.count(255)!=len(pixels):nonblank.add(pn)
                if pn in maps and maps[pn][0].strip():column_findings[pn]=engine.signature_column_proposals(*maps[pn],doc[pn-1].rect,page=doc[pn-1])
        unreadable=[pn for pn in pages if pn not in maps or (not maps[pn][0].strip() and pn in nonblank)]
        seeds=_seeds(review)
        texts=[maps.get(pn,('',[]))[0] for pn in pages]
        validator=lambda index,f:engine.name_geometry_valid(f,maps.get(index+1,('',[]))[1])
        found,_=recognizers.analyze_hmu_document(texts,external_seeds=seeds,_finding_validator=validator)
        for pn,fs in enumerate(found,1):
            text,chars=maps.get(pn,('',[]))
            ref=review['pages'][pn-1]
            for q in column_findings.get(pn,[]):
                findings.append(dict(page=pn,kind=q['kind'],text=q['text'],rects=q['rects'],score=q['score'],
                    rule=q['rule'],reason='visible_output_candidate',review_status='PENDING_REVIEW'))
            extra=engine.additional_findings(text,seeds)
            engine._check_name_geometry(extra,lambda f:engine.name_geometry_valid(f,chars))
            for f in fs+extra:
                if f.entity_type not in PII_TYPES:continue
                findings.append(dict(page=pn,kind=f.entity_type,text=f.text,rects=engine.span_rects(chars,f.start,f.end),
                    score=f.score,rule=f.rule,reason='visible_output_candidate',review_status=f.review_status))
        for page in review['pages']:
            masks=[r for q in page['proposals'] if q['selected'] and q['kind']!='WATERMARK_TEXT' for r in q['rects']]+page['manual_rects']
            for q in page['proposals']:
                if q['kind'] in PII_TYPES and not q['selected'] and (page['page'],q['id']) not in erased_source and not all(_covered(r,masks) for r in q['rects']):
                    findings.append(dict(page=page['page'],kind=q['kind'],text=q.get('text',''),rects=q['rects'],
                        score=q.get('score'),rule=q.get('rule',''),reason='unselected_source_candidate',proposal_id=q['id']))
    unique={}
    for finding in findings:
        key=hashlib.sha256(json.dumps({k:finding.get(k) for k in ('page','kind','text','rects','reason')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
        unique[key]={'id':key,**finding}
    result={**identity,'pages_expected':expected,'pages_checked':len(set(maps)&set(pages)),
            'findings':list(unique.values()),'unreadable_pages':unreadable,'structural_ok':bool(structural),
            'status':'FAIL' if not structural else ('NEEDS_REVIEW' if unique or unreadable or set(maps)!=set(pages) else 'PASS'),
            'seconds':time.perf_counter()-start,'scope':'Visible PDF OCR plus source candidates; not exhaustive independent PII ground truth'}
    current=json.loads((job/'review.json').read_text(encoding='utf8'))
    if _review_digest(current)!=review_hash or engine.sha(pdf)!=digest:
        raise ValueError('PDF or review revision changed during verification')
    engine.save_json(cache,result)
    return result
