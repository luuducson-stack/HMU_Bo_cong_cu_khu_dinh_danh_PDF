import unittest,tempfile,json,hashlib
from pathlib import Path
import fitz
from engine import prepare,export,save_json,apply_review_to_page,span_rects,prepare_case,export_case,approve_all_pages
from ocr_helper import ocr_pdf_pages

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'input.pdf';d=fitz.open();p=d.new_page(width=500,height=300)
        p.insert_text((30,50),'Ho ten: Nguyen Van An',fontsize=12)
        p.insert_text((30,100),'Clinical: C34 / C71.9 / D38.1',fontsize=12)
        p.insert_text((30,130),'Creatinin 95; Glucose 5.2',fontsize=12)
        d.set_metadata({'author':'PERSON PRIVATE'});d.embfile_add('secret.txt',b'SECRET ID')
        d.save(self.source);d.close()
        self.job=self.root/'job';self.data=prepare(self.source,self.job)
    def tearDown(self):self.temp.cleanup()
    def test_export_requires_review(self):
        with self.assertRaises(ValueError):export(self.job)
    def test_redaction_and_rebuild(self):
        # Manual rectangle selects patient text but leaves clinical lines.
        self.data['pages'][0]['manual_rects']=[[25,35,210,54]]
        self.data['pages'][0]['reviewed']=True;save_json(self.job/'review.json',self.data)
        original_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        out,qc=export(self.job)
        with fitz.open(out) as d:
            self.assertEqual(d[0].get_text(),'');self.assertEqual(d.embfile_count(),0)
            self.assertNotIn('PERSON PRIVATE',str(d.metadata));self.assertTrue(d[0].get_images())
            # Output has a white patient region and still has visible clinical ink.
            blank=d[0].get_pixmap(dpi=200,clip=fitz.Rect(26,35,209,54))
            self.assertGreater(sum(blank.samples)/len(blank.samples),254)
            clinical=d[0].get_pixmap(dpi=200,clip=fitz.Rect(25,85,300,135))
            self.assertLess(sum(clinical.samples)/len(clinical.samples),253)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),original_hash)
        self.assertFalse(qc['source_objects_copied'])
    def test_modified_working_pdf_rejected(self):
        with (self.job/'working_private.pdf').open('ab') as f:f.write(b'changed')
        with self.assertRaises(ValueError):export(self.job,True)
    def test_rectangle_outside_page_rejected(self):
        self.data['pages'][0]['manual_rects']=[[-1,0,100,100]]
        save_json(self.job/'review.json',self.data)
        with self.assertRaises(ValueError):export(self.job,True)
    def test_metadata_and_page_structure(self):
        self.assertEqual(len(self.data['pages']),1)
        self.assertTrue(all(q['rects'] for q in self.data['pages'][0]['proposals']))
        self.assertFalse(any(q['clinical_overlap'] for q in self.data['pages'][0]['proposals']))

    def test_image_padding_does_not_erase_clinical_text(self):
        d=fitz.open();p=d.new_page(width=300,height=200)
        p.insert_text((40,90),'Clinical C34')
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),True)
        pix.clear_with(255);pix.set_alpha(bytes(10000))
        p.insert_image(fitz.Rect(30,30,150,130),stream=pix.tobytes('png'))
        before=p.get_text()
        state={'proposals':[{'kind':'IMAGE_REVIEW','selected':True,'rects':[[30,30,150,130]],'clinical_overlap':False}],'manual_rects':[]}
        rects,removed,fallback=apply_review_to_page(p,state,1)
        self.assertEqual(p.get_text(),before);self.assertEqual(removed,[0]);self.assertEqual(fallback,[])
        d.close()
    def test_selected_annotation_preserves_underlying_text(self):
        d=fitz.open();p=d.new_page(width=300,height=200)
        p.insert_text((40,90),'Clinical C34')
        a=p.add_freetext_annot(fitz.Rect(30,30,150,130),'PRIVATE NAME')
        state={'proposals':[{'kind':'ANNOTATION_REVIEW','selected':True,'rects':[list(a.rect)],'clinical_overlap':False}],'manual_rects':[]}
        apply_review_to_page(p,state,1)
        self.assertIn('Clinical C34',p.get_text());self.assertFalse(list(p.annots() or []));d.close()

    def test_ocr_pdf_pages_on_image_only_page(self):
        # Create a PDF page with text, rasterize it to an image-only PDF (fonts=0), and test OCR char_map
        src_doc = fitz.open()
        sp = src_doc.new_page(width=600, height=400)
        sp.insert_text((50, 80), 'Ho ten: TRAN THI BAN', fontsize=16)
        sp.insert_text((50, 120), 'Bac si chi dinh: Nguyen Van Thuyen', fontsize=16)
        pix = sp.get_pixmap(dpi=200, alpha=False)
        src_doc.close()

        img_pdf = self.root / 'image_only.pdf'
        img_doc = fitz.open()
        for _ in range(2):
            ip = img_doc.new_page(width=600, height=400)
            ip.insert_image(ip.rect, stream=pix.tobytes('png'))
        img_doc.save(img_pdf)
        img_doc.close()

        ocr_res = ocr_pdf_pages(img_pdf, [1, 2], dpi=200)
        self.assertIn(1, ocr_res)
        self.assertIn(2, ocr_res)
        text, chars = ocr_res[1]
        self.assertIn('TRAN THI BAN', text.upper())
        self.assertEqual(len(text), len(chars))
        idx = text.upper().find('TRAN THI BAN')
        rects = span_rects(chars, idx, idx + len('TRAN THI BAN'))
        self.assertTrue(rects)
        # Ensure bounding box is near y=60..95 on the 600x400 PDF page
        self.assertTrue(40 <= rects[0][1] <= 95 and 60 <= rects[0][3] <= 110)

    def test_boxed_dob_redacted_and_age_preserved(self):
        pdf_path = self.root / 'boxed_dob.pdf'
        doc = fitz.open()
        p = doc.new_page(width=600, height=300)
        p.insert_text((40, 80), '1. Ho va ten (In hoa): CAO THI SUONG', fontsize=11)
        p.insert_text((520, 65), 'Tuoi', fontsize=10)
        p.insert_text((300, 80), '2. Ngay sinh', fontsize=10)
        for idx, digit in enumerate(['1', '5', '1', '0', '1', '9', '5', '8']):
            p.insert_text((365 + idx * 16, 80), digit, fontsize=10)
        # Age boxes (6 | 8) on the right at x=525, 545
        p.insert_text((525, 80), '6', fontsize=10)
        p.insert_text((545, 80), '8', fontsize=10)
        doc.save(pdf_path)
        doc.close()

        job_dir = self.root / 'job_boxed'
        data = prepare(pdf_path, job_dir)
        props = data['pages'][0]['proposals']
        dob_rects = [r for q in props if q['selected'] and q['kind'] == 'DATE_OF_BIRTH' for r in q['rects']]
        self.assertTrue(dob_rects, 'Expected boxed DOB to be detected and selected')
        # Verify DOB rects cover x=365..485 but never reach Age at x>=520
        for r in dob_rects:
            self.assertLess(r[2], 518, f'DOB rect {r} overlapped Age column!')

    def test_multi_watermark_redacted_and_excluded_from_patient(self):
        pdf_path = self.root / 'multi_wm.pdf'
        doc = fitz.open()
        p = doc.new_page(width=600, height=400)
        p.insert_text((40, 60), '1. Ho va ten: CAO THI SUONG', fontsize=12)
        for y in (120, 220, 320):
            p.insert_text((100, y), 'Ho Thi Minh Chau_20260803161916', fontsize=10, rotate=90)
        doc.save(pdf_path)
        doc.close()

        job_dir = self.root / 'job_wm'
        data = prepare(pdf_path, job_dir)
        props = data['pages'][0]['proposals']
        wm_props = [q for q in props if q['selected'] and q['kind'] == 'WATERMARK_TEXT']
        self.assertGreaterEqual(len(wm_props), 1)
        patient_props = [q for q in props if q['kind'] == 'PATIENT_NAME']
        self.assertTrue(all('Chau' not in q['text'] for q in patient_props))

    def test_auto_signature_selection_preserves_logo_and_clinical_image(self):
        pdf_path = self.root / 'sig_vs_logo.pdf'
        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 50), False)
        pix.clear_with(200)
        # 1. Top-left logo (should stay selected=False)
        p.insert_image(fitz.Rect(30, 20, 120, 70), stream=pix.tobytes('png'))
        # 2. Large clinical image in middle (should stay selected=False)
        p.insert_image(fitz.Rect(50, 200, 450, 450), stream=pix.tobytes('png'))
        # 3. Doctor signature image under TRUONG KHOA heading (should be selected=True)
        p.insert_text((380, 580), 'TRUONG KHOA', fontsize=12)
        p.insert_image(fitz.Rect(360, 600, 480, 660), stream=pix.tobytes('png'))
        p.insert_text((370, 680), 'BSCKII. Pham Ba Que', fontsize=12)
        doc.save(pdf_path)
        doc.close()

        job_dir = self.root / 'job_sig'
        data = prepare(pdf_path, job_dir)
        props = data['pages'][0]['proposals']
        img_props = [q for q in props if q['kind'] in {'IMAGE_REVIEW', 'SIGNATURE_IMAGE'}]
        self.assertEqual(len(img_props), 3)
        # Logo at top-left
        self.assertFalse(img_props[0]['selected'])
        # Large clinical image
        self.assertFalse(img_props[1]['selected'])
        # Signature image under TRUONG KHOA
        self.assertTrue(img_props[2]['selected'])

    def test_audit_summary_and_case_folder_mode(self):
        case_dir = self.root / '2603040231_LE_THI_LINH'
        case_dir.mkdir()
        for idx in (1, 2):
            f = case_dir / f'doc_{idx}.pdf'
            d = fitz.open()
            p = d.new_page(width=500, height=300)
            if idx == 1:
                p.insert_text((30, 50), 'Ho ten: LE THI LINH', fontsize=12)
                p.insert_text((30, 80), 'Ngay sinh: 14/07/1965   Tuoi: 61', fontsize=12)
            else:
                # Second file has unlabelled patient name propagated from case seeds
                p.insert_text((30, 50), 'Benh nhan: LE THI LINH', fontsize=12)
                p.insert_text((30, 80), 'Ma ho so: 2603040231   Ket qua: Binh thuong', fontsize=12)
            d.save(f)
            d.close()

        case_job = self.root / 'case_job'
        summary = prepare_case(case_dir, case_job, study_id='DHYHN_01')
        self.assertEqual(len(summary['files']), 2)
        self.assertTrue((case_job / 'AUDIT_SUMMARY.md').exists())
        out_info = export_case(case_job, approve_all=True)
        self.assertEqual(len(out_info['outputs']), 2)
        for out_pdf in out_info['outputs']:
            self.assertTrue(Path(out_pdf).exists())

    def test_approve_all_pages_and_audit_markdown_content(self):
        updated = approve_all_pages(self.job)
        self.assertTrue(all(p['reviewed'] for p in updated['pages']))
        out, qc = export(self.job)
        self.assertTrue(out.exists())
        self.assertEqual(qc['status'], 'HUMAN_REVIEWED_NEEDS_FINAL_QC')
        audit_md = (self.job / 'AUDIT_SUMMARY.md').read_text(encoding='utf-8')
        self.assertIn('Nguyen Van An', audit_md)
        self.assertIn('[ĐÃ XÓA:PATIENT_NAME]', audit_md)

    def test_ink_expansion_and_proposal_subsumption(self):
        from engine import expand_rects_with_pixel_ink, merge_and_subsume_proposals
        doc = fitz.open()
        p = doc.new_page(width=500, height=200)
        # Draw "BSCKI. Dong Manh Cuong"
        p.insert_text((50, 80), 'BSCKI. Dong Manh Cuong', fontsize=12)
        # Suppose OCR only caught 'BSCKI. Dong Manh' ending around x=140
        fake_rect = [50.0, 70.0, 140.0, 85.0]
        expanded = expand_rects_with_pixel_ink(p, [fake_rect], max_expand_pt=80.0, max_x1=450.0)
        self.assertEqual(len(expanded), 1)
        # Should expand to cover "Cuong" past x=170
        self.assertGreater(expanded[0][2], 170.0, f"Expected ink expansion beyond 170, got: {expanded[0]}")

        # Test Subsumption
        props = [
            {'id': 'p1-1', 'kind': 'PATIENT_NAME', 'text': 'TRINH VAN HUONG', 'rects': [[100, 50, 200, 70]], 'selected': True},
            {'id': 'p1-2', 'kind': 'HEALTHCARE_STAFF_NAME', 'text': 'VAN HUONG', 'rects': [[130, 50, 200, 70]], 'selected': True},
            {'id': 'p1-3', 'kind': 'ADDRESS_VN', 'text': 'Xa Van Loc', 'rects': [[100, 100, 180, 120]], 'selected': True},
        ]
        subsumed = merge_and_subsume_proposals(props)
        # Different field types retain their review identities even when nested.
        texts = [q['text'] for q in subsumed]
        self.assertIn('TRINH VAN HUONG', texts)
        self.assertIn('VAN HUONG', texts)
        self.assertIn('Xa Van Loc', texts)
        doc.close()

if __name__=='__main__':unittest.main()
