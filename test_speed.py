import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import fitz
import engine as e
import ocr_helper


class SpeedTests(unittest.TestCase):
    def test_vector_image_parser_does_not_validate_every_path_number_in_python(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200);image=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False);image.clear_with(0)
            p.insert_image(fitz.Rect(20,20,40,40),pixmap=image)
            raw=b'\n'.join(doc.xref_stream(x) for x in p.get_contents());raw=b'0 0 m 1 2 3 4 5 6 c S\n'*200+raw
            x=doc.get_new_xref();doc.update_object(x,'<<>>');doc.update_stream(x,raw);p.set_contents(x)
            infos=p.get_image_info();names={x[7] for x in p.get_images(full=True)}
            with patch.object(e.re,'fullmatch',wraps=e.re.fullmatch) as validate:
                spans=e._graphics_image_spans(p,raw,[[20,20,40,40]],infos,names)
            self.assertTrue(spans);self.assertLess(validate.call_count,50,'Outline operands must be skipped in the compiled scanner')
            self.assertEqual(e.remove_selected_image_paints(p,[[20,20,40,40]]),[0]);self.assertIn(b'1 2 3 4 5 6 c S',doc.xref_stream(p.get_contents()[0]))

    def test_deleting_annotation_or_widget_keeps_partial_scan_pixel_fallback(self):
        for kind in ('widget','annotation'):
            with self.subTest(kind=kind),fitz.open() as doc:
                p=doc.new_page(width=300,height=200);scan=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,300,200),False);scan.clear_with(120)
                p.insert_image(p.rect,pixmap=scan);proposals=[]
                if kind=='widget':
                    w=fitz.Widget();w.field_name='signature';w.field_type=fitz.PDF_WIDGET_TYPE_SIGNATURE;w.rect=fitz.Rect(10,10,80,80);p.add_widget(w)
                    proposals.append(dict(kind='WIDGET_REVIEW',selected=True,rects=[[10,10,80,80]],clinical_overlap=False));roi=[20,20,40,40]
                else:
                    a=p.add_rect_annot(fitz.Rect(20,20,40,40));roi=list(a.rect)
                proposals.append(dict(kind='SIGNATURE_IMAGE',selected=True,rects=[roi],clinical_overlap=False))
                rects,removed,fallback=e.apply_review_to_page(p,dict(proposals=proposals,manual_rects=[],protected_rects=[]),1)
                self.assertEqual(rects,[roi]);self.assertEqual(fallback,[roi]);self.assertEqual(removed,[])
                self.assertFalse(list(p.widgets() or []));self.assertFalse(list(p.annots() or []))

    def test_deleted_widget_does_not_hide_underlying_selected_image(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200);pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            widget=fitz.Widget();widget.field_name='signature';widget.field_type=fitz.PDF_WIDGET_TYPE_SIGNATURE;widget.rect=fitz.Rect(5,5,45,45);p.add_widget(widget)
            review=dict(proposals=[dict(kind='WIDGET_REVIEW',selected=True,rects=[[5,5,45,45]],clinical_overlap=False),dict(kind='SIGNATURE_IMAGE',selected=True,rects=[[10,10,30,30]],clinical_overlap=False)],manual_rects=[],protected_rects=[])
            self.assertEqual(len(p.get_image_info()),1)
            e.apply_review_to_page(p,review,1)
            self.assertEqual(list(p.widgets() or []),[])
            self.assertEqual(p.get_image_info(),[])

    def test_duplicate_image_regions_do_not_white_out_underlying_clinical_image(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200)
            photo=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);photo.clear_with(120)
            p.insert_image(fitz.Rect(50,50,150,150),pixmap=photo);expected=p.get_pixmap().samples
            sig=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);sig.clear_with(0)
            p.insert_image(fitz.Rect(80,80,100,100),pixmap=sig)
            review=dict(proposals=[dict(kind='SIGNATURE_IMAGE',selected=True,rects=[[80,80,100,100]],clinical_overlap=False) for _ in range(2)],manual_rects=[],protected_rects=[])
            rects,removed,fallback=e.apply_review_to_page(p,review,1)
            self.assertEqual(removed,[0,1]);self.assertEqual(rects,[]);self.assertEqual(fallback,[])
            self.assertEqual(p.get_pixmap().samples,expected)

    def test_nested_image_at_same_bbox_requires_pixel_fallback(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200);pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            image=p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            form=doc.get_new_xref();doc.update_object(form,f'<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] /Resources << /XObject << /Inner {image} 0 R >> >> >>');doc.update_stream(form,b'/Inner Do')
            resources=int(doc.xref_get_key(p.xref,'Resources')[1].split()[0]);doc.xref_set_key(resources,'XObject/Nested',f'{form} 0 R')
            raw=b'\n'.join(doc.xref_stream(x) for x in p.get_contents())+b'\nq 20 0 0 20 10 170 cm /Nested Do Q\n'
            x=doc.get_new_xref();doc.update_object(x,'<<>>');doc.update_stream(x,raw);p.set_contents(x)
            self.assertEqual(len(p.get_image_info()),2)
            self.assertEqual(e.remove_selected_image_paints(p,[[10,10,30,30]]),[])
            self.assertEqual(len(p.get_image_info()),1)

    def test_image_rewrite_text_guard_restores_original_content_references(self):
        with fitz.open(self.source) as doc:
            p=doc[0];pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(20,20,40,40),pixmap=pix)
            references=p.get_contents();text=p.get_text()
            with patch.object(fitz.Page,'get_text',side_effect=[text,'changed native text']):
                self.assertEqual(e.remove_selected_image_paints(p,[[20,20,40,40]]),[])
            self.assertEqual(p.get_contents(),references)
            self.assertEqual(p.get_text(),text)
            self.assertEqual(len(p.get_image_info()),1)

    def test_image_removal_preserves_pending_vector_path(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200);p.draw_rect(p.rect,fill=(.5,.5,.5),color=None)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(20,20,40,40),pixmap=pix);name=p.get_images()[0][7]
            chunks=[doc.xref_stream(x) for x in p.get_contents()]
            raw=chunks[0]+b'\n0 G 2 w 10 10 m 180 180 l\n'+b'\n'.join(chunks[1:])+b'\nS'
            x=doc.get_new_xref();doc.update_object(x,'<<>>');doc.update_stream(x,raw);p.set_contents(x)
            with fitz.open(stream=doc.tobytes(),filetype='pdf') as control:
                cp=control[0];cx=control.get_new_xref();control.update_object(cx,'<<>>')
                control.update_stream(cx,raw.replace(('/'+name+' Do').encode(),b''));cp.set_contents(cx)
                expected=cp.get_pixmap(dpi=200).samples
                self.assertEqual(e.remove_selected_image_paints(p,[[20,20,40,40]]),[0])
                self.assertEqual(p.get_pixmap(dpi=200).samples,expected)
                self.assertEqual(p.get_image_info(),[])

    def test_prior_geometry_v5_job_requires_fresh_recognition(self):
        job=self.root/'old_policy';data=e.prepare(self.source,job,case_xml_index=[])
        data['policy']='remove_names_dob_phone_address_staff_signatures_keep_age_clinical_and_record_ids_geometry_v5'
        e.save_json(job/'review.json',data)
        with self.assertRaisesRegex(ValueError,'policy changed'):
            e.ensure_job(job)

    def test_render_worker_error_does_not_return_partial_pages(self):
        out=self.root/'failedrenders';out.mkdir()
        with self.assertRaises(fitz.FileNotFoundError):
            e._render_scan_pages(self.root/'missing.pdf',list(range(1,65)),200,out)
        self.assertEqual(list(out.iterdir()),[])

    def test_empty_native_text_does_not_extract_a_second_textpage(self):
        source=self.root/'blank.pdf'
        with fitz.open() as doc:
            p=doc.new_page(width=100,height=100)
            self.assertEqual(p.get_text('text',sort=False),'')
            self.assertEqual(e.char_map(p),('',[]))
            doc.save(source)
        with patch.object(e,'char_map',side_effect=AssertionError('second textpage')),patch.object(e,'rotated_watermark_rects',side_effect=AssertionError('empty native watermark extraction')),patch.object(e,'ocr_pdf_pages',return_value={1:('',[])}):
            data=e.prepare(source,self.root/'blankjob',case_xml_index=[])
        self.assertTrue(data['pages'][0]['ocr_used'])

    def test_render_processes_preserve_pages_and_pixels(self):
        source=self.root/'many.pdf';out=self.root/'renders';out.mkdir()
        with fitz.open() as doc:
            for i in range(64):
                p=doc.new_page(width=36,height=48)
                p.draw_rect(fitz.Rect(2+i%5,3,11+i%7,19),color=(0,0,0),fill=(i/64,0.2,0.7))
                if i in (0,31,63):
                    p.set_cropbox(fitz.Rect(1,2,35,46))
                    p.set_rotation({0:180,31:90,63:270}[i])
                    annot=p.add_rect_annot(fitz.Rect(4,24,25,31));annot.update()
            doc.save(source)
        records=e._render_scan_pages(source,list(range(1,65)),200,out)
        self.assertEqual(sorted(r['page'] for r in records),list(range(1,65)))
        with fitz.open(source) as doc:
            for pn in (1,32,64):
                expected=doc[pn-1].get_pixmap(dpi=200,alpha=False)
                actual=fitz.Pixmap(str(out/f'{pn}.png'))
                self.assertEqual(actual.samples,expected.samples)
                record=next(r for r in records if r['page']==pn)
                self.assertEqual((record['width'],record['height']),(expected.width,expected.height))

    def test_export_bulk_white_mask_matches_pixel_oracle(self):
        job=self.root/'job';data=e.prepare(self.source,job,case_xml_index=[])
        data['pages'][0]['proposals']=[];data['pages'][0]['manual_rects']=[[17.13,26.73,117.89,46.91]]
        e.save_json(job/'review.json',data)
        with fitz.open(job/'working_private.pdf') as source:
            expected=source[0].get_pixmap(dpi=200,alpha=False)
            expected.set_rect((fitz.Rect(data['pages'][0]['manual_rects'][0])*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            rgb=expected.samples
        with patch.object(fitz.Pixmap,'set_rect',side_effect=AssertionError('per-channel Python setter')):
            out,_=e.export(job,draft=True)
        with fitz.open(out) as result:
            actual=fitz.Pixmap(result,result[0].get_images()[0][0])
            self.assertEqual(actual.samples,rgb)

    def test_qr_outline_negatives_do_not_allocate_pairwise_rectangles(self):
        drawings=[dict(rect=(10+x*4,10+y*4,12+x*4,12+y*4),fill=(0,0,0)) for y in range(10) for x in range(10)]
        drawings.extend(dict(rect=(1,1,2,2)) for _ in range(2100))
        with fitz.open(self.source) as doc:
            self.assertEqual(e.vector_qr_rects(doc[0],drawings),[[10.,10.,48.,48.]])
            with patch.object(fitz,'Rect',wraps=fitz.Rect) as rectangles:
                self.assertEqual(e.vector_qr_rects(doc[0],drawings),[[10.,10.,48.,48.]])
            self.assertLessEqual(rectangles.call_count,102)

    def test_audit_geometry_is_converted_once_without_changing_masks(self):
        text='AB CD EF'
        chars=[(i,0,[i*3,0,i*3+2,5],ch) for i,ch in enumerate(text)]
        review={'proposals':[dict(kind='PATIENT_NAME',selected=True,text='CD',rects=[[9,0,14,5]]),
                             dict(kind='SIGNATURE_IMAGE',selected=True,text='EF',rects=[[18,0,23,5]])],
                'manual_rects':[[0,0,2,5]]}
        self.assertEqual(e.build_review_markdown(text,chars,review,native_length=6),
                         '[ĐÃ XÓA:REGION]B [ĐÃ XÓA:PATIENT_NAME] [ĐÃ XÓA:SIGNATURE_IMAGE][ĐÃ XÓA:SIGNATURE_IMAGE]')
        many=chars*100
        with patch.object(fitz,'Rect',wraps=fitz.Rect) as rectangles:
            e.build_review_markdown(text,many,review,native_length=6)
        self.assertLessEqual(rectangles.call_count,len(many)+10)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'input.pdf'
        with fitz.open() as doc:
            p = doc.new_page(width=300, height=200)
            p.insert_text((20, 40), 'Ho ten: NGUYEN VAN AN')
            p.insert_text((20, 100), 'Clinical C34 / Glucose 5.2')
            doc.save(self.source)

    def test_export_audit_reuses_applied_masks(self):
        job = self.root / 'job'
        e.prepare(self.source, job, case_xml_index=[])
        with patch.object(e, 'apply_review_to_page', wraps=e.apply_review_to_page) as apply:
            e.export(job, draft=True)
        self.assertEqual(apply.call_count, 1)

    def test_generated_audit_records_current_revision(self):
        job=self.root/'job';data=e.prepare(self.source,job,case_xml_index=[])
        self.assertEqual((job/'audit_revision.txt').read_text(),str(data['revision']))

    def test_lossless_stream_uses_fast_compression(self):
        import zlib
        job = self.root / 'job'
        e.prepare(self.source, job, case_xml_index=[])
        with patch.object(zlib, 'compress', wraps=zlib.compress) as compress:
            out, _ = e.export(job, draft=True)
        self.assertTrue(any(c.args[1:] == (1,) for c in compress.call_args_list))
        with fitz.open(out) as doc:
            self.assertEqual(doc[0].get_text(), '')
            self.assertEqual(len(doc[0].get_images()), 1)

    def test_filename_seed_survives_private_storage_name(self):
        with fitz.open() as doc:
            p = doc.new_page(); p.insert_text((20, 40), 'Ho ten: TRINHVANHU0NG')
            doc.save(self.root / 'source_private.pdf')
        data = e.prepare(self.root / 'source_private.pdf', self.root / 'job',
                         case_xml_index=[], source_name='BA87654321_TRINH_VAN_HUONG.pdf')
        self.assertEqual(sum(q['selected'] and q['kind'] == 'PATIENT_NAME'
                             for p in data['pages'] for q in p['proposals']), 1)

    def test_no_matching_image_skips_stream_parser(self):
        with fitz.open(self.source) as doc:
            with patch.object(e, 'ContentStream', side_effect=AssertionError('unnecessary parse')):
                self.assertEqual(e.remove_selected_image_paints(doc[0], [[10, 10, 15, 15]]), [])

    def test_image_removal_preserves_text_and_has_graphics_fast_path(self):
        with fitz.open(self.source) as doc:
            p = doc[0]; rect = fitz.Rect(10, 20, 170, 60)
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 20), False); pix.clear_with(0)
            xref = p.insert_image(rect, pixmap=pix, keep_proportion=False)
            other = doc.new_page(width=300, height=200); other.insert_image(rect, xref=xref)
            p = doc[0]; text = p.get_text()
            self.assertEqual(e.remove_selected_image_paints(p, [list(rect)]), [0])
            self.assertEqual(p.get_text(), text)
            self.assertEqual(len(doc[1].get_image_info()), 1)
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200);p.draw_line((10,100),(180,100))
            expected=p.get_pixmap(dpi=200).samples
            p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix,keep_proportion=False)
            with patch.object(e,'_LocatedContentStream',side_effect=AssertionError('unneeded full parser')):
                self.assertEqual(e.remove_selected_image_paints(p,[[10,10,30,30]]),[0])
            self.assertEqual(p.get_pixmap(dpi=200).samples,expected)

    def test_compact_drawings_same_candidates(self):
        with fitz.open(self.source) as doc:
            p = doc[0]
            p.draw_line((10,150),(150,150))
            for i in range(20): p.draw_rect(fitz.Rect(10+i*3, 120, 11+i*3, 145), fill=(0,0,0))
            self.assertEqual(e.barcode_rects(p, p.get_drawings()), e.barcode_rects(p, p.get_cdrawings()))
            self.assertEqual(e.vector_qr_rects(p, p.get_drawings()), e.vector_qr_rects(p, p.get_cdrawings()))

    def test_cached_displaylist_matches_ink_regions(self):
        with fitz.open(self.source) as doc:
            p = doc[0]; rects = [[20,30,100,45]]
            expected = e.expand_rects_with_pixel_ink(p, rects)
            with patch.object(fitz.Page, 'get_pixmap', side_effect=AssertionError('reparse')):
                actual = e.expand_rects_with_pixel_ink(p, rects, _display_list=p.get_displaylist())
            self.assertEqual(expected, actual)

    def test_prerendered_png_does_not_decode_again(self):
        images = self.root / 'images'; images.mkdir()
        with fitz.open(self.source) as doc:
            doc[0].get_pixmap(dpi=200).save(images/'1.png')
        with patch.object(fitz, 'Pixmap', side_effect=AssertionError('redundant decode')):
            maps = ocr_helper.ocr_pdf_pages(self.source, [1], pre_rendered_dir=images)
        self.assertIn(1, maps)
        self.assertTrue(maps[1][0].strip())

    def test_unselected_redact_does_not_remove_clinical_image(self):
        with fitz.open(self.source) as doc:
            p=doc[0]; pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(30)
            p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            p.insert_image(fitz.Rect(100,100,160,160),pixmap=pix)
            p.add_redact_annot(fitz.Rect(100,100,160,160))
            e.remove_selected_image_paints(p,[[10,10,30,30]])
            self.assertEqual(len(p.get_image_info()),1)
            self.assertEqual(len(list(p.annots())),1)

    def test_fast_preview_png_same_rgb(self):
        with fitz.open(self.source) as doc:
            pix=doc[0].get_pixmap(dpi=200,alpha=False)
            e.save_preview(pix,self.root/'fast.png')
            self.assertEqual(fitz.Pixmap(str(self.root/'fast.png')).samples,pix.samples)

    def test_ocr_pipe_progress_before_exit_and_timeout(self):
        import subprocess,sys
        seen=[]
        with subprocess.Popen([sys.executable,'-u','-c',"import time;print('PAGE_DONE:1',flush=True);time.sleep(.5)"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as proc:
            ocr_helper._read_ocr_process(proc,5,lambda line:seen.append((line,proc.poll())))
        self.assertTrue(seen)
        self.assertIsNone(seen[0][1])
        with subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as proc:
            with self.assertRaises(RuntimeError): ocr_helper._read_ocr_process(proc,.1,lambda line:None)
            self.assertIsNotNone(proc.poll())

    def test_image_removal_preserves_original_vector_stream_bytes(self):
        with fitz.open(self.source) as doc:
            p=doc[0];p.draw_line((10.123456789,100.987654321),(250.7654321,100.987654321))
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            before=[doc.xref_stream(x) for x in p.get_contents()]
            e.remove_selected_image_paints(p,[[10,10,30,30]])
            after=b'\n'.join(doc.xref_stream(x) for x in p.get_contents())
            for stream in before[:-1]:self.assertIn(stream,after)
            self.assertEqual(p.get_image_info(),[])

    def test_text_masks_do_not_apply_unselected_source_redactions(self):
        with fitz.open(self.source) as doc:
            p=doc[0];p.add_redact_annot(fitz.Rect(15,80,250,120))
            before=p.get_text()
            review={'proposals':[],'manual_rects':[[20,30,120,45]],'protected_rects':[]}
            e.apply_review_to_page(p,review,1)
            self.assertEqual(p.get_text(),before)
            self.assertEqual(len(list(p.annots())),1)

    def test_audit_cache_rejects_changed_selection(self):
        job=self.root/'job';data=e.prepare(self.source,job,case_xml_index=[]);cache={}
        e._write_export_pair(job,data,self.root/'result.pdf',True,applied_pages=cache)
        data['pages'][0]['manual_rects']=[[10,10,15,15]]
        with self.assertRaisesRegex(ValueError,'snapshot'):e.generate_audit_markdown(job,data,applied_pages=cache)

    def test_duplicate_pixels_distinct_image_resources_are_both_removed(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            a=p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            b=doc.get_new_xref();doc.update_object(b,doc.xref_object(a));doc.update_stream(b,doc.xref_stream(a))
            p.insert_image(fitz.Rect(80,80,100,100),xref=b)
            removed=e.remove_selected_image_paints(p,[[10,10,30,30],[80,80,100,100]])
            self.assertEqual(removed,[0,1]);self.assertEqual(p.get_image_info(),[])

    def test_partial_image_resource_keeps_exact_drawing_bytes(self):
        with fitz.open(self.source) as doc:
            p=doc[0];pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            original=doc.xref_stream(p.get_contents()[0])
            a=p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            p.insert_image(fitz.Rect(80,80,100,100),xref=a)
            self.assertEqual(e.remove_selected_image_paints(p,[[10,10,30,30]]),[0])
            after=b'\n'.join(doc.xref_stream(x) for x in p.get_contents())
            self.assertIn(original,after);self.assertEqual(len(p.get_image_info()),1)

    def test_graphics_only_partial_image_avoids_full_parser(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200);p.draw_line((10,50),(180,50))
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            x=p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            p.insert_image(fitz.Rect(80,80,100,100),xref=x)
            with patch.object(e,'_LocatedContentStream',side_effect=AssertionError('full parser')):
                self.assertEqual(e.remove_selected_image_paints(p,[[10,10,30,30]]),[0])
            self.assertEqual(len(p.get_image_info()),1)

    def test_nested_form_image_is_not_falsely_reported_removed(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            image=p.insert_image(fitz.Rect(10,10,30,30),pixmap=pix)
            form=doc.get_new_xref();doc.update_object(form,f'<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] /Resources << /XObject << /Inner {image} 0 R >> >> >>');doc.update_stream(form,b'/Inner Do')
            resources=int(doc.xref_get_key(p.xref,'Resources')[1].split()[0]);doc.xref_set_key(resources,'XObject/Nested',f'{form} 0 R')
            raw=b'\n'.join(doc.xref_stream(x) for x in p.get_contents())+b'\nq 20 0 0 20 80 100 cm /Nested Do Q\n'
            stream=doc.get_new_xref();doc.update_object(stream,'<< >>');doc.update_stream(stream,raw);p.set_contents(stream)
            self.assertEqual(len(p.get_image_info()),2)
            self.assertEqual(e.remove_selected_image_paints(p,[[10,10,30,30],[80,80,100,100]]),[0])
            self.assertEqual(len(p.get_image_info()),1)

    def test_graphics_scanner_ignores_operator_letters_inside_pdf_names(self):
        with fitz.open() as doc:
            p=doc.new_page(width=200,height=200)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(50,130,70,150),pixmap=pix)
            resources=int(doc.xref_get_key(p.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resources,'ExtGState','<< /Foo.q << /Type /ExtGState >> /Foo.Q << /Type /ExtGState >> >>')
            raw=b'1 0 0 1 0 50 cm /Foo.q gs 1 0 0 1 50 0 cm /Foo.Q gs q 20 0 0 20 0 0 cm /fzImg0 Do Q 1 0 0 1 -50 0 cm q 20 0 0 20 0 0 cm /fzImg0 Do Q'
            stream=doc.get_new_xref();doc.update_object(stream,'<< >>');doc.update_stream(stream,raw);p.set_contents(stream)
            self.assertEqual([list(i['bbox']) for i in p.get_image_info()],[[50,130,70,150],[0,130,20,150]])
            self.assertEqual(e.remove_selected_image_paints(p,[[0,130,20,150]]),[0])
            self.assertEqual([list(i['bbox']) for i in p.get_image_info()],[[50,130,70,150]])

    def test_graphics_scanner_rejects_unknown_tokens(self):
        with fitz.open(self.source) as doc:
            for raw in (b'BX Strange.q EX',b'12bad',b'/Im 2 Do',b'/Im 2 cm',b'[0 1] Strange',b'Q',b'q'):
                with self.subTest(raw=raw):
                    self.assertIsNone(e._graphics_image_spans(doc[0],raw,[],[],set()))
            self.assertEqual(e._graphics_image_spans(doc[0],b'q [0 1] 0 d 1 0 0 1 0 0 cm /Other \n Do Q',[],[],set()),[])

    def test_audit_cache_rotations_match_recomputed_masks(self):
        for angle in (90,180,270):
            source=self.root/f'rotate{angle}.pdf'
            with fitz.open(self.source) as doc:
                doc[0].set_rotation(angle);doc.save(source)
            job=self.root/f'job{angle}';data=e.prepare(source,job,case_xml_index=[])
            data['pages'][0]['manual_rects']=[[10,10,20,20]]
            if data['pages'][0]['proposals']:data['pages'][0]['proposals'][0]['selected']=False
            cache={};e._write_export_pair(job,data,self.root/f'out{angle}.pdf',True,applied_pages=cache)
            cached=e.generate_audit_markdown(job,data,applied_pages=cache).read_text(encoding='utf8')
            recomputed=e.generate_audit_markdown(job,data).read_text(encoding='utf8')
            self.assertEqual(cached,recomputed)

    def test_overlapping_signature_removal_keeps_underlying_picture(self):
        with fitz.open(self.source) as doc:
            p=doc[0];photo=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);photo.clear_with(120)
            p.insert_image(fitz.Rect(50,50,150,150),pixmap=photo)
            expected=p.get_pixmap(dpi=150).samples
            sig=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);sig.clear_with(0)
            p.insert_image(fitz.Rect(80,80,100,100),pixmap=sig)
            self.assertEqual(e.remove_selected_image_paints(p,[[80,80,100,100]]),[0])
            self.assertEqual(p.get_pixmap(dpi=150).samples,expected)

    def test_inline_image_fallback_preserves_following_text_geometry(self):
        with fitz.open(self.source) as doc:
            p=doc[0];raw=b'\n'.join(doc.xref_stream(x) for x in p.get_contents())
            original=p.get_text('words')
            stream=doc.get_new_xref();doc.update_object(stream,'<< >>')
            doc.update_stream(stream,b'q 20 0 0 20 10 150 cm BI /W 1 /H 1 /BPC 8 /CS /RGB ID \x00\x00\x00 EI Q\n'+raw);p.set_contents(stream)
            self.assertEqual(e.remove_selected_image_paints(p,[[10,30,30,50]]),[0])
            self.assertEqual(p.get_image_info(),[])
            self.assertEqual(p.get_text('words'),original)

    def test_ocr_callback_error_kills_backend(self):
        import subprocess,sys
        def fail(line):raise ValueError('callback failed')
        with subprocess.Popen([sys.executable,'-u','-c',"import time;print('PAGE_DONE:1',flush=True);time.sleep(10)"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as proc:
            with self.assertRaisesRegex(ValueError,'callback'):ocr_helper._read_ocr_process(proc,5,fail)
            self.assertIsNotNone(proc.poll())

    def test_invalid_prerender_png_rejected_before_ocr(self):
        images=self.root/'images';images.mkdir();(images/'1.png').write_bytes(b'not a png')
        with patch.object(ocr_helper.subprocess,'Popen',side_effect=AssertionError('must not launch')):
            with self.assertRaisesRegex(ValueError,'PNG'):ocr_helper.ocr_pdf_pages(self.source,[1],pre_rendered_dir=images)

    def test_filename_seed_rejects_paths_and_normalizes_unicode(self):
        from hmu_recognizers import extract_case_seeds
        import unicodedata
        for name in ('../bad.pdf',r'C:\bad.pdf',r'folder\bad.pdf',7):
            with self.assertRaises(ValueError):extract_case_seeds(self.source,xml_index=[],source_name=name)
        name='BA87654321_NGUYỄN_VĂN_AN.pdf'
        a=extract_case_seeds(self.source,xml_index=[],source_name=name)
        b=extract_case_seeds(self.source,xml_index=[],source_name=unicodedata.normalize('NFD',name))
        self.assertEqual(a,b)

    def test_qr_candidate_rejects_square_glyph_bounds_with_curves(self):
        with fitz.open() as doc:
            page=doc.new_page(width=300,height=300)
            shapes=[]
            for y in range(10):
                for x in range(10):
                    r=(10+x*4,10+y*4,12+x*4,12+y*4)
                    shapes.append({'rect':r,'fill':(0,0,0),'items':[('c',(r[0],r[1]),(r[2],r[1]),(r[0],r[3]),(r[2],r[3]))]})
            self.assertEqual(e.vector_qr_rects(page,shapes),[])

    def test_source_basename_overrides_private_path_identity(self):
        from hmu_recognizers import extract_case_seeds
        source=self.root/'NGUYEN VAN KHAC'/'source_private.pdf'
        source.parent.mkdir();source.write_bytes(self.source.read_bytes())
        seeds=extract_case_seeds(source,source_name='2600000001_TRAN_THI_BINH.pdf',xml_index=[])
        self.assertEqual(seeds.get('PATIENT_NAME'),['TRAN THI BINH'])

    def test_partial_paint_removal_matches_independent_render_control(self):
        with fitz.open() as doc:
            p=doc.new_page(width=300,height=300)
            p.draw_line((10.125,170.875),(280.625,170.875))
            pixels=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,4,4),False);pixels.clear_with(0)
            xref=0;selected_streams=[]
            for i in range(24):
                rect=fitz.Rect(10+(i%6)*40.125,20+(i//6)*40.25,20+(i%6)*40.125,30+(i//6)*40.25)
                xref=p.insert_image(rect,pixmap=pixels) if not xref else p.insert_image(rect,xref=xref)
                if i%3==0:selected_streams.append(p.get_contents()[-1])
            resources=int(doc.xref_get_key(p.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resources,'ExtGState','<< /Foo.q << /Type /ExtGState >> /Foo.Q << /Type /ExtGState >> >>')
            chunks=[(x,doc.xref_stream(x)) for x in p.get_contents()]
            prefix=b'/Foo.q gs 1 0 0 1 7.1234 3.9876 cm /Foo.Q gs\n'
            stream=doc.get_new_xref();doc.update_object(stream,'<< >>');doc.update_stream(stream,prefix+b'\n'.join(raw for _,raw in chunks));p.set_contents(stream)
            rects=[list(info['bbox']) for i,info in enumerate(p.get_image_info()) if i%3==0]
            with fitz.open(stream=doc.tobytes(),filetype='pdf') as control:
                cp=control[0];ref=control.get_new_xref();control.update_object(ref,'<< >>')
                control.update_stream(ref,prefix+b'\n'.join(raw for x,raw in chunks if x not in selected_streams));cp.set_contents(ref)
                expected=cp.get_pixmap(dpi=200).samples
                self.assertEqual(e.remove_selected_image_paints(p,rects),list(range(8)))
                self.assertEqual(p.get_pixmap(dpi=200).samples,expected)
