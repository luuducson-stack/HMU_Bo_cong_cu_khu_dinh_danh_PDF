import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import engine


class OutputQcTests(unittest.TestCase):
    def test_nearly_covered_source_bbox_needs_actual_blank_pixel_proof(self):
        for ink in (False,True):
            with self.subTest(remaining_ink=ink):
                candidate=dict(id='near-mask',kind='PERSON_NAME_UNCLASSIFIED',text='TRAN THI BINH',rects=[[180,170,260,180]],selected=False,clinical_overlap=False,review_status='CONTEXT_REQUIRED')
                mask=dict(id='selected-field',kind='SIGNATURE_REGION',text='Selected identity field',rects=[[180.4,170,260,180]],selected=True,clinical_overlap=False)
                review=json.loads((self.job/'review.json').read_text(encoding='utf8'));review['pages'][0]['proposals']=[q for q in review['pages'][0]['proposals'] if q['id'] not in {'near-mask','selected-field'}]+[candidate,mask];engine.save_json(self.job/'review.json',review)
                self.product=self.root/f'near-{ink}.pdf'
                with fitz.open() as raw,fitz.open() as pdf:
                    p=raw.new_page(width=300,height=240)
                    if ink:p.draw_rect(fitz.Rect(180.02,173,180.35,175),fill=(0,0,0),color=None)
                    pix=p.get_pixmap(dpi=200,alpha=False);p=pdf.new_page(width=300,height=240);p.insert_image(p.rect,pixmap=pix);pdf.save(self.product)
                with fitz.open() as benign:
                    p=benign.new_page(width=300,height=240);p.insert_text((20,110),'Clinical stable glucose 5.2');report=self.verify({1:engine.char_map(p)})
                flagged=any(f.get('proposal_id')=='near-mask' for f in report['findings']);self.assertEqual(flagged,ink)

    def test_identity_cell_ink_cannot_pass_even_when_ocr_misses_it(self):
        q=dict(id='identity-cell',kind='SIGNATURE_REGION',text='Identity cell',rects=[[180,170,190,180]],selected=True,clinical_overlap=False,rule='explicit_identity_column_cell')
        self.review['pages'][0]['proposals'].append(q);engine.save_json(self.job/'review.json',self.review)
        self.product=self.root/'remaining-cell.pdf'
        with fitz.open() as raw,fitz.open() as pdf:
            p=raw.new_page(width=300,height=240);p.draw_rect(fitz.Rect(182,172,185,175),fill=(0,0,0),color=None)
            pix=p.get_pixmap(dpi=200,alpha=False);p=pdf.new_page(width=300,height=240);p.insert_image(p.rect,pixmap=pix);pdf.save(self.product)
        with fitz.open() as d:
            p=d.new_page(width=300,height=240);p.insert_text((20,110),'Clinical stable glucose 5.2')
            report=self.verify({1:engine.char_map(p)})
        self.assertTrue(any(f['reason']=='identity_cell_not_blank' for f in report['findings']))
        self.assertNotEqual(report['status'],'PASS')

    def test_sparse_visible_content_with_empty_ocr_cannot_pass(self):
        self.product=self.root/'sparse.pdf'
        with fitz.open() as raw,fitz.open() as pdf:
            p=raw.new_page(width=300,height=240)
            p.draw_rect(fitz.Rect(180,170,180.7,171),fill=(0,0,0),color=None)
            pix=p.get_pixmap(dpi=200,alpha=False)
            p=pdf.new_page(width=300,height=240);p.insert_image(p.rect,pixmap=pix);pdf.save(self.product)
        report=self.verify({1:('',[])})
        self.assertNotEqual(report['status'],'PASS')
        self.assertEqual(report['unreadable_pages'],[1])
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('output_qc'),'Final PDF verifier is missing')
        import output_qc
        self.qc=output_qc
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.job=self.root/'job'
        self.source=self.root/'original.pdf'
        with fitz.open() as d:
            p=d.new_page(width=300,height=240)
            p.insert_text((20,35),'Ho ten: NGUYEN VAN AN')
            p.insert_text((20,110),'Clinical stable glucose 5.2')
            d.save(self.source)
        self.review=engine.prepare(self.source,self.job,case_xml_index=[])
        self.product,_=engine.export(self.job,draft=True)

    def verify(self, maps):
        with patch.object(self.qc,'ocr_pdf_pages',return_value=maps):
            return self.qc.verify_output(self.job,self.product,expected_revision=self.review['revision'],ocr_workers=1)

    def test_missing_ocr_page_is_not_a_pass(self):
        report=self.verify({})
        self.assertNotEqual(report['status'],'PASS')
        self.assertEqual(report['pages_checked'],0)

    def test_unreadable_page_blocks_pass(self):
        report=self.verify({1:('',[])})
        self.assertNotEqual(report['status'],'PASS')
        self.assertEqual(report['unreadable_pages'],[1])

    def test_visible_patient_name_remains_a_finding(self):
        with fitz.open(self.source) as d:maps={1:engine.char_map(d[0])}
        report=self.verify(maps)
        self.assertEqual(report['status'],'NEEDS_REVIEW')
        self.assertTrue(any(f['kind']=='PATIENT_NAME' for f in report['findings']))

    def test_clean_ocr_is_not_human_approval(self):
        with fitz.open() as d:
            p=d.new_page(width=300,height=240);p.insert_text((20,110),'Clinical stable glucose 5.2')
            report=self.verify({1:engine.char_map(p)})
        self.assertEqual(report['status'],'PASS')
        self.assertEqual(report['pdf_sha256'],engine.sha(self.product))
        stored=json.loads((self.job/'review.json').read_text(encoding='utf8'))
        self.assertFalse(any(p['reviewed'] for p in stored['pages']))

    def test_wrong_revision_is_rejected_before_ocr(self):
        with patch.object(self.qc,'ocr_pdf_pages',side_effect=AssertionError('must not OCR stale revision')):
            with self.assertRaisesRegex(ValueError,'revision'):
                self.qc.verify_output(self.job,self.product,expected_revision=self.review['revision']+1,ocr_workers=1)

    def test_modified_pdf_does_not_reuse_cached_result(self):
        with fitz.open() as d:
            p=d.new_page(width=300,height=240);p.insert_text((20,110),'Clinical stable glucose 5.2')
            maps={1:engine.char_map(p)}
        self.verify(maps)
        with self.product.open('ab') as f:f.write(b'\n% changed\n')
        with patch.object(self.qc,'ocr_pdf_pages',return_value=maps) as ocr:
            report=self.qc.verify_output(self.job,self.product,expected_revision=self.review['revision'],ocr_workers=1)
        self.assertTrue(ocr.called)
        self.assertEqual(report['pdf_sha256'],engine.sha(self.product))

    def test_unselected_name_candidate_blocks_automatic_clearance(self):
        data=json.loads((self.job/'review.json').read_text(encoding='utf8'))
        data['pages'][0]['proposals'].append(dict(id='uncertain',kind='PERSON_NAME_UNCLASSIFIED',text='TRAN THI BINH',rects=[[20,140,110,155]],selected=False,clinical_overlap=False,review_status='CONTEXT_REQUIRED'))
        engine.save_json(self.job/'review.json',data)
        with fitz.open() as d:
            p=d.new_page(width=300,height=240);p.insert_text((20,110),'Clinical stable glucose 5.2')
            report=self.verify({1:engine.char_map(p)})
        self.assertEqual(report['status'],'NEEDS_REVIEW')
        self.assertTrue(any(f['reason']=='unselected_source_candidate' for f in report['findings']))

    def test_decimal_subregion_is_covered_without_float32_slivers(self):
        self.assertTrue(self.qc._covered([123.45,234.56,170.89,245.67],[[123.45,234.56,190.12,245.67]]))
        self.assertFalse(self.qc._covered([123.45,234.56,190.13,245.67],[[123.45,234.56,190.12,245.67]]))

    def test_review_only_change_reuses_ocr_but_mask_change_does_not(self):
        maps={1:('Clinical stable glucose 5.2',[])}
        first=self.verify(maps)
        data=json.loads((self.job/'review.json').read_text(encoding='utf8'))
        data['revision']+=1;data['pages'][0]['reviewed']=True;data['pages'][0]['note']='Checked'
        engine.save_json(self.job/'review.json',data)
        with patch.object(self.qc,'ocr_pdf_pages',side_effect=AssertionError('Review only must not repeat OCR')):
            result=self.qc.verify_output(self.job,self.product,expected_revision=data['revision'],ocr_workers=1)
        self.assertEqual(result['revision'],data['revision'])
        self.assertEqual(result['content_sha256'],first['content_sha256'])
        data['revision']+=1;data['pages'][0]['manual_rects']=[[15,15,25,25]]
        engine.save_json(self.job/'review.json',data)
        with patch.object(self.qc,'ocr_pdf_pages',return_value=maps) as ocr:
            self.qc.verify_output(self.job,self.product,expected_revision=data['revision'],ocr_workers=1)
        self.assertTrue(ocr.called)


if __name__=='__main__':unittest.main()
