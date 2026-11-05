"""Independent labelled-region scoring; partial coverage is always a miss."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from output_qc import _covered


def evaluate_regions(labels,predictions):
    result={mode:{'tp':0,'fn':0} for mode in ('proposal','selection')}
    for label in labels:
        if label['action']!='must_redact':continue
        for mode in result:
            boxes=[r for p in predictions if p['page']==label['page'] and p['kind']==label['kind']
                and (mode=='proposal' or p['selected']) for r in p['rects']]
            good=all(_covered(r,boxes) for r in label['rects'])
            result[mode]['tp' if good else 'fn']+=1
    for counts in result.values():
        total=counts['tp']+counts['fn'];counts['recall']=counts['tp']/total if total else None
    result['preserve_overlaps']=sum(any(fitz.Rect(r).intersects(fitz.Rect(m)) for p in predictions
        if p['page']==label['page'] and p['selected'] for r in label['rects'] for m in p['rects'])
        for label in labels if label['action']=='must_preserve')
    result['scope']='Labelled regions only; precision requires exhaustive negative annotations'
    return result


def evaluate_labels(labels:Path,predictions:Path,final_pdf_dir:Path) -> dict:
    truth=json.loads(Path(labels).read_text(encoding='utf8'));pred=json.loads(Path(predictions).read_text(encoding='utf8'))
    results=[]
    for case in truth['cases']:
        matches=[p for p in pred['cases'] if p['case_id']==case['case_id'] and p['source_sha256']==case['source_sha256']]
        if len(matches)!=1:raise ValueError('Missing prediction or wrong source hash')
        proposed=matches[0];regions=case['labels']
        if len({r['entity_id'] for r in regions})!=len(regions):raise ValueError('Duplicate independent label ID')
        output=(Path(final_pdf_dir)/proposed['pdf']).resolve()
        if not output.is_relative_to(Path(final_pdf_dir).resolve()):raise ValueError('Output path outside root')
        score=evaluate_regions(regions,proposed['proposals']);pixel_misses=[]
        with fitz.open(output) as doc:
            for region in regions:
                if region['action']=='uncertain':raise ValueError('Adjudicate labels before scoring')
                if region['action']!='must_redact':continue
                if not 1<=region['page']<=len(doc):raise ValueError('Label page outside PDF')
                for coords in region['rects']:
                    rect=fitz.Rect(coords);page=doc[region['page']-1]
                    if rect.is_empty or not page.rect.contains(rect):raise ValueError('Invalid label rectangle')
                    pix=page.get_pixmap(dpi=200,clip=rect,alpha=False)
                    if any(value<250 for value in pix.samples):pixel_misses.append(region['entity_id']);break
        results.append(dict(case_id=case['case_id'],**score,actual_output_nonwhite_labels=pixel_misses))
    return {'cases':results,'scope':'Actual-PDF white-mask checks on independent labelled PII regions; preservation needs source/control pixel comparison'}
