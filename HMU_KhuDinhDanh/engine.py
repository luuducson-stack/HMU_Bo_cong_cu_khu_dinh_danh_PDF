"""Offline PDF workflow v2.0: Coordinate-Linked Markdown + OCR fallback + Auto-Signature & Boxed DOB redaction.

This exporter rebuilds pages from rendered pixels after applying approved
redactions. It never copies source PDF objects into the deliverable.
"""
import argparse, collections, hashlib, json, re, math, unicodedata
from pathlib import Path
import fitz
from pypdf.generic import ContentStream, DecodedStreamObject
from hmu_recognizers import (
    analyze_hmu_document, protected_hits, extract_case_seeds,
    Finding, SURNAMES, PERSON_NAME, WATERMARK_RE, _valid, _exact_flexible_pattern, _strip_accents, _NAME_START
)
from ocr_helper import ocr_pdf_pages

VERSION = 'HMU-PDF-Workflow-2.0'
fitz.TOOLS.set_small_glyph_heights(True)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_json(path, data):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def remove_isolated_watermarks(doc):
    """Remove separate one-text-object or multi-watermark streams if clinical text is unchanged."""
    log = []
    for pn, p in enumerate(doc, 1):
        rotated = []
        for b in p.get_text('dict')['blocks']:
            for line in b.get('lines', []):
                if abs(line['dir'][1]) > .1:
                    txt = ''.join(s['text'] for s in line['spans']).strip()
                    if txt:
                        rotated.append(txt)
        if not rotated:
            continue
        before = p.get_text()
        for xref in p.get_contents():
            stream = doc.xref_stream(xref)
            if not (stream and len(stream) < 20000 and b'BT' in stream
                    and b'ET' in stream and b' Do' not in stream and b'Tm' in stream):
                continue
            doc.update_stream(xref, b'')
            after = p.get_text()
            removed = [name for name in rotated if name in before and name not in after]
            if removed:
                check = before
                for rname in sorted(removed, key=len, reverse=True):
                    if rname + '\n' in check:
                        check = check.replace(rname + '\n', '', 1)
                    else:
                        check = check.replace(rname, '', 1)
                if check.strip() == after.strip():
                    log.append({
                        'page': pn,
                        'method': 'isolated_text_stream',
                        'removed_count': len(removed),
                        'removed_name_sha256': hashlib.sha256(removed[0].encode()).hexdigest()
                    })
                    before = after
                    continue
            doc.update_stream(xref, stream)
    return log

def char_map(page):
    text = ''; chars = []; line_id = 0
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                for c in span['chars']:
                    chars.append((len(text), line_id, c['bbox'], c['c']))
                    text += c['c']
            text += '\n'; line_id += 1
    if text != page.get_text('text', sort=False):
        raise ValueError('Text-to-geometry mismatch; page needs alternate extraction')
    return text, chars

def span_rects(chars, a, b):
    by_line = {}
    for offset, line, bbox, c in chars:
        if a <= offset < b and not c.isspace():
            r = fitz.Rect(bbox)
            if line in by_line:
                by_line[line] |= r
            else:
                by_line[line] = r
    return [[round(v, 3) for v in r] for r in by_line.values()]

def expand_rects_with_pixel_ink(page, rects, max_expand_pt=75.0, max_x1=None):
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
            pix = page.get_pixmap(dpi=dpi, clip=probe_rect, alpha=False)
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
                    if found_any and cur_gap > max_gap_px:
                        break

            if found_any and last_ink_px > int(3.0 * scale):
                add_pt = last_ink_px / scale + 3.0
                new_x1 = min(limit_x1, fr.x1 + add_pt)
                fr.x1 = max(fr.x1, new_x1)
        except Exception:
            pass
        expanded_rects.append([round(v, 3) for v in fr])
    return expanded_rects

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

def barcode_rects(page):
    groups = collections.defaultdict(list)
    for d in page.get_drawings():
        r = d['rect']
        if d['fill'] is not None and r.width < 5 and r.height >= 10:
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
                out.append([round(v, 3) for v in rect])
    return out

