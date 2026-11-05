"""Offline PDF workflow v2.0: Coordinate-Linked Markdown + OCR fallback + Auto-Signature & Boxed DOB redaction.

This exporter rebuilds pages from rendered pixels after applying approved
redactions. It never copies source PDF objects into the deliverable.
"""
import zlib, struct
import argparse, collections, hashlib, json, re, math, unicodedata, secrets, shutil, copy
from bisect import bisect_left
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import fitz
from pypdf.generic import ContentStream, DecodedStreamObject
from hmu_recognizers import (
    analyze_hmu_document, protected_hits, extract_case_seeds, build_case_xml_index,
    Finding, SURNAMES, PERSON_NAME, WATERMARK_RE, _valid, _exact_flexible_pattern, _strip_accents, _NAME_START, _FIELD_BOUNDARY, _build_folded_index, _person_name_context, _check_name_geometry, _SIG_HEADING
)
from ocr_helper import ocr_pdf_pages, ocr_pdf_regions, ocr_settings_fingerprint

VERSION = 'HMU-PDF-Workflow-2.0'
POLICY = 'remove_names_dob_phone_address_staff_signatures_keep_age_clinical_and_record_ids_geometry_v20'
fitz.TOOLS.set_small_glyph_heights(True)

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as src:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def save_preview(pix, path):
    """Write lossless RGB PNG with fast deflate for OCR and private previews."""
    if pix.n != 3 or pix.alpha:
        raise ValueError('Preview requires opaque RGB')
    row = pix.width * 3
    rows = bytearray((row + 1) * pix.height)
    samples = pix.samples_mv
    for y in range(pix.height):
        start = y * (row + 1) + 1
        rows[start:start+row] = samples[y*pix.stride:y*pix.stride+row]
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    header = struct.pack('>IIBBBBB', pix.width, pix.height, 8, 2, 0, 0, 0)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
                           chunk(b'IDAT', zlib.compress(rows, 1)) + chunk(b'IEND', b''))


def _render_page_batch(pdf_path, page_numbers, dpi, output_dir, progress_cb=None):
    records=[]
    with fitz.open(pdf_path) as doc:
        for i,pn in enumerate(page_numbers,1):
            pix=doc[pn-1].get_pixmap(dpi=dpi,alpha=False)
            path=Path(output_dir)/f'{pn}.png';save_preview(pix,path)
            records.append(dict(page=pn,width=pix.width,height=pix.height,path=str(path)))
            if progress_cb and (i==1 or i%15==0 or i==len(page_numbers)):progress_cb(i,len(page_numbers))
    return records


def _render_scan_pages(pdf_path, page_numbers, dpi, output_dir, progress_cb=None, *, max_workers=None):
    if max_workers is not None and (type(max_workers) is not int or not 1<=max_workers<=2):
        raise ValueError('Render workers must be 1 or 2')
    workers=max_workers or (2 if len(page_numbers)>=64 else 1)
    if workers==1:
        return _render_page_batch(pdf_path,page_numbers,dpi,output_dir,progress_cb)
    # Each process owns its Document; MuPDF objects must never cross threads/processes.
    records=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(_render_page_batch,str(pdf_path),page_numbers[i::workers],dpi,str(output_dir)) for i in range(workers)]
        for future in as_completed(futures):
            records.extend(future.result())
            if progress_cb:progress_cb(len(records),len(page_numbers))
    if sorted(r['page'] for r in records)!=sorted(page_numbers):raise RuntimeError('Incomplete rendered page map')
    return sorted(records,key=lambda r:r['page'])


def save_json(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    compact = path.parent.name == 'analysis_private'
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=None if compact else 2,
                               separators=(',', ':') if compact else None), encoding='utf-8')
    import time
    for attempt in range(51):
        try:
            temp.replace(path)
            break
        except PermissionError as exc:
            if getattr(exc,'winerror',None) not in {5,32,33} or attempt==50:raise
            time.sleep(.02)

def remove_isolated_watermarks(doc):
    """Preparation never destroys content before review."""
    return []


def _non_watermark_state(page):
    lines = []
    for block in page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines', []):
            if WATERMARK_RE.fullmatch(''.join(x['text'] for x in line['spans']).strip()):
                continue
            lines.append([(x['text'], x['bbox'], x['font'], x['size'], x['color']) for x in line['spans']])
    # Removing a text paint shifts sequence/block indices without changing appearance.
    drawings = [{k:v for k,v in item.items() if k != 'seqno'} for item in page.get_drawings()]
    images = [{k:v for k,v in item.items() if k != 'number'} for item in page.get_image_info()]
    return lines, drawings, images


def _watermark_proof(page):
    """Prove isolated text removal; compare semantic appearance, not sequence indices."""
    result = {}; doc = page.parent
    marks_before = rotated_watermark_rects(page)
    if not marks_before:
        return result
    before = _non_watermark_state(page); text_before = page.get_text()
    for xref in page.get_contents():
        raw = doc.xref_stream(xref)
        # A decoded text-paint stream must contain a BT operator.
        if not raw or b'BT' not in raw:
            continue
        stream = DecodedStreamObject(); stream.set_data(raw)
        try:
            operations = ContentStream(stream, None).operations
            allowed = {b'q',b'Q',b'cm',b'BT',b'ET',b'Tm',b'Tf',b'TL',b'Td',b'TD',b'Tj',b'TJ',b"'",b'"',b'Tc',b'Tw',b'Tz',b'Ts',b'Tr',b'rg',b'RG',b'g',b'G',b'k',b'K',b'gs'}
            if any(op not in allowed for _,op in operations): continue
            if not operations or operations[0][1] != b'q' or operations[-1][1] != b'Q': continue
            balance = 0; unscoped = False
            for _,op in operations:
                if op == b'q': balance += 1
                elif op == b'Q': balance -= 1
                elif balance == 0: unscoped = True
                if balance < 0: unscoped = True; break
            if balance or unscoped: continue
            doc.update_stream(xref, b'')
            marks_after = rotated_watermark_rects(page)
            removed = [r for t,r in marks_before if (t,r) not in marks_after]
            if not removed:
                continue
            if text_before != page.get_text() and before == _non_watermark_state(page):
                result[xref] = removed
        finally:
            doc.update_stream(xref, raw)
    return result


def _watermark_xrefs(proof, target_rect=None):
    return [xref for xref,rects in proof.items() if target_rect is None or
            any(max(abs(a-b) for a,b in zip(r,target_rect)) < .5 for r in rects)]


def watermark_streams(page, target_rect=None):
    return _watermark_xrefs(_watermark_proof(page),target_rect)


