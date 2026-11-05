import unittest
import tempfile
import subprocess
from pathlib import Path
import fitz
from unittest.mock import patch
import ocr_helper as ocr

class OcrSafetyTests(unittest.TestCase):
    def test_region_ocr_maps_local_rotation_back_to_native_page(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'source.pdf';doc=fitz.open();p=doc.new_page(width=300,height=200);p.insert_text((60,90),'TRAN THI MAI');doc.save(source);doc.close()
            regions=[dict(key=str(rotation),page=1,rect=[50,50,150,100],rotation=rotation) for rotation in (0,90,270)]
            def backend(path,pages,**kwargs):
                # Independently hand-derived local coordinates for the same native rectangle.
                boxes={1:(10,20,30,30),2:(20,10,30,30),3:(20,70,30,90)}
                return {pn:('X',[(0,0,boxes[pn],'X')]) for pn in pages}
            with patch.object(ocr,'ocr_pdf_pages',side_effect=backend):
                results=ocr.ocr_pdf_regions(source,regions)
            for text,chars in results.values():
                self.assertEqual(text,'X')
                # Raster clipping rounds each edge to the surrounding 200-dpi pixel.
                for actual,expected in zip(chars[0][2],(60,70,80,80)):
                    self.assertAlmostEqual(actual,expected,delta=.36)

    def test_real_region_ocr_reads_vertical_name_and_returns_native_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'vertical.pdf';doc=fitz.open();p=doc.new_page(width=300,height=400)
            p.insert_text((100,300),'TRAN THI MAI',rotate=90,fontsize=20);p.set_rotation(270);doc.save(path);doc.close()
            results=ocr.ocr_pdf_regions(path,[dict(key='signature',page=1,rect=[60,130,125,320],rotation=90)])
            text,chars=results['signature'];self.assertIn('TRAN THI MAI',text.upper())
            self.assertTrue(chars)
            for _,_,rect,ch in chars:
                self.assertTrue(fitz.Rect(59,129,126,321).contains(fitz.Rect(rect)))
    def test_real_identifier_crossing_tile_seam_is_complete(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'seam.pdf'
            source=fitz.open();page=source.new_page(width=3600,height=160)
            page.insert_text((1436,80),'0912345678',fontsize=10)
            page.insert_text((1436,110),'NGUYEN VAN AN',fontsize=10)
            page.insert_text((1436,140),'12 PHO MINH KHAI HA NOI',fontsize=10)
            pix=page.get_pixmap(dpi=200,alpha=False);doc=fitz.open()
            page=doc.new_page(width=3600,height=160);page.insert_image(page.rect,stream=pix.tobytes('png'))
            doc.save(path);doc.close();source.close()
            text,chars=ocr.ocr_pdf_pages(path,[1],max_workers=1)[1]
            self.assertIn('0912345678',text)
            self.assertIn('NGUYEN VAN AN',text.upper())
            self.assertIn('12 PHO MINH KHAI HA NOI',text.upper())
    def test_ocr_settings_fingerprint_caches_and_changes_with_language(self):
        ocr.ocr_settings_fingerprint.cache_clear()
        with patch.object(ocr.platform,'platform',return_value='Windows-test'), patch.object(ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'en-US\n4096\n','')) as run:
            first=ocr.ocr_settings_fingerprint()
            self.assertEqual(first,ocr.ocr_settings_fingerprint())
            self.assertEqual(run.call_count,1)
            self.assertNotEqual(first,ocr.ocr_settings_fingerprint(300))
        ocr.ocr_settings_fingerprint.cache_clear()
        with patch.object(ocr.platform,'platform',return_value='Windows-test'), patch.object(ocr.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'vi-VN\n4096\n','')):
            self.assertNotEqual(first,ocr.ocr_settings_fingerprint())
        ocr.ocr_settings_fingerprint.cache_clear()
    def test_real_ocr_normalizes_pdf_rotation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'rotated.pdf'
            source=fitz.open();page=source.new_page(width=600,height=400)
            page.insert_text((50,80),'TRAN THI BAN',fontsize=16)
            pix=page.get_pixmap(dpi=200,alpha=False);doc=fitz.open()
            for angle in (0,90,180,270):
                page=doc.new_page(width=600,height=400)
                page.insert_image(page.rect,stream=pix.tobytes('png'));page.set_rotation(angle)
            doc.save(path);doc.close();source.close()
            maps=ocr.ocr_pdf_pages(path,[1,2,3,4])
            for text,chars in maps.values():
                self.assertIn('TRAN THI BAN',text.upper())
                self.assertTrue(all(40<=b[0]<=170 and 60<=b[1]<=90 for _,_,b,ch in chars if ch.strip()))
    def test_real_large_page_tiles_keep_complete_name(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'large.pdf'
            source=fitz.open();page=source.new_page(width=1600,height=200)
            page.insert_text((1400,100),'TRAN THI BAN',fontsize=16)
            pix=page.get_pixmap(dpi=200,alpha=False)
            doc=fitz.open();page=doc.new_page(width=1600,height=200)
            page.insert_image(page.rect,stream=pix.tobytes('png'));doc.save(path)
            doc.close();source.close()
            text,chars=ocr.ocr_pdf_pages(path,[1],max_workers=1)[1]
            self.assertIn('TRAN THI BAN',text.upper())
            self.assertTrue(all(0<=b[0]<=b[2]<=1600 and 0<=b[1]<=b[3]<=200 for _,_,b,_ in chars))
    def test_tile_origins_cover_edges_with_overlap(self):
        self.assertEqual(ocr._tile_origins(4100,4096,64),[0,4])
        self.assertEqual(ocr._tile_origins(100,4096,64),[0])
    def test_merge_tile_words_preserves_different_overlapping_text(self):
        words=[{'t':'NAME','x':10,'y':10,'w':80,'h':20}, {'t':'NAME','x':11,'y':10,'w':80,'h':20}, {'t':'DIFFERENT','x':10,'y':10,'w':80,'h':20}]
        self.assertEqual(len(ocr._deduplicate_words(words)),2)
    def test_ocr_worker_count_rejects_invalid_value(self):
        with self.assertRaises(ValueError):ocr.ocr_pdf_pages('unused.pdf',[1],max_workers=0)
    def test_char_boxes_stay_inside_page(self):
        text,chars=ocr.build_char_map_from_ocr_words([{'t':'A','x':99.8,'y':99.8,'w':4,'h':4}],100,100,100,100)
        self.assertTrue(all(0<=b[0]<=b[2]<=100 and 0<=b[1]<=b[3]<=100 for _,_,b,_ in chars))
if __name__=='__main__':unittest.main()