def _precompile_additional_seeds(seeds):
    """Precompile regex patterns for additional_findings once per document instead of per page."""
    exact_compiled = []
    folded_compiled = []
    phone_compiled = []

    for kind, values in (seeds or {}).items():
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
                split_v = re.split(r'(?i)\s+(?=(?:tuổi|tubi|tudi|giới\s*tính|gibi\s*tinh|khoa|phòng|giường)\s*:)', v)[0].rstrip()
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
            findings.append(Finding('PERSON_NAME', a, a + len(v), .94, v, 'workflow_unlabelled_name_review'))

    if not seeds and not _precompiled:
        return findings

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
    return findings

def vector_qr_rects(page):
    squares = []
    for drawing in page.get_drawings():
        r = drawing['rect']; fill = drawing.get('fill')
        if (fill and max(fill) < .4 and 1 <= r.width <= 8 and 1 <= r.height <= 8
                and abs(r.width - r.height) < .3):
            squares.append(r)
    groups = []
    while squares:
        cluster = [squares.pop()]; bounds = fitz.Rect(cluster[0]); changed = True
        while changed:
            changed = False; remaining = []
            for r in squares:
                pad = max(r.width, r.height) * 2.1
                if (bounds + (-pad, -pad, pad, pad)).intersects(r):
                    cluster.append(r); bounds |= r; changed = True
                else:
                    remaining.append(r)
            squares = remaining
        if len(cluster) >= 80 and .75 < bounds.width / bounds.height < 1.35:
            groups.append([round(v, 3) for v in bounds])
    return groups

def rotated_watermark_rects(page):
    """Detect rotated watermark spans (e.g. Hồ Thị Minh Châu_20260803161916) directly from page dict."""
    out = []
    for b in page.get_text('dict')['blocks']:
        for line in b.get('lines', []):
            if abs(line['dir'][1]) > .1:
                txt = ''.join(s['text'] for s in line['spans']).strip()
                if txt and ('_' in txt or len(txt) >= 6):
                    out.append((txt, [round(v, 3) for v in fitz.Rect(line['bbox'])]))
    return out

def boxed_dob_and_bhyt_proposals(page, chars, text, start_idx=0):
    """Detect 8-box split DOB (1|5|1|0|1|9|5|8) and scanned DOB box strips while strictly protecting Age boxes."""
    proposals = []
    # Find Age column x0 on cover pages ("Tuổi" / "Tuôi" / "Tubi" / "Tuöi")
    age_x0 = min(page.rect.width * 0.85, 515.0)
    for m_age in re.finditer(r'(?i)\b(?:tu[oôơöổ]i|tubi|tudi)\b', text):
        rs = span_rects(chars, m_age.start(), m_age.end())
        if rs and rs[0][0] > 420 and rs[0][1] < 220:
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
        # Collect any digit characters on the same horizontal row between label end and age_x0
        digit_rects = []
        digit_chars = []
        for offset, line_id, bbox, ch in chars:
            if ch.isdigit() and bbox[0] >= lbl[2] - 2.0 and bbox[2] <= age_x0 - 4.0:
                yc = 0.5 * (bbox[1] + bbox[3])
                if row_y0 <= yc <= row_y1:
                    digit_rects.append(fitz.Rect(bbox))
                    digit_chars.append(ch)
        if len(digit_rects) >= 4:
            union = digit_rects[0]
            for dr in digit_rects[1:]:
                union |= dr
            union.x1 = min(union.x1, age_x0 - 5.0)
            proposals.append({
                'id': f'p-dob-box-{start_idx + len(proposals)}',
                'kind': 'DATE_OF_BIRTH',
                'text': ''.join(digit_chars),
                'rule': 'v20_boxed_dob_preserve_age',
                'rects': [[round(v, 3) for v in union]],
                'selected': True,
                'clinical_overlap': False,
            })
        elif lbl[2] + 25.0 < age_x0 - 10.0:
            # Scanned cover sheet where OCR saw "2. Sinh ngày" and "Tuổi" but skipped grid box digits
            box_rect = [round(lbl[2] + 3.0, 3), round(lbl[1] - 3.0, 3), round(age_x0 - 8.0, 3), round(lbl[3] + 4.0, 3)]
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
            bh_rect = [round(lbl[2] + 3.0, 3), round(lbl[1] - 4.0, 3), round(page.rect.width - 36.0, 3), round(lbl[3] + 5.0, 3)]
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