def char_map(page):
    text = ''; chars = []; line_id = 0
    rotation_matrix = page.rotation_matrix if page.rotation else None
    textpage = page.get_textpage(flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
    for block in textpage.extractRAWDICT()['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                for c in span['chars']:
                    chars.append((len(text), line_id, tuple(fitz.Rect(c['bbox']) * rotation_matrix) if rotation_matrix is not None else c['bbox'], c['c']))
                    text += c['c']
            text += '\n'; line_id += 1
    if text != textpage.extractText(sort=False):
        raise ValueError('Text-to-geometry mismatch; page needs alternate extraction')
    return text, chars

def span_rects(chars, a, b):
    by_line = {}
    lo = bisect_left(chars, a, key=lambda x: x[0]); hi = bisect_left(chars, b, key=lambda x: x[0])
    for offset, line, bbox, c in chars[lo:hi]:
        if a <= offset < b and not c.isspace():
            r = fitz.Rect(bbox)
            if line in by_line and r.x0 - by_line[line][-1].x1 <= max(12, r.height):
                by_line[line][-1] |= r
            else:
                by_line.setdefault(line, []).append(r)
    return [[round(v, 3) for v in r] for group in by_line.values() for r in group]


def name_geometry_valid(finding, chars):
    boxes=[fitz.Rect(r) for r in span_rects(chars,finding.start,finding.end)]
    if not boxes:return False
    connected=[boxes.pop()]
    labelled_patient=finding.entity_type=='PATIENT_NAME' and finding.rule.startswith(('v20_strict_field','v20_inline_patient'))
    titled_staff=finding.entity_type=='HEALTHCARE_STAFF_NAME' and any(tag in finding.rule for tag in (':confirmed_case_short',':confirmed_grid_short'))
    gap_factor=3 if labelled_patient or titled_staff else 1.25
    while boxes:
        for i,r in enumerate(boxes):
            if any(max(max(r.x0-s.x1,s.x0-r.x1,0),max(r.y0-s.y1,s.y0-r.y1,0))
                   <=(gap_factor if abs(r.y0-s.y0)<min(r.height,s.height)/2 else 1.25)*max(min(r.width,r.height),min(s.width,s.height)) for s in connected):
                connected.append(boxes.pop(i));break
        else:return False
    return True


def insurance_value_rects(text,chars,finding,page_rect):
    from hmu_recognizers import INSURANCE_CARD_LABEL
    rects=span_rects(chars,finding.start,finding.end)
    prefix=text[max(0,finding.start-100):finding.start]
    label=re.search(INSURANCE_CARD_LABEL+r'[ \t]*[:：][ \t]*$',prefix,re.I)
    boxes=span_rects(chars,max(0,finding.start-100)+label.start(),finding.start) if label else []
    if not boxes or not rects:
        finding.review_status='CONTEXT_REQUIRED';finding.score=.75;finding.rule+=':FIELD_GEOMETRY_REQUIRED_REVIEW';return rects
    value=fitz.Rect(rects[0])
    for r in rects[1:]:value|=fitz.Rect(r)
    last=max((fitz.Rect(r) for r in boxes),key=lambda r:r.x1)
    bad_layout=last.x1>value.x0 or abs(last.y0-value.y0)>max(last.height,value.height)
    candidate=fitz.Rect(min(value.x0,last.x1+3),min(value.y0,last.y0)-1,value.x1+1,max(value.y1,last.y1)+1) & page_rect
    la=max(0,finding.start-100)+label.start()
    if bad_layout or any(ch.strip() and candidate.intersects(fitz.Rect(bb)) for off,_,bb,ch in chars if not la<=off<finding.end):
        finding.review_status='CONTEXT_REQUIRED';finding.score=.75;finding.rule+=':FIELD_GEOMETRY_REQUIRED_REVIEW';return rects
    value=candidate
    return [[round(v,3) for v in value]]


def staff_name_rects(text,chars,finding):
    from hmu_recognizers import _TITLE
    start=finding.start
    prefix=text[max(0,start-45):start]
    title=re.search(r'(?<!\w)(?i:'+_TITLE+r')$',prefix)
    if title:start=max(0,finding.start-45)+title.start()
    rects=span_rects(chars,start,finding.end);groups=[]
    for r in sorted(rects,key=lambda r:(r[1]+r[3])/2):
        for group in groups:
            if any(min(r[3],s[3])-max(r[1],s[1])>=.5*min(r[3]-r[1],s[3]-s[1]) for s in group):
                group.append(r);break
        else:groups.append([r])
    return [[r[0],min(s[1] for s in group),r[2],max(s[3] for s in group)] for group in groups for r in group]


def trim_titled_name_to_column(finding,text,chars):
    from hmu_recognizers import valid_titled_staff
    if finding.entity_type!='HEALTHCARE_STAFF_NAME' or not finding.rule.startswith('v20_title_name') or name_geometry_valid(finding,chars):return False
    boxes=span_rects(chars,finding.start,finding.end)
    if not boxes:return False
    first=fitz.Rect(boxes[0])
    for box in boxes[1:]:
        r=fitz.Rect(box)
        if 0<=r.x0-first.x1<=3*first.height and min(r.y1,first.y1)-max(r.y0,first.y0)>.5*min(r.height,first.height):first|=r
    offsets=[off for off,_,bb,_ in chars if finding.start<=off<finding.end and bb[0]>first.x1+1.25*first.height
        and min(bb[3],first.y1)-max(bb[1],first.y0)>.25*min(bb[3]-bb[1],first.height)]
    if not offsets:return False
    value=text[finding.start:min(offsets)].rstrip()
    if not 2<=len(value.split())<=5 or not valid_titled_staff(value):return False
    finding.end=finding.start+len(value);finding.text=value
    finding.review_status='PENDING_REVIEW' if len(value.split())>=3 else 'CONTEXT_REQUIRED';finding.score=.99 if len(value.split())>=3 else .75;finding.rule+=':column_prefix_trim'
    return True


def signature_heading_confirms(finding,text,chars):
    if finding.entity_type not in {'HEALTHCARE_STAFF_NAME','PERSON_NAME_UNCLASSIFIED','PERSON_NAME'}:return False
    minimum=2 if any(tag in finding.rule for tag in (':confirmed_case_short',':confirmed_grid_short')) else 3
    known=any(tag in finding.rule for tag in (':confirmed_case_short',':confirmed_case_full'))
    if len(finding.text.split())<minimum or (not known and not _valid('HEALTHCARE_STAFF_NAME',finding.text)) or not name_geometry_valid(finding,chars):return False
    boxes=span_rects(chars,finding.start,finding.end)
    name=fitz.Rect(boxes[0])
    for box in boxes[1:]:name|=fitz.Rect(box)
    flat,indices=_build_folded_index(text)
    pattern=r'nguoi\s*du[yv]et\s*ket\s*qua|b[ai]c\s*(?:s[iyj]\s*)?chi\s*dinh|truong\s*khoa|giam\s*doc|thu\s*truong\s*(?:don\s*vi|co\s*quan)|b[ai]c\s*s[iyjs]?[\W_]*\s*(?:dieu|dibu)\s*tri|b[ai]c\s*(?:s[iyjs]?[\W_]*\s*)?chuyen\s*khoa'
    for match in re.finditer(pattern,flat):
        rs=span_rects(chars,indices[match.start()],indices[match.end()-1]+1)
        if not rs:continue
        ordered=sorted((fitz.Rect(r) for r in rs),key=lambda r:r.x0)
        if max(r.y0 for r in ordered)-min(r.y0 for r in ordered)>max(r.height for r in ordered):continue
        if any(b.x0-a.x1>3*max(a.height,b.height) for a,b in zip(ordered,ordered[1:])):continue
        header=fitz.Rect(ordered[0])
        for r in ordered[1:]:header|=r
        if 0<=name.y0-header.y1<=90 and abs((name.x0+name.x1-header.x0-header.x1)/2)<=max(80,header.width):return True
    return False


def footer_signature_fields(text,chars,page_rect,pn,*,image_rects=(),native_images=()):
    flat,indices=_build_folded_index(text);out=[]
    roles=r'nguoi\s*lap\s*bang\s*ke|ke\s*to[aor]n\s*vien\s*phi|xac[^\n]{0,20}cua\s*nguoi(?:\s*benh)?'
    headers=[fitz.Rect(r) for m in re.finditer(roles,flat) for r in span_rects(chars,indices[m.start()],indices[m.end()-1]+1) if r[1]>page_rect.height*.4]
    words=[(m.group(),r) for m in re.finditer(r'\S+',text) for r in span_rects(chars,m.start(),m.end())]
    for header in headers:
        center=(header.x0+header.x1)/2
        instructions=[fitz.Rect(r) for m in re.finditer(r'ghi\s*ro\s*h[eop]\s*ten',flat) for r in span_rects(chars,indices[m.start()],indices[m.end()-1]+1)
            if 0<=r[1]-header.y1<25 and abs((r[0]+r[2])/2-center)<90]
        if not instructions:continue
        top=max(r.y1 for r in instructions)+4;left=max(page_rect.x0,center-105);right=min(page_rect.x1,center+105)
        rows=[]
        for value,r in sorted(words,key=lambda w:w[1][1]):
            if not (left<=r[0] and r[2]<=right and top+5<=r[1]<=top+90):continue
            for row in rows:
                if abs((r[1]+r[3]-row[0][1][1]-row[0][1][3])/2)<3:row.append((value,r));break
            else:rows.append([(value,r)])
        groups=[]
        for row in rows:
            row.sort(key=lambda w:w[1][0])
            group=[]
            for word in row:
                if group and word[1][0]-group[-1][1][2]>3*max(word[1][3]-word[1][1],group[-1][1][3]-group[-1][1][1]):groups.append(group);group=[]
                group.append(word)
            if group:groups.append(group)
        for row in groups:
            if _strip_accents(row[0][0].lower()).rstrip(':') in {'chau','con'}:row=row[1:]
            if not 2<=len(row)<=6:continue
            value=' '.join(w for w,_ in row);clean=re.sub(r'[•!*?]','',value)
            if any(ch.isdigit() for ch in value) or sum(w[0].isupper() for w,_ in row)<len(row)-1 or not _valid('PERSON_NAME',clean) or protected_hits(clean):continue
            name=fitz.Rect(row[0][1])
            for _,r in row[1:]:name|=fitz.Rect(r)
            name=(name+(-1,-1,1,1)) & page_rect
            if any(name.intersects(fitz.Rect(r)) for r in image_rects):continue
            out.append(dict(id=f'p{pn}-footer{len(out)}',kind='PERSON_NAME',selected=True,clinical_overlap=False,text=value,
                rects=[list(name)],rule='explicit_footer_role_instruction_name',provenance='bounded_signature_form_field'))
            zone=fitz.Rect(left,top,right,name.y0+.5)
            if zone.height>=10 and not any(fitz.Rect(r).intersects(zone) for _,r in words) and not any(zone.intersects(fitz.Rect(r)) for r in image_rects):
                signatures=[list(r) for r in native_images if left<=r[0] and r[2]<=right and top-4<=r[1]<name.y0 and r[3]<=name.y1+2 and r[3]-r[1]<100]
                out.append(dict(id=f'p{pn}-footer{len(out)}',kind='SIGNATURE_IMAGE',selected=True,clinical_overlap=False,text='Vùng ký trong trường họ tên cuối biểu mẫu',
                    rects=signatures or [list(zone)],provenance='bounded_signature_form_field'))
            break
    return out


def scanned_signature_proposals(page,text,chars,proposals,pn,clinical_bands=()):
    flat,indices=_build_folded_index(text);headers=[]
    pattern=r'b[ai]c\s*(?:s[iyjs]?[\W_]*\s*)?(?:(?:dieu|dibu)\s*tri|lam\s*benh\s*[ai]n)|nguoi\s*(?:giao|nhan)\s*ho\s*s[oc]'
    for m in re.finditer(pattern,flat):
        a,b=indices[m.start()],indices[m.end()-1]+1;boxes=span_rects(chars,a,b)
        if not boxes:continue
        header=fitz.Rect(boxes[0])
        for r in boxes[1:]:header|=fitz.Rect(r)
        if header.y0>page.rect.height*.55:headers.append((header,a,b,max((r[1]+r[3])/2 for r in boxes)))
    out=[]
    for q in proposals:
        if not q['selected'] or q['kind'] not in {'HEALTHCARE_STAFF_NAME','PERSON_NAME','RELATIVE_NAME'}:continue
        for values in q['rects']:
            name=fitz.Rect(values)
            candidates=[h for h in headers if 20<=name.y0-h[0].y1<=160 and abs((h[0].x0+h[0].x1-name.x0-name.x1)/2)<80]
            if not candidates:continue
            header,ha,hb,last_line_mid=max(candidates,key=lambda h:h[0].y1);center=(name.x0+name.x1)/2
            clip=fitz.Rect(max(0,min(header.x0,center-75)),header.y0,min(page.rect.x1,max(header.x1,center+75)),min(page.rect.y1,header.y1+20))
            pix=page.get_pixmap(dpi=200,clip=clip,colorspace=fitz.csGRAY,alpha=False);samples=pix.samples
            top=header.y1+6;blank=0;gap_end=None
            for y in range(max(0,int(last_line_mid*200/72)-pix.y),pix.height):
                blank=blank+1 if sum(v<220 for v in samples[y*pix.stride:y*pix.stride+pix.width])<3 else 0
                if blank>=3:gap_end=y+1;break
            # Preserve the label margin unless a sustained signature stroke starts inside it.
            run=None;missing=0
            for y in range(gap_end if gap_end is not None else pix.height,pix.height):
                if sum(v<220 for v in samples[y*pix.stride:y*pix.stride+pix.width])>=3:
                    if run is None:run=y
                    missing=0
                    if y-run>=7*200/72 and (pix.y+run)*72/200<top:
                        top=max((pix.y+gap_end)*72/200,(pix.y+run)*72/200-.75);break
                else:
                    missing+=1
                    if missing>=3:run=None
            zone=fitz.Rect(max(0,center-75),top,min(page.rect.width,center+75),name.y0-2)
            for label in re.finditer(r'(?im)[^\n]*(?:ghi|ng[aàåä]y)[^\n]*',text):
                for box in span_rects(chars,label.start(),label.end()):
                    if fitz.Rect(box).intersects(zone):zone.y0=max(zone.y0,box[3]+2)
            if zone.height<10 or any(zone.y0<bottom and zone.y1>top for top,bottom in clinical_bands):continue
            if any(fitz.Rect(r).intersects(zone) for word in re.finditer(r'\S+',text) if not ha<=word.start()<hb for r in span_rects(chars,word.start(),word.end())):continue
            out.append(dict(id=f'p{pn}-scanrole{len(out)}',kind='SIGNATURE_IMAGE',text='Vùng ký giữa chức danh và họ tên đã xác nhận',
                rects=[[round(v,3) for v in zone]],selected=True,clinical_overlap=False,provenance='bounded_role_name_signature'))
    return out

def patient_name_value_rect(text, chars, page_rect):
    """Only an explicit name field with a same-line next label has safe value bounds."""
    anchor=re.search(r'(?i)\(\s*in\s*hoa\s*\)\s*[:：]',text)
    if not anchor:return None
    prefix=text[max(0,anchor.start()-35):anchor.start()]
    if not re.search(r'(?i)(?:h[oọq.]*|10)\s*t[eêéè]n\s*$',prefix):return None
    labels=span_rects(chars,anchor.start(),anchor.end())
    boundary=_FIELD_BOUNDARY.search(text,anchor.end())
    if not labels or not boundary:return None
    fields=span_rects(chars,boundary.start(),min(len(text),boundary.end()+5))
    label=fitz.Rect(labels[-1])
    if not fields or abs(fields[0][1]-label.y0)>=10:return None
    r=fitz.Rect(label.x1+2,max(0,label.y0-4),fields[0][0]-1,min(page_rect.height,label.y1))
    values=[bb for off,_,bb,ch in chars if anchor.end()<=off<boundary.start() and ch.strip() and bb[0]>=r.x0 and bb[2]<=r.x1 and bb[1]<label.y1 and bb[3]>label.y0]
    if values and min(bb[0] for bb in values)-r.x0<=3*max(bb[3]-bb[1] for bb in values):r.y1=min(r.y1,max(bb[3] for bb in values))
    if r.is_empty or r.width>page_rect.width*.5 or not page_rect.contains(r):return None
    return [round(v,3) for v in r]


def signature_table_columns(text,chars,page_rect):
    folded=_strip_accents(text.lower())
    if not re.search(r'theo\s*doi',folded) or not re.search(r'cham\s*s[oa]c',folded):return []
    headers=list(re.finditer(r'(?i)\bk[yýsi5eéê]\s*t[eêéo]n\b',text));result=[]
    for header in headers:
        boxes=span_rects(chars,header.start(),header.end())
        if len(boxes)!=1:continue
        box=fitz.Rect(boxes[0])
        if box.x0<page_rect.width*.65:continue
        neighbours=[bb[2] for _,_,bb,ch in chars if ch.strip() and bb[2]<box.x0-4 and bb[1]<box.y1 and bb[3]>box.y0]
        if not neighbours:continue
        left=(max(neighbours)+box.x0)/2
        result.append((left,box.y1))
    return result


def signature_column_proposals(text, chars, page_rect,*,page=None,mask_cells=False):
    """Names inside the explicitly labelled signature column of a care table."""
    from hmu_recognizers import _ocr_word_regex
    result=[];columns=[(left,page_rect.x1,top,page_rect.y1) for left,top in signature_table_columns(text,chars,page_rect)] if page is None else []
    flat,indices=_build_folded_index(text)
    roles=r'\bk[yse]\s*t[eo]n\b'
    if re.search(r'ten\s*dich\s*truy[eo]n',flat):roles+=r'|di[eob]u\s*du[o&0u•]*ng|b[ai]c\s*si\b'
    headers=[fitz.Rect(r) for m in re.finditer(roles,flat) for r in span_rects(chars,indices[m.start()],indices[m.end()-1]+1) if r[0]>page_rect.width*.6]
    if page is not None and headers:
        pix=page.get_pixmap(dpi=150,colorspace=fitz.csGRAY,alpha=False);samples=pix.samples_mv;stride=pix.stride;s=150/72;physical=[]
        for header in headers:
            y0=max(0,int(header.y0*s));y1=min(pix.height,int((header.y1+35)*s));walls=[]
            for x in range(int(page_rect.width*.55*s),pix.width):
                if y1-y0>30 and sum(samples[y*stride+x]<190 for y in range(y0,y1))>.8*(y1-y0):
                    if not walls or x-walls[-1][-1]>2:walls.append([x])
                    else:walls[-1].append(x)
            edges=[sum(w)/len(w)/s for w in walls];center=(header.x0+header.x1)/2
            cell=next(((a,b) for a,b in zip(edges,edges[1:]) if a<center<b and 30<b-a<page_rect.width*.4),None)
            if cell is None:continue
            left,right=cell;x0=int((left+2)*s);x1=int((right-2)*s)
            bottoms=[y/s for y in range(int(header.y1*s),min(pix.height,int((header.y1+35)*s))) if sum(samples[y*stride+x]<190 for x in range(x0,x1))>.8*(x1-x0)]
            if not bottoms:continue
            start=int(min(bottoms)*s);end=start;missing=0
            for y in range(start,pix.height):
                both=all(any(samples[y*stride+x]<190 for x in range(max(0,int(wall*s)-2),min(pix.width,int(wall*s)+3))) for wall in (left,right))
                if both:end=y;missing=0
                else:missing+=1
                if missing>=8:break
            physical.append((left+.2,right-.2,min(bottoms)+2,end/s))
        if physical:columns=physical
    cell_segments=None
    for left,right,top,bottom in columns:
        blocked=[]
        if page is not None:
            protected=[r for _,a,b,_ in protected_hits(text) for r in span_rects(chars,a,b)]
            if mask_cells:
                if cell_segments is None:cell_segments=signature_cell_segments(page)
                # A row rule continues into a neighbouring column; identity ink cannot prove its own border.
                edges=sorted({round(y,1) for kind,y,a,b in cell_segments if kind=='h' and a<=left+2 and b>=right-2
                    and (a<left-10 or b>right+10) and top-3<=y<=bottom+2})
                edges=[y for i,y in enumerate(edges) if not i or y-edges[i-1]>2]
                for upper,lower in zip(edges,edges[1:]):
                    cell=fitz.Rect(left+1.3,upper+1.5,right-1.3,lower-1.5)
                    if cell.height<5:continue
                    overlap=any(cell.intersects(fitz.Rect(r)) for r in protected)
                    labelled=any(cell.intersects(header) for header in headers)
                    guarded=overlap or labelled
                    if guarded:blocked.append(cell)
                    result.append(dict(kind='HEALTHCARE_STAFF_NAME' if guarded else 'SIGNATURE_REGION',
                        text='Ô định danh có nhãn/nội dung cần giữ: cần duyệt' if guarded else 'Ô họ tên/ký có khung và nhãn định danh',
                        rects=[list(cell)],selected=not guarded,
                        clinical_overlap=guarded,score=.99,rule=('identity_cell_clinical_review' if overlap else 'identity_cell_label_review') if guarded else 'explicit_identity_column_cell',
                        provenance='identity_header_and_closed_native_cell'))
            for info in page.get_image_info():
                image=fitz.Rect(info['bbox'])*page.rotation_matrix
                if not (left<=image.x0 and image.x1<=right and top<image.y0 and image.y1<bottom):continue
                if any(image.intersects(r) for r in blocked):continue
                if any(image.intersects(fitz.Rect(r)) for r in protected):continue
                if cell_segments is None:cell_segments=signature_cell_segments(page)
                if not image_in_signature_cell(page,image,top-2,_pix=pix,_segments=cell_segments):continue
                result.append(dict(kind='SIGNATURE_IMAGE',text='Ảnh ký trong cột định danh có khung bảng',rects=[list(image)],selected=True,
                    clinical_overlap=False,score=.99,rule='explicit_identity_cell_signature_image',provenance='identity_header_and_enclosing_cell'))
        lines={}
        for c in chars:
            if c[2][0]>=left and c[2][2]<=right and c[2][1]>top+2 and c[2][3]<bottom:lines.setdefault(c[1],[]).append(c)
        rows=[]
        for values in lines.values():
            values.sort();parts=[];previous=None
            for off,_,_,ch in values:
                if previous is not None and off>previous+1:parts.append(' ')
                parts.append(ch);previous=off
            value=''.join(parts).strip()
            if value:rows.append([value,values])
        rows.sort(key=lambda r:min(c[2][1] for c in r[1]))
        i=0
        while i<len(rows):
            value,values=rows[i];i+=1;value=_NAME_START.sub('',value).strip();tokens=value.split()
            if not tokens:continue
            first=_strip_accents(tokens[0].lower())
            if not any(re.fullmatch(_ocr_word_regex(s),first,re.I) for s in SURNAMES):continue
            if len(tokens)<=2 and i<len(rows):
                extra,next_chars=rows[i]
                y1=max(c[2][3] for c in values);height=max(c[2][3]-c[2][1] for c in values)
                if len(extra.split())<=2 and 0<=min(c[2][1] for c in next_chars)-y1<=2*height:
                    value+=' '+extra;values+=next_chars;i+=1
            if not 3<=len(value.split())<=5 or not _valid('HEALTHCARE_STAFF_NAME',value):continue
            if sum(t[0].isupper() for t in value.split())<len(value.split())-1:continue
            rects=span_rects(values,min(c[0] for c in values),max(c[0] for c in values)+1)
            if any(fitz.Rect(r).intersects(cell) for r in rects for cell in blocked):continue
            result.append(dict(kind='HEALTHCARE_STAFF_NAME',text=value,rects=rects,selected=True,
                clinical_overlap=False,score=.99,rule='explicit_care_signature_column',provenance='Tên trong cột ký tên của phiếu chăm sóc'))
    return result


def expand_rects_with_pixel_ink(page, rects, max_expand_pt=75.0, max_x1=None, *, barriers=(), _display_list=None):
    """Scan pixel raster of page rightward from each rect to cover any word-drop ink (e.g. 'Lộc', 'Cường')."""
    if not rects:
        return []
    p_rect = page.rect
    limit_x1 = (max_x1 if max_x1 is not None else (p_rect.width - 20.0))
    dpi = 150
    scale = dpi / 72.0
    expanded_rects = []

    for r in rects:
        fr = fitz.Rect(r)
        limit_x1 = min([max_x1 if max_x1 is not None else p_rect.width - 20.0] +
                       [bb[0] - 1.0 for bb in barriers if bb[0] >= fr.x1 and bb[1] < fr.y1 and bb[3] > fr.y0])
        if fr.x1 >= limit_x1 - 2.0:
            expanded_rects.append([round(v, 3) for v in fr])
            continue
        # Probe a band immediately to the right of fr.x1
        probe_w = min(max_expand_pt, limit_x1 - fr.x1)
        if probe_w <= 3.0:
            expanded_rects.append([round(v, 3) for v in fr])
            continue
        probe_rect = fitz.Rect(fr.x1 - 1.0, max(0.0, fr.y0 - 2.0), fr.x1 + probe_w, min(p_rect.height, fr.y1 + 2.0))
        try:
            pix = (_display_list.get_pixmap(matrix=fitz.Matrix(scale,scale), clip=probe_rect, alpha=False)
                   if _display_list is not None else page.get_pixmap(dpi=dpi, clip=probe_rect, alpha=False))
            pw, ph = pix.width, pix.height
            if pw <= 2 or ph <= 2:
                expanded_rects.append([round(v, 3) for v in fr])
                continue
            samples = pix.samples
            n = pix.n
            col_has_ink = []
            for col in range(pw):
                dark_pixels = 0
                for row in range(ph):
                    idx = (row * pw + col) * n
                    # Pixel luminance < 210 indicates non-white stroke/ink
                    lum = 0.299 * samples[idx] + 0.587 * samples[idx + 1] + 0.114 * samples[idx + 2]
                    if lum < 210:
                        dark_pixels += 1
                        break
                col_has_ink.append(dark_pixels >= 1)

            # Find trailing contiguous ink groups (allow gap up to ~14pt / 29px space between words)
            max_gap_px = int(14.0 * scale)
            last_ink_px = 0
            cur_gap = 0
            found_any = False
            for col_idx, has_ink in enumerate(col_has_ink):
                if has_ink:
                    last_ink_px = col_idx
                    cur_gap = 0
                    found_any = True
                else:
                    cur_gap += 1
                    if cur_gap > max_gap_px:
                        break

            if found_any and last_ink_px > int(3.0 * scale):
                add_pt = last_ink_px / scale + 3.0
                new_x1 = min(limit_x1, fr.x1 + add_pt)
                fr.x1 = max(fr.x1, new_x1)
        except Exception:
            pass
        expanded_rects.append([round(v, 3) for v in fr])
    return expanded_rects


def labelled_footer_name_rects(text,chars,rects,page_rect):
    result=[list(r) for r in rects]
    for m in re.finditer(r'(?i)\bh[oọq][ \t]*(?:v[aàäå][ \t]*)?t[eêéèiaâă]n[ \t]*[:：]?',text):
        labels=span_rects(chars,m.start(),m.end())
        if len(labels)!=1:continue
        label=fitz.Rect(labels[0])
        if label.y0<page_rect.height*.55:continue
        for r in result:
            if 0<r[0]-label.x1<100 and min(r[3],label.y1)-max(r[1],label.y0)>.5*min(r[3]-r[1],label.height):
                candidate=fitz.Rect(min(r[0],label.x1+3),r[1],r[2],min(page_rect.y1,r[3]+4))
                if any(ch.strip() and candidate.intersects(fitz.Rect(bb)) and not any(fitz.Rect(old).intersects(fitz.Rect(bb)) for old in rects)
                       for off,_,bb,ch in chars if not m.start()<=off<m.end()):continue
                r[0]=candidate.x0;r[3]=candidate.y1
    return result


def pad_name_rects(rects,barriers,images=()):
    out=[]
    for r in rects:
        if any((fitz.Rect(r)+(-2,-2,2,2)).intersects(fitz.Rect(image)) for image in images):out.append(list(r));continue
        a,b,c,d=r[0]-.75,r[1]-3,r[2]+.75,r[3]+3
        for x0,y0,x1,y1 in barriers:
            if x0<r[2] and x1>r[0] and y0<r[3] and y1>r[1]:continue
            if y0<d and y1>b:
                if x1<=r[0]:a=max(a,min(r[0],x1+.4))
                if x0>=r[2]:c=min(c,max(r[2],x0-.4))
            if x0<c and x1>a:
                if y1<=r[1]:b=max(b,min(r[1],y1+3))
                if y0>=r[3]:d=min(d,max(r[3],y0-3))
        out.append([round(v,3) for v in (a,b,c,d)])
    return out


def name_in_single_table_cell(page,rects):
    if not rects:return False
    r=fitz.Rect(rects[0])
    for box in rects[1:]:r|=fitz.Rect(box)
    pix=page.get_pixmap(dpi=150,colorspace=fitz.csGRAY,alpha=False);samples=pix.samples_mv;stride=pix.stride;s=150/72
    y0=max(0,int((r.y0-30)*s));y1=min(pix.height,int((r.y1+30)*s));walls=[]
    for x in range(pix.width):
        if y1-y0>=50 and sum(samples[y*stride+x]<190 for y in range(y0,y1))>.85*(y1-y0):walls.append(x/s)
    return bool(any(x<r.x0 for x in walls) and any(x>r.x1 for x in walls) and not any(r.x0+.2<x<r.x1-.2 for x in walls))


def clip_text_masks_to_grid(page,rects,*,_pix=None):
    """OCR word boxes may include a table edge; a long continuous stroke bounds the cell."""
    pix=_pix or page.get_pixmap(dpi=150,colorspace=fitz.csGRAY,alpha=False)
    scale=150/72;samples=pix.samples;stride=pix.stride;result=[]
    for values in rects:
        r=fitz.Rect(values)
        y0=max(0,int((r.y0-30)*scale));y1=min(pix.height,int((r.y1+30)*scale))
        lines=[]
        main0=max(y0,int(r.y0*scale));main1=min(y1,int(r.y1*scale)+1)
        for x in range(max(0,int((r.x0-2)*scale)),min(pix.width,int((r.x1+2)*scale))):
            dark=lambda a,b: b>a and sum(samples[y*stride+x]<190 for y in range(a,b))>.85*(b-a)
            if dark(main0,main1) and ((main0-y0>=30 and dark(y0,main0)) or (y1-main1>=30 and dark(main1,y1))):lines.append(x)
        parts=[r]
        for x in lines:
            a,b=(x-1)/scale,(x+2)/scale;next_parts=[]
            for part in parts:
                if b<=part.x0 or a>=part.x1:next_parts.append(part);continue
                if a>part.x0:next_parts.append(fitz.Rect(part.x0,part.y0,a,part.y1))
                if b<part.x1:next_parts.append(fitz.Rect(b,part.y0,part.x1,part.y1))
            parts=next_parts
        x0=max(0,int((r.x0-30)*scale));x1=min(pix.width,int((r.x1+30)*scale))
        for y in range(max(0,int((r.y0-2)*scale)),min(pix.height,int((r.y1+2)*scale))):
            run=longest=0
            for x in range(x0,x1):
                run=run+1 if samples[y*stride+x]<190 else 0;longest=max(longest,run)
            if longest<20*scale:continue
            main0=max(0,int(r.x0*scale));main1=min(pix.width,int(r.x1*scale)+1)
            if sum(samples[y*stride+x]<190 for x in range(main0,main1))<.85*(main1-main0):continue
            a,b=(y-1)/scale,(y+2)/scale;next_parts=[]
            for part in parts:
                if b<=part.y0 or a>=part.y1:next_parts.append(part);continue
                if a>part.y0:next_parts.append(fitz.Rect(part.x0,part.y0,part.x1,a))
                if b<part.y1:next_parts.append(fitz.Rect(part.x0,b,part.x1,part.y1))
            parts=next_parts
        result.extend([round(v,3) for v in part] for part in parts if not part.is_empty)
    return result


def signature_cell_segments(page):
    segments=[];horizontal={};matrix=page.rotation_matrix;rotated=bool(page.rotation)
    for drawing in page.get_cdrawings():
        for item in drawing['items']:
            if item[0]=='l':pairs=[(item[1],item[2])]
            elif item[0]=='re':
                r=fitz.Rect(item[1]);pairs=[(r.tl,r.tr),(r.tr,r.br),(r.br,r.bl),(r.bl,r.tl)]
            else:continue
            for a,b in pairs:
                if rotated:a=fitz.Point(a)*matrix;b=fitz.Point(b)*matrix
                if abs(a[0]-b[0])<.02 and abs(a[1]-b[1])>20:segments.append(('v',a[0],min(a[1],b[1]),max(a[1],b[1])))
                if abs(a[1]-b[1])<.02 and abs(a[0]-b[0])>.1:
                    horizontal.setdefault(round(a[1],2),[]).append((min(a[0],b[0]),max(a[0],b[0])))
    # Dotted table rules are many short vector segments, not a single long line.
    for y,parts in horizontal.items():
        left=right=None
        for a,b in sorted(parts):
            if right is not None and a>right+2:
                if right-left>20:segments.append(('h',y,left,right))
                left=right=None
            left=a if left is None else left;right=max(b,right if right is not None else b)
        if right is not None and right-left>20:segments.append(('h',y,left,right))
    return segments


def image_in_signature_cell(page,image,header_bottom,*,_pix=None,_segments=None):
    segments=_segments if _segments is not None else signature_cell_segments(page)
    vertical=[s for s in segments if s[0]=='v' and s[2]<=image.y0 and s[3]>=image.y1]
    horizontal=[s for s in segments if s[0]=='h' and s[2]<=image.x0 and s[3]>=image.x1]
    if (any(s[1]<=image.x0 for s in vertical) and any(s[1]>=image.x1 for s in vertical)
        and any(header_bottom<=s[1]<=image.y0 for s in horizontal) and any(s[1]>=image.y1 for s in horizontal)):return True
    pix=_pix or page.get_pixmap(dpi=150,colorspace=fitz.csGRAY,alpha=False);samples=pix.samples_mv;stride=pix.stride;s=150/72
    top=max(0,int(header_bottom*s));bottom=min(pix.height,int(image.y1*s)+1)
    if bottom-top<30:return False
    def vertical_border(a,b):
        return any(sum(samples[y*stride+x]<190 for y in range(top,bottom))>.85*(bottom-top)
            for x in range(max(0,int(a*s)),min(pix.width,int(b*s)+1)))
    x0=max(0,int(image.x0*s));x1=min(pix.width,int(image.x1*s)+1)
    def horizontal_border(a,b):
        return any(sum(samples[y*stride+x]<190 for x in range(x0,x1))>.85*(x1-x0)
            for y in range(max(0,int(a*s)),min(pix.height,int(b*s)+1)))
    return (vertical_border(image.x0-10,image.x0-1) and vertical_border(image.x1+1,image.x1+10)
        and horizontal_border(header_bottom,image.y0-1) and horizontal_border(image.y1+1,image.y1+40))

def merge_and_subsume_proposals(proposals):
    """Subsume smaller proposal boxes completely inside larger ones on the same line to avoid clutter."""
    if len(proposals) <= 1:
        return proposals
    # Filter proposals whose all rects are strictly contained inside another proposal's rects
    kept = []
    # Sort proposals by total area descending so larger containers come first
    def _box_area(q):
        return sum((r[2] - r[0]) * (r[3] - r[1]) for r in q.get('rects', []))

    sorted_props = sorted(proposals, key=lambda q: (q.get('selected', False), _box_area(q)), reverse=True)

    for i, p_curr in enumerate(sorted_props):
        curr_rects = [fitz.Rect(r) for r in p_curr.get('rects', [])]
        if not curr_rects:
            continue
        subsumed = False
        for p_parent in kept:
            # Only subsume if both are selected or both unselected
            if p_curr.get('selected') != p_parent.get('selected'):
                continue
            if p_curr.get('kind') != p_parent.get('kind'):
                continue
            parent_rects = [fitz.Rect(r) for r in p_parent.get('rects', [])]
            # Check if each rect of p_curr is within 2pt of some parent rect
            all_inside = True
            for cr in curr_rects:
                inside_any = any(
                    (cr.x0 >= pr.x0 - 3.0 and cr.x1 <= pr.x1 + 3.0 and cr.y0 >= pr.y0 - 3.0 and cr.y1 <= pr.y1 + 3.0)
                    for pr in parent_rects
                )
                if not inside_any:
                    all_inside = False
                    break
            if all_inside:
                subsumed = True
                break
        if not subsumed:
            kept.append(p_curr)

    # Re-sort back to stable visual order (page top-to-bottom, left-to-right)
    return sorted(kept, key=lambda q: (min(r[1] for r in q['rects']), min(r[0] for r in q['rects'])))

def barcode_rects(page, drawings=None):
    groups = collections.defaultdict(list)
    for d in (page.get_drawings() if drawings is None else drawings):
        r = fitz.Rect(d['rect'])
        if d.get('fill') is not None and r.width < 5 and r.height >= 10:
            groups[(round(r.y0), round(r.y1))].append(r)
    out = []
    for rs in groups.values():
        rs = sorted(rs, key=lambda r: r.x0); clusters = []
        for r in rs:
            if not clusters or r.x0 - clusters[-1][-1].x1 > 8:
                clusters.append([r])
            else:
                clusters[-1].append(r)
        for group in clusters:
            if len(group) >= 15:
                rect = fitz.Rect(group[0])
                for r in group[1:]:
                    rect |= r
                out.append([round(v, 3) for v in (rect*page.rotation_matrix)])
    return out

def _precompile_additional_seeds(seeds):
    """Precompile regex patterns for additional_findings once per document instead of per page."""
    exact_compiled = []
    folded_compiled = []
    phone_compiled = []

    for kind, values in (seeds or {}).items():
        if kind=='YEAR_OF_BIRTH':continue  # A known year can also be a treatment year; require a birth label.
        for value in values:
            if not value or len(value) < 3:
                continue
            exact_compiled.append((kind, _exact_flexible_pattern(value)))

    for seed_kind in ('PATIENT_NAME', 'HEALTHCARE_STAFF_NAME', 'RELATIVE_NAME', 'PERSON_NAME', 'ADDRESS_VN'):
        for value in (seeds or {}).get(seed_kind, []):
            if len(value.split()) < 2:
                continue
            simple = _strip_accents(value.lower())
            folded_compiled.append((seed_kind, _exact_flexible_pattern(simple), .93, 'workflow_known_accent_variant_review'))
            parts = simple.split()
            if seed_kind == 'PATIENT_NAME':
                compact_chars = re.sub(r'\s+', '', simple)
                if len(compact_chars) >= 5:
                    ocr_pat = re.compile(r'(?<!\w)' + r'[ \t\-._]*'.join(re.escape(c) for c in compact_chars) + r'(?!\w)', re.I)
                    folded_compiled.append(('PATIENT_NAME', ocr_pat, .94, 'workflow_ocr_fuzzy_patient_name'))
                if len(parts) >= 3:
                    short_pat = re.compile(r'(?<!\w)' + re.escape(parts[0]) + r'[ \t]+' + re.escape(parts[-1]) + r'(?!\w)', re.I)
                    folded_compiled.append(('PATIENT_NAME', short_pat, .92, 'workflow_ocr_short_patient_name'))

    for value in (seeds or {}).get('PHONE_NUMBER_VN', []):
        digits = re.sub(r'\D', '', value)
        if 9 <= len(digits) <= 12:
            phone_compiled.append(re.compile(r'(?<!\w)' + r'[ \t.-]*'.join(digits) + r'(?!\w)'))

    return exact_compiled, folded_compiled, phone_compiled

def additional_findings(text, seeds, _precompiled=None):
    from hmu_recognizers import split_address_findings
    findings = []
    # Note: SOURCE_LINK_ID, PATIENT_ID, MEDICAL_RECORD_ID are preserved for post-inspection (hậu kiểm).
    patterns = [
        ('ACCESS_CREDENTIAL', r'(?im)(?:tài\s*khoản|mật\s*khẩu)\s*:[ \t\xa0]*(?:\n[ \t\xa0]*)?([A-Za-z0-9._@-]{3,64})(?!\w)'),
        ('NATIONAL_ID', r'(?im)(?:số\s*CMTND/số\s*hộ\s*chiếu/Căn\s*cước|số\s*CMTND|Căn\s*cước)\s*:\s*(\d{9,12})(?!\d)'),
        ('CONTACT_PHONE', r'(?im)(?:số\s*ĐT|số\s*điện\s*thoại|điện\s*thoại(?:\s*số|\s*cá\s*nhân)?|di[eệ]n\s*(?:tho[aạ]i)?)\s*[:.\-]?\s*((?:0|\+84)(?:[ .-]?\d){8,10})'),
        ('HEALTHCARE_STAFF_NAME', r'(?im)(?:k[yý]\s*s[oố]\s*b[oở]i|ng[uư][oờ]i\s*k[iíyý]|tôi\s*tên\s*là)\s*:\s*([^\n,;:]+)'),
        ('EMAIL', r'(?i)(?<![\w.-])([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})(?!\w)'),
        ('ADDRESS_VN', r'(?im)(?:x[aã]\s*,?\s*ph[uư][oờ]ng|th[oô]n\s*,?\s*ph[oố6]|s[oố]\s*nh[aà]|đ[uư][oờ]ng\s*ph[oố]|t[iỉ]nh\s*[.,]?\s*(?:th[aà]nh\s*)?ph[oố]|diachi|đ[iị]a\s*ch[iỉ])\s*[:.\-]*[ \t\xa0]*([^\n:]{3,100})'),
    ]
    for kind, pattern in patterns:
        for m in re.finditer(pattern, text):
            a, b = m.span(1); v = text[a:b].rstrip(); b = a + len(v)
            if kind == 'ACCESS_CREDENTIAL' and not any(c.isdigit() for c in v):
                continue
            if kind == 'HEALTHCARE_STAFF_NAME':
                stripped = _NAME_START.sub('', v)
                a += len(v) - len(stripped)
                v = stripped.strip()
                b = a + len(v)
                if not re.fullmatch(PERSON_NAME, v) or not _valid('HEALTHCARE_STAFF_NAME', v):
                    continue
            if kind == 'ADDRESS_VN':
                # Stop before "Tuổi:" or "Giới tính:" if on same line
                boundary = _FIELD_BOUNDARY.search(text,a)
                split_v = text[a:min(b,boundary.start())].rstrip() if boundary else v
                v = split_v
                b = a + len(v)
                if not _valid('ADDRESS_VN', v):
                    continue
            if v:
                findings.append(Finding(kind, a, b, .95, v, 'workflow_label_or_contact'))

    for m in re.finditer(r'(?m)^[ \t\xa0]*([^\n]+?)[ \t\xa0]*$', text):
        raw = m.group(1)
        if WATERMARK_RE.match(raw):
            continue
        v = raw.strip(); parts = v.split()
        if (2 <= len(parts) <= 7 and _strip_accents(parts[0].lower()) in SURNAMES and all(t[0].isupper() for t in parts)
                and v not in {'Hà Nội', 'Hồ Chí Minh', 'Cao HA', 'Việt Nam', 'Viet Nam', 'Thanh Hóa', 'Thanh Hoa', 'Quảng Trị', 'Ninh Bình'}
                and re.fullmatch(PERSON_NAME, v) and _valid('HEALTHCARE_STAFF_NAME', v)):
            a = m.start(1) + len(raw) - len(raw.lstrip())
            findings.append(Finding('PERSON_NAME', a, a + len(v), .75, v, 'workflow_unlabelled_name_review:CONTEXT_REQUIRED_REVIEW', 'CONTEXT_REQUIRED'))

    if not seeds and not _precompiled:
        return split_address_findings(text,findings)

    exact_compiled, folded_compiled, phone_compiled = _precompiled or _precompile_additional_seeds(seeds)

    for kind, rx in exact_compiled:
        for m in rx.finditer(text):
            findings.append(Finding(kind, m.start(), m.end(), .96, m.group(), 'workflow_document_known_review'))

    if folded_compiled and text:
        folded = []; indices = []
        for i, ch in enumerate(text):
            chars = _strip_accents(ch.lower())
            for c in chars:
                folded.append(c); indices.append(i)
        flat = ''.join(folded)

        for seed_kind, rx, score, rule_name in folded_compiled:
            for m in rx.finditer(flat):
                a, b = indices[m.start()], indices[m.end() - 1] + 1
                while b < len(text) and unicodedata.combining(text[b]):
                    b += 1
                findings.append(Finding(seed_kind, a, b, score, text[a:b], rule_name))

    for rx in phone_compiled:
        for m in rx.finditer(text):
            findings.append(Finding('PHONE_NUMBER_VN', m.start(), m.end(), .95, m.group(), 'workflow_known_phone_review'))
    for f in findings:
        if (f.entity_type in {'PATIENT_NAME','RELATIVE_NAME','HEALTHCARE_STAFF_NAME','PERSON_NAME'}
                and f.rule in {'workflow_document_known_review','workflow_known_accent_variant_review','workflow_ocr_fuzzy_patient_name','workflow_ocr_short_patient_name'}
                and not _person_name_context(text,f.start,f.text)):
            f.score=.75;f.review_status='CONTEXT_REQUIRED';f.rule+=':CONTEXT_REQUIRED_REVIEW'
    return split_address_findings(text,findings)

def vector_qr_rects(page, drawings=None):
    squares = []
    for drawing in (page.get_drawings() if drawings is None else drawings):
        # Outlined glyphs can have square bounds; curved letter paths are not QR modules.
        if any(item[0]=='c' for item in drawing.get('items',())): continue
        fill = drawing.get('fill')
        if not fill or max(fill) >= .4: continue
        r = tuple(drawing['rect']); width=r[2]-r[0]; height=r[3]-r[1]
        if 1 <= width <= 8 and 1 <= height <= 8 and abs(width-height) < .3:
            squares.append(r)
    groups = []
    while squares:
        cluster = [squares.pop()]; bounds = cluster[0]; changed = True
        while changed:
            changed = False; remaining = []
            for r in squares:
                pad = max(r[2]-r[0],r[3]-r[1]) * 2.1
                if bounds[0]-pad < r[2] and r[0] < bounds[2]+pad and bounds[1]-pad < r[3] and r[1] < bounds[3]+pad:
                    cluster.append(r)
                    bounds=(min(bounds[0],r[0]),min(bounds[1],r[1]),max(bounds[2],r[2]),max(bounds[3],r[3])); changed = True
                else:
                    remaining.append(r)
            squares = remaining
        if len(cluster) >= 80 and .75 < (bounds[2]-bounds[0])/(bounds[3]-bounds[1]) < 1.35:
            groups.append([round(v, 3) for v in (fitz.Rect(bounds)*page.rotation_matrix)])
    return groups

def rotated_watermark_rects(page):
    """Detect rotated watermark spans (e.g. Hồ Thị Minh Châu_20260803161916) directly from page dict."""
    out = []
    for b in page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in b.get('lines', []):
            if abs(line['dir'][1]) > .1:
                txt = ''.join(s['text'] for s in line['spans']).strip()
                if WATERMARK_RE.fullmatch(txt):
                    out.append((txt, [round(v, 3) for v in (fitz.Rect(line['bbox'])*page.rotation_matrix)]))
    return out

def boxed_dob_and_bhyt_proposals(page, chars, text, start_idx=0):
    """Detect 8-box split DOB (1|5|1|0|1|9|5|8) and scanned DOB box strips while strictly protecting Age boxes."""
    proposals = []
    # Find Age column x0 on cover pages ("Tuổi" / "Tuôi" / "Tubi" / "Tuöi")
    age_x0 = min(page.rect.width * 0.85, 515.0)
    age_labels = []
    for m_age in re.finditer(r'(?i)\b(?:tu[oôơöổ]i|tubi|tudi)\b', text):
        rs = span_rects(chars, m_age.start(), m_age.end())
        age_labels.extend(rs)
        if rs and rs[0][0] > page.rect.width * .65 and rs[0][1] < 220:
            age_x0 = min(age_x0, rs[0][0] - 4.0)

    # Search for "2. Sinh ngày" / "2. Ngày sinh" / OCR "2.Sinh ngäy" in top administrative section
    for m_dob in re.finditer(r'(?i)(?:2\s*[.,_]?\s*)?(?:sinh\s*ng[aàäå]y|ng[aàäå]y\s*sinh|2\s+sinh)\s*[:.]?', text):
        rs = span_rects(chars, m_dob.start(), m_dob.end())
        if not rs:
            continue
        lbl = rs[0]
        if lbl[1] > 260:
            continue
        row_y0, row_y1 = lbl[1] - 4.0, lbl[3] + 5.0
        row_age_x0 = min([age_x0] + [r[0] - 4.0 for r in age_labels
                                   if r[0] > lbl[2] and lbl[1] - 30 <= r[3] and r[1] <= row_y1])
        # Collect any digit characters on the same horizontal row between label end and row_age_x0
        digit_rects = []
        digit_chars = []
        for offset, line_id, bbox, ch in chars:
            if ch.isdigit() and bbox[0] >= lbl[2] - 2.0 and bbox[2] <= row_age_x0 - 4.0:
                yc = 0.5 * (bbox[1] + bbox[3])
                if row_y0 <= yc <= row_y1:
                    digit_rects.append(fitz.Rect(bbox))
                    digit_chars.append(ch)
        if len(digit_rects) >= 4:
            union = digit_rects[0]
            for dr in digit_rects[1:]:
                union |= dr
            union.x1 = min(union.x1, row_age_x0 - 5.0)
            proposals.append({
                'id': f'p-dob-box-{start_idx + len(proposals)}',
                'kind': 'DATE_OF_BIRTH',
                'text': ''.join(digit_chars),
                'rule': 'v20_boxed_dob_preserve_age',
                'rects': [[round(v, 3) for v in union]],
                'selected': True,
                'clinical_overlap': False,
            })
        elif lbl[2] + 25.0 < row_age_x0 - 10.0:
            # Scanned cover sheet where OCR saw "2. Sinh ngày" and "Tuổi" but skipped grid box digits
            box_rect = [round(lbl[2] + 3.0, 3), round(lbl[1] - 3.0, 3), round(row_age_x0 - 8.0, 3), round(lbl[3] + 4.0, 3)]
            proposals.append({
                'id': f'p-dob-scanbox-{start_idx + len(proposals)}',
                'kind': 'DATE_OF_BIRTH',
                'text': 'Ô ngày tháng năm sinh (bảo vệ cột Tuổi)',
                'rule': 'v20_scanned_dob_box_strip',
                'rects': [box_rect],
                'selected': True,
                'clinical_overlap': False,
            })

    # Also check "Số thẻ BHYT" on cover sheet (row y < 310) to cover split BHYT boxes on that row
    for m_bh in re.finditer(r'(?i)(?:\b202\d\s+(?:s[oố6]\s*)?th[eéẻ]\b(?:\s*BHYT)?|(?:s[oố6]\s*th[eéẻ]\s*|th[eéẻ]\s*)?BHYT(?![^\n]{0,15}gi[aáå]\s*(?:tr[iị]|d[eếé]n)))', text):
        rs = span_rects(chars, max(m_bh.start(), m_bh.end() - 6), m_bh.end())
        if not rs:
            continue
        lbl = rs[-1]
        if 145 <= lbl[1] <= 310 and lbl[0] >= 250 and lbl[2] + 30 < page.rect.width - 35:
            stops = [r[0] - 1.0 for m in _FIELD_BOUNDARY.finditer(text, m_bh.end())
                     for r in span_rects(chars,m.end(),min(len(text),m.end()+18))
                     if r[0] > lbl[2] and r[1] < lbl[3] + 5 and r[3] > lbl[1] - 4]
            end_x = min([page.rect.width - 36.0] + stops)
            if end_x <= lbl[2] + 3.0:
                continue
            bh_rect = [round(lbl[2] + 3.0, 3), round(lbl[1] - 4.0, 3), round(end_x, 3), round(lbl[3] + 5.0, 3)]
            proposals.append({
                'id': f'p-bhyt-box-{start_idx + len(proposals)}',
                'kind': 'HEALTH_INSURANCE_ID',
                'text': 'Ô số thẻ BHYT (5-6 ô)',
                'rule': 'v20_boxed_bhyt_strip',
                'rects': [bh_rect],
                'selected': True,
                'clinical_overlap': False,
            })
    return proposals, age_x0

def boxed_age_proposals(page, chars, text):
    out=[]
    for m in re.finditer(r'(?i)\b(?:tu[oôơöổ]i|tubi|tudi)\b',text):
        rs=span_rects(chars,m.start(),m.end())
        if not rs: continue
        label=fitz.Rect(rs[0])
        band=fitz.Rect(max(0,label.x0-6),label.y1+1,min(page.rect.width,label.x1+30),min(page.rect.height,label.y1+34))
        pix=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=band,colorspace=fitz.csGRAY,alpha=False)
        w,h=pix.width,pix.height; grid=pix.samples.translate(bytes(1 if i<240 else 0 for i in range(256)))
        rows=[y for y in range(h) if sum(grid[y*w:(y+1)*w])>w*.5]
        if not rows: continue
        top=rows[0];bottom=next((y for y in rows if y-top>=16),None)
        if bottom is None or top>24: continue
        vertical=[x for x in range(w) if sum(grid[y*w+x] for y in range(top+3,bottom-2))>(bottom-top-5)*.85]
        edges=[]
        for x in vertical:
            if not edges or x-edges[-1][-1]>2: edges.append([x])
            else: edges[-1].append(x)
        columns=[(g[0]+g[-1])/2 for g in edges]
        if not 2<=len(columns)<=4: continue
        for left,right in zip(columns,columns[1:]):
            if not 12<=right-left<=50: continue
            rect=[(left+3)/2+band.x0,(top+3)/2+band.y0,(right-3)/2+band.x0,(bottom-3)/2+band.y0]
            out.append(dict(id=f'agebox{len(out)}',kind='PATIENT_AGE',text='Giá trị tuổi trong ô; OCR không đọc được',rule='labelled_age_grid',
                            provenance='age_anchor_and_raster_grid',rects=[rect],selected=True,clinical_overlap=False))
    return out


def nurse_signature_regions(page, chars, text, pn):
    """Use a labelled table row; raster grid detection also covers scanned/outline text."""
    folded,indices = _build_folded_index(text)
    anchors = list(re.finditer(r'di[eob]u\s*du[o&0u•]*ng|nguoi\s*(?:lap\s*)?phieu', folded))
    if not anchors or not re.search(r'ghi\s*t[eé]n', folded):
        return []
    out = []
    for anchor in anchors:
        rs = span_rects(chars, indices[anchor.start()], indices[anchor.end()-1]+1)
        if not rs:
            continue
        label = fitz.Rect(rs[0])
        band = fitz.Rect(0, max(0, label.y0 - 45), page.rect.width, min(page.rect.height, label.y1 + 240))
        pix = page.get_pixmap(matrix=fitz.Matrix(2,2), clip=band, colorspace=fitz.csGRAY, alpha=False)
        width, height = pix.width, pix.height
        ink = pix.samples.translate(bytes(1 if i < 180 else 0 for i in range(256)))
        grid = pix.samples.translate(bytes(1 if i < 240 else 0 for i in range(256)))
        horizontal = [y for y in range(height) if sum(grid[y*width:(y+1)*width]) > width * .55]
        above = [y for y in horizontal if y / 2 + band.y0 < label.y0 - 1]
        below = [y for y in horizontal if y / 2 + band.y0 > label.y1 + 8]
        if not above or not below:
            continue
        top, bottom = max(above), min(below)
        if bottom - top < 30:
            continue
        vertical = [x for x in range(width) if sum(grid[y*width+x] for y in range(top+3,bottom-2)) > (bottom-top-5)*.85]
        edges = []
        for x in vertical:
            if not edges or x-edges[-1][-1]>2: edges.append([x])
            else: edges[-1].append(x)
        columns = [(group[0]+group[-1])/2 for group in edges]
        label_cell = next(((left/2,right/2) for left,right in zip(columns,columns[1:]) if left/2 <= (label.x0+label.x1)/2 <= right/2),None)
        instructions = [r for instruction in re.finditer(r'ghi\s*ten',folded)
                        for r in span_rects(chars,indices[instruction.start()],indices[instruction.end()-1]+1)]
        if label_cell is None or not any(r[0]>=label_cell[0] and r[2]<=label_cell[1] and
                                        r[1]>=top/2+band.y0 and r[3]<=bottom/2+band.y0 for r in instructions):
            continue
        for left,right in zip(columns, columns[1:]):
            if left/2 < label.x1 or right-left < 14:
                continue
            x0,x1=int(left+4),int(right-3); y0,y1=top+4,bottom-3
            occupied = [(x,y) for y in range(y0,y1) for x in range(x0,x1) if ink[y*width+x]]
            if len(occupied) < 6:
                continue
            xs,ys=zip(*occupied)
            rect=[max(x0,min(xs)-2)/2,max(y0,min(ys)-2)/2+band.y0,
                  min(x1,max(xs)+3)/2,min(y1,max(ys)+3)/2+band.y0]
            out.append(dict(id=f'p{pn}-nurse{len(out)}',kind='SIGNATURE_REGION',text='Chữ ký/tên trong ô có nhãn; cần kiểm tra từng ô',
                            rule='nurse_signature_table_cell_ink',provenance='label_and_raster_grid',rects=[rect],selected=True,clinical_overlap=False))
    return out


def build_image_and_signature_proposals(page, chars, text, existing_proposals, pn):
    """Classify page images into Logo (keep), Clinical Image (keep), or Doctor Signature (auto-select=True)."""
    out = nurse_signature_regions(page, chars, text, pn)
    images = page.get_image_info()
    if not images:return out
    folded, offsets = _build_folded_index(text)
    clinical_bands = []
    for heading in re.finditer(r'(?m)^[ \t]*hinh\s*anh(?:[ \t]+[^\n:]{1,40})?[:：]?[ \t]*$', folded):
        labels = span_rects(chars, offsets[heading.start()], offsets[heading.end()-1]+1)
        if not labels: continue
        top = max(r[3] for r in labels)
        ends = [r[1] for end in re.finditer(r'ket\s*(?:qua|luan)|mo\s*ta',folded)
                for r in span_rects(chars,offsets[end.start()],offsets[end.end()-1]+1) if r[1]>top+4]
        if ends: clinical_bands.append((top,min(ends)))
    # Gather signature anchor rects (headings like TRƯỞNG KHOA, GIÁM ĐỐC, BÁC SĨ..., or staff names in lower half)
    sig_anchors = []
    leader_anchors = []
    bare_role = re.compile(r'(?i)\s*(?:bac\s*s[iy]|nguoi\s*(?:duyet(?:\s*ket\s*qua)?|ky|thuc\s*hien)|ky\s*so\s*boi|chu_ky_\w*)\s*[:：]?\s*')
    for m in re.finditer(r'(?m)^[^\n]+$',text):
        label=m.group().strip().rstrip(':：').strip()
        if not (_SIG_HEADING.fullmatch(label) or bare_role.fullmatch(_strip_accents(label))):continue
        rs = span_rects(chars, m.start(), m.end())
        for r in rs:
            sig_anchors.append(fitz.Rect(r))
            if re.fullmatch(r'(?i)(?:t/?l\.?\s*)?truong\s*khoa|giam\s*doc(?:\s*benh\s*vien)?',_strip_accents(label)):
                leader_anchors.append(r)
    for q in existing_proposals:
        if (q['kind'] == 'HEALTHCARE_STAFF_NAME' or (q['kind']=='RELATIVE_NAME' and all(r[1]>page.rect.height*.55 for r in q['rects']))) and q.get('selected') and q.get('review_status')!='CONTEXT_REQUIRED':
            for r in q['rects']:
                sig_anchors.append(fitz.Rect(r))

    full_page_scan = False
    signature_columns=signature_table_columns(text,chars,page.rect)
    signature_grid=page.get_pixmap(dpi=150,colorspace=fitz.csGRAY,alpha=False) if signature_columns else None
    for b in images:
        if b['width'] > 20 and b['height'] > 15:
            ib = fitz.Rect(b['bbox']) * page.rotation_matrix
            # 1. Full-page scan image
            if ib.width > page.rect.width * 0.75 and ib.height > page.rect.height * 0.75:
                full_page_scan = True
                continue
            if ib.width>40 and ib.height>30 and any(ib.y0>=top-2 and ib.y1<=bottom+2 for top,bottom in clinical_bands):
                out.append(dict(id=f'p{pn}-i{len(out)}',kind='IMAGE_REVIEW',text='Ảnh chuyên môn trong vùng Hình ảnh/Kết quả - giữ nguyên',
                                rects=[[round(v,3) for v in ib]],selected=False,clinical_overlap=False,provenance='clinical_heading_band'))
                continue
            # 2. Top-left Hospital Logo -> keep (selected=False)
            confirmed_name_below=any(q['kind']=='HEALTHCARE_STAFF_NAME' and q.get('selected') and q.get('review_status')!='CONTEXT_REQUIRED'
                and any(-2<=r[1]-ib.y1<=20 and abs((r[0]+r[2]-ib.x0-ib.x1)/2)<80 for r in q['rects']) for q in existing_proposals)
            if ib.x0 < 230 and ib.y0 < 130 and ib.width < 230 and ib.height < 120 and not confirmed_name_below:
                out.append({
                    'id': f'p{pn}-i{len(out)}',
                    'kind': 'IMAGE_REVIEW',
                    'text': 'Logo/biểu trưng đầu trang - giữ nguyên',
                    'rects': [[round(v, 3) for v in ib]],
                    'selected': False,
                    'clinical_overlap': False,
                })
                continue
            # 3. Large clinical / diagnostic image -> keep (selected=False)
            if ib.width > 290 and ib.height > 175:
                out.append({
                    'id': f'p{pn}-i{len(out)}',
                    'kind': 'IMAGE_REVIEW',
                    'text': 'Ảnh chuyên môn/chẩn đoán hình ảnh - giữ nguyên',
                    'rects': [[round(v, 3) for v in ib]],
                    'selected': False,
                    'clinical_overlap': False,
                })
                continue
            # 4. Check proximity to signature anchors or bottom signature zone
            near_sig = any(
                (ib.x0 - 80 <= a.x1 and ib.x1 + 80 >= a.x0 and -120 <= (ib.y0 - a.y1) <= 130)
                or (ib.x0 - 80 <= a.x1 and ib.x1 + 80 >= a.x0 and -130 <= (a.y0 - ib.y1) <= 40)
                for a in sig_anchors
            )
            is_sig = near_sig or any(ib.x0>=left and ib.y0>top+2 and ib.width<page.rect.width/3 and ib.height<page.rect.height/4
                and image_in_signature_cell(page,ib,top,_pix=signature_grid) for left,top in signature_columns)
            out.append({
                'id': f'p{pn}-i{len(out)}',
                'kind': 'SIGNATURE_IMAGE' if is_sig else 'IMAGE_REVIEW',
                'text': 'Ảnh chữ ký/con dấu bác sĩ - tự động xóa' if is_sig else 'Ảnh: chọn nếu chữ ký/QR; bỏ chọn nếu ảnh chuyên môn',
                'rects': [[round(v, 3) for v in ib]],
                'selected': bool(is_sig),
                'clinical_overlap': False,
            })

    # 5. If full-page scan (e.g. 3.BVQT cover page 1), add signature zone between "Trưởng khoa" and doctor name
    if full_page_scan:
        out.extend(scanned_signature_proposals(page,text,chars,existing_proposals,pn,clinical_bands))
        tk_rects = leader_anchors
        staff_rects = [r for q in existing_proposals if q['kind'] in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME'} and q.get('selected') and q.get('review_status')!='CONTEXT_REQUIRED' for r in q['rects'] if r[1] > page.rect.height * 0.7]
        for tk in tk_rects:
            if tk[1] > page.rect.height * 0.7:
                matching_staff = [sr for sr in staff_rects if sr[1] > tk[3] and sr[1] - tk[3] < 130 and abs(sr[0] - tk[0]) < 160]
                if matching_staff:
                    sr = matching_staff[0]
                    sig_zone = [
                        round(max(10.0, min(tk[0], sr[0]) - 20.0), 3),
                        round(tk[3] + 2.0, 3),
                        round(min(page.rect.width - 10.0, max(tk[2], sr[2]) + 25.0), 3),
                        round(sr[1] - 1.0, 3),
                    ]
                    if sig_zone[3] > sig_zone[1] + 8.0:
                        out.append({
                            'id': f'p{pn}-sigscan-{len(out)}',
                            'kind': 'SIGNATURE_IMAGE',
                            'text': 'Vùng chữ ký bác sĩ trên trang scan - tự động xóa',
                            'rects': [sig_zone],
                            'selected': True,
                            'clinical_overlap': False,
                        })
    return out

def generate_audit_markdown(job_dir: Path, data: dict, *, applied_pages=None) -> Path:
    """Generate Coordinate-Linked Markdown Audit Summary (AUDIT_SUMMARY.md) for fast double-check."""
    job_dir = Path(job_dir)
    if applied_pages is not None and applied_pages.get("snapshot") != hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest():
        raise ValueError("Audit snapshot changed")
    lines = [
        f"Internal PII audit; job_id={data.get('job_id', 'legacy')}; revision={data.get('revision', 0)}; draft={data.get('export_draft', 'not_exported')}; source_fingerprint={data.get('working_sha256', '')}",
        f"# Báo Cáo Khử Định Danh Bệnh Án (`{data.get('study_id', 'HMU_CASE')}`)",
        "",
        f"- **Phiên bản công cụ:** `{data.get('version', VERSION)}`",
        f"- **Tổng số trang:** `{len(data.get('pages', []))}`",
        f"- **Số trang dùng Offline OCR (trang scan/vector):** `{data.get('ocr_pages_count', 0)}`",
        f"- **Số stream watermark đã bóc tách:** `{len(data.get('watermarks_removed', []))}`",
        f"- **Chính sách:** Xóa Tên BN/Người nhà, SĐT, Địa chỉ, Ngày/Năm sinh, Tên & Chữ ký nhân viên; Giữ Tuổi, Giới tính, Mã HS/BN và Tên Bệnh viện.",
        "",
        "## 1. Thống kê các vùng đã tự động đánh dấu xóa (`selected = True`)",
        "",
        "| Trang | Loại thông tin (`kind`) | Nội dung phát hiện | Tọa độ `[x0, y0, x1, y1]` |",
        "| :---: | :--- | :--- | :--- |",
    ]
    for p in data.get("pages", []):
        pn = p["page"]
        for q in p.get("proposals", []):
            if q.get("selected"):
                safe_txt = str(q.get("text", "")).replace("\n", " ").replace("|", "/")
                coords = ", ".join(str(r) for r in q.get("rects", [])[:2])
                lines.append(f"| {pn} | `{q['kind']}` | {safe_txt[:80]} | `{coords}` |")
    lines.extend([
        "",
        "## 2. Nội dung văn bản Markdown sau khi khử định danh (Theo từng trang)",
        "",
    ])
    audit_doc=None
    try:
        for p in data.get("pages", []):
            pn = p["page"]
            lines.append(f"### Trang {pn}")
            analysis_path = job_dir / 'analysis_private' / f'{pn}.json'
            analysis = json.loads(analysis_path.read_text(encoding='utf8')) if analysis_path.exists() else None
            redacted_md = 'Analysis unavailable: source recheck required'
            if analysis:
                try:
                    if applied_pages is not None:
                        pixel_rects=applied_pages[pn]
                    else:
                        if audit_doc is None: audit_doc=fitz.open(job_dir / 'working_private.pdf')
                        audit_page=audit_doc[pn-1]
                        pixel_rects,_,_=apply_review_to_page(audit_page,p,pn)
                        pixel_rects=[list(fitz.Rect(r)*audit_page.rotation_matrix) for r in pixel_rects]
                    redacted_md = build_review_markdown(analysis['text'],analysis['chars'],p,pixel_rects,analysis.get('native_length')).strip()
                except ValueError as error:
                    redacted_md = 'Preview blocked pending review: '+str(error)

            if redacted_md:
                lines.append("```markdown")
                lines.append(redacted_md[:4000])
                lines.append("```")
            else:
                lines.append("*(Trang hình ảnh/biểu đồ không có lớp văn bản)*")
            lines.append("")
    finally:
        if audit_doc is not None: audit_doc.close()

    audit_path = job_dir / "AUDIT_SUMMARY.md"
    audit_path.write_text("\n".join(lines), encoding="utf-8")
    (job_dir/'audit_revision.txt').write_text(str(data['revision']),encoding='utf8')
    return audit_path

def _build_redacted_markdown(text: str, findings: list) -> str:
    if not text:
        return ""
    spans = sorted(
        [(f.start, f.end, f.entity_type) for f in findings if 0 <= f.start < f.end <= len(text)],
        key=lambda x: (x[0], -(x[1] - x[0]))
    )
    merged = []
    for s, e, k in spans:
        if not merged or s >= merged[-1][1]:
            merged.append([s, e, k])
        else:
            merged[-1][1] = max(merged[-1][1], e)
    out = []
    last = 0
    for s, e, k in merged:
        out.append(text[last:s])
        out.append(f"[ĐÃ XÓA:{k}]")
        last = e
    out.append(text[last:])
    return "".join(out)

def combine_page_maps(native_map, ocr_map):
    nt, nc = native_map; ot, oc = ocr_map
    if not nt.strip(): return ot, oc
    native_words = []
    for m in re.finditer(r'\S+', nt):
        rs = span_rects(nc,m.start(),m.end())
        if rs: native_words.append((m.group().casefold(),fitz.Rect(rs[0])))
    skip = set()
    for m in re.finditer(r'\S+', ot):
        rs = span_rects(oc,m.start(),m.end())
        if rs:
            r = fitz.Rect(rs[0])
            if any(w == m.group().casefold() and (r & nr).get_area() > .7 * min(r.get_area(),nr.get_area()) for w,nr in native_words):
                skip.update(range(m.start(),m.end()))
    text = nt + '\n'; chars = list(nc); line_base = max((c[1] for c in nc),default=0)+1
    for offset,line,bbox,ch in oc:
        if offset not in skip:
            chars.append((len(text),line+line_base,bbox,ch));text += ch
    return text,chars


def build_review_markdown(text, chars, review, pixel_rects=None, native_length=None):
    fs = []
    # Normalize each box once; Rect.intersects otherwise allocates for every pair.
    def boxes(rects):
        return [r for r in map(fitz.Rect,rects) if not r.is_empty and not r.is_infinite]
    glyphs=[(offset,ch,rs[0]) for offset,_,bbox,ch in chars if (rs:=boxes([bbox]))]
    def overlaps(a, rects):
        return any(a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1 for b in rects)
    rects = list(review.get('manual_rects', [])) if pixel_rects is None else list(pixel_rects)
    for q in review['proposals']:
        if not q['selected']: continue
        if q['kind'] == 'WATERMARK_TEXT':
            fs.extend(Finding(q['kind'],a,b,1,text[a:b],'review') for a,b in q.get('text_spans',[]))
        elif pixel_rects is None and q['kind'] not in {'IMAGE_REVIEW','SIGNATURE_IMAGE','WIDGET_REVIEW','ANNOTATION_REVIEW'}:
            rects.extend(q['rects'])
        elif q['kind'] in {'IMAGE_REVIEW','SIGNATURE_IMAGE'} and native_length is not None:
            image_boxes=boxes(q['rects'])
            for offset,ch,bbox in glyphs:
                if offset >= native_length and not ch.isspace() and overlaps(bbox,image_boxes):
                    fs.append(Finding(q['kind'],offset,offset+1,1,ch,'review'))
    rects=boxes(rects)
    for offset,ch,bbox in glyphs:
        if not ch.isspace() and overlaps(bbox,rects):
            fs.append(Finding('REGION',offset,offset+1,1,ch,'review'))
    # Keep recognized entity labels for text findings still selected.
    for q in review['proposals']:
        if q['selected'] and q['kind'] not in {'WATERMARK_TEXT','IMAGE_REVIEW','SIGNATURE_IMAGE','ANNOTATION_REVIEW','WIDGET_REVIEW','PATIENT_AGE'}:
            entity_boxes=boxes(q['rects'])
            for m in re.finditer(re.escape(q.get('text','')), text):
                if m.start() < m.end() and any(overlaps(bbox,entity_boxes) for offset,_,bbox in glyphs if m.start() <= offset < m.end()):
                    fs.append(Finding(q['kind'],m.start(),m.end(),1,m.group(),'review'))
    return _build_redacted_markdown(text,fs)


def validate_redaction_regions(rects, protected_rects, pn):
    if any(fitz.Rect(r).intersects(fitz.Rect(pr)) for r in rects for pr in protected_rects):
        raise ValueError(f'Clinical overlap on page {pn}; correct the selected region')


def ensure_job(job):
    job = Path(job); data = json.loads((job / 'review.json').read_text(encoding='utf8')); changed = False
    if data.get('policy') != POLICY:
        raise ValueError('Redaction policy changed; prepare a new job from the original PDF')
    if data.get('watermarks_removed'):
        data['status'] = 'SOURCE_RECHECK_REQUIRED'
    if 'job_id' not in data:
        data.update(schema_version=2,job_id=secrets.token_hex(16),revision=0);changed=True
    with fitz.open(job / 'working_private.pdf') as doc:
        if sha(job / 'working_private.pdf') != data['working_sha256']: raise ValueError('Working PDF changed; refuse export')
        for pn,page in enumerate(doc,1):
            ap=job/'analysis_private'/f'{pn}.json'
            if not ap.exists():
                text,chars=char_map(page);native_length=len(text);ocr_used=not text.strip() or bool(page.get_image_info())
                if ocr_used:
                    ot,oc=ocr_pdf_pages(job/'working_private.pdf',[pn])[pn]
                    if page.rotation:
                        rotation_matrix=page.rotation_matrix
                        oc=[(a,line,tuple(fitz.Rect(bb)*rotation_matrix),ch) for a,line,bb,ch in oc]
                    text,chars=combine_page_maps((text,chars),(ot,oc))
                protected=[r for kind,a,b,_ in protected_hits(text) if kind=='ICD10' for r in span_rects(chars,a,b)]
                ap.parent.mkdir(exist_ok=True);save_json(ap,dict(text=text,chars=chars,native_length=native_length,ocr_settings_fingerprint=ocr_settings_fingerprint() if ocr_used else None,protected_rects=protected,source_fingerprint=data['working_sha256']))
                data['pages'][pn-1]['reviewed']=False;changed=True
            analysis=json.loads(ap.read_text(encoding='utf8'))
            if analysis.get('ocr_settings_fingerprint') and analysis['ocr_settings_fingerprint'] != ocr_settings_fingerprint():
                raise ValueError('OCR settings changed; prepare again')
            if analysis['source_fingerprint'] != data['working_sha256']: raise ValueError('Analysis fingerprint changed; prepare again')
            data['pages'][pn-1]['protected_rects']=analysis['protected_rects']
    if changed: save_json(job/'review.json',data)
    return data


def recover_job(job, source, new_job):
    """Recover old destructive jobs only from the byte-identical original, preserving the old job."""
    original=json.loads((Path(job)/'review.json').read_text(encoding='utf8'))
    if sha(source) != original['source_sha256']:
        raise ValueError('Source hash does not match the original; recovery refused')
    return prepare(source,new_job,study_id=original['study_id'])


read_review = ensure_job


def prepare(source, job, study_id='HMU_CASE_0001', external_seeds=None, progress_cb=None, *, case_xml_index=None, source_name=None, ocr_workers=None, render_workers=None):
    source = Path(source); job = Path(job)
    if job.exists() and any(job.iterdir()):
        raise ValueError('Use a new empty job directory')
    job.mkdir(parents=True, exist_ok=True); (job / 'pages').mkdir()
    if progress_cb:
        progress_cb(f'Đang trích xuất hạt giống XML & kiểm tra file {source.name}...')
    auto_seeds = extract_case_seeds(source, xml_index=case_xml_index, source_name=source_name)
    if external_seeds:
        for k, v in external_seeds.items():
            auto_seeds.setdefault(k, [])
            for item in v:
                if item not in auto_seeds[k]:
                    auto_seeds[k].append(item)

    with fitz.open(source) as doc:
        if doc.is_encrypted:
            raise ValueError('Encrypted PDF must be unlocked in the approved environment')
        if not len(doc):
            raise ValueError('Empty PDF')
        wm = remove_isolated_watermarks(doc)
        work = job / 'working_private.pdf'
        doc.save(work, garbage=4, deflate=True)

    with fitz.open(work) as doc:
        total_pages = len(doc)
        raw_texts = [p.get_text('text', sort=False) for p in doc]
        textless_pnos = [idx + 1 for idx, t in enumerate(raw_texts) if not t.strip() or bool(doc[idx].get_image_info())]
        if textless_pnos:
            _render_scan_pages(work,textless_pnos,200,job/'pages',
                (lambda done,total:progress_cb(f'Đang tách ảnh trang scan {done}/{total} ({source.name})...')) if progress_cb else None, max_workers=render_workers)
            if progress_cb:
                progress_cb(f'Đang chạy OCR bất đồng bộ 0/{len(textless_pnos)} trang scan ({source.name})...')
        ocr_maps = ocr_pdf_pages(
            work,
            textless_pnos,
            dpi=200,
            progress_cb=(lambda done, tot: progress_cb(f'Đang chạy OCR bất đồng bộ {done}/{tot} trang scan ({source.name})...')) if progress_cb else None,
            pre_rendered_dir=job / 'pages',
            max_workers=ocr_workers,
        ) if textless_pnos else {}

        page_maps = []
        native_lengths = []
        texts = []
        for pn, p in enumerate(doc, 1):
            native_map = char_map(p) if raw_texts[pn-1] else ('',[])
            native_lengths.append(len(native_map[0]))
            if pn in ocr_maps:
                ot, oc = ocr_maps[pn]
                if p.rotation:
                    rotation_matrix=p.rotation_matrix
                    oc = [(a,line,tuple(fitz.Rect(bb)*rotation_matrix),ch) for a,line,bb,ch in oc]
                t, c = combine_page_maps(native_map, (ot,oc))
            else:
                t, c = native_map
            page_maps.append((t, c))
            texts.append(t)

        validator=lambda pn,f:name_geometry_valid(f,page_maps[pn][1])
        findings, known = analyze_hmu_document(texts, external_seeds=auto_seeds, _finding_validator=validator)
        retries=[]; retry_rects={}; retry_pages=set(); bounded_name_fields={}
        for pn,(p,(text,chars),fs) in enumerate(zip(doc,page_maps,findings),1):
            bounded=patient_name_value_rect(text,chars,p.rect)
            if bounded:bounded_name_fields[pn]=bounded
            if any(f.entity_type=='PATIENT_NAME' and f.review_status!='CONTEXT_REQUIRED' for f in fs): continue
            anchor=re.search(r'(?i)\(\s*in\s*hoa\s*\)\s*[:：]',text)
            if not anchor: continue
            rs=span_rects(chars,anchor.start(),anchor.end())
            if not rs: continue
            label=fitz.Rect(rs[-1]); right=p.rect.width-20
            next_field=_FIELD_BOUNDARY.search(text,anchor.end())
            if next_field:
                fields=span_rects(chars,next_field.start(),min(len(text),next_field.end()+5))
                if fields and abs(fields[0][1]-label.y0)<10: right=min(right,fields[0][0]-1)
            rect=fitz.Rect(label.x1+2,max(0,label.y0-4),right,min(p.rect.height,label.y1+5))
            if rect.is_empty: continue
            retry_rects[pn]=list(rect)
            retries.append(dict(key=f'patient-{pn}',page=pn,rect=list(rect*p.derotation_matrix),rotation=0))
        if retries:
            try: retry_maps=ocr_pdf_regions(work,retries,dpi=200,max_workers=ocr_workers)
            except (RuntimeError,OSError): retry_maps={}
            for region in retries:
                pn=region['page'];ot,oc=retry_maps.get(region['key'],('',[]))
                if not ot.strip(): continue
                prefix='\nHọ tên: ';old_text,old_chars=page_maps[pn-1]
                line_base=max((c[1] for c in old_chars),default=0)+1
                oc=[(a+len(old_text)+len(prefix),line+line_base,tuple(fitz.Rect(bb)*doc[pn-1].rotation_matrix),ch) for a,line,bb,ch in oc]
                page_maps[pn-1]=(old_text+prefix+ot,old_chars+oc);texts[pn-1]=page_maps[pn-1][0];retry_pages.add(pn)
            findings,known=analyze_hmu_document(texts,external_seeds=auto_seeds,_finding_validator=validator)
        seeds = {
            kind: sorted(
                set(known.get(kind, []))
                | {
                    f.text for fs in findings for f in fs
                    if f.entity_type == kind and f.review_status != 'CONTEXT_REQUIRED' and f.score >= (0.97 if kind in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME_UNCLASSIFIED'} else 0.95)
                    and not f.rule.startswith(('memorized_staff_mid_given','memorized_staff_sur_given','memorized_staff_wrapped_given'))
                    and _valid(kind, f.text)
                }
                | set(auto_seeds.get(kind, []))
            )
            for kind in ['YEAR_OF_BIRTH', 'ADDRESS_VN', 'DATE_OF_BIRTH', 'PHONE_NUMBER_VN', 'PATIENT_NAME', 'RELATIVE_NAME', 'HEALTHCARE_STAFF_NAME']
        }
        seeds['DATE_OF_BIRTH'] = sorted(
            {f.text for fs in findings for f in fs if f.entity_type == 'DATE_OF_BIRTH' and 'CONFLICT' not in f.rule}
            | set(auto_seeds.get('DATE_OF_BIRTH', []))
        )
        base_add_per_page = [additional_findings(text, {}) for text in texts]
        for fs,(_,chars) in zip(base_add_per_page,page_maps):_check_name_geometry(fs,lambda f:name_geometry_valid(f,chars))
        addresses = set(seeds['ADDRESS_VN']) | {
            f.text for add_fs in base_add_per_page for f in add_fs if f.entity_type == 'ADDRESS_VN'
        }
        for value in list(addresses):
            variant = re.sub(r'(?i)^(?:phường|xã|thôn|tổ|phố|đường)\s+', '', value)
            if len(variant) >= 8:
                addresses.add(variant)
        seeds['ADDRESS_VN'] = sorted(addresses)
        seeds['PERSON_NAME'] = sorted(
            {f.text for fs, add_fs in zip(findings, base_add_per_page)
             for f in fs + add_fs
             if f.entity_type in {'PATIENT_NAME', 'RELATIVE_NAME', 'HEALTHCARE_STAFF_NAME', 'PERSON_NAME'}
             and f.review_status != 'CONTEXT_REQUIRED'
             and not f.rule.startswith(('memorized_staff_mid_given','memorized_staff_sur_given','memorized_staff_wrapped_given'))
             and len(f.text.split()) >= 2 and re.fullmatch(PERSON_NAME, f.text)
             and not WATERMARK_RE.match(f.text)}
            | set(auto_seeds.get('PATIENT_NAME', []))
            | set(auto_seeds.get('HEALTHCARE_STAFF_NAME', []))
        )
        precompiled_add = _precompile_additional_seeds(seeds)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', study_id):
            raise ValueError('Invalid research ID')
        data = {
            'version': VERSION,
            'schema_version': 2, 'job_id': secrets.token_hex(16), 'revision': 0,
            'study_id': study_id,
            'source_file': source.name,
            'source_sha256': sha(source),
            'working_sha256': sha(work),
            'watermarks_removed': wm,
            'ocr_pages_count': len(set(textless_pnos)|retry_pages),
            'pages': [],
            'policy': POLICY,
            'dpi': 200,
            'status': 'NEEDS_VISUAL_REVIEW'
        }
        for pn, (p, (text, chars), fs) in enumerate(zip(doc, page_maps, findings), 1):
            proposals = []
            clinical = protected_hits(text)
            all_fs = fs + additional_findings(text, seeds, _precompiled=precompiled_add)
            from hmu_recognizers import _ocr_word_regex
            for f in all_fs:trim_titled_name_to_column(f,text,chars)
            for f in all_fs:
                parts=f.text.split()
                if f.entity_type=='HEALTHCARE_STAFF_NAME' and len(parts)>=3:
                    for full in seeds.get('HEALTHCARE_STAFF_NAME',[]):
                        tokens=full.split()
                        if len(tokens)==len(parts) and all(re.fullmatch(_ocr_word_regex(_strip_accents(w.lower())),_strip_accents(v.lower()),re.I) for w,v in zip(tokens,parts)):
                            f.rule+=':confirmed_case_full';break
                if f.entity_type=='HEALTHCARE_STAFF_NAME' and f.rule.startswith('v20_title_name') and len(parts)==2:
                    for full in seeds.get('HEALTHCARE_STAFF_NAME',[]):
                        tokens=full.split()
                        if len(tokens)>=3 and all(re.fullmatch(_ocr_word_regex(_strip_accents(w.lower())),_strip_accents(v.lower()),re.I) for w,v in ((tokens[0],parts[0]),(tokens[-1],parts[-1]))):
                            f.rule+=':confirmed_case_short';break
                    if ':confirmed_case_short' not in f.rule and not name_geometry_valid(f,chars):
                        prior=f.rule;f.rule+=':confirmed_grid_short'
                        if not signature_heading_confirms(f,text,chars) or not name_in_single_table_cell(p,span_rects(chars,f.start,f.end)):f.rule=prior
            _check_name_geometry(all_fs,lambda f:name_geometry_valid(f,chars))
            for f in all_fs:
                if f.review_status=='CONTEXT_REQUIRED' and signature_heading_confirms(f,text,chars):
                    f.review_status='PENDING_REVIEW';f.score=.99;f.rule+=':signature_heading_geometry'
            boxed_props, age_x0 = boxed_dob_and_bhyt_proposals(p, chars, text, start_idx=0)
            age_barriers = [r for q in boxed_age_proposals(p, chars, text) for r in q['rects']]
            seen = set()
            selected_findings_for_md = []
            for f in sorted(all_fs,key=lambda f:(f.review_status!='CONTEXT_REQUIRED',f.score),reverse=True):
                if f.entity_type in {'PATIENT_ID', 'MEDICAL_RECORD_ID', 'SOURCE_LINK_ID', 'WATERMARK_TEXT', 'PATIENT_AGE'}:
                    continue
                if (f.start, f.end) in seen:
                    continue
                seen.add((f.start, f.end))
                rects = staff_name_rects(text,chars,f) if f.entity_type=='HEALTHCARE_STAFF_NAME' else span_rects(chars, f.start, f.end)
                if f.rule=='insurance_missing_prefix_ocr':rects=insurance_value_rects(text,chars,f,p.rect)
                if not rects:
                    continue
                # Ensure DOB/YOB rects on cover sheet never cross into Age column
                if f.entity_type in {'DATE_OF_BIRTH', 'YEAR_OF_BIRTH'}:
                    clipped = []
                    for r in rects:
                        if r[1] < 250 and r[0] < age_x0 - 5.0:
                            r = [r[0], r[1], min(r[2], round(age_x0 - 6.0, 3)), r[3]]
                        if r[2] > r[0] + 1.0:
                            clipped.append(r)
                    rects = clipped
                    if not rects:
                        continue
                overlap = any(max(f.start, a) < min(f.end, b) for kind, a, b, _ in clinical if kind == 'ICD10')
                is_sel = ('CONFLICT' not in f.rule) and f.review_status != 'CONTEXT_REQUIRED' and not overlap
                if is_sel:
                    selected_findings_for_md.append(f)
                proposals.append({
                    'id': f'p{pn}-t{len(proposals)}',
                    'kind': f.entity_type,
                    'text': f.text,
                    'rule': f.rule,
                    'review_status': f.review_status,
                    'score': f.score,
                    'rects': rects,
                    'selected': is_sel,
                    'clinical_overlap': overlap
                })
                if pn in retry_pages and f.entity_type=='PATIENT_NAME':
                    proposals[-1]['provenance']='patient_name_roi_retry'
                if f.review_status=='CONTEXT_REQUIRED':
                    proposals[-1]['provenance']=('Vùng tên nối qua các ô/cột; cần duyệt' if 'GEOMETRY_REQUIRED_REVIEW' in f.rule
                                                else 'Tên chưa đủ ngữ cảnh xác nhận; cần duyệt')
                    if f.rule.startswith('insurance_missing_prefix_ocr'):proposals[-1]['provenance']='Mã thẻ chưa khớp vị trí nhãn; cần kiểm tra vùng giá trị'
            if pn in bounded_name_fields:
                # OCR can drop a surname; explicit neighbouring labels bound the entire value.
                proposals.append(dict(id=f'p{pn}-patient-field',kind='PATIENT_NAME',text='',
                    rule='explicit_bounded_patient_field',provenance='Toàn ô họ tên (in hoa), giới hạn bởi nhãn trường kế bên',
                    rects=[bounded_name_fields[pn]],selected=True,clinical_overlap=False,score=.99))
            elif pn in retry_rects and not any(q['kind']=='PATIENT_NAME' for q in proposals):
                proposals.append(dict(id=f'p{pn}-patient-unresolved',kind='PATIENT_NAME_REVIEW',text='OCR cục bộ chưa nhận diện chắc tên bệnh nhân; cần khoanh/kiểm tra',
                                      provenance='patient_name_roi_retry_unresolved',rects=[retry_rects[pn]],selected=False,clinical_overlap=False))
            for proposal in signature_column_proposals(text,page_maps[pn-1][1],p.rect,page=p,mask_cells=True):
                proposal['id']=f'p{pn}-column{len(proposals)}';proposals.append(proposal)
            # Add boxed DOB / BHYT proposals
            for bp in boxed_props:
                bp['id'] = f'p{pn}-box{len(proposals)}'
                proposals.append(bp)
            # Watermark bounds are display-only, never a white pixel mask.
            page_watermarks=rotated_watermark_rects(p) if raw_texts[pn-1] else []
            wm_proof=_watermark_proof(p) if page_watermarks else {}
            for wm_txt, wm_rect in page_watermarks:
                proposals.append({
                    'id': f'p{pn}-wm{len(proposals)}',
                    'kind': 'WATERMARK_TEXT',
                    'text': wm_txt,
                    'rule': 'reviewed_watermark_object',
                    'method': 'isolated_watermark_stream', 'stream_xrefs': _watermark_xrefs(wm_proof, wm_rect),
                    'text_spans': [[m.start(), m.end()] for m in re.finditer(re.escape(wm_txt), text)],
                    'rects': [wm_rect],
                    'selected': True,
                    'clinical_overlap': False
                })
            # Barcodes kept unselected by default so record/specimen IDs remain for post-inspection
            drawings = p.get_cdrawings()
            for r in barcode_rects(p, drawings):
                proposals.append({
                    'id': f'p{pn}-b{len(proposals)}',
                    'kind': 'BARCODE_CANDIDATE',
                    'text': 'Mã vạch hồ sơ/bệnh phẩm - giữ để hậu kiểm (chọn nếu muốn xóa)',
                    'rects': [r],
                    'selected': False,
                    'clinical_overlap': False
                })
            for r in vector_qr_rects(p, drawings):
                proposals.append({
                    'id': f'p{pn}-q{len(proposals)}',
                    'kind': 'QR_VECTOR_CANDIDATE',
                    'text': 'QR dạng vector - tự động xóa',
                    'rects': [r],
                    'selected': True,
                    'clinical_overlap': False
                })
            # Classify images & auto-select doctor signatures
            img_props = build_image_and_signature_proposals(p, chars, text, proposals, pn)
            proposals.extend(img_props)
            footer_images=[r for q in img_props if q['kind']=='IMAGE_REVIEW' for r in q['rects'] if q.get('provenance')=='clinical_heading_band' or (r[2]-r[0]>290 and r[3]-r[1]>175)]
            proposals.extend(footer_signature_fields(text,chars,p.rect,pn,image_rects=footer_images,native_images=[list(fitz.Rect(i['bbox'])*p.rotation_matrix) for i in p.get_image_info()]))
            for a in list(p.annots() or []):
                proposals.append({
                    'id': f'p{pn}-a{len(proposals)}',
                    'kind': 'ANNOTATION_REVIEW',
                    'text': 'Ghi chú/dấu ký: chọn nếu chứa định danh; giữ nếu có nội dung chuyên môn',
                    'rects': [list((a.rect*p.rotation_matrix) & p.rect)],
                    'selected': False,
                    'clinical_overlap': False
                })
            for w in list(p.widgets() or []):
                if (w.rect & p.rect).is_empty:
                    continue
                is_sig_widget = (w.field_type_string == 'Signature') or ('chu_ky' in (w.field_name or '').lower())
                proposals.append({
                    'id': f'p{pn}-w{len(proposals)}',
                    'kind': 'WIDGET_REVIEW',
                    'text': 'Trường chữ ký số/biểu mẫu',
                    'rects': [list((w.rect*p.rotation_matrix) & p.rect)],
                    'selected': is_sig_widget,
                    'clinical_overlap': False
                })
            ink_display_list = p.get_displaylist(annots=True)
            # Apply ink-bounding-box expansion for text fields to never drop trailing words (like 'Lộc' or 'Cường')
            # Protect Age column on cover sheets if pn <= 3
            protect_max_x1 = min(age_x0 - 5.0, 465.0) if pn <= 3 else (p.rect.width - 25.0)
            field_barriers = [r for m in _FIELD_BOUNDARY.finditer(text) for r in span_rects(chars, m.start(), min(len(text), m.end() + 18))]
            field_barriers.extend(r for m in re.finditer(r'\S+',text) for r in span_rects(chars,m.start(),m.end()))
            field_barriers.extend(age_barriers)
            image_barriers=[r for q in proposals if q['kind'] in {'IMAGE_REVIEW','SIGNATURE_IMAGE'} and not q['selected'] for r in q['rects']]
            for q in proposals:
                if q['selected'] and q['kind'] in {'PATIENT_NAME', 'HEALTHCARE_STAFF_NAME', 'ADDRESS_VN', 'RELATIVE_NAME', 'PERSON_NAME_UNCLASSIFIED', 'PERSON_NAME'}:
                    if q['kind']=='PATIENT_NAME' and pn in bounded_name_fields and all(fitz.Rect(bounded_name_fields[pn]).contains(fitz.Rect(r)) for r in q['rects']):
                        q['rects']=[list(bounded_name_fields[pn])];continue
                    if q['kind'] in {'HEALTHCARE_STAFF_NAME','PERSON_NAME','RELATIVE_NAME'}:q['rects']=labelled_footer_name_rects(text,chars,q['rects'],p.rect)
                    if q['kind']!='ADDRESS_VN' and q.get('rule')!='explicit_bounded_patient_field':q['rects']=pad_name_rects(q['rects'],field_barriers,footer_images if q.get('rule')=='explicit_footer_role_instruction_name' else image_barriers)
                    q['rects'] = expand_rects_with_pixel_ink(p, q['rects'], max_expand_pt=50.0, max_x1=protect_max_x1, barriers=field_barriers, _display_list=ink_display_list)
            grid_pix=ink_display_list.get_pixmap(matrix=fitz.Matrix(150/72,150/72),colorspace=fitz.csGRAY,alpha=False)
            for q in proposals:
                if q['kind'] in {'PATIENT_NAME','HEALTHCARE_STAFF_NAME','PERSON_NAME','PERSON_NAME_UNCLASSIFIED'}:
                    q['rects']=clip_text_masks_to_grid(p,q['rects'],_pix=grid_pix)

            blocked_cells=[fitz.Rect(r) for q in proposals if q.get('rule') in {'identity_cell_clinical_review','identity_cell_label_review'} for r in q['rects']]
            for q in proposals:
                if q['selected'] and any(fitz.Rect(r).intersects(cell) for r in q['rects'] for cell in blocked_cells):
                    q['selected']=False;q['clinical_overlap']=True

            # Subsume smaller overlapping proposals (e.g. inner names) into larger outer proposals
            proposals = merge_and_subsume_proposals(proposals)

            # Clamp all proposal rects strictly inside p.rect (avoid float round-up past page edge)
            for q in proposals:
                clamped_rects = []
                for r in q.get('rects', []):
                    cr = fitz.Rect(r) & p.rect
                    if not cr.is_empty and not cr.is_infinite:
                        x0 = max(round(p.rect.x0 + 0.01, 3), round(cr.x0, 3))
                        y0 = max(round(p.rect.y0 + 0.01, 3), round(cr.y0, 3))
                        x1 = min(round(p.rect.x1 - 0.01, 3), round(cr.x1, 3))
                        y1 = min(round(p.rect.y1 - 0.01, 3), round(cr.y1, 3))
                        if x1 > x0 and y1 > y0:
                            clamped_rects.append([x0, y0, x1, y1])
                q['rects'] = clamped_rects
            proposals = [q for q in proposals if q['rects']]
            if progress_cb and (pn == 1 or pn % 10 == 0 or pn == total_pages):
                progress_cb(f'Đang nhận diện PII & dựng ảnh xem trước trang {pn}/{total_pages} ({source.name})...')
            page_png = job / 'pages' / f'{pn}.png'
            if not page_png.exists():
                save_preview(p.get_pixmap(dpi=110, alpha=False), page_png)
            raw_page_text = raw_texts[pn - 1]
            analysis = {'text': text, 'chars': chars, 'source_fingerprint': data['working_sha256'],
                        'ocr_settings_fingerprint': ocr_settings_fingerprint() if pn in ocr_maps or pn in retry_pages else None,
                        'native_length': native_lengths[pn-1],
                        'protected_rects': [r for kind,a,b,_ in clinical if kind == 'ICD10' for r in span_rects(chars,a,b)]}
            (job / 'analysis_private').mkdir(exist_ok=True)
            save_json(job / 'analysis_private' / f'{pn}.json', analysis)
            data['pages'].append({
                'page': pn,
                'width': p.rect.width,
                'height': p.rect.height,
                'text_sha256': hashlib.sha256(raw_page_text.encode()).hexdigest(),
                'ocr_used': pn in ocr_maps or pn in retry_pages,
                'reviewed': False,
                'proposals': proposals,
                'manual_rects': [],
                'protected_rects': analysis['protected_rects'],
                'note': '',
                'redacted_markdown': _build_redacted_markdown(text, selected_findings_for_md)
            })
    save_json(job / 'review.json', data)
    generate_audit_markdown(job, data)
    return data

def validate_review(data, doc):
    if len(data['pages']) != len(doc):
        raise ValueError('Review/PDF page count differs')
    for pn, (review, p) in enumerate(zip(data['pages'], doc), 1):
        if review['page'] != pn:
            raise ValueError('Page order mismatch')
        if hashlib.sha256(p.get_text('text', sort=False).encode()).hexdigest() != review['text_sha256']:
            raise ValueError('Page text changed since preparation')
        for r in [r for q in review['proposals'] if q['selected'] for r in q['rects']] + review['manual_rects']:
            if len(r) != 4 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in r):
                raise ValueError('Invalid rectangle')
            rect = fitz.Rect(r)
            if rect.is_empty or rect.is_infinite or not p.rect.contains(rect):
                raise ValueError('Rectangle outside page')

def _graphics_image_spans(page, source, selected_rects, infos, names):
    # shortcut: only unquoted graphics streams; text, comments and inline images use pypdf.
    if any(marker in source for marker in (b'(', b'<', b'%', b'BI')): return None
    number=rb'[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)'
    allowed=set(b'b b* B B* BDC BMC BT BX c CS cs d d0 d1 DP EMC ET EX f F f* G g gs h i j J K k l m M MP n re RG rg ri s S SC sc SCN scn sh T* Tc Td TD Tf Tj TJ TL Tm Tr Ts Tw Tz v w W W* y'.split())
    # Consume complete PDF names and regular tokens, never operator suffixes inside a name.
    boundary=rb'(?=[\x00\t\n\f\r ()<>\[\]/%]|$)'
    inert=rb'(?:(?:'+number+rb'|'+b'|'.join(re.escape(op) for op in sorted(allowed,key=len,reverse=True))+rb')'+boundary+rb'[\x00\t\n\f\r ]*)+'
    # Skip validated vector operands/operators in C; retain original byte offsets for image paints.
    tokens=re.compile(rb'(?P<inert>'+inert+rb')|(?P<space>[\x00\t\n\f\r ]+)|/[^\x00\t\n\f\r ()<>\[\]/%]*|[^\x00\t\n\f\r ()<>\[\]/%]+|[\[\]]')
    ctm=fitz.Matrix(1,0,0,1,0,0);stack=[];spans=[];previous=None;depth=0
    for match in tokens.finditer(source):
        if match.lastgroup=='space':continue
        if match.lastgroup=='inert':previous=None;continue
        value=match.group()
        if value==b'[':depth+=1;previous=None;continue
        if value==b']':
            depth-=1
            if depth<0:return None
            previous=None;continue
        if depth:continue
        if value==b'q': stack.append(fitz.Matrix(ctm))
        elif value==b'Q':
            if not stack: return None
            ctm=stack.pop()
        elif value==b'cm':
            values=source[max(0,match.start()-512):match.start()].split()[-6:]
            if len(values)!=6 or not all(re.fullmatch(number,v) for v in values):return None
            values=list(map(float,values))
            if not all(math.isfinite(v) for v in values):return None
            ctm=fitz.Matrix(*values)*ctm
        elif value==b'Do':
            if previous is None or not previous[0].startswith(b'/'):return None
            name=previous[0][1:].decode('latin1')
            if name in names:
                bbox=fitz.Rect(0,0,1,1)*ctm*page.transformation_matrix
                index=next((i for i,r in enumerate(selected_rects) if max(abs(a-b) for a,b in zip(bbox,r))<.5),None)
                if index is not None:spans.append((previous[1],match.end(),index))
        elif not value.startswith(b'/') and value not in allowed and not re.fullmatch(number,value):return None
        previous=(value,match.start())
    expected=collections.Counter(next((i for i,r in enumerate(selected_rects) if max(abs(a-b) for a,b in zip(info['bbox'],r))<.5),None) for info in infos)
    expected.pop(None,None)
    if stack or depth or collections.Counter(i for _,_,i in spans)!=expected:return None
    return spans


class _LocatedContentStream(ContentStream):
    """Use pypdf's parser, retaining byte ranges so unrelated drawing bytes never change."""
    def _parse_content_stream(self, stream):
        self.operation_ends=[]
        ends=self.operation_ends
        class Operations(list):
            def append(self, item):
                super().append(item)
                ends.append(stream.tell())
        self._operations=Operations()
        super()._parse_content_stream(stream)


def remove_selected_image_paints(page, selected_rects):
    if not selected_rects:
        return []
    infos=page.get_image_info()
    def matches(info,rect):return max(abs(a-b) for a,b in zip(info['bbox'],rect))<.5
    matched={i for i,r in enumerate(selected_rects) if any(matches(info,r) for info in infos)}
    if not matched:
        return []
    def confirmed_removed():
        remaining=page.get_image_info()
        return sorted(i for i in matched if not any(matches(info,selected_rects[i]) for info in remaining))
    doc = page.parent
    images=page.get_images(full=True)
    # Delete image operators, never replace them with Forms: a Form clears a pending path.
    original_contents=doc.xref_get_key(page.xref,'Contents')[1]
    source = b'\n'.join(doc.xref_stream(x) for x in page.get_contents())
    names = {x[7] for x in images if x[9] == 0}
    spans=_graphics_image_spans(page,source,selected_rects,infos,names)
    if spans:
        pieces=[];last=0
        for start,end,_ in spans:pieces.append(source[last:start]);last=end
        pieces.append(source[last:])
        replacement=doc.get_new_xref();doc.update_object(replacement,'<< >>')
        doc.update_stream(replacement,b''.join(pieces),compress=False);page.set_contents(replacement);page._image_info=None
        return confirmed_removed()
    stream = DecodedStreamObject(); stream.set_data(source); content = _LocatedContentStream(stream, None)
    ctm = fitz.Matrix(1, 0, 0, 1, 0, 0); stack = []; ops = []; removed = []; removed_operations=[]
    for operation_index,(operands, operator) in enumerate(content.operations):
        if operator == b'q':
            stack.append(fitz.Matrix(ctm))
        elif operator == b'Q':
            ctm = stack.pop() if stack else fitz.Matrix(1, 0, 0, 1, 0, 0)
        elif operator == b'cm':
            ctm = fitz.Matrix(*[float(x) for x in operands]) * ctm
        image = operator == b'INLINE IMAGE' or (operator == b'Do' and str(operands[0]).lstrip('/') in names)
        if image:
            bbox = fitz.Rect(0, 0, 1, 1) * ctm * page.transformation_matrix
            match = next((i for i, r in enumerate(selected_rects)
                          if max(abs(a - b) for a, b in zip(bbox, r)) < .5), None)
            if match is not None:
                removed.append(match); removed_operations.append(operation_index); continue
        ops.append((operands, operator))
    if not removed:
        return []
    before = page.get_text('text', sort=False)
    pieces=[];last=0
    for index in removed_operations:
        start=content.operation_ends[index-1] if index else 0
        pieces.append(source[last:start]);last=content.operation_ends[index]
    pieces.append(source[last:])
    rewritten=b''.join(pieces)
    newxref = doc.get_new_xref(); doc.update_object(newxref, '<< >>'); doc.update_stream(newxref, rewritten,compress=False); page.set_contents(newxref)
    page._image_info = None
    if page.get_text('text', sort=False) != before:
        doc.xref_set_key(page.xref,'Contents',original_contents);page._image_info=None;return []
    return confirmed_removed()

def apply_review_to_page(p, review, pn):
    display_review = review
    if p.rotation:
        review = copy.deepcopy(review)
        for q in review['proposals']:
            q['rects'] = [list(fitz.Rect(r)*p.derotation_matrix) for r in q['rects']]
        review['manual_rects'] = [list(fitz.Rect(r)*p.derotation_matrix) for r in review['manual_rects']]
        review['protected_rects'] = [list(fitz.Rect(r)*p.derotation_matrix) for r in review.get('protected_rects',[])]
    selected_watermarks = [q for q in display_review['proposals'] if q['selected'] and q['kind'] == 'WATERMARK_TEXT']
    if selected_watermarks:
        proof = _watermark_proof(p)
        safe = list(proof)
        for q in selected_watermarks:
            if not q.get('stream_xrefs') or not set(q['stream_xrefs']).issubset(set(_watermark_xrefs(proof, q['rects'][0]))):
                raise ValueError(f'UNSAFE_WATERMARK_REMOVAL on page {pn}')
        targets = set(x for q in selected_watermarks for x in q.get('stream_xrefs', []))
        partially_selected = any(not q['selected'] and targets.intersection(_watermark_xrefs(proof, q['rects'][0])) for q in display_review['proposals'] if q['kind']=='WATERMARK_TEXT')
        if not targets or not targets.issubset(set(safe)) or partially_selected:
            raise ValueError(f'UNSAFE_WATERMARK_REMOVAL on page {pn}')
        # A content stream may be shared by pages with different review choices.
        doc = p.parent
        source = b'\n'.join(doc.xref_stream(x) for x in p.get_contents() if x not in targets)
        replacement = doc.get_new_xref(); doc.update_object(replacement, '<< >>')
        doc.update_stream(replacement, source); p.set_contents(replacement)
    image_rects = [r for q in review['proposals'] if q['selected'] and q['kind'] in {'IMAGE_REVIEW', 'SIGNATURE_IMAGE'} for r in q['rects']]
    validate_redaction_regions(image_rects, review.get('protected_rects',[]), pn)
    removed_images = []
    selected_annots = [r for q in review['proposals'] if q['selected'] and q['kind'] == 'ANNOTATION_REVIEW' for r in q['rects']]
    for a in list(p.annots() or []):
        matches = [i for i, r in enumerate(image_rects) if max(abs(x - y) for x, y in zip(a.rect, r)) < .5]
        if matches or any(max(abs(x - y) for x, y in zip(a.rect, r)) < .5 for r in selected_annots):
            p.delete_annot(a)
    selected_widgets = [r for q in review['proposals'] if q['selected'] and q['kind'] == 'WIDGET_REVIEW' for r in q['rects']]
    for w in list(p.widgets() or []):
        if any(max(abs(x - y) for x, y in zip(w.rect & p.rect, r)) < .5 for r in selected_widgets):
            p.delete_widget(w)
    # Annotation/widget deletion is not proof that selected page-image pixels disappeared.
    p._image_info=None
    pending = [i for i in range(len(image_rects)) if i not in removed_images]
    removed_images.extend(pending[i] for i in remove_selected_image_paints(p, [image_rects[i] for i in pending]))
    fallback = [r for i, r in enumerate(image_rects) if i not in removed_images]
    rects = [
        r for q in review['proposals']
        if q['selected'] and q['kind'] not in {'IMAGE_REVIEW', 'SIGNATURE_IMAGE', 'ANNOTATION_REVIEW', 'WIDGET_REVIEW', 'WATERMARK_TEXT'}
        for r in q['rects']
    ] + fallback + review['manual_rects']
    if any(q['selected'] and q['clinical_overlap'] for q in review['proposals']):
        raise ValueError(f'Clinical overlap on page {pn}; deselect/correct before export')
    validate_redaction_regions(rects, review.get('protected_rects', []), pn)
    # Rectangles are physically erased on the final raster; do not rewrite source glyphs or grids.
    return rects, removed_images, fallback

def approve_all_pages(job):
    """Mark all pages in a job directory as reviewed=True and persist review.json."""
    job = Path(job)
    current = ensure_job(job)
    current['revision'] += 1
    for page_item in current['pages']:
        page_item['reviewed'] = True
    with fitz.open(job / 'working_private.pdf') as doc:
        validate_review(current, doc)
    save_json(job / 'review.json', current)
    return current

def _write_export_pair(job, snapshot, destination, draft, progress_cb=None, *, applied_pages=None):
    data = snapshot; data['export_draft'] = bool(draft); job=Path(job)
    work = job / 'working_private.pdf'
    if not isinstance(data.get('dpi', 200), int) or not 150 <= data.get('dpi', 200) <= 600:
        raise ValueError('Export DPI must be between 150 and 600')
    if sha(work) != data['working_sha256']:
        raise ValueError('Working PDF changed; refuse export')
    if not draft and not all(p['reviewed'] for p in data['pages']):
        raise ValueError('Review all pages, or export a draft for review')
    study_id = data.get('study_id', 'HMU_CASE_0001')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', study_id):
        raise ValueError('Invalid research ID')
    output = Path(destination)
    if not draft and data.get('status') == 'SOURCE_RECHECK_REQUIRED':
        raise ValueError('SOURCE_RECHECK_REQUIRED: prepare a new job from the matching original PDF')
    report = []; final = fitz.open()
    try:
        with fitz.open(work) as doc:
            total_pages = len(doc)
            validate_review(data, doc)
            for pn, (p, review) in enumerate(zip(doc, data['pages']), 1):
                if progress_cb and (pn == 1 or pn % 10 == 0 or pn == total_pages):
                    progress_cb(f'Đang xóa định danh & kết xuất PDF trang {pn}/{total_pages}...')
                rects, removed_images, fallback = apply_review_to_page(p, review, pn)
                if applied_pages is not None:
                    applied_pages[pn] = [list(fitz.Rect(r)*p.rotation_matrix) for r in rects]
                pix = p.get_pixmap(dpi=int(data.get('dpi', 200)), alpha=False, annots=True)
                scale = int(data.get('dpi', 200)) / 72
                samples=pix.samples_mv
                for r in rects:
                    ir = ((fitz.Rect(r) * p.rotation_matrix & p.rect) * fitz.Matrix(scale, scale)).irect & pix.irect
                    if not ir.is_empty:
                        # PyMuPDF1.26 set_rect loops over channels in Python; write exact RGB rows.
                        white=b'\xff'*(ir.width*3)
                        for y in range(ir.y0,ir.y1):
                            start=(y-pix.y)*pix.stride+(ir.x0-pix.x)*3
                            samples[start:start+len(white)]=white
                new = final.new_page(width=p.rect.width, height=p.rect.height)
                image_xref = new.insert_image(new.rect, pixmap=pix)
                # Compress once per image instead of retaining raw RGB for the whole document.
                if final.xref_get_key(image_xref, 'Filter')[0] == 'null':
                    final.update_stream(image_xref, zlib.compress(pix.samples, 1), compress=False)
                    final.xref_set_key(image_xref, 'Filter', '/FlateDecode')
                report.append({
                    'page': pn,
                    'reviewed': review['reviewed'],
                    'redaction_regions': len(rects),
                    'image_paints_removed': len(removed_images),
                    'watermark_streams_removed': len({xref for q in review['proposals'] if q['selected'] and q['kind']=='WATERMARK_TEXT' for xref in q.get('stream_xrefs',[])}),
                    'image_pixel_fallback_regions': len(fallback),
                    'clinical_overlap': False,
                    'output_mode': 'rebuilt_image_page'
                })
        final.set_metadata({}); final.save(output, garbage=4, deflate=True); final.close()
        with fitz.open(output) as check:
            assert len(check) == len(data['pages']) and not any(p.get_text().strip() for p in check)
            assert check.embfile_count() == 0 and not any(list(p.annots() or []) or list(p.widgets() or []) for p in check)
        result = {
            'tool': VERSION,
            'study_id': study_id,
            'output': output.name,
            'output_sha256': sha(output),
            'job_id': data['job_id'], 'revision': data['revision'],
            'pages': len(report),
            'dpi': data.get('dpi', 200),
            'watermarks_removed': sum(p['watermark_streams_removed'] for p in report),
            'source_objects_copied': False,
            'searchable_text': False,
            'attachments': 0,
            'status': 'DRAFT_NEEDS_QC' if draft else 'HUMAN_REVIEWED_NEEDS_FINAL_QC',
            'dicom_jpeg_processed': False,
            'page_results': report
        }
        save_json(output.with_suffix('.qc.json'), result)
        if applied_pages is not None:
            applied_pages["snapshot"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return output, result
    finally:
        if not final.is_closed: final.close()


def _publish_generation(job, staging, export_id, records, data):
    destination = job/'exports'/export_id
    destination.parent.mkdir(exist_ok=True)
    staging.replace(destination)
    pointer = {'export_id':export_id,'job_id':data.get('job_id'),'revision':data.get('revision',0),'files':records}
    save_json(job/'last_export.json',pointer)
    return destination


def export(job, draft=False, approve_all=False, output_path=None, progress_cb=None):
    job=Path(job);data=approve_all_pages(job) if approve_all else ensure_job(job)
    if output_path is not None:
        return _write_export_pair(job,data,output_path,draft,progress_cb)
    export_id=secrets.token_hex(12);staging=job/'.export_staging'/export_id;staging.mkdir(parents=True)
    name=data['study_id']+('_DRAFT.pdf' if draft else '_REDACTED.pdf')
    try:
        applied_pages={}
        out,qc=_write_export_pair(job,data,staging/name,draft,progress_cb,applied_pages=applied_pages)
        generate_audit_markdown(job,data,applied_pages=applied_pages)
        destination=_publish_generation(job,staging,export_id,[{'pdf':name,'qc':out.with_suffix('.qc.json').name,'output_sha256':qc['output_sha256'],'job_id':data['job_id'],'revision':data['revision']}],data)
        return destination/name,qc
    finally:
        if staging.exists():shutil.rmtree(staging)


def prepare_case(case_path, job_root, study_id='HMU_CASE_0001', progress_cb=None):
    """Prepare either a single PDF file or a case directory of 40-90 PDFs (like 1.DHYHN) sharing case seeds."""
    case_path = Path(case_path).resolve()
    job_root = Path(job_root).resolve()
    if job_root.exists() and any(job_root.iterdir()):
        raise ValueError('Use a new empty job_root directory')
    job_root.mkdir(parents=True, exist_ok=True)
    pdfs = [case_path] if case_path.is_file() else sorted(case_path.glob('*.pdf'))
    if not pdfs:
        raise ValueError(f'Không tìm thấy file PDF trực tiếp trong thư mục: {case_path}')

    if progress_cb:
        progress_cb(f'Đang trích xuất hạt giống định danh ca bệnh ({case_path.name})...')
    case_xml_index = build_case_xml_index(case_path)
    shared_seeds = extract_case_seeds(case_path, xml_index=case_xml_index)
    # First pass over up to 5 cover/key files to enrich shared_seeds (e.g. EMR_BA001 cover sheet in 1.DHYHN)
    cover_candidates = [p for p in pdfs if 'BA001' in p.name or 'Tờ_bìa' in p.name] + pdfs[:3]
    sample_texts = [];sample_chars=[]
    for cp in list(dict.fromkeys(cover_candidates))[:4]:
        try:
            with fitz.open(cp) as d:
                for p in d[:2]:
                    t,cs = char_map(p)
                    if t.strip():
                        sample_texts.append(t)
                        sample_chars.append(cs)
        except Exception:
            pass
    if sample_texts:
        _, learned = analyze_hmu_document(sample_texts, external_seeds=shared_seeds,_finding_validator=lambda pn,f:name_geometry_valid(f,sample_chars[pn]))
        for k, vals in learned.items():
            shared_seeds.setdefault(k, [])
            for v in vals:
                if v not in shared_seeds[k]:
                    shared_seeds[k].append(v)

    files_info = []
    combined_md = [
        f"# Báo Cáo Tổng Hợp Khử Định Danh Ca Bệnh (`{study_id}`)",
        f"- **Đường dẫn nguồn:** `{case_path}`",
        f"- **Số lượng file PDF:** `{len(pdfs)}`",
        f"- **Hạt giống định danh ca bệnh (Case Seeds):** `{json.dumps(shared_seeds, ensure_ascii=False)}`",
        "",
    ]
    for idx, pdf_file in enumerate(pdfs, 1):
        sub_id = study_id
        sub_job = job_root / f"file_{idx:03d}"
        d = prepare(
            pdf_file,
            sub_job,
            study_id=sub_id,
            external_seeds=shared_seeds,
            case_xml_index=case_xml_index,
            progress_cb=(lambda msg, i=idx, n=len(pdfs): progress_cb(f'[File {i}/{n}] {msg}')) if progress_cb else None,
        )
        files_info.append({
            'index': idx,
            'source_name': pdf_file.name,
            'sub_job': str(sub_job.relative_to(job_root)),
            'pages': len(d['pages']),
            'ocr_pages_count': d.get('ocr_pages_count', 0),
        })
        sub_audit = (sub_job / 'AUDIT_SUMMARY.md').read_text(encoding='utf-8')
        combined_md.append(f"---\n## File {idx}/{len(pdfs)}: `{pdf_file.name}`\n")
        combined_md.append(sub_audit)

    manifest = {
        'version': VERSION,
        'study_id': study_id,
        'source_path': str(case_path),
        'shared_seeds': shared_seeds,
        'files': files_info,
    }
    save_json(job_root / 'case_manifest.json', manifest)
    (job_root / 'AUDIT_SUMMARY.md').write_text('\n'.join(combined_md), encoding='utf-8')
    return manifest

def export_case(job_root, draft=False, approve_all=False, progress_cb=None):
    job_root=Path(job_root).resolve();mp=job_root/'case_manifest.json'
    if not mp.exists():
        out,qc=export(job_root,draft,approve_all,progress_cb=progress_cb)
        return {'outputs':[str(out)],'qcs':[qc],'output_dir':str(out.parent),'count':1}
    manifest=json.loads(mp.read_text(encoding='utf8'));snapshots=[]
    for item in manifest['files']:
        job=(job_root/item['sub_job']).resolve()
        if not job.is_relative_to(job_root):raise ValueError('Invalid sub-job path')
        data=approve_all_pages(job) if approve_all else ensure_job(job)
        if not draft and not all(p['reviewed'] for p in data['pages']):raise ValueError('Review all files before exporting the case')
        with fitz.open(job/'working_private.pdf') as doc:validate_review(data,doc)
        snapshots.append((job,data))
    export_id=secrets.token_hex(12);staging=job_root/'.export_staging'/export_id;staging.mkdir(parents=True)
    records=[];qcs=[];audits=[]
    try:
        for idx,(job,data) in enumerate(snapshots,1):
            name=f"{manifest['study_id']}_F{idx:03d}_{'DRAFT' if draft else 'REDACTED'}.pdf"
            applied_pages={}
            out,qc=_write_export_pair(job,data,staging/name,draft,progress_cb,applied_pages=applied_pages)
            audits.append(generate_audit_markdown(job,data,applied_pages=applied_pages).read_text(encoding='utf8'));qcs.append(qc)
            records.append({'pdf':name,'qc':out.with_suffix('.qc.json').name,'output_sha256':qc['output_sha256'],'job_id':data['job_id'],'revision':data['revision']})
        combined=['# Internal case audit — contains PII']+audits
        (job_root/'AUDIT_SUMMARY.md').write_text('\n'.join(combined),encoding='utf8')
        destination=_publish_generation(job_root,staging,export_id,records,{'job_id':snapshots[0][1]['job_id'],'revision':snapshots[0][1]['revision']})
        return {'outputs':[str(destination/r['pdf']) for r in records],'qcs':qcs,'output_dir':str(destination),'count':len(records)}
    finally:
        if staging.exists():shutil.rmtree(staging)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('pdf'); prep.add_argument('--job', required=True); prep.add_argument('--study-id', default='HMU_CASE_0001')
    exp = sub.add_parser('export'); exp.add_argument('--job', required=True); exp.add_argument('--draft', action='store_true'); exp.add_argument('--approve-all', action='store_true')
    pcase = sub.add_parser('prepare-case'); pcase.add_argument('path'); pcase.add_argument('--job', required=True); pcase.add_argument('--study-id', default='HMU_CASE_0001')
    ecase = sub.add_parser('export-case'); ecase.add_argument('--job', required=True); ecase.add_argument('--draft', action='store_true')
    recover = sub.add_parser('recover'); recover.add_argument('--job',required=True); recover.add_argument('--source',required=True); recover.add_argument('--new-job',required=True)
    args = parser.parse_args()
    if args.command == 'recover':
        d=recover_job(args.job,args.source,args.new_job)
        print(json.dumps({'job':str(args.new_job),'job_id':d['job_id'],'status':d['status']}))
    elif args.command == 'prepare':
        d = prepare(args.pdf, args.job, study_id=args.study_id)
        print(json.dumps({'pages': len(d['pages']), 'job': args.job, 'ocr_pages': d['ocr_pages_count'], 'watermarks_removed': len(d['watermarks_removed'])}))
    elif args.command == 'export':
        out, result = export(args.job, args.draft, approve_all=args.approve_all)
        print(json.dumps({'output': str(out), 'status': result['status']}))
    elif args.command == 'prepare-case':
        m = prepare_case(args.path, args.job, study_id=args.study_id)
        print(json.dumps({'files': len(m['files']), 'job': args.job}))
    elif args.command == 'export-case':
        res = export_case(args.job, draft=args.draft, approve_all=False)
        print(json.dumps(res))
