import json
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import fitz
import engine as e
from hmu_recognizers import analyze_hmu_text, analyze_hmu_document


class Round2Tests(unittest.TestCase):
    def test_uncertain_staff_name_does_not_authorize_image_redaction(self):
        for full in (False,True):
            with self.subTest(full=full):
                doc=fitz.open();p=doc.new_page(width=400,height=400)
                pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);pix.clear_with(180)
                p.insert_image(p.rect if full else fitz.Rect(220,210,285,275),pixmap=pix)
                if full:p.insert_text((260,305),'Truong khoa')
                text,chars=e.char_map(p)
                uncertain=dict(kind='HEALTHCARE_STAFF_NAME',rects=[[245,350,330,365]] if full else [[210,185,290,199]],selected=False,review_status='CONTEXT_REQUIRED')
                props=e.build_image_and_signature_proposals(p,chars,text,[uncertain],1)
                self.assertFalse([q for q in props if q['selected']]);doc.close()

    def test_narrative_doctor_mention_is_not_a_signature_image_heading(self):
        for label,selected in (('Bac si ghi nhan',False),('Bac si',True),('Truong khoa ghi nhan',False),('Truong khoa',True)):
            with self.subTest(label=label):
                doc=fitz.open();p=doc.new_page(width=400,height=400)
                p.insert_text((180,180),label);pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);pix.clear_with(180)
                p.insert_image(fitz.Rect(220,210,285,275),pixmap=pix);text,chars=e.char_map(p)
                props=e.build_image_and_signature_proposals(p,chars,text,[],1)
                self.assertEqual(any(q['selected'] for q in props),selected);doc.close()

    def test_full_scan_signature_zone_requires_a_standalone_leader_heading(self):
        for label,selected in (('Truong khoa ghi nhan',False),('Truong khoa',True)):
            with self.subTest(label=label):
                doc=fitz.open();p=doc.new_page(width=400,height=400)
                pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);pix.clear_with(180)
                p.insert_image(p.rect,pixmap=pix);p.insert_text((260,305),label)
                text,chars=e.char_map(p)
                staff=dict(kind='HEALTHCARE_STAFF_NAME',rects=[[245,350,330,365]],selected=True)
                props=e.build_image_and_signature_proposals(p,chars,text,[staff],1)
                self.assertEqual(any(q['selected'] for q in props),selected);doc.close()

    def test_geometry_validator_uses_original_unicode_offsets_before_seed_learning(self):
        text=unicodedata.normalize('NFD','Bác sĩ điều trị: NGUYỄN VĂN AN')+'\r\n';seen=[]
        def validate(page,f):
            self.assertEqual(page,0);self.assertEqual(text[f.start:f.end],f.text);seen.append(f)
            return False
        pages,known=analyze_hmu_document([text],_finding_validator=validate)
        self.assertTrue(seen);self.assertFalse(known.get('HEALTHCARE_STAFF_NAME'))
        self.assertTrue(all(f.review_status=='CONTEXT_REQUIRED' for f in pages[0]))

    def test_wrapped_title_name_cannot_jump_into_clinical_column(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page(width=500,height=240)
            p.insert_text((30,40),'Ho ten: TRAN VAN AN');p.insert_text((40,100),'BSCKI. NGUYEN VAN')
            p.insert_text((280,116),'Spironolacton');drug=p.search_for('Spironolacton')[0]
            control=fitz.open();cp=control.new_page(width=500,height=240);cp.insert_image(cp.rect,pixmap=p.get_pixmap(dpi=200,alpha=False));expected=cp.get_pixmap(dpi=200,clip=drug,alpha=False).samples
            doc.save(root/'input.pdf');doc.close();data=e.prepare(root/'input.pdf',root/'job',case_xml_index=[])
            crossing=[q for q in data['pages'][0]['proposals'] if any(fitz.Rect(r).intersects(drug) for r in q['rects'])]
            self.assertTrue(crossing);self.assertTrue(all(not q['selected'] for q in crossing))
            output,_=e.export(root/'job',draft=True)
            with fitz.open(output) as final:self.assertEqual(final[0].get_pixmap(dpi=200,clip=drug,alpha=False).samples,expected)
            control.close()

    def test_bhyt_box_strip_preserves_following_age_field(self):
        doc=fitz.open();p=doc.new_page(width=700,height=400)
        p.insert_text((280,180),'So the BHYT: DN4014012345678',fontsize=10)
        p.insert_text((520,180),'Tuoi: 94',fontsize=10)
        text,chars=e.char_map(p);qs,_=e.boxed_dob_and_bhyt_proposals(p,chars,text)
        age=p.search_for('Tuoi: 94')[0];self.assertTrue(qs)
        self.assertFalse(any(fitz.Rect(r).intersects(age) for q in qs for r in q['rects']))
        doc.close()

    def test_dob_on_same_row_cannot_redact_age_in_small_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page(width=400,height=180)
            p.insert_text((30,60),'Sinh ngay: 01/01/1950',fontsize=10);p.insert_text((200,60),'Tuoi: 94',fontsize=10)
            age=p.search_for('Tuoi: 94')[0];control=fitz.open();cp=control.new_page(width=400,height=180)
            cp.insert_image(cp.rect,pixmap=p.get_pixmap(dpi=200,alpha=False));expected=cp.get_pixmap(dpi=200,clip=age,alpha=False).samples
            doc.save(root/'input.pdf');doc.close();data=e.prepare(root/'input.pdf',root/'job',case_xml_index=[])
            self.assertTrue([q for q in data['pages'][0]['proposals'] if q['kind']=='DATE_OF_BIRTH' and q['selected']])
            output,_=e.export(root/'job',draft=True)
            with fitz.open(output) as final:self.assertEqual(final[0].get_pixmap(dpi=200,clip=age,alpha=False).samples,expected)
            control.close()

    def test_dob_fallback_strip_stops_before_nearby_age_label(self):
        doc=fitz.open();p=doc.new_page(width=400,height=180)
        p.insert_text((30,60),'Sinh ngay:');p.insert_text((200,60),'Tuoi')
        text,chars=e.char_map(p);qs,_=e.boxed_dob_and_bhyt_proposals(p,chars,text)
        age=p.search_for('Tuoi')[0]
        self.assertTrue(qs);self.assertTrue(all(fitz.Rect(r).x1<age.x0 for q in qs for r in q['rects']))
        doc.close()

    def test_scan_auto_selects_confirmed_identity_and_keeps_uncertain_and_clinical(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page(width=400,height=500)
            p.insert_text((30,40),'Ho ten: NGUYEN VAN AN');p.insert_text((30,65),'Bac si dieu tri: Ho Van Hai')
            p.insert_text((30,105),'HINH ANH');p.insert_text((30,400),'KET QUA')
            image=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,300,180),False);image.clear_with(180)
            p.insert_image(fitz.Rect(30,120,370,330),pixmap=image)
            doc.new_page(width=400,height=500).insert_text((30,60),'Ho van hai la: Nhe')
            doc.save(root/'input.pdf');doc.close()
            with patch.object(e,'ocr_pdf_pages',return_value={1:('',[])}) as ocr:
                data=e.prepare(root/'input.pdf',root/'job',case_xml_index=[])
            ocr.assert_called_once()
            names=[q for q in data['pages'][0]['proposals'] if q['kind'] in {'PATIENT_NAME','HEALTHCARE_STAFF_NAME'}]
            self.assertTrue(names);self.assertTrue(all(q['selected'] for q in names))
            images=[q for q in data['pages'][0]['proposals'] if q['kind']=='IMAGE_REVIEW']
            self.assertTrue(images);self.assertTrue(all(not q['selected'] for q in images))
            uncertain=[q for q in data['pages'][1]['proposals'] if q.get('review_status')=='CONTEXT_REQUIRED']
            self.assertTrue(uncertain);self.assertTrue(all(not q['selected'] for q in uncertain))

    def test_export_keeps_patient_age_and_offers_no_age_redactions(self):
        for value in ('94', '9 | 4', '100', '0'):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as td:
                root=Path(td);doc=fitz.open();p=doc.new_page(width=400,height=180)
                p.insert_text((30,60),'Ho ten: NGUYEN VAN AN');p.insert_text((30,90),'Tuoi: '+value+' tuoi')
                area=fitz.Rect(25,75,250,96);control=fitz.open();cp=control.new_page(width=400,height=180)
                cp.insert_image(cp.rect,pixmap=p.get_pixmap(dpi=200,alpha=False));expected=cp.get_pixmap(dpi=200,clip=area,alpha=False).samples
                doc.save(root/'input.pdf');doc.close();data=e.prepare(root/'input.pdf',root/'job',case_xml_index=[])
                self.assertFalse([q for q in data['pages'][0]['proposals'] if q['kind']=='PATIENT_AGE'])
                product,_=e.export(root/'job',draft=True)
                with fitz.open(product) as output:self.assertEqual(output[0].get_pixmap(dpi=200,clip=area,alpha=False).samples,expected)
                audit=(root/'job/AUDIT_SUMMARY.md').read_text(encoding='utf8')
                self.assertIn(value,audit);self.assertIn('Giữ Tuổi',audit)
                self.assertNotIn('giá trị Tuổi',audit)
                control.close()

    def test_clinical_header_suffix_is_not_a_person_name_field(self):
        for heading in ('Chẩn đoán bệnh nhân', 'Chẩn đoán người bệnh', 'Chẩn đoán BN',
                        'Kết luận của bác sĩ', 'Ý kiến bác sĩ điều trị', 'Y lệnh điều dưỡng'):
            with self.subTest(heading=heading):
                clinical=heading+': Hở van hai lá: Nhẹ'
                pages,_=analyze_hmu_document(['Họ tên: Hồ Văn Hải\nBác sĩ điều trị: Hồ Văn Hải',clinical])
                self.assertTrue(pages[1]);self.assertTrue(all(f.review_status=='CONTEXT_REQUIRED' for f in pages[1]))
                found=e.additional_findings(clinical,{'PATIENT_NAME':['Hồ Văn Hải'],'HEALTHCARE_STAFF_NAME':['Hồ Văn Hải']})
                self.assertTrue(found);self.assertTrue(all(f.review_status=='CONTEXT_REQUIRED' for f in found))

    def test_learned_full_names_require_person_context_in_every_path(self):
        for label, seed, clinical in (
            ('Bác sĩ điều trị', 'Hồ Văn Hải', 'Hở van hai lá: Nhẹ'),
            ('Họ tên', 'Hồ Văn Hải', 'Hở van hai lá: Nhẹ'),
            ('Bac si dieu tri', 'Ho Van Hai', 'Ho van hai la: Nhe'),
            ('Họ tên', 'Lỗ Văn Hải', 'Lỗ van hai lá: 2 cm2'),
        ):
            with self.subTest(label=label, seed=seed):
                pages, _ = analyze_hmu_document([label+': '+seed, clinical])
                self.assertTrue(pages[1])
                self.assertTrue(all(f.review_status == 'CONTEXT_REQUIRED' for f in pages[1]))
                extra=e.additional_findings(clinical,{kind:[seed] for kind in ('PATIENT_NAME','HEALTHCARE_STAFF_NAME','PERSON_NAME','RELATIVE_NAME')})
                self.assertTrue(extra)
                self.assertTrue(all(f.review_status == 'CONTEXT_REQUIRED' for f in extra))

    def test_ink_expansion_preserves_adjacent_unlabelled_clinical_result(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page(width=400,height=160)
            p.insert_text((30,60),'Ho ten: NGUYEN VAN AN',fontsize=10)
            p.insert_text((159,60),'EF 94',fontsize=10)
            clinical=p.search_for('EF 94')[0];name=p.search_for('NGUYEN VAN AN')[0]
            reference=fitz.open();rp=reference.new_page(width=400,height=160);rp.insert_image(rp.rect,pixmap=p.get_pixmap(dpi=200,alpha=False))
            expected=rp.get_pixmap(dpi=200,clip=clinical,alpha=False).samples
            doc.save(root/'input.pdf');doc.close()
            e.prepare(root/'input.pdf',root/'job',case_xml_index=[]);product,_=e.export(root/'job',draft=True)
            with fitz.open(product) as final:
                self.assertEqual(final[0].get_pixmap(dpi=200,clip=clinical,alpha=False).samples,expected)
                self.assertFalse(any(c<220 for c in final[0].get_pixmap(dpi=200,clip=name,alpha=False).samples))
            reference.close()

    def test_standalone_fuzzy_surname_given_clinical_words_require_context(self):
        pages, _ = analyze_hmu_document(['Người in: Lê Thị Văn', 'lỗ van'])
        self.assertTrue(pages[1])
        self.assertTrue(all(f.review_status == 'CONTEXT_REQUIRED' for f in pages[1]))

    def test_staff_role_in_narrative_cannot_authorize_fuzzy_clinical_words(self):
        pages, _ = analyze_hmu_document(['Bác sĩ điều trị: Nguyễn Văn Hải',
            'Bác sĩ điều trị van hai lá hở.\nBác sĩ: Văn Hải\nBác sĩ điều trị\nVăn Hải'])
        self.assertFalse([f for f in pages[1] if f.start < 29 and f.review_status != 'CONTEXT_REQUIRED'])
        self.assertEqual(len([f for f in pages[1] if f.text == 'Văn Hải' and f.review_status != 'CONTEXT_REQUIRED']), 2)

    def test_unlabelled_candidates_cannot_teach_clinical_words_as_staff(self):
        pages, known = analyze_hmu_document(['CAO HUYẾT ÁP\nĐỖ VĂN HẢI', 'CAO HUYẾT ÁP'])
        self.assertTrue(pages[0])
        self.assertTrue(all(f.review_status == 'CONTEXT_REQUIRED' for fs in pages for f in fs))
        self.assertFalse(known.get('PERSON_NAME_UNCLASSIFIED'))

    def test_unlabelled_engine_candidates_remain_visible_without_auto_mask(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page();p.insert_text((30,60),'Cao Huyet Ap')
            doc.save(root/'source.pdf');doc.close()
            data=e.prepare(root/'source.pdf',root/'job',case_xml_index=[])
            candidates=[q for q in data['pages'][0]['proposals'] if q['kind'] in {'PERSON_NAME','PERSON_NAME_UNCLASSIFIED','HEALTHCARE_STAFF_NAME'}]
            self.assertTrue(candidates);self.assertTrue(all(not q['selected'] for q in candidates))

    def test_bare_age_heading_cannot_consume_number_on_next_field(self):
        text='Tuổi\n1.1--10 ten (in hoa): TRẦN VĂN AN 2. Sinh ngày:'
        self.assertFalse([f for f in analyze_hmu_text(text) if f.entity_type=='PATIENT_AGE'])
        self.assertEqual([f.text for f in analyze_hmu_text('Tuổi:\n94') if f.entity_type=='PATIENT_AGE'],['94'])

    def test_export_compresses_unique_raster_images_before_saving(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'input.pdf';doc=fitz.open()
            for _ in range(2):
                p=doc.new_page(width=200,height=150);p.insert_text((20,50),'Ho ten: NGUYEN VAN AN')
            doc.save(source);doc.close();e.prepare(source,root/'job',case_xml_index=[])
            compressed=[];update=fitz.Document.update_stream;save=fitz.Document.save
            def write(document,xref,buffer,*args,**kwargs):
                if document.xref_is_image(xref):compressed.append(xref)
                return update(document,xref,buffer,*args,**kwargs)
            def checked_save(document,*args,**kwargs):
                for page in document:
                    for image in page.get_images():
                        self.assertLess(len(document.xref_stream_raw(image[0])),len(document.xref_stream(image[0])))
                return save(document,*args,**kwargs)
            with patch.object(fitz.Document,'update_stream',new=write),patch.object(fitz.Document,'save',new=checked_save):
                e.export(root/'job',draft=True)
            self.assertEqual(len(compressed),1)

    def test_patient_age_in_narrative_keeps_clinical_numbers(self):
        text='Bệnh nhân nam94 tuổi, tỉnh táo; EF 94; nhịp tim 94. Tiền sử: khởi phát bệnh lúc 40 tuổi.'
        self.assertEqual([f.text for f in analyze_hmu_text(text) if f.entity_type=='PATIENT_AGE'],['94'])

    def test_clinical_image_band_takes_priority_over_nearby_signature(self):
        doc=fitz.open();p=doc.new_page(width=450,height=400)
        p.insert_text((250,160),'Bac si dieu tri')
        p.insert_text((40,180),'HINH ANH NOI SOI');p.insert_text((40,300),'KET QUA NOI SOI')
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,64,64),False);pix.clear_with(60)
        photo=fitz.Rect(70,190,190,280);sig=fitz.Rect(250,105,370,145)
        p.insert_image(photo,pixmap=pix);p.insert_image(sig,pixmap=pix)
        text,chars=e.char_map(p);qs=e.build_image_and_signature_proposals(p,chars,text,[],1)
        self.assertFalse(next(q for q in qs if fitz.Rect(q['rects'][0])==photo)['selected'])
        self.assertTrue(next(q for q in qs if fitz.Rect(q['rects'][0])==sig)['selected'])
        doc.close()

    def test_export_avoids_png_encode_decode_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'input.pdf';doc=fitz.open();p=doc.new_page(width=200,height=150)
            p.insert_text((20,50),'Ho ten: NGUYEN VAN AN');p.insert_text((20,90),'Glucose 5.2')
            name=p.search_for('NGUYEN VAN AN')[0];doc.save(source);doc.close()
            e.prepare(source,root/'job',case_xml_index=[])
            calls=[];original=fitz.Pixmap.tobytes
            def encode(pix,*args,**kwargs):
                calls.append(args);return original(pix,*args,**kwargs)
            with patch.object(fitz.Pixmap,'tobytes',new=encode):output,_=e.export(root/'job',draft=True)
            self.assertEqual(calls,[])
            with fitz.open(output) as product:
                self.assertEqual(product[0].get_text(),'')
                self.assertTrue(all(v==255 for v in product[0].get_pixmap(dpi=200,clip=name,colorspace=fitz.csGRAY,alpha=False).samples))

    def test_phone_label_with_ocr_lost_th(self):
        text = 'Dién åoai 0901234567\nMã hồ sơ: 0912345678\nĐiện giải 0923456789'
        found = [f for f in analyze_hmu_text(text) if f.entity_type == 'PHONE_NUMBER_VN']
        self.assertEqual([f.text for f in found], ['0901234567'])
        self.assertEqual(text[found[0].start:found[0].end], '0901234567')

    def test_prepare_skips_identity_transform_for_each_ocr_character(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();doc.new_page(width=400,height=200);doc.save(root/'source.pdf');doc.close()
            text='Ho ten: TRAN THI MAI\n';chars=[(i,0,(20+i*5,40,25+i*5,50),c) for i,c in enumerate(text)]
            boxes={tuple(c[2]) for c in chars};identity=[];original=fitz.Rect.__mul__
            def multiply(rect,matrix):
                if tuple(rect) in boxes and tuple(matrix)==(1.,0.,0.,1.,0.,0.): identity.append(1)
                return original(rect,matrix)
            with patch.object(e,'ocr_pdf_pages',return_value={1:(text,chars)}),patch.object(fitz.Rect,'__mul__',multiply):
                e.prepare(root/'source.pdf',root/'job',case_xml_index=[])
            self.assertEqual(len(identity),0)
            actual=json.loads((root/'job/analysis_private/1.json').read_text(encoding='utf8'))
            self.assertEqual([tuple(c[2]) for c in actual['chars']],[tuple(c[2]) for c in chars])
    def test_dense_outline_fixture_is_textless_and_reproducible(self):
        from benchmarks.benchmark_dense_vector import build_dense_pdf
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);a=build_dense_pdf(root/'a.pdf',pages=1);b=build_dense_pdf(root/'b.pdf',pages=1)
            self.assertEqual(e.sha(root/'a.pdf'),e.sha(root/'b.pdf'))
            self.assertEqual(a,b)
            with fitz.open(root/'a.pdf') as doc:
                self.assertFalse(doc[0].get_text().strip());self.assertGreater(len(doc[0].get_drawings()),2000)
    def test_audit_opens_one_pdf_for_all_page_masks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open()
            for i in range(3):doc.new_page().insert_text((30,60),f'Clinical observation {i}')
            doc.save(root/'source.pdf');doc.close();data=e.prepare(root/'source.pdf',root/'job',case_xml_index=[])
            actual_open=fitz.open
            with patch.object(e.fitz,'open',wraps=actual_open) as opened:
                audit=e.generate_audit_markdown(root/'job',data).read_text(encoding='utf8')
            calls=[c for c in opened.call_args_list if c.args and Path(c.args[0]).name=='working_private.pdf']
            self.assertEqual(len(calls),1)
            for i in range(3):self.assertIn(f'Clinical observation {i}',audit)

    def test_batch_builds_each_snapshot_audit_once(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);case=root/'case';case.mkdir()
            for i in range(2):
                doc=fitz.open();doc.new_page().insert_text((30,60),f'Clinical observation {i}');doc.save(case/f'{i}.pdf');doc.close()
            e.prepare_case(case,root/'jobs','TEST')
            with patch.object(e,'generate_audit_markdown',wraps=e.generate_audit_markdown) as audit:
                result=e.export_case(root/'jobs',draft=True)
            self.assertEqual(audit.call_count,2)
            text=(root/'jobs/AUDIT_SUMMARY.md').read_text(encoding='utf8')
            self.assertIn('Clinical observation 0',text);self.assertIn('Clinical observation 1',text)
            self.assertEqual(result['count'],2)

    def test_watermark_proof_once_for_multiple_targets(self):
        doc=fitz.open();p=doc.new_page(width=500,height=500)
        p.insert_text((50,60),'Clinical C34')
        p.insert_text((150,300),'Ho Thi Minh Chau_20260803161916',rotate=90)
        p.insert_text((350,300),'Ho Thi Minh Chau_20260803161916',rotate=90)
        props=[]
        for text,rect in e.rotated_watermark_rects(p):
            props.append(dict(id=str(len(props)),kind='WATERMARK_TEXT',selected=True,clinical_overlap=False,rects=[rect],stream_xrefs=e.watermark_streams(p,rect)))
        actual_state=e._non_watermark_state
        with patch.object(e,'_non_watermark_state',wraps=actual_state) as states:
            e.apply_review_to_page(p,dict(proposals=props,manual_rects=[]),1)
        # One baseline plus one comparison for each isolated watermark stream.
        self.assertEqual(states.call_count,3)
        self.assertIn('Clinical C34',p.get_text());self.assertNotIn('Ho Thi Minh Chau',p.get_text());doc.close()

    def test_one_safe_watermark_cannot_authorize_an_unsafe_target(self):
        doc=fitz.open();p=doc.new_page(width=500,height=500)
        p.insert_text((100,350),'Ho Thi Minh Chau_20260803161916',rotate=90)
        safe=p.get_contents()[-1]
        p.insert_text((300,350),'Ho Thi Minh Chau_20260803161916',rotate=90)
        unsafe=p.get_contents()[-1];p.insert_text((30,60),'Clinical C34');clinical=p.get_contents()[-1]
        doc.update_stream(unsafe,doc.xref_stream(unsafe)+doc.xref_stream(clinical))
        doc.xref_set_key(p.xref,'Contents',f'[{safe} 0 R {unsafe} 0 R]')
        marks=e.rotated_watermark_rects(p);before=p.get_text()
        props=[dict(kind='WATERMARK_TEXT',selected=True,clinical_overlap=False,rects=[rect],stream_xrefs=[safe]) for _,rect in marks]
        with self.assertRaisesRegex(ValueError,'UNSAFE_WATERMARK_REMOVAL'):
            e.apply_review_to_page(p,dict(proposals=props,manual_rects=[]),1)
        self.assertEqual(p.get_text(),before);doc.close()

    def test_partial_same_stream_watermark_selection_is_refused(self):
        doc=fitz.open();p=doc.new_page(width=500,height=500)
        for x in (100,300):p.insert_text((x,350),'Ho Thi Minh Chau_20260803161916',rotate=90)
        contents=p.get_contents();joined=doc.get_new_xref();doc.update_object(joined,'<< >>');doc.update_stream(joined,b'\n'.join(doc.xref_stream(x) for x in contents));p.set_contents(joined)
        props=[dict(kind='WATERMARK_TEXT',selected=i==0,clinical_overlap=False,rects=[rect],stream_xrefs=[joined]) for i,(_,rect) in enumerate(e.rotated_watermark_rects(p))]
        with self.assertRaisesRegex(ValueError,'UNSAFE_WATERMARK_REMOVAL'):
            e.apply_review_to_page(p,dict(proposals=props,manual_rects=[]),1)
        self.assertEqual(len(e.rotated_watermark_rects(p)),2);doc.close()

    def test_address_stops_at_all_insurance_labels(self):
        for label in ('Số BHYT', 'Số thẻ BHYT:', 'S6 BHYT', 'BHYT:'):
            text = 'Địa chỉ: Phường Minh Khai, Hà Nội  ' + label + ' HT 2 38 38 12345678'
            for findings in (analyze_hmu_text(text), e.additional_findings(text, {})):
                addresses = [f.text for f in findings if f.entity_type == 'ADDRESS_VN']
                self.assertEqual(addresses, ['Phường Minh Khai, Hà Nội'])
            bh = [f for f in analyze_hmu_text(text) if f.entity_type == 'HEALTH_INSURANCE_ID']
            self.assertEqual([f.text for f in bh], ['HT 2 38 38 12345678'])

    def test_age_only_labelled_value(self):
        for value in ('0', '94', '100', '9 | 4', '\n94'):
            text = 'Tuổi: ' + value + ' tuổi  Giới tính: Nam\nEF 94; Glucose 94; Nhịp tim 94'
            found = [f for f in analyze_hmu_text(text) if f.entity_type == 'PATIENT_AGE']
            self.assertEqual(len(found), 1)
            self.assertEqual(''.join(c for c in found[0].text if c.isdigit()), ''.join(c for c in value if c.isdigit()))
            self.assertEqual(text[found[0].start:found[0].end], found[0].text)

    def test_age_unit_does_not_become_next_line_age_label(self):
        text='Tuổi: 94 tuổi\n100\nGlucose: 5.2'
        self.assertEqual([f.text for f in analyze_hmu_text(text) if f.entity_type=='PATIENT_AGE'],['94'])

    def test_age_stops_before_next_numbered_field(self):
        text='Tuoi: 94  1. Gioi tinh: Nam'
        self.assertEqual([f.text for f in analyze_hmu_text(text) if f.entity_type=='PATIENT_AGE'],['94'])

    def test_prepare_keeps_split_age_digits_and_border_unselected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page();p.insert_text((30,60),'Tuoi: 9 | 4')
            doc.save(root/'source.pdf');doc.close();data=e.prepare(root/'source.pdf',root/'job',case_xml_index=[])
            ages=[q for q in data['pages'][0]['proposals'] if q['kind']=='PATIENT_AGE']
            self.assertEqual(ages,[])

    def test_cover_label_with_ocr_digits_and_noisy_name(self):
        text = 'BỆNH VIỆN ĐẠI HỌC\n1.1--10 ten (in hoa): TRÀ-N vÅN NÁ-M 2. Sinh ngäy:\n'
        found = [f.text for f in analyze_hmu_text(text) if f.entity_type == 'PATIENT_NAME']
        self.assertIn('TRÀ-N vÅN NÁ-M', found)

    def test_short_fuzzy_staff_needs_name_context(self):
        pages, _ = analyze_hmu_document([
            'Bác sĩ điều trị: Nguyễn Văn Hải\nNgười in: Trần Lỗ Văn',
            'Van hai lá: Không\nDiện tích lỗ van: 4 cm\nHẹp van hai lá: Không\nBác sĩ ghi nhận van hai lá: Không\n'
            'Bác sĩ: Van Hai\nBác sĩ: Lỗ Văn\n',
        ])
        clinical_end = 'Van hai lá: Không\nDiện tích lỗ van: 4 cm\nHẹp van hai lá: Không\nBác sĩ ghi nhận van hai lá: Không\n'
        self.assertFalse([f for f in pages[1] if f.start < len(clinical_end) and f.review_status!='CONTEXT_REQUIRED'])
        self.assertTrue([f for f in pages[1] if f.text.lower() == 'van hai'])

    def test_other_staff_surname_cannot_authorize_clinical_suffix(self):
        pages,_=analyze_hmu_document(['Bác sĩ điều trị: Nguyễn Văn Hải\nNgười in: Hồ Thị Mai',
                                      'Hở van hai lá: Nhẹ\nBác sĩ: Văn Hải'])
        self.assertFalse([f for f in pages[1] if f.start<18 and f.review_status!='CONTEXT_REQUIRED'])
        self.assertTrue([f for f in pages[1] if f.text=='Văn Hải' and f.review_status!='CONTEXT_REQUIRED'])

    def test_learned_two_word_staff_name_still_requires_signer_context(self):
        pages,_=analyze_hmu_document(['Người in: Văn Hải','Van hai lá: Không\nBác sĩ: Văn Hải'])
        self.assertFalse([f for f in pages[1] if f.start<17 and f.review_status!='CONTEXT_REQUIRED'])
        self.assertTrue([f for f in pages[1] if f.start>=17 and f.text=='Văn Hải' and f.review_status!='CONTEXT_REQUIRED'])

    def test_uncertain_staff_suffix_is_visible_but_unselected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();doc.new_page().insert_text((30,60),'Bac si dieu tri: Nguyen Van Hai')
            doc.new_page().insert_text((30,60),'Van Hai');doc.save(root/'source.pdf');doc.close()
            data=e.prepare(root/'source.pdf',root/'job',case_xml_index=[])
            candidates=[q for q in data['pages'][1]['proposals'] if q['text']=='Van Hai']
            self.assertTrue(candidates);self.assertTrue(all(not q['selected'] for q in candidates))

    def test_address_preserves_room_boundaries_and_city_name(self):
        for label in ('Phòng:','Giường:'):
            text='Địa chỉ: Hải Phòng '+label+' 201'
            for fs in (analyze_hmu_text(text),e.additional_findings(text,{})):
                self.assertEqual([f.text for f in fs if f.entity_type=='ADDRESS_VN'],['Hải Phòng'])

    def test_age_audit_keeps_separator_between_digit_masks(self):
        text='Tuoi: 9 | 4';chars=[(i,0,(i*5,10,i*5+5,20),c) for i,c in enumerate(text)]
        review=dict(proposals=[dict(kind='PATIENT_AGE',text='9 | 4',selected=True,rects=[[30,10,35,20],[50,10,55,20]])],manual_rects=[])
        audit=e.build_review_markdown(text,chars,review,pixel_rects=[[30,10,35,20],[50,10,55,20]])
        self.assertIn('|',audit);self.assertNotIn('9',audit);self.assertNotIn('4',audit)

    def test_span_rects_does_not_bridge_columns(self):
        chars = [(0, 0, (10, 10, 20, 20), 'A'), (1, 0, (20, 10, 200, 20), ' '), (2, 0, (200, 10, 210, 20), 'B')]
        self.assertEqual(e.span_rects(chars, 0, 3), [[10, 10, 20, 20], [200, 10, 210, 20]])

    def test_subsume_keeps_different_field_and_identity(self):
        props = [dict(id='a',kind='ADDRESS_VN',selected=True,rects=[[10,10,100,30]]), dict(id='b',kind='HEALTH_INSURANCE_ID',selected=True,rects=[[40,10,80,30]])]
        self.assertEqual({q['id'] for q in e.merge_and_subsume_proposals(props)}, {'a', 'b'})

    def test_ink_expansion_stops_before_known_next_label(self):
        doc = fitz.open(); p = doc.new_page(width=400,height=200)
        p.insert_text((30,80), 'Nguyen Van An Tuoi: 94')
        text, chars = e.char_map(p)
        rects = e.span_rects(chars, 0, len('Nguyen Van An'))
        label = e.span_rects(chars, text.index('Tuoi'), text.index('Tuoi')+4)[0]
        result = e.expand_rects_with_pixel_ink(p, rects, barriers=[label])
        self.assertLess(result[0][2], label[0]); doc.close()

    def test_old_policy_job_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); doc = fitz.open(); doc.new_page(); doc.save(root/'source.pdf'); doc.close()
            data=e.prepare(root/'source.pdf', root/'job', case_xml_index=[])
            data['policy']='remove_names_dob_phone_address_staff_signatures_keep_age_clinical_and_record_ids_v4'; e.save_json(root/'job/review.json',data)
            with self.assertRaisesRegex(ValueError, 'policy|Policy'):
                e.ensure_job(root/'job')

    def test_nurse_table_masks_occupied_cells_preserves_grid_and_empty_cell(self):
        doc = fitz.open(); p = doc.new_page(width=400,height=400)
        for y in (250,350): p.draw_line((20,y),(380,y))
        for x in (20,120,200,280,380): p.draw_line((x,250),(x,350))
        p.insert_text((30,280),'Dieu duong'); p.insert_text((30,300),'Ky va ghi ten')
        p.insert_text((150,340),'TRAN THI MAI',rotate=90)
        p.draw_line((220,270),(245,285));p.draw_line((245,285),(238,267))
        text,chars=e.char_map(p)
        proposals=e.build_image_and_signature_proposals(p,chars,text,[],1)
        signatures=[q for q in proposals if q['kind']=='SIGNATURE_REGION']
        self.assertEqual(len(signatures),2)
        for q in signatures:
            self.assertTrue(q['selected']); self.assertEqual(len(q['rects']),1)
            r=q['rects'][0];self.assertGreater(r[0],120);self.assertLess(r[2],280)
            self.assertGreater(r[1],250);self.assertLess(r[3],350)
        doc.close()

    def test_nurse_anchor_preserves_decomposed_unicode_offsets(self):
        doc=fitz.open();p=doc.new_page(width=400,height=400)
        for y in (250,350):p.draw_line((20,y),(380,y))
        for x in (20,120,200,380):p.draw_line((x,250),(x,350))
        p.draw_line((140,270),(170,290))
        text=unicodedata.normalize('NFD','Địa chỉ\nĐiều dưỡng\nKý và ghi tên\n')
        chars=[];line=0;column=0
        for i,ch in enumerate(text):
            y=(20,270,295)[min(line,2)]
            chars.append((i,line,(30+column*4,y,34+column*4,y+10),ch))
            if ch=='\n':line+=1;column=0
            else:column+=1
        self.assertEqual(len(e.nurse_signature_regions(p,chars,text,1)),1);doc.close()

    def test_nurse_clinical_row_cannot_borrow_unrelated_signature_instruction(self):
        doc=fitz.open();p=doc.new_page(width=400,height=400)
        for y in (150,210):p.draw_line((20,y),(380,y))
        for x in (20,120,200,280,380):p.draw_line((x,150),(x,210))
        p.insert_text((25,180),'Dieu duong');p.insert_text((130,180),'Mach80');p.insert_text((210,180),'SpO298');p.insert_text((290,180),'HA120/80')
        p.insert_text((20,350),'Bac si: Ky va ghi ten')
        text,chars=e.char_map(p)
        self.assertFalse(e.nurse_signature_regions(p,chars,text,1));doc.close()

    def test_boxed_age_when_ocr_missed_digits(self):
        doc=fitz.open();p=doc.new_page(width=400,height=200)
        p.insert_text((300,50),'Tuoi')
        for x in (300,315,330):p.draw_line((x,55),(x,72))
        for y in (55,72):p.draw_line((300,y),(330,y))
        p.insert_text((303,68),'9');p.insert_text((318,68),'4')
        text,chars=e.char_map(p);text=text[:5];chars=[c for c in chars if c[0]<4]
        qs=e.boxed_age_proposals(p,chars,text)
        self.assertEqual(len(qs),2)
        for q in qs:
            self.assertEqual(q['kind'],'PATIENT_AGE');r=q['rects'][0]
            self.assertGreater(r[1],55);self.assertLess(r[3],72)
        doc.close()

    def test_cover_missing_name_retries_only_value_region(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);doc=fitz.open();p=doc.new_page(width=400,height=200)
            p.insert_text((20,60),'Ho ten (in hoa): ____');doc.save(root/'source.pdf');doc.close()
            name='TRAN THI MAI';chars=[(i,0,(110+i*5,50,115+i*5,61),c) for i,c in enumerate(name)]
            with patch.object(e,'ocr_pdf_regions',return_value={'patient-1':(name,chars)}) as retry:
                data=e.prepare(root/'source.pdf',root/'job',case_xml_index=[])
            self.assertEqual(retry.call_count,1)
            names=[q for q in data['pages'][0]['proposals'] if q['kind']=='PATIENT_NAME']
            self.assertTrue(any(q['text']==name for q in names))
            self.assertTrue(all(q.get('provenance')=='patient_name_roi_retry' for q in names))

    def test_nurse_export_masks_ink_preserves_table_pixels(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.pdf';doc=fitz.open();p=doc.new_page(width=400,height=400)
            for y in (250,350):p.draw_line((20,y),(380,y))
            for x in (20,120,200,280,380):p.draw_line((x,250),(x,350))
            p.insert_text((30,280),'Dieu duong');p.insert_text((30,300),'Ky va ghi ten')
            p.insert_text((150,340),'TRAN THI MAI',rotate=90);p.draw_line((220,270),(245,285))
            doc.save(source);doc.close();data=e.prepare(source,root/'job',case_xml_index=[])
            for q in data['pages'][0]['proposals']:
                q['selected']=q['kind']=='SIGNATURE_REGION'
            e.save_json(root/'job/review.json',data);out,qc=e.export(root/'job',draft=True)
            self.assertEqual(qc['status'],'DRAFT_NEEDS_QC')
            with fitz.open(source) as src,fitz.open(out) as dst:
                before=src[0].get_pixmap(dpi=200,alpha=False);after=dst[0].get_pixmap(dpi=200,alpha=False)
                # Compare independently chosen protected regions: label and every table border.
                for rect in ([20,250,380,251],[20,349,380,351],[119,250,121,350],[199,250,201,350],[279,250,281,350],[25,265,110,310]):
                    ir=(fitz.Rect(rect)*fitz.Matrix(200/72,200/72)).irect
                    for y in range(ir.y0,ir.y1):
                        a=(y*before.width+ir.x0)*3;b=(y*before.width+ir.x1)*3
                        self.assertEqual(before.samples[a:b],after.samples[a:b])
                for q in data['pages'][0]['proposals']:
                    if q['kind']=='SIGNATURE_REGION':
                        ir=(fitz.Rect(q['rects'][0])*fitz.Matrix(200/72,200/72)).irect
                        for y in range(ir.y0,ir.y1):
                            row=after.samples[(y*after.width+ir.x0)*3:(y*after.width+ir.x1)*3]
                            self.assertEqual(row,b'\xff'*len(row))


if __name__ == '__main__':
    unittest.main()