def build_image_and_signature_proposals(page, chars, text, existing_proposals, pn):
    """Classify page images into Logo (keep), Clinical Image (keep), or Doctor Signature (auto-select=True)."""
    out = []
    # Gather signature anchor rects (headings like TRƯỞNG KHOA, GIÁM ĐỐC, BÁC SĨ..., or staff names in lower half)
    sig_anchors = []
    sig_heading_rx = re.compile(
        r'(?i)(?:gi[aá]m\s*đ[oố]c|tr[uư][oơở]ng\s*khoa|b[aá]c\s*s[ĩỹi]\b|b[aá]c\s*cui\s*dinh|'
        r'ng[uư][oơờ]i\s*(?:duy[eệv]t|giao|nh[aậ]n|k[iíyý]|th[uự]c\s*hi[eệ]n)|'
        r'k[yý]\s*s[oố]\s*b[oở]i|x[aá]c\s*nh[aậ]n\s*k[eế]t\s*qu[aả]|chu_ky_)'
    )
    for m in sig_heading_rx.finditer(text):
        rs = span_rects(chars, m.start(), m.end())
        for r in rs:
            sig_anchors.append(fitz.Rect(r))
    for q in existing_proposals:
        if q['kind'] == 'HEALTHCARE_STAFF_NAME':
            for r in q['rects']:
                sig_anchors.append(fitz.Rect(r))

    full_page_scan = False
    for b in page.get_text('dict')['blocks']:
        if b['type'] == 1 and b['width'] > 20 and b['height'] > 15:
            ib = fitz.Rect(b['bbox'])
            # 1. Full-page scan image
            if ib.width > page.rect.width * 0.75 and ib.height > page.rect.height * 0.75:
                full_page_scan = True
                continue
            # 2. Top-left Hospital Logo -> keep (selected=False)
            if ib.x0 < 230 and ib.y0 < 130 and ib.width < 230 and ib.height < 120:
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
            in_bottom_sig_band = (ib.y0 > page.rect.height * 0.52 and ib.width <= 300 and ib.height <= 165)
            is_sig = near_sig or in_bottom_sig_band
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
        tk_rects = []
        for m in re.finditer(r'(?i)(?:t[rnuưoơở&a-z]{2,7}ng\s*khoa|truong\s*khoa|gi[aáåä]m\s*[dđ][oốöc]{2,3}|giam\s*ddc)', text):
            tk_rects.extend(span_rects(chars, m.start(), m.end()))
        staff_rects = [r for q in existing_proposals if q['kind'] in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME'} for r in q['rects'] if r[1] > page.rect.height * 0.7]
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

def generate_audit_markdown(job_dir: Path, data: dict) -> Path:
    """Generate Coordinate-Linked Markdown Audit Summary (AUDIT_SUMMARY.md) for fast double-check."""
    job_dir = Path(job_dir)
    lines = [
        f"# Báo Cáo Khử Định Danh Bệnh Án (`{data.get('study_id', 'HMU_CASE')}`)",
        "",
        f"- **Phiên bản công cụ:** `{data.get('version', VERSION)}`",
        f"- **Tổng số trang:** `{len(data.get('pages', []))}`",
        f"- **Số trang dùng Offline OCR (trang scan/vector):** `{data.get('ocr_pages_count', 0)}`",
        f"- **Số stream watermark đã bóc tách:** `{len(data.get('watermarks_removed', []))}`",
        f"- **Chính sách:** Xóa Tên BN/Người nhà, SĐT, Địa chỉ, Ngày/Năm sinh (giữ Tuổi & Giới tính), Tên & Chữ ký Bác sĩ; Giữ lại Mã HS/BN và Tên Bệnh viện để hậu kiểm.",
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
    for p in data.get("pages", []):
        pn = p["page"]
        lines.append(f"### Trang {pn}")
        redacted_md = p.get("redacted_markdown", "").strip()
        if redacted_md:
            lines.append("```markdown")
            lines.append(redacted_md[:4000])
            lines.append("```")
        else:
            lines.append("*(Trang hình ảnh/biểu đồ không có lớp văn bản)*")
        lines.append("")

    audit_path = job_dir / "AUDIT_SUMMARY.md"
    audit_path.write_text("\n".join(lines), encoding="utf-8")
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
    out = []
    last = 0
    for s, e, k in merged:
        out.append(text[last:s])
        out.append(f"[ĐÃ XÓA:{k}]")
        last = e
    out.append(text[last:])
    return "".join(out)

def prepare(source, job, study_id='HMU_CASE_0001', external_seeds=None, progress_cb=None):
    source = Path(source); job = Path(job)
    if job.exists() and any(job.iterdir()):
        raise ValueError('Use a new empty job directory')
    job.mkdir(parents=True, exist_ok=True); (job / 'pages').mkdir()
    if progress_cb:
        progress_cb(f'Đang trích xuất hạt giống XML & kiểm tra file {source.name}...')
    auto_seeds = extract_case_seeds(source)
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
        textless_pnos = [idx + 1 for idx, t in enumerate(raw_texts) if not t.strip()]
        if textless_pnos:
            for idx_t, pno in enumerate(textless_pnos, 1):
                if progress_cb and (idx_t == 1 or idx_t % 15 == 0 or idx_t == len(textless_pnos)):
                    progress_cb(f'Đang tách ảnh trang scan {idx_t}/{len(textless_pnos)} ({source.name})...')
                doc[pno - 1].get_pixmap(dpi=200, alpha=False).save(job / 'pages' / f'{pno}.png')
            if progress_cb:
                progress_cb(f'Đang chạy OCR bất đồng bộ 0/{len(textless_pnos)} trang scan ({source.name})...')
        ocr_maps = ocr_pdf_pages(
            work,
            textless_pnos,
            dpi=200,
            progress_cb=(lambda done, tot: progress_cb(f'Đang chạy OCR bất đồng bộ {done}/{tot} trang scan ({source.name})...')) if progress_cb else None,
            pre_rendered_dir=job / 'pages',
        ) if textless_pnos else {}

        page_maps = []
        texts = []
        for pn, p in enumerate(doc, 1):
            if pn in ocr_maps:
                t, c = ocr_maps[pn]
            else:
                t, c = char_map(p)
            page_maps.append((t, c))
            texts.append(t)

        findings, known = analyze_hmu_document(texts, external_seeds=auto_seeds)
        seeds = {
            kind: sorted(
                set(known.get(kind, []))
                | {
                    f.text for fs in findings for f in fs
                    if f.entity_type == kind and f.score >= (0.97 if kind in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME_UNCLASSIFIED'} else 0.95)
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
            'study_id': study_id,
            'source_file': source.name,
            'source_sha256': sha(source),
            'working_sha256': sha(work),
            'watermarks_removed': wm,
            'ocr_pages_count': len(textless_pnos),
            'pages': [],
            'policy': 'remove_names_dob_phone_address_doctor_signatures_keep_clinical_and_record_ids',
            'dpi': 200,
            'status': 'NEEDS_VISUAL_REVIEW'
        }
        for pn, (p, (text, chars), fs) in enumerate(zip(doc, page_maps, findings), 1):
            proposals = []
            clinical = protected_hits(text)
            all_fs = fs + additional_findings(text, seeds, _precompiled=precompiled_add)
            boxed_props, age_x0 = boxed_dob_and_bhyt_proposals(p, chars, text, start_idx=0)
            seen = set()
            selected_findings_for_md = []
            for f in all_fs:
                if f.entity_type in {'PATIENT_ID', 'MEDICAL_RECORD_ID', 'SOURCE_LINK_ID'}:
                    continue
                if (f.start, f.end) in seen:
                    continue
                seen.add((f.start, f.end))
                rects = span_rects(chars, f.start, f.end)
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
                is_sel = ('CONFLICT' not in f.rule) and not overlap
                if is_sel:
                    selected_findings_for_md.append(f)
                proposals.append({
                    'id': f'p{pn}-t{len(proposals)}',
                    'kind': f.entity_type,
                    'text': f.text,
                    'rule': f.rule,
                    'rects': rects,
                    'selected': is_sel,
                    'clinical_overlap': overlap
                })
            # Add boxed DOB / BHYT proposals
            for bp in boxed_props:
                bp['id'] = f'p{pn}-box{len(proposals)}'
                proposals.append(bp)
            # Add rotated watermark bounding boxes from page dict
            for wm_txt, wm_rect in rotated_watermark_rects(p):
                proposals.append({
                    'id': f'p{pn}-wm{len(proposals)}',
                    'kind': 'WATERMARK_TEXT',
                    'text': wm_txt,
                    'rule': 'v20_rotated_watermark_bbox',
                    'rects': [wm_rect],
                    'selected': True,
                    'clinical_overlap': False
                })
            # Barcodes kept unselected by default so record/specimen IDs remain for post-inspection
            for r in barcode_rects(p):
                proposals.append({
                    'id': f'p{pn}-b{len(proposals)}',
                    'kind': 'BARCODE_CANDIDATE',
                    'text': 'Mã vạch hồ sơ/bệnh phẩm - giữ để hậu kiểm (chọn nếu muốn xóa)',
                    'rects': [r],
                    'selected': False,
                    'clinical_overlap': False
                })
            for r in vector_qr_rects(p):
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
            for a in list(p.annots() or []):
                proposals.append({
                    'id': f'p{pn}-a{len(proposals)}',
                    'kind': 'ANNOTATION_REVIEW',
                    'text': 'Ghi chú/dấu ký: chọn nếu chứa định danh; giữ nếu có nội dung chuyên môn',
                    'rects': [list(a.rect & p.rect)],
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
                    'rects': [list(w.rect & p.rect)],
                    'selected': is_sig_widget,
                    'clinical_overlap': False
                })
            # Apply ink-bounding-box expansion for text fields to never drop trailing words (like 'Lộc' or 'Cường')
            # Protect Age column on cover sheets if pn <= 3
            protect_max_x1 = min(age_x0 - 5.0, 465.0) if pn <= 3 else (p.rect.width - 25.0)
            for q in proposals:
                if q['selected'] and q['kind'] in {'PATIENT_NAME', 'HEALTHCARE_STAFF_NAME', 'ADDRESS_VN', 'RELATIVE_NAME', 'PERSON_NAME_UNCLASSIFIED', 'PERSON_NAME'}:
                    q['rects'] = expand_rects_with_pixel_ink(p, q['rects'], max_expand_pt=50.0, max_x1=protect_max_x1)

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
                p.get_pixmap(dpi=110, alpha=False).save(page_png)
            raw_page_text = p.get_text('text', sort=False)
            data['pages'].append({
                'page': pn,
                'width': p.rect.width,
                'height': p.rect.height,
                'text_sha256': hashlib.sha256(raw_page_text.encode()).hexdigest(),
                'ocr_used': pn in ocr_maps,
                'reviewed': False,
                'proposals': proposals,
                'manual_rects': [],
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

def remove_selected_image_paints(page, selected_rects):
    if not selected_rects:
        return []
    doc = page.parent
    source = b'\n'.join(doc.xref_stream(x) for x in page.get_contents())
    stream = DecodedStreamObject(); stream.set_data(source); content = ContentStream(stream, None)
    names = {x[7] for x in page.get_images(full=True) if x[9] == 0}
    ctm = fitz.Matrix(1, 0, 0, 1, 0, 0); stack = []; ops = []; removed = []
    for operands, operator in content.operations:
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
                removed.append(match); continue
        ops.append((operands, operator))
    if not removed:
        return []
    before = page.get_text('text', sort=False); content.operations = ops
    newxref = doc.get_new_xref(); doc.update_object(newxref, '<< >>'); doc.update_stream(newxref, content.get_data()); page.set_contents(newxref)
    if page.get_text('text', sort=False) != before:
        doc.update_stream(newxref, source); return []
    return sorted(set(removed))

def apply_review_to_page(p, review, pn):
    image_rects = [r for q in review['proposals'] if q['selected'] and q['kind'] in {'IMAGE_REVIEW', 'SIGNATURE_IMAGE'} for r in q['rects']]
    removed_images = []
    selected_annots = [r for q in review['proposals'] if q['selected'] and q['kind'] == 'ANNOTATION_REVIEW' for r in q['rects']]
    for a in list(p.annots() or []):
        matches = [i for i, r in enumerate(image_rects) if max(abs(x - y) for x, y in zip(a.rect, r)) < .5]
        if matches or any(max(abs(x - y) for x, y in zip(a.rect, r)) < .5 for r in selected_annots):
            p.delete_annot(a); removed_images.extend(matches)
    selected_widgets = [r for q in review['proposals'] if q['selected'] and q['kind'] == 'WIDGET_REVIEW' for r in q['rects']]
    for w in list(p.widgets() or []):
        if any(max(abs(x - y) for x, y in zip(w.rect & p.rect, r)) < .5 for r in selected_widgets):
            removed_images.extend(i for i, r in enumerate(image_rects) if w.rect.contains(fitz.Rect(r)))
            p.delete_widget(w)
    pending = [i for i in range(len(image_rects)) if i not in removed_images]
    removed_images.extend(pending[i] for i in remove_selected_image_paints(p, [image_rects[i] for i in pending]))
    fallback = [r for i, r in enumerate(image_rects) if i not in removed_images]
    rects = [
        r for q in review['proposals']
        if q['selected'] and q['kind'] not in {'IMAGE_REVIEW', 'SIGNATURE_IMAGE', 'ANNOTATION_REVIEW', 'WIDGET_REVIEW'}
        for r in q['rects']
    ] + fallback + review['manual_rects']
    if any(q['selected'] and q['clinical_overlap'] for q in review['proposals']):
        raise ValueError(f'Clinical overlap on page {pn}; deselect/correct before export')
    for rect in rects:
        p.add_redact_annot(fitz.Rect(rect) & p.rect, fill=(1, 1, 1))
    if rects:
        p.apply_redactions(images=2, graphics=2, text=0)
    return rects, removed_images, fallback

def approve_all_pages(job):
    """Mark all pages in a job directory as reviewed=True and persist review.json."""
    job = Path(job)
    current = json.loads((job / 'review.json').read_text(encoding='utf-8'))
    for page_item in current['pages']:
        page_item['reviewed'] = True
    with fitz.open(job / 'working_private.pdf') as doc:
        validate_review(current, doc)
    save_json(job / 'review.json', current)
    return current

def export(job, draft=False, approve_all=False, output_path=None, progress_cb=None):
    job = Path(job)
    if approve_all:
        data = approve_all_pages(job)
    else:
        data = json.loads((job / 'review.json').read_text(encoding='utf-8'))
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
    output = Path(output_path) if output_path else job / (study_id + ('_DRAFT.pdf' if draft else '_REDACTED.pdf'))
    report = []; final = fitz.open()
    with fitz.open(work) as doc:
        total_pages = len(doc)
        validate_review(data, doc)
        for pn, (p, review) in enumerate(zip(doc, data['pages']), 1):
            if progress_cb and (pn == 1 or pn % 10 == 0 or pn == total_pages):
                progress_cb(f'Đang xóa định danh & kết xuất PDF trang {pn}/{total_pages}...')
            rects, removed_images, fallback = apply_review_to_page(p, review, pn)
            pix = p.get_pixmap(dpi=int(data.get('dpi', 200)), alpha=False, annots=True)
            scale = int(data.get('dpi', 200)) / 72
            for r in rects:
                ir = ((fitz.Rect(r) & p.rect) * fitz.Matrix(scale, scale)).irect & pix.irect
                if not ir.is_empty:
                    pix.set_rect(ir, (255, 255, 255))
            new = final.new_page(width=p.rect.width, height=p.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes('png'))
            report.append({
                'page': pn,
                'reviewed': review['reviewed'],
                'redaction_regions': len(rects),
                'image_paints_removed': len(removed_images),
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
        'pages': len(report),
        'dpi': data.get('dpi', 200),
        'watermarks_removed': len(data['watermarks_removed']),
        'source_objects_copied': False,
        'searchable_text': False,
        'attachments': 0,
        'status': 'DRAFT_NEEDS_QC' if draft else 'HUMAN_REVIEWED_NEEDS_FINAL_QC',
        'dicom_jpeg_processed': False,
        'page_results': report
    }
    save_json(output.with_suffix('.qc.json'), result)
    return output, result

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
    shared_seeds = extract_case_seeds(case_path)
    # First pass over up to 5 cover/key files to enrich shared_seeds (e.g. EMR_BA001 cover sheet in 1.DHYHN)
    cover_candidates = [p for p in pdfs if 'BA001' in p.name or 'Tờ_bìa' in p.name] + pdfs[:3]
    sample_texts = []
    for cp in cover_candidates[:4]:
        try:
            with fitz.open(cp) as d:
                for p in d[:2]:
                    t = p.get_text('text', sort=False)
                    if t.strip():
                        sample_texts.append(t)
        except Exception:
            pass
    if sample_texts:
        _, learned = analyze_hmu_document(sample_texts, external_seeds=shared_seeds)
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
        sub_id = f"{study_id}_F{idx:03d}" if len(pdfs) > 1 else study_id
        sub_job = job_root / f"file_{idx:03d}"
        d = prepare(
            pdf_file,
            sub_job,
            study_id=sub_id,
            external_seeds=shared_seeds,
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

def export_case(job_root, draft=False, approve_all=True, progress_cb=None):
    """Export all prepared PDFs in a case job directory, preserving individual PDF files."""
    job_root = Path(job_root).resolve()
    manifest_path = job_root / 'case_manifest.json'
    if not manifest_path.exists():
        out, qc = export(job_root, draft=draft, approve_all=approve_all, progress_cb=progress_cb)
        return {'outputs': [str(out)], 'qcs': [qc]}

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    out_dir = job_root / 'output_pdfs'
    out_dir.mkdir(exist_ok=True)
    outputs = []
    qcs = []
    patient_names = manifest.get('shared_seeds', {}).get('PATIENT_NAME', [])
    total_files = len(manifest['files'])
    for idx, item in enumerate(manifest['files'], 1):
        sub_job = job_root / item['sub_job']
        # Anonymize patient name in output filename if present while keeping original file structure
        safe_name = item['source_name']
        for pname in patient_names:
            safe_name = re.sub(re.escape(pname), 'REDACTED', safe_name, flags=re.I)
            safe_name = re.sub(re.escape(_strip_accents(pname)), 'REDACTED', safe_name, flags=re.I)
        target_pdf = out_dir / safe_name
        out, qc = export(
            sub_job,
            draft=draft,
            approve_all=approve_all,
            output_path=target_pdf,
            progress_cb=(lambda msg, i=idx, n=total_files: progress_cb(f'[Xuất file {i}/{n}] {msg}')) if progress_cb else None,
        )
        outputs.append(str(out))
        qcs.append(qc)
    return {'outputs': outputs, 'output_dir': str(out_dir), 'count': len(outputs)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('pdf'); prep.add_argument('--job', required=True); prep.add_argument('--study-id', default='HMU_CASE_0001')
    exp = sub.add_parser('export'); exp.add_argument('--job', required=True); exp.add_argument('--draft', action='store_true'); exp.add_argument('--approve-all', action='store_true')
    pcase = sub.add_parser('prepare-case'); pcase.add_argument('path'); pcase.add_argument('--job', required=True); pcase.add_argument('--study-id', default='HMU_CASE_0001')
    ecase = sub.add_parser('export-case'); ecase.add_argument('--job', required=True); ecase.add_argument('--draft', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        d = prepare(args.pdf, args.job, study_id=args.study_id)
        print(json.dumps({'pages': len(d['pages']), 'job': args.job, 'ocr_pages': d['ocr_pages_count'], 'watermarks_removed': len(d['watermarks_removed'])}))
    elif args.command == 'export':
        out, result = export(args.job, args.draft, approve_all=args.approve_all)
        print(json.dumps({'output': str(out), 'status': result['status']}))
    elif args.command == 'prepare-case':
        m = prepare_case(args.path, args.job, study_id=args.study_id)
        print(json.dumps({'files': len(m['files']), 'job': args.job}))
    elif args.command == 'export-case':
        res = export_case(args.job, draft=args.draft, approve_all=True)
        print(json.dumps(res))
