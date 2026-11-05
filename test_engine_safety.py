import unittest, tempfile, json, hashlib
from pathlib import Path
from unittest.mock import patch
import fitz
import engine as e
from hmu_recognizers import Finding

class EngineSafetyTests(unittest.TestCase):
    def test_signature_stroke_cannot_supply_its_own_identity_row_border(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.draw_line((480,150),(560,150),width=.8)
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p,mask_cells=True)
            self.assertTrue(any(q['selected'] and fitz.Rect(r).contains(fitz.Point(520,150)) for q in found for r in q['rects']))

    def test_closed_identity_cells_keep_dotted_row_borders(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,240):p.draw_line((20,y),(560,y),width=.4)
            for y in (140,200):
                for x in range(20,560,2):p.draw_line((x,y),(x+.4,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((486,110),'Ngy-T!vax')
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p,mask_cells=True)
            before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for q in found:
                if q['selected']:
                    for r in q['rects']:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            for y in (140,200):
                box=(fitz.Rect(481,y-1,559,y+1)*fitz.Matrix(200/72,200/72)).irect
                for row in range(box.y0,box.y1):self.assertEqual(before.samples_mv[row*before.stride+box.x0*3:row*before.stride+box.x1*3].tobytes(),after.samples_mv[row*after.stride+box.x0*3:row*after.stride+box.x1*3].tobytes())

    def test_repeated_identity_header_inside_grid_is_preserved(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,300),width=.4)
            for y in (30,80,140,200,240,300):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((500,220),'Dieu duong');p.insert_text((486,110),'Ngy-T!vax')
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p,mask_cells=True)
            self.assertFalse(any(q['selected'] and fitz.Rect(r).intersects(fitz.Rect(490,205,558,225)) for q in found for r in q['rects']))

    def test_closed_identity_cells_cover_unreadable_names_and_keep_grid(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((486,110),'Ngy-T!vax');p.insert_text((300,110),'Glucose 5.2')
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p,mask_cells=True)
            cells=[q for q in found if q.get('rule')=='explicit_identity_column_cell']
            self.assertTrue(cells);self.assertTrue(any(fitz.Rect(r).contains(fitz.Point(510,105)) for q in cells for r in q['rects']))
            before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for q in cells:
                for r in q['rects']:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            for crop in ((20,29,561,31),(20,79,561,81),(20,139,561,141),(20,239,561,241),(299,90,399,120),(480,30,481,240),(559,30,561,240),(490,35,558,70)):
                box=(fitz.Rect(crop)*fitz.Matrix(200/72,200/72)).irect
                for y in range(box.y0,box.y1):self.assertEqual(before.samples_mv[y*before.stride+box.x0*3:y*before.stride+box.x1*3].tobytes(),after.samples_mv[y*after.stride+box.x0*3:y*after.stride+box.x1*3].tobytes())

    def test_closed_identity_cell_with_clinical_text_requires_review(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((486,110),'Glucose 5.2');p.insert_text((486,130),'Le Huu Binh')
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p,mask_cells=True)
            self.assertTrue(any(q.get('rule')=='identity_cell_clinical_review' and not q['selected'] for q in found))
            self.assertFalse(any(q['selected'] and fitz.Rect(r).intersects(fitz.Rect(481,82,559,138)) for q in found for r in q['rects']))

    def test_missing_prefix_insurance_requires_matching_label_geometry(self):
        from hmu_recognizers import analyze_hmu_text
        for x,y in ((40,100),(180,180)):
            with fitz.open() as d:
                p=d.new_page(width=600,height=800);p.insert_text((400,100),'So the BHYT:');p.insert_text((x,y),'1234567890123')
                text,chars=e.char_map(p);text=text.replace('\n',' ');f=next(f for f in analyze_hmu_text(text) if f.entity_type=='HEALTH_INSURANCE_ID')
                e.insurance_value_rects(text,chars,f,p.rect);self.assertEqual(f.review_status,'CONTEXT_REQUIRED')

    def test_insurance_value_bounds_cover_missing_ocr_prefix_and_preserve_labels(self):
        from hmu_recognizers import analyze_hmu_text
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((50,100),'So the BHYT:');p.insert_text((180,100),'KC1234567890123');p.insert_text((50,140),'Ma HS: 1234567890123')
            text,chars=e.char_map(p);a=text.index('KC');code=e.span_rects(chars,a,a+15)[0];label=e.span_rects(chars,0,text.index(':')+1)[0]
            mapped=(text[:a]+text[a+2:]).replace('\n',' ');mc=[(i if i<a else i-2,l,bb,ch) for i,l,bb,ch in chars if not a<=i<a+2]
            f=next(f for f in analyze_hmu_text(mapped) if f.entity_type=='HEALTH_INSURANCE_ID')
            rects=e.insurance_value_rects(mapped,mc,f,p.rect)
            self.assertTrue(any(fitz.Rect(r).contains(fitz.Rect(code)) for r in rects));self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(label)) for r in rects))
            self.assertTrue(all(r[3]<125 for r in rects))

    def test_insurance_value_cannot_expand_across_unrelated_clinical_words(self):
        from hmu_recognizers import analyze_hmu_text
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((50,100),'So the BHYT:');p.insert_text((500,100),'1234567890123');p.insert_text((300,100),'Glucose 5.2')
            text,chars=e.char_map(p);text=text.replace('\n',' ');f=next(f for f in analyze_hmu_text(text) if f.entity_type=='HEALTH_INSURANCE_ID')
            rects=e.insurance_value_rects(text,chars,f,p.rect)
            clinical=e.span_rects(chars,text.index('Glucose'),text.index('Glucose')+11)
            self.assertEqual(f.review_status,'CONTEXT_REQUIRED');self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(c)) for r in rects for c in clinical))

    def test_identity_images_do_not_reparse_native_geometry_per_image(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong')
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0)
            for y in (95,155):p.insert_image(fitz.Rect(486,y,550,y+35),pixmap=pix,keep_proportion=False)
            text,chars=e.char_map(p)
            class Counted(list):
                visits=0
                def __iter__(self):self.visits+=1;return super().__iter__()
            drawings=[dict(dr,items=Counted(dr['items'])) for dr in p.get_cdrawings()]
            with patch.object(fitz.Page,'get_cdrawings',return_value=drawings):found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertEqual(sum(q['kind']=='SIGNATURE_IMAGE' for q in found),2);self.assertEqual(max(dr['items'].visits for dr in drawings),1)


    def test_segmented_native_cell_walls_do_not_need_raster_fallback(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for top,bottom in ((80,140),(140,200)):
                for x in (480,560):p.draw_line((x,top),(x,bottom),width=.4)
            for y in (80,140,200):p.draw_line((480,y),(560,y),width=.4)
            with patch.object(fitz.Page,'get_pixmap',side_effect=AssertionError('Unexpected raster fallback')):
                self.assertTrue(e.image_in_signature_cell(p,fitz.Rect(490,155,550,190),80))

    def test_raster_identity_images_reuse_the_existing_page_pixmap(self):
        with fitz.open() as original,fitz.open() as target:
            p=original.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');text,chars=e.char_map(p);background=p.get_pixmap(dpi=200,alpha=False)
            p=target.new_page(width=600,height=800);p.insert_image(p.rect,pixmap=background)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0)
            for y in (95,155):p.insert_image(fitz.Rect(486,y,550,y+35),pixmap=pix,keep_proportion=False)
            get_pixmap=fitz.Page.get_pixmap;calls=[]
            def capture(page,*args,**kwargs):calls.append(page.number);return get_pixmap(page,*args,**kwargs)
            with patch.object(fitz.Page,'get_pixmap',capture):found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertEqual(sum(q['kind']=='SIGNATURE_IMAGE' for q in found),2);self.assertEqual(len(calls),1)

    def test_footer_value_never_shrinks_an_existing_name_box(self):
        text='Ho ten:TRAN VAN AN';chars=[(i,0,(20,720,99.5,730),ch) if i<7 else (i,0,(100,720,160,730),ch) for i,ch in enumerate(text)]
        self.assertLessEqual(e.labelled_footer_name_rects(text,chars,[[100,720,160,730]],fitz.Rect(0,0,600,800))[0][0],100)

    def test_footer_label_pixels_survive_an_ocr_box_shortened_at_its_right_edge(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.draw_rect(p.rect,fill=(.98,.98,.98),color=None);p.insert_text((350,730),'Ho ten:');p.insert_text((420,730),'TRAN VAN AN')
            text,chars=e.char_map(p);a=text.index('TRAN');label=fitz.Rect(e.span_rects(chars,0,text.index(':')+1)[0]);name=e.span_rects(chars,a,a+11)
            chars=[(i,l,(bb[0],bb[1],bb[2]-1.4,bb[3]),ch) if i==text.index(':') else (i,l,bb,ch) for i,l,bb,ch in chars]
            masks=e.pad_name_rects(e.labelled_footer_name_rects(text,chars,name,p.rect),e.span_rects(chars,0,text.index(':')+1))
            before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for r in masks:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            old,new=before.samples,after.samples;crop=((label+(-1,-1,0,1))*fitz.Matrix(200/72,200/72)).irect
            for y in range(crop.y0,crop.y1):self.assertEqual(old[y*before.stride+crop.x0*3:y*before.stride+crop.x1*3],new[y*after.stride+crop.x0*3:y*after.stride+crop.x1*3])

    def test_identity_images_reuse_native_table_drawings_per_page(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong')
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0)
            for y in (95,155):p.insert_image(fitz.Rect(486,y,550,y+35),pixmap=pix,keep_proportion=False)
            text,chars=e.char_map(p);original=fitz.Page.get_cdrawings;calls=[]
            def capture(page,*args,**kwargs):calls.append(page.number);return original(page,*args,**kwargs)
            with patch.object(fitz.Page,'get_cdrawings',capture):found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertEqual(sum(q['kind']=='SIGNATURE_IMAGE' for q in found),2);self.assertEqual(len(calls),1)

    def test_bounded_patient_field_prevents_duplicate_name_halo_expansion(self):
        source=self.root/'bounded.pdf'
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((50,100),'Ho ten (in hoa): TRAN VAN AN   Ngay sinh:',fontsize=11);d.save(source)
            text,chars=e.char_map(p);field=fitz.Rect(e.patient_name_value_rect(text,chars,p.rect))
        data=e.prepare(source,self.root/'boundedjob',case_xml_index=[])
        names=[q for q in data['pages'][0]['proposals'] if q['selected'] and q['kind']=='PATIENT_NAME']
        self.assertTrue(any(q['text']=='TRAN VAN AN' for q in names))
        self.assertTrue(all(field.contains(fitz.Rect(r)) for q in names for r in q['rects']))

    def test_scan_role_preserves_texture_in_label_margin_when_signature_is_lower(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.draw_rect(p.rect,fill=(.98,.98,.98),color=None);p.insert_text((410,640),'Bac sy dieu tri');p.draw_line((440,680),(470,700),width=1);p.insert_text((410,735),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);found=e.scanned_signature_proposals(p,text,chars,[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,725,530,738]])],1)
            self.assertTrue(found);before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for q in found:
                for r in q['rects']:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            a,b=before.samples,after.samples;crop=(fitz.Rect(405,628,550,646)*fitz.Matrix(200/72,200/72)).irect
            for y in range(crop.y0,crop.y1):self.assertEqual(a[y*before.stride+crop.x0*3:y*before.stride+crop.x1*3],b[y*after.stride+crop.x0*3:y*after.stride+crop.x1*3])

    def test_broken_ocr_role_words_stay_in_the_same_column(self):
        for x,expected in ((445,True),(590,False)):
            with fitz.open() as d:
                p=d.new_page(width=800,height=800);p.insert_text((400,550),'Bac');p.insert_text((x,550),'CHUYEN KHOA');p.insert_text((430,610),'TRAN AN')
                text,chars=e.char_map(p);a=text.index('TRAN');f=Finding('HEALTHCARE_STAFF_NAME',a,a+7,.75,'TRAN AN','v20_title_name:confirmed_case_short','CONTEXT_REQUIRED')
                self.assertEqual(e.signature_heading_confirms(f,text,chars),expected)

    def test_structured_selected_name_wins_over_uncertain_same_span_alias(self):
        source=self.root/'priority.pdf'
        with fitz.open() as d:
            d.new_page().insert_text((50,80),'TRAN VAN AN');d.save(source)
        with fitz.open(source) as d:text,chars=e.char_map(d[0])
        # Use the generated native text's actual span; only detector ordering is mocked.
        a=0;b=len(text.strip());value=text[a:b]
        fs=[Finding('PERSON_NAME',a,b,.75,value,'memorized_staff_sur_given','CONTEXT_REQUIRED'),Finding('PERSON_NAME',a,b,.99,value,'explicit_name_label_ocr')]
        with patch.object(e,'analyze_hmu_document',return_value=([fs],{})),patch.object(e,'additional_findings',return_value=[]):data=e.prepare(source,self.root/'priorityjob',case_xml_index=[])
        self.assertTrue(any(q['text']==value and q['selected'] for q in data['pages'][0]['proposals']))

    def test_infusion_nurse_ocr_header_and_native_signature_keep_clinical_image(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Diou duong');p.insert_text((486,110),'Le Huu Binh')
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(486,95,550,130),pixmap=pix,keep_proportion=False);p.insert_image(fitz.Rect(310,95,360,130),pixmap=pix,keep_proportion=False)
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertTrue(any(q['kind']=='HEALTHCARE_STAFF_NAME' for q in found))
            images=[r for q in found if q['kind']=='SIGNATURE_IMAGE' for r in q['rects']]
            self.assertEqual(images,[[486,95,550,130]])

    def test_identity_column_keeps_image_containing_protected_clinical_text(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((490,110),'Glucose 5.2',fontsize=8)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0);p.insert_image(fitz.Rect(486,95,550,130),pixmap=pix)
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertFalse(any(q['kind']=='SIGNATURE_IMAGE' for q in found))

    def test_image_pixels_cannot_supply_their_own_table_cell_borders(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (480,560):p.draw_line((x,50),(x,300),width=.4)
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0);r=fitz.Rect(490,150,550,200);p.insert_image(r,pixmap=pix,keep_proportion=False)
            self.assertFalse(e.image_in_signature_cell(p,r,100))

    def test_footer_name_label_accepts_tan_ocr_variant(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((350,730),'HQ tan');p.insert_text((420,730),'TRAN VAN AN')
            text,chars=e.char_map(p);a=text.index('TRAN');rs=e.span_rects(chars,a,a+11)
            self.assertGreater(e.labelled_footer_name_rects(text,chars,rs,p.rect)[0][3],rs[0][3]+2)

    def test_daily_form_writer_signature_cells_preserve_clinical_rows(self):
        with fitz.open() as d:
            p=d.new_page(width=400,height=400)
            for x in (20,120,200,280,380):p.draw_line((x,250),(x,350),width=.4)
            for y in (250,350):p.draw_line((20,y),(380,y),width=.4)
            p.insert_text((30,280),'Nguoi phieu',fontsize=8);p.insert_text((30,300),'Hang ngay ghi ten vao o',fontsize=7);p.insert_text((150,340),'TRAN THI BINH',rotate=90);p.insert_text((20,220),'Glucose 5.2')
            text,chars=e.char_map(p);found=e.nurse_signature_regions(p,chars,text,1)
            self.assertTrue(found);self.assertTrue(all(r[1]>250 for q in found for r in q['rects']))

    def test_infusion_identity_column_stops_at_end_of_physical_table(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((486,110),'Le Huu Binh');p.insert_text((486,310),'Ha Kali Mau')
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertTrue(any(q['text']=='Le Huu Binh' for q in found));self.assertFalse(any('Kali' in q['text'] for q in found))

    def test_real_page_signature_column_requires_physical_grid_proof(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((20,50),'Theo doi dien bien');p.insert_text((300,50),'Thuc hien y lenh/cham soc');p.insert_text((510,50),'Ky ten');p.insert_text((500,100),'TRAN THI BINH')
            text,chars=e.char_map(p)
            self.assertEqual(e.signature_column_proposals(text,chars,p.rect,page=p),[])

    def test_wrapped_scanned_role_heading_keeps_every_line_of_printed_text(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((410,620),'Bac si');p.insert_text((410,640),'dieu tri');p.insert_text((410,735),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);found=e.scanned_signature_proposals(p,text,chars,[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,725,530,738]])],1)
            self.assertTrue(found);before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for q in found:
                for r in q['rects']:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            a,b=before.samples,after.samples;crop=(fitz.Rect(405,608,550,645)*fitz.Matrix(200/72,200/72)).irect
            for y in range(crop.y0,crop.y1):self.assertEqual(a[y*before.stride+crop.x0*3:y*before.stride+crop.x1*3],b[y*after.stride+crop.x0*3:y*after.stride+crop.x1*3])

    def test_infusion_identity_columns_follow_grid_not_header_text_indent(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (20,300,400,480,560):p.draw_line((x,30),(x,240),width=.4)
            for y in (30,80,140,200,240):p.draw_line((20,y),(560,y),width=.4)
            p.insert_text((300,50),'Ten dich truyen/');p.insert_text((410,50),'Bic si');p.insert_text((410,65),'chi dinh');p.insert_text((500,50),'Dieu duong');p.insert_text((500,65),'thuc hien')
            p.insert_text((300,110),'Glucose 5.2');p.insert_text((410,110),'BSCKI. TRAN');p.insert_text((410,124),'VAN AN');p.insert_text((486,110),'Le Huu Binh')
            text,chars=e.char_map(p);found=e.signature_column_proposals(text,chars,p.rect,page=p)
            self.assertTrue(any(q['text']=='Le Huu Binh' for q in found));self.assertTrue(any(q['text']=='TRAN VAN AN' for q in found))
            clinical=e.span_rects(chars,text.index('Glucose'),text.index('Glucose')+11)
            self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(c)) for q in found for r in q['rects'] for c in clinical))

    def test_infusion_names_without_grid_are_not_automatically_selected(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((300,50),'Ten dich truyen/');p.insert_text((500,50),'Dieu duong');p.insert_text((486,110),'Le Huu Binh')
            text,chars=e.char_map(p)
            self.assertEqual(e.signature_column_proposals(text,chars,p.rect,page=p),[])

    def test_known_full_staff_name_ocr_error_uses_role_heading_without_si(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((400,550),'Bac CHUYEN KHOA');p.insert_text((410,610),'Tr?m Van Thing')
            text,chars=e.char_map(p);a=text.index('Tr?m')
            f=Finding('HEALTHCARE_STAFF_NAME',a,a+14,.75,'Tr?m Van Thing','workflow_known_accent_variant_review:confirmed_case_full','CONTEXT_REQUIRED')
            self.assertTrue(e.signature_heading_confirms(f,text,chars))

    def test_titled_name_prefix_stops_before_staggered_second_column(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((100,520),'BSCKI. Tran Van An');p.insert_text((360,526),'LE THI BINH')
            text,chars=e.char_map(p);text=text.replace('\n',' ');a=text.index('Tran');b=text.index('LE THI')+11
            f=Finding('HEALTHCARE_STAFF_NAME',a,b,.75,text[a:b],'v20_title_name:GEOMETRY_REQUIRED_REVIEW','CONTEXT_REQUIRED')
            self.assertTrue(e.trim_titled_name_to_column(f,text,chars));self.assertEqual(f.text,'Tran Van An')

    def test_name_padding_reserves_neighbor_word_diacritics(self):
        rect=e.pad_name_rects([[30,10,100,20]],[[30,23,100,33]])[0]
        self.assertEqual(rect[3],20)

    def test_footer_uses_exact_native_signature_images_instead_of_whitening_whole_field(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((90,500),'NGUOI LAP BANG KE');p.insert_text((90,518),'(ky, ghi ro ho ten)');p.insert_text((105,570),'Le Huu An')
            text,chars=e.char_map(p);image=[110,535,155,572]
            found=e.footer_signature_fields(text,chars,p.rect,1,native_images=[image])
            self.assertEqual([r for q in found if q['kind']=='SIGNATURE_IMAGE' for r in q['rects']],[image])

    def test_signature_fragments_do_not_block_explicit_footer_name_field(self):
        source=self.root/'footer.pdf'
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((90,500),'NGUOI LAP BANG KE');p.insert_text((90,518),'(ky, ghi ro ho ten)');p.insert_text((105,570),'Le Huu An')
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,80),False);pix.clear_with(0);p.insert_image(fitz.Rect(110,535,155,572),pixmap=pix);d.save(source)
        with patch.object(e,'ocr_pdf_pages',return_value={}):data=e.prepare(source,self.root/'footerjob',case_xml_index=[])
        self.assertTrue(any(q.get('rule')=='explicit_footer_role_instruction_name' and q['selected'] for q in data['pages'][0]['proposals']))

    def test_missing_leading_name_ocr_keeps_full_bounded_field_height(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((50,100),'Ho ten (in hoa):',fontsize=14);p.insert_text((250,98),'THI BINH',fontsize=10);p.insert_text((320,100),'Ngay sinh:',fontsize=14)
            text,chars=e.char_map(p);rect=e.patient_name_value_rect(text,chars,p.rect)
            label=e.span_rects(chars,text.index('(in'),text.index('):')+2)[-1]
            self.assertAlmostEqual(rect[3],label[3],places=2)

    def test_name_padding_covers_missing_diacritic_above_ocr_box(self):
        rect=e.pad_name_rects([[30,30,100,40]],[])[0]
        self.assertLessEqual(rect[1],27.5)

    def test_footer_name_label_can_lose_its_colon_in_ocr(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((350,730),'Ho ten');p.insert_text((420,730),'TRAN VAN AN')
            text,chars=e.char_map(p);a=text.index('TRAN');rs=e.span_rects(chars,a,a+11)
            self.assertGreater(e.labelled_footer_name_rects(text,chars,rs,p.rect)[0][3],rs[0][3]+2)

    def test_scanned_signature_starts_after_actual_role_ink_and_before_signature(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((410,640),'Bac si dieu tri');p.draw_line((440,646),(470,656),width=1);p.insert_text((410,735),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);found=e.scanned_signature_proposals(p,text,chars,[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,725,530,738]])],1)
            self.assertTrue(found);self.assertLess(found[0]['rects'][0][1],645.5)
            before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for q in found:
                for r in q['rects']:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            crop=(fitz.Rect(405,628,550,644)*fitz.Matrix(200/72,200/72)).irect
            for y in range(crop.y0,crop.y1):self.assertEqual(before.samples[y*before.stride+crop.x0*3:y*before.stride+crop.x1*3],after.samples[y*after.stride+crop.x0*3:y*after.stride+crop.x1*3])

    def test_scanned_signature_does_not_erase_intervening_clinical_words(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((410,640),'Bac si dieu tri');p.insert_text((410,690),'Glucose 5.2');p.insert_text((410,735),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);found=e.scanned_signature_proposals(p,text,chars,[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,725,530,738]])],1)
            clinical=e.span_rects(chars,text.index('Glucose'),text.index('Glucose')+11)
            self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(c)) for q in found for r in q['rects'] for c in clinical))

    def test_top_of_continuation_page_signature_is_not_a_hospital_logo(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((100,135),'BSCKI. TRAN VAN AN')
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,120,60),False);pix.clear_with(0)
            p.insert_image(fitz.Rect(100,90,160,120),pixmap=pix)
            text,chars=e.char_map(p);a=text.index('TRAN');rs=e.span_rects(chars,a,a+11)
            found=e.build_image_and_signature_proposals(p,chars,text,[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=rs)],1)
            self.assertTrue(any(q['kind']=='SIGNATURE_IMAGE' and q['selected'] for q in found))

    def test_footer_field_expansion_keeps_unrelated_words_inside_new_bounds(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((300,730),'Ho ten:');p.insert_text((370,730),'Glucose',fontsize=6);p.insert_text((420,730),'TRAN VAN AN')
            text,chars=e.char_map(p);a=text.index('TRAN');rs=e.span_rects(chars,a,a+11)
            out=e.labelled_footer_name_rects(text,chars,rs,p.rect)
            clinical=e.span_rects(chars,text.index('Glucose'),text.index('Glucose')+7)
            self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(c)) for r in out for c in clinical))

    def test_footer_signature_keeps_an_embedded_image_between_label_and_name(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((90,500),'NGUOI LAP BANG KE');p.insert_text((90,518),'(ky, ghi ro ho ten)');p.insert_text((105,570),'Le Huu An')
            text,chars=e.char_map(p)
            found=e.footer_signature_fields(text,chars,p.rect,1,image_rects=[[90,530,150,550]])
            self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(90,530,150,550)) for q in found for r in q['rects']))

    def test_footer_signature_keeps_clinical_text_between_instruction_and_name(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((90,500),'NGUOI LAP BANG KE');p.insert_text((90,518),'(ky, ghi ro ho ten)')
            p.insert_text((90,540),'Glucose 5.2');p.insert_text((105,570),'Le Huu An')
            text,chars=e.char_map(p);found=e.footer_signature_fields(text,chars,p.rect,1)
            self.assertTrue(any(q['kind']=='PERSON_NAME' for q in found))
            protected=e.span_rects(chars,text.index('Glucose'),text.index('Glucose')+11)
            self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(c)) for q in found for r in q['rects'] for c in protected))

    def test_footer_name_never_joins_disconnected_clinical_column(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((90,500),'NGUOI LAP BANG KE');p.insert_text((90,518),'(ky, ghi ro ho ten)')
            p.insert_text((45,570),'Le Huu An');p.insert_text((190,570),'Glucose')
            text,chars=e.char_map(p);found=e.footer_signature_fields(text,chars,p.rect,1)
            self.assertTrue(any(q['kind']=='PERSON_NAME' and q['text']=='Le Huu An' for q in found))
            protected=e.span_rects(chars,text.index('Glucose'),text.index('Glucose')+7)
            self.assertFalse(any(fitz.Rect(r).intersects(fitz.Rect(c)) for q in found for r in q['rects'] for c in protected))

    def test_footer_signature_fields_require_role_instruction_and_printed_name(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x,role,name in ((90,'NGUOI LAP BANG KE','Le Huu An'),(350,'KE TOAN VIEN PHI','Nguy h! Phuong Binh')):
                p.insert_text((x,500),role);p.insert_text((x,518),'(ky, ghi ro ho ten)');p.insert_text((x+15,570),name)
            p.insert_text((90,475),'Clinical C34')
            text,chars=e.char_map(p);found=e.footer_signature_fields(text,chars,p.rect,1)
            self.assertEqual(len(found),4)
            self.assertTrue(all(r[1]>520 for q in found for r in q['rects']))
            self.assertEqual(e.footer_signature_fields(text.replace('ghi ro ho ten','              '),chars,p.rect,1),[])

    def test_footer_name_field_includes_underline_but_keeps_label(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((350,730),'Ho va ten:');p.insert_text((420,730),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);a=text.index('BSCKI');rs=e.span_rects(chars,a,a+len('BSCKI. TRAN VAN AN'))
            out=e.labelled_footer_name_rects(text,chars,rs,p.rect)
            label=e.span_rects(chars,0,text.index('BSCKI'))[0]
            self.assertGreater(out[0][0],label[2]);self.assertLess(out[0][0],rs[0][0]);self.assertGreater(out[0][3],rs[0][3]+2)
            self.assertEqual(e.labelled_footer_name_rects('Clinical result',chars,rs,p.rect),rs)

    def test_confirmed_case_short_name_can_have_ocr_surname_punctuation(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((400,550),"Bac s' dibu tri");p.insert_text((400,610),'Ph?m An')
            text,chars=e.char_map(p);a=text.index('Ph?m')
            f=Finding('HEALTHCARE_STAFF_NAME',a,a+7,.99,'Ph?m An','v20_title_name:confirmed_case_short')
            self.assertTrue(e.signature_heading_confirms(f,text,chars))

    def test_scan_signature_accepts_ocr_case_record_doctor_heading(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((410,640),"Bic ss' lam benh in");p.insert_text((410,735),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p)
            self.assertTrue(e.scanned_signature_proposals(p,text,chars,[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,725,530,738]])],1))

    def test_bounded_patient_field_bottom_follows_value_not_taller_label(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((50,100),'Ho ten (in hoa):',fontsize=14);p.insert_text((160,98),'TRAN VAN AN',fontsize=10);p.insert_text((320,100),'Ngay sinh:',fontsize=14)
            text,chars=e.char_map(p);rect=e.patient_name_value_rect(text,chars,p.rect)
            name=fitz.Rect(e.span_rects(chars,text.index('TRAN'),text.index('TRAN')+11)[0])
            self.assertAlmostEqual(rect[3],name.y1,places=2)

    def test_name_halo_does_not_erase_adjacent_horizontal_grid(self):
        with fitz.open() as d:
            p=d.new_page(width=300,height=300);p.draw_line((20,103.5),(280,103.5),width=.3)
            before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            rects=e.clip_text_masks_to_grid(p,e.pad_name_rects([[190,90,255,103]],[]))
            for r in rects:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            crop=(fitz.Rect(190,103.1,255,103.9)*fitz.Matrix(200/72,200/72)).irect
            for y in range(crop.y0,crop.y1):self.assertEqual(before.samples[y*before.stride+crop.x0*3:y*before.stride+crop.x1*3],after.samples[y*after.stride+crop.x0*3:y*after.stride+crop.x1*3])
    def test_name_halo_padding_respects_adjacent_word_barriers(self):
        rect=e.pad_name_rects([[50.2,10,100,20]],[[40,10,50,20],[100.3,10,110,20]])[0]
        self.assertGreaterEqual(rect[0],50)
        self.assertLessEqual(rect[2],100.3)
        self.assertLess(rect[1],10);self.assertGreater(rect[3],20)

    def test_name_cell_proof_rejects_cross_column_word_pair(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for x in (60,330,560):p.draw_line((x,50),(x,750),width=.3)
            self.assertTrue(e.name_in_single_table_cell(p,[[400,600,440,610],[460,600,490,610]]))
            self.assertFalse(e.name_in_single_table_cell(p,[[280,600,315,610],[345,600,390,610]]))
    def test_scan_signature_keeps_role_when_ocr_box_misses_descenders(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((410,560),'Bac sy dieu tri');p.insert_text((410,650),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);name_start=text.index('BSCKI')
            chars=[(a,l,(r[0],r[1],r[2],r[3]-4),ch) if a<name_start else (a,l,r,ch) for a,l,r,ch in chars]
            proposals=[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,639,520,653]])]
            zones=e.scanned_signature_proposals(p,text,chars,proposals,1)
            self.assertTrue(zones)
            before=p.get_pixmap(dpi=200,alpha=False);after=p.get_pixmap(dpi=200,alpha=False)
            for q in zones:
                for r in q['rects']:after.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            crop=(fitz.Rect(405,548,550,564)*fitz.Matrix(200/72,200/72)).irect
            for y in range(crop.y0,crop.y1):self.assertEqual(before.samples[y*before.stride+crop.x0*3:y*before.stride+crop.x1*3],after.samples[y*after.stride+crop.x0*3:y*after.stride+crop.x1*3])
    def test_known_birth_year_does_not_propagate_into_treatment_date(self):
        fs=e.additional_findings('Dieu tri ngay 01/04/2026',{'YEAR_OF_BIRTH':['2026']})
        self.assertFalse(any(f.entity_type=='YEAR_OF_BIRTH' for f in fs))
    def test_scanned_signature_is_bounded_by_role_and_confirmed_name(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800);p.insert_text((410,560),'Bac si dieu tri');p.insert_text((410,650),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p)
            proposals=[dict(kind='HEALTHCARE_STAFF_NAME',selected=True,rects=[[410,639,520,653]])]
            found=e.scanned_signature_proposals(p,text,chars,proposals,1)
            self.assertEqual(len(found),1)
            self.assertGreater(found[0]['rects'][0][1],560)
            self.assertLess(found[0]['rects'][0][3],639)
            proposals[0]['selected']=False
            self.assertEqual(e.scanned_signature_proposals(p,text,chars,proposals,1),[])

    def test_titled_name_allows_dropped_middle_word_but_not_separate_column(self):
        chars=[(0,0,(10,10,45,20),'N'),(1,0,(71,10,105,20),'A')]
        f=Finding('HEALTHCARE_STAFF_NAME',0,2,.99,'NGUYEN AN','v20_title_name')
        self.assertFalse(e.name_geometry_valid(f,chars))
        f.rule+=':confirmed_case_short'
        self.assertTrue(e.name_geometry_valid(f,chars))
        chars[1]=(1,0,(180,10,215,20),'A')
        self.assertFalse(e.name_geometry_valid(f,chars))
    def test_titled_doctor_prefix_does_not_consume_drug_in_next_column(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            p.insert_text((50,100),'BSCKI. Tran Thi Binh');p.insert_text((330,100),'Verospiron')
            text,chars=e.char_map(p);text=text.replace('\n',' ');a=text.index('Tran');b=text.index('Verospiron')+len('Verospiron')
            f=Finding('HEALTHCARE_STAFF_NAME',a,b,.75,text[a:b],'v20_title_name:GEOMETRY_REQUIRED_REVIEW','CONTEXT_REQUIRED')
            self.assertTrue(e.trim_titled_name_to_column(f,text,chars))
            self.assertEqual(f.text,'Tran Thi Binh')
            self.assertTrue(e.name_geometry_valid(f,chars))
    def test_title_and_name_boxes_share_complete_same_baseline_height(self):
        text='BSCKI. TRAN VAN AN'
        chars=[(0,0,(10,12,45,18),'B'),(7,1,(46,10,100,20),'T')]
        f=Finding('HEALTHCARE_STAFF_NAME',7,len(text),.99,'TRAN VAN AN','v20_title_name')
        rects=e.staff_name_rects(text,chars,f)
        self.assertTrue(all(r[1]==10 and r[3]==20 for r in rects))
    def test_raster_table_proves_signature_cell_extent(self):
        with fitz.open() as src,fitz.open() as d:
            p=src.new_page(width=600,height=800);p.draw_rect(fitz.Rect(490,30,560,240),width=.3)
            p.draw_line((490,190),(560,190),width=.3)
            pix=p.get_pixmap(dpi=200,alpha=False)
            p=d.new_page(width=600,height=800);p.insert_image(p.rect,pixmap=pix)
            self.assertTrue(e.image_in_signature_cell(p,fitz.Rect(500,200,555,230),70))
            self.assertFalse(e.image_in_signature_cell(p,fitz.Rect(500,500,555,530),70))

    def test_grid_strip_preserves_antialias_at_export_dpi(self):
        with fitz.open() as d:
            p=d.new_page(width=300,height=300);p.draw_line((234.18,20),(234.18,106),width=.3)
            before=p.get_pixmap(dpi=200,alpha=False)
            actual=p.get_pixmap(dpi=200,alpha=False)
            for r in e.clip_text_masks_to_grid(p,[[190,90,255,103]]):actual.set_rect((fitz.Rect(r)*fitz.Matrix(200/72,200/72)).irect,(255,255,255))
            region=(fitz.Rect(233.8,90,234.6,103)*fitz.Matrix(200/72,200/72)).irect
            for y in range(region.y0,region.y1):
                self.assertEqual(before.samples[y*before.stride+region.x0*3:y*before.stride+region.x1*3],actual.samples[y*actual.stride+region.x0*3:y*actual.stride+region.x1*3])
    def test_signature_image_in_labelled_care_table_needs_no_printed_staff_name(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            p.insert_text((20,50),'Theo doi dien bien')
            p.insert_text((300,50),'Thuc hien y lenh/cham soc')
            p.insert_text((510,50),'Ky ten')
            p.draw_rect(fitz.Rect(490,30,560,140),width=.3)
            p.draw_line((490,70),(560,70),width=.3)
            image=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,30,20),False);image.clear_with(100)
            p.insert_image(fitz.Rect(500,100,555,130),pixmap=image)
            text,chars=e.char_map(p)
            result=e.build_image_and_signature_proposals(p,chars,text,[],1)
            self.assertTrue(any(q['kind']=='SIGNATURE_IMAGE' and q['selected'] for q in result))

    def test_clinical_image_below_short_care_table_is_kept(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            for xy,text in [((20,50),'Theo doi dien bien'),((300,50),'Thuc hien y lenh/cham soc'),((510,50),'Ky ten')]:p.insert_text(xy,text)
            p.draw_rect(fitz.Rect(490,30,560,140),width=.3)
            image=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,30,20),False);image.clear_with(100)
            p.insert_image(fitz.Rect(500,500,555,530),pixmap=image)
            text,chars=e.char_map(p)
            self.assertFalse(any(q['selected'] for q in e.build_image_and_signature_proposals(p,chars,text,[],1)))

    def test_grid_between_name_parts_keeps_masks_on_both_sides(self):
        with fitz.open() as d:
            p=d.new_page(width=300,height=300);p.draw_line((220,20),(220,280),width=.3)
            rects=e.clip_text_masks_to_grid(p,[[190,90,255,103]])
            self.assertTrue(any(r[0]==190 and r[2]>218 for r in rects))
            self.assertTrue(any(r[0]<222 and r[2]==255 for r in rects))
    def test_labelled_patient_name_allows_ocr_dropped_middle_word_gap(self):
        chars=[(0,0,(10,10,45,20),'N'),(1,0,(71,10,105,20),'A')]
        f=Finding('PATIENT_NAME',0,2,.99,'NA','v20_strict_field')
        self.assertTrue(e.name_geometry_valid(f,chars))
        chars[1]=(1,0,(180,10,215,20),'A')
        self.assertFalse(e.name_geometry_valid(f,chars))
    def test_staff_mask_includes_ocr_title_box_that_can_hide_dropped_surname(self):
        with fitz.open() as d:
            p=d.new_page();p.insert_text((40,80),'BSCKI. TRAN VAN AN')
            text,chars=e.char_map(p);start=text.index('TRAN')
            f=Finding('HEALTHCARE_STAFF_NAME',start,start+11,.99,'TRAN VAN AN','v20_title_name')
            rects=e.staff_name_rects(text,chars,f)
            self.assertLess(rects[0][0],45)

    def test_signature_heading_confirms_name_only_in_its_column(self):
        with fitz.open() as d:
            p=d.new_page(width=600,height=800)
            p.insert_text((390,600),'NGUOI DUYET KET QUA')
            p.insert_text((400,640),'TRAN THI BINH')
            text,chars=e.char_map(p);start=text.index('TRAN')
            f=Finding('HEALTHCARE_STAFF_NAME',start,start+13,.75,'TRAN THI BINH','memorized_staff_ocr_full','CONTEXT_REQUIRED')
            self.assertTrue(e.signature_heading_confirms(f,text,chars))
            far=[(a,l,(r[0]-300,r[1],r[2]-300,r[3]),ch) if a>=start else (a,l,r,ch) for a,l,r,ch in chars]
            self.assertFalse(e.signature_heading_confirms(f,text,far))
    def test_name_mask_clips_to_raster_grid_without_erasing_border(self):
        with fitz.open() as d:
            p=d.new_page(width=300,height=300)
            p.draw_line((250,20),(250,280),color=(0,0,0),width=.3)
            p.insert_text((195,100),'TRAN AN',fontsize=9)
            rect=e.clip_text_masks_to_grid(p,[[190,90,255,103]])[0]
            self.assertLess(rect[2],249.5)
            self.assertGreater(rect[2],245)
            self.assertEqual(rect[:2],[190,90])
    def test_atomic_json_retries_temporary_windows_reader_lock(self):
        target=self.root/'state.json'
        original=Path.replace;attempts=[]
        def replace(source,destination):
            attempts.append(1)
            if len(attempts)<3:
                error=PermissionError('temporary reader lock');error.winerror=5;raise error
            return original(source,destination)
        with patch.object(Path,'replace',replace):e.save_json(target,{'revision':3})
        self.assertEqual(json.loads(target.read_text()),{'revision':3})
        self.assertEqual(len(attempts),3)
    def test_signature_table_column_handles_wrapped_names_without_clinical_column(self):
        with fitz.open() as doc:
            p=doc.new_page(width=600,height=800)
            p.insert_text((20,50),'Theo doi dien bien')
            p.insert_text((300,50),'Thuc hien y lenh/cham soc')
            p.insert_text((510,50),'Ky ten')
            p.insert_text((20,100),'Clinical glucose 5.2')
            p.insert_text((300,100),'Thuc hien y lenh')
            p.insert_text((500,100),'TRAN THI')
            p.insert_text((510,114),'BINH')
            text,chars=e.char_map(p)
            found=e.signature_column_proposals(text,chars,p.rect)
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]['text'],'TRAN THI BINH')
            self.assertTrue(all(r[0]>480 for r in found[0]['rects']))
            self.assertEqual(e.signature_column_proposals(text.replace('Ky ten','So lieu'),chars,p.rect),[])
    def test_name_field_covers_missing_surname_without_crossing_next_field(self):
        with fitz.open() as doc:
            p=doc.new_page(width=500,height=300)
            p.insert_text((20,40),'Ho ten (in hoa):')
            p.insert_text((150,40),'THI MAI')
            p.insert_text((260,40),'Sinh ngay: 01/01/1970')
            p.draw_rect(fitz.Rect(120,46,130,58),color=(0,0,0))
            p.insert_text((20,70),'Clinical glucose 5.2')
            text,chars=e.char_map(p)
            rect=e.patient_name_value_rect(text,chars,p.rect)
            self.assertIsNotNone(rect)
            self.assertLess(rect[0],115)
            self.assertGreater(rect[2],190)
            self.assertLess(rect[2],260)
            self.assertLess(rect[3],60)
            self.assertFalse(fitz.Rect(rect).intersects(fitz.Rect(120,46,130,58)), 'Name field must keep the next-row checkbox border')
            self.assertIsNone(e.patient_name_value_rect('Ho ten (in hoa):',chars,p.rect))
            wrong=text.replace('Ho ten','Don vi')
            self.assertIsNone(e.patient_name_value_rect(wrong,chars,p.rect))
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def pdf(self,name='source.pdf',watermark=False):
        pth=self.root/name; d=fitz.open();p=d.new_page(width=600,height=800)
        p.insert_text((30,60),'Ho ten: Nguyen Van An')
        p.insert_text((30,120),'Clinical C34 / Glucose 5.2')
        if watermark:p.insert_text((280,400),'Ho Thi Minh Chau_20260803161916',rotate=90)
        d.save(pth);d.close();return pth
    def test_union_masks_overlapping_tail(self):
        s='ABCDEFGHIJK';out=e._build_redacted_markdown(s,[Finding('A',0,5,1,s[:5],'x'),Finding('B',3,10,1,s[3:10],'x')])
        self.assertNotIn('FGHIJ',out);self.assertTrue(out.endswith('K'))
    def test_no_stream_removed_before_review(self):
        d=fitz.open();p=d.new_page();p.insert_text((100,300),'Clinical C34',rotate=90)
        before=p.get_text();self.assertEqual(e.remove_isolated_watermarks(d),[]);self.assertEqual(p.get_text(),before);d.close()
    def test_small_bottom_image_is_not_signature(self):
        d=fitz.open();p=d.new_page(width=600,height=800);pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,200,100),False);pix.clear_with(150)
        p.insert_image(fitz.Rect(50,500,250,600),stream=pix.tobytes('png'))
        qs=e.build_image_and_signature_proposals(p,[],'',[],1);self.assertFalse(qs[0]['selected']);d.close()
    def test_manual_icd_rejected(self):
        data=e.prepare(self.pdf(),self.root/'job');page=data['pages'][0];page['manual_rects']=[[25,105,170,125]];page['reviewed']=True;e.save_json(self.root/'job/review.json',data)
        with self.assertRaisesRegex(ValueError,'Clinical overlap'):e.export(self.root/'job')
    def test_generation_and_current_audit(self):
        job=self.root/'job';data=e.prepare(self.pdf(),job);self.assertIn('job_id',data)
        for q in data['pages'][0]['proposals']:q['selected']=False
        e.save_json(job/'review.json',data);e.generate_audit_markdown(job,data)
        audit=(job/'AUDIT_SUMMARY.md').read_text(encoding='utf8');self.assertIn('Ho ten: Nguyen Van An',audit)
        out,qc=e.export(job,approve_all=True);pointer=json.loads((job/'last_export.json').read_text());self.assertIn('exports',str(out));self.assertEqual(pointer['files'][0]['pdf'],out.name)
    def test_failed_qc_preserves_generation(self):
        job=self.root/'job';e.prepare(self.pdf(),job);out,_=e.export(job,approve_all=True);old=(job/'last_export.json').read_bytes();digest=e.sha(out)
        original=e.save_json
        def fail(path,data):
            if str(path).endswith('.qc.json'):raise OSError('disk error')
            return original(path,data)
        with patch.object(e,'save_json',side_effect=fail):
            with self.assertRaises(OSError):e.export(job)
        self.assertEqual((job/'last_export.json').read_bytes(),old);self.assertEqual(e.sha(out),digest)
    def test_batch_safe_names_and_64_id(self):
        case=self.root/'case';case.mkdir();self.pdf().rename(case/'Nguyen_Van_An.pdf');self.pdf('second.pdf').rename(case/'NGUYEN VAN AN.pdf')
        job=self.root/'job';e.prepare_case(case,job,'A'*64)
        with self.assertRaises(ValueError):e.export_case(job)
        result=e.export_case(job,approve_all=True);self.assertEqual(result['count'],2);self.assertEqual(len(set(result['outputs'])),2)
        self.assertTrue(all(Path(p).name.startswith('A'*64+'_F') for p in result['outputs']))
    def test_stream_watermark_preserves_underlying_text(self):
        src=self.pdf(watermark=True);job=self.root/'job';data=e.prepare(src,job)
        with fitz.open(job/'working_private.pdf') as d:self.assertIn('Ho Thi Minh Chau',d[0].get_text())
        out,qc=e.export(job,approve_all=True);self.assertTrue(out.exists());self.assertGreater(qc['watermarks_removed'],0);self.assertEqual(qc['watermarks_removed'],sum(p['watermark_streams_removed'] for p in qc['page_results']))
    def test_hash_stream_matches(self):
        p=self.root/'bytes';p.write_bytes(b'abc'*1000000);self.assertEqual(e.sha(p),hashlib.sha256(p.read_bytes()).hexdigest())

    def test_initial_white_gap_does_not_expand(self):
        d=fitz.open();p=d.new_page(width=500,height=200);p.insert_text((145,80),'Clinical')
        r=e.expand_rects_with_pixel_ink(p,[[20,65,100,85]],max_expand_pt=80)
        self.assertEqual(r,[[20,65,100,85]]);d.close()
    def test_unsafe_shared_watermark_stream_rejected(self):
        src=self.pdf(watermark=True)
        with fitz.open(src) as doc:
            doc[0].clean_contents();doc.save(self.root/'merged.pdf')
        job=self.root/'job';e.prepare(self.root/'merged.pdf',job)
        with self.assertRaisesRegex(ValueError,'UNSAFE_WATERMARK_REMOVAL'):e.export(job,approve_all=True)
    def test_watermark_removal_matches_clean_reference_pixels(self):
        src=self.pdf(watermark=True);clean=self.pdf('clean.pdf');job=self.root/'job';data=e.prepare(src,job)
        for q in data['pages'][0]['proposals']:
            if q['kind']!='WATERMARK_TEXT':q['selected']=False
        e.save_json(job/'review.json',data);out,_=e.export(job,approve_all=True)
        with fitz.open(out) as result,fitz.open(clean) as reference:
            # Same pixel grid: output is a lossless full-page render of the clean source.
            a=result[0].get_pixmap(dpi=200,alpha=False);b=reference[0].get_pixmap(dpi=200,alpha=False)
            self.assertEqual((a.width,a.height),(b.width,b.height));self.assertEqual(a.samples,b.samples)
    def test_watermark_deselect_preserves_stream(self):
        job=self.root/'job';data=e.prepare(self.pdf(watermark=True),job)
        for q in data['pages'][0]['proposals']:q['selected']=False
        e.save_json(job/'review.json',data);out,_=e.export(job,approve_all=True)
        with fitz.open(out) as result,fitz.open(job/'working_private.pdf') as ref:
            a=result[0].get_pixmap(dpi=200);b=ref[0].get_pixmap(dpi=200);self.assertEqual(a.samples,b.samples)
    def test_pointer_failure_keeps_old_generation(self):
        job=self.root/'job';e.prepare(self.pdf(),job);out,_=e.export(job,approve_all=True);old=(job/'last_export.json').read_bytes()
        original=e.save_json
        def fail(path,data):
            if Path(path).name=='last_export.json':raise OSError('pointer denied')
            return original(path,data)
        with patch.object(e,'save_json',side_effect=fail):
            with self.assertRaises(OSError):e.export(job)
        self.assertEqual((job/'last_export.json').read_bytes(),old);self.assertTrue(out.exists())
    def test_legacy_removed_streams_require_source_recheck(self):
        job=self.root/'job';data=e.prepare(self.pdf(),job);data['watermarks_removed']=[{'page':1}];e.save_json(job/'review.json',data)
        with self.assertRaisesRegex(ValueError,'SOURCE_RECHECK_REQUIRED'):e.export(job,approve_all=True)
    def test_audit_manual_region_updates_current_text(self):
        job=self.root/'job';data=e.prepare(self.pdf(),job)
        for q in data['pages'][0]['proposals']:q['selected']=False
        data['pages'][0]['manual_rects']=[[65,45,160,70]];e.generate_audit_markdown(job,data)
        raw=(job/'AUDIT_SUMMARY.md').read_text(encoding='utf8');self.assertNotIn('Ho ten: Nguyen Van An',raw)
    def test_rotated_crop_pages_use_display_geometry(self):
        for rotation in (0,90,180,270):
            src=self.root/f'rot{rotation}.pdf';d=fitz.open();p=d.new_page(width=600,height=800);p.insert_text((80,100),'Ho ten: Nguyen Van An');p.set_cropbox(fitz.Rect(20,20,580,780));p.set_rotation(rotation);expected=p.rect;d.save(src);d.close()
            job=self.root/f'job{rotation}';data=e.prepare(src,job);self.assertEqual((data['pages'][0]['width'],data['pages'][0]['height']),(expected.width,expected.height))
            out,_=e.export(job,approve_all=True)
            with fitz.open(out) as result:self.assertEqual(result[0].rect,expected)
    def test_mixed_page_ocr_finds_scanned_name(self):
        d=fitz.open();p=d.new_page(width=600,height=400);p.insert_text((50,80),'Ho ten: TRAN THI BAN',fontsize=16);pix=p.get_pixmap(dpi=200);d.close()
        src=self.root/'mixed.pdf';d=fitz.open();p=d.new_page(width=600,height=500);p.insert_text((20,20),'Header');p.insert_image(fitz.Rect(0,50,600,450),stream=pix.tobytes('png'));d.save(src);d.close()
        data=e.prepare(src,self.root/'mixedjob');self.assertTrue(data['pages'][0]['ocr_used']);self.assertTrue(any('TRAN THI BAN' in q['text'].upper() for q in data['pages'][0]['proposals']))
    def test_safe_watermark_does_not_hide_unsafe_second_stream(self):
        src=self.pdf(watermark=True)
        with fitz.open(src) as doc:
            p=doc[0];p.clean_contents();p.insert_text((450,500),'Tran Thi Mai_20260803161916',rotate=90);doc.save(self.root/'both.pdf')
        job=self.root/'job';data=e.prepare(self.root/'both.pdf',job)
        watermarks=[q for q in data['pages'][0]['proposals'] if q['kind']=='WATERMARK_TEXT']
        self.assertTrue(any(q['stream_xrefs'] for q in watermarks));self.assertTrue(any(not q['stream_xrefs'] for q in watermarks))
        with self.assertRaisesRegex(ValueError,'UNSAFE_WATERMARK_REMOVAL'):e.export(job,approve_all=True)
    def test_unscoped_graphics_state_watermark_is_not_safe(self):
        src=self.pdf(watermark=True)
        with fitz.open(src) as doc:
            page=doc[0];xref=page.get_contents()[-1];raw=doc.xref_stream(xref);raw=raw.strip();self.assertTrue(raw.startswith(b'q'));doc.update_stream(xref,raw[1:-1]);doc.save(self.root/'unscoped.pdf')
        job=self.root/'job';data=e.prepare(self.root/'unscoped.pdf',job)
        with self.assertRaisesRegex(ValueError,'UNSAFE_WATERMARK_REMOVAL'):e.export(job,approve_all=True)
    def test_image_object_removal_over_protected_ocr_is_rejected(self):
        d=fitz.open();p=d.new_page(width=400,height=400);pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,100,100),False);pix.clear_with(0);p.insert_image(fitz.Rect(50,50,150,150),stream=pix.tobytes('png'))
        review={'proposals':[{'kind':'IMAGE_REVIEW','selected':True,'clinical_overlap':False,'rects':[[50,50,150,150]]}],'manual_rects':[],'protected_rects':[[70,70,100,90]]}
        with self.assertRaisesRegex(ValueError,'Clinical overlap'):e.apply_review_to_page(p,review,1)
        d.close()
    def test_audit_masks_fallback_image_text_but_keeps_native_under_removed_image(self):
        text='native SECRET';chars=[(i,0,(10+i*6,30,16+i*6,42),ch) for i,ch in enumerate(text)]
        review={'proposals':[{'kind':'IMAGE_REVIEW','selected':True,'clinical_overlap':False,'rects':[[40,25,100,45]]}],'manual_rects':[]}
        self.assertNotIn('SECRET',e.build_review_markdown(text,chars,review,[[40,25,100,45]],len(text)))
        self.assertIn('SECRET',e.build_review_markdown(text,chars,review,[],len(text)))
    def test_small_raster_phone_strip_requires_ocr(self):
        d=fitz.open();p=d.new_page(width=120,height=25);p.insert_text((1,18),'SDT: 0912345678',fontsize=12);pix=p.get_pixmap(dpi=200);d.close()
        src=self.root/'strip.pdf';d=fitz.open();p=d.new_page(width=300,height=200);p.insert_text((20,30),'Header');p.insert_image(fitz.Rect(20,60,140,85),stream=pix.tobytes('png'));d.save(src);d.close()
        data=e.prepare(src,self.root/'stripjob');self.assertTrue(data['pages'][0]['ocr_used'])
        analysis=json.loads((self.root/'stripjob/analysis_private/1.json').read_text());self.assertIn('0912345678',analysis['text'])

    def test_recover_job_verifies_source_hash_and_preserves_old_job(self):
        source=self.pdf();old=self.root/'old';data=e.prepare(source,old);data['watermarks_removed']=[{'page':1}];e.save_json(old/'review.json',data);before=(old/'review.json').read_bytes()
        wrong=self.pdf('wrong.pdf')
        with wrong.open('ab') as f:f.write(b'changed')
        with self.assertRaisesRegex(ValueError,'Source hash'):e.recover_job(old,wrong,self.root/'bad')
        self.assertFalse((self.root/'bad').exists());self.assertEqual((old/'review.json').read_bytes(),before)
        recovered=e.recover_job(old,source,self.root/'recovered');self.assertFalse(any(p['reviewed'] for p in recovered['pages']));self.assertNotEqual(data['job_id'],recovered['job_id']);self.assertEqual((old/'review.json').read_bytes(),before)
    def test_audit_header_identifies_review_snapshot(self):
        job=self.root/'job';data=e.prepare(self.pdf(),job);raw=e.generate_audit_markdown(job,data).read_text(encoding='utf8')
        self.assertIn(data['job_id'],raw);self.assertIn(data['working_sha256'],raw);self.assertIn('revision',raw);self.assertIn('draft',raw)

    def test_ocr_settings_change_invalidates_analysis(self):
        job=self.root/'job';data=e.prepare(self.pdf(),job);path=job/'analysis_private/1.json';analysis=json.loads(path.read_text());analysis['ocr_settings_fingerprint']='old';e.save_json(path,analysis)
        with patch.object(e,'ocr_settings_fingerprint',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'OCR settings changed'):e.ensure_job(job)
    def test_legacy_analysis_rebuilt_without_autoapproval(self):
        job=self.root/'job';data=e.prepare(self.pdf(),job);data['pages'][0]['reviewed']=True;data.pop('job_id');e.save_json(job/'review.json',data);(job/'analysis_private/1.json').unlink()
        migrated=e.ensure_job(job);self.assertIn('job_id',migrated);self.assertFalse(migrated['pages'][0]['reviewed']);self.assertTrue((job/'analysis_private/1.json').exists())

    def test_rotated_audit_uses_display_masks(self):
        for rotation in (90,180,270):
            src=self.root/f'auditrot{rotation}.pdf';doc=fitz.open();p=doc.new_page();p.insert_text((50,80),'SECRET');p.set_rotation(rotation);doc.save(src);doc.close()
            job=self.root/f'ar{rotation}';data=e.prepare(src,job)
            analysis=json.loads((job/'analysis_private/1.json').read_text());data['pages'][0]['proposals']=[];data['pages'][0]['manual_rects']=e.span_rects(analysis['chars'],0,6)
            raw=e.generate_audit_markdown(job,data).read_text(encoding='utf8');self.assertNotIn('SECRET',raw)

    def test_case_xml_parse_once(self):
        from hmu_recognizers import build_case_xml_index,extract_case_seeds
        case=self.root/'1234567890_NGUYEN_VAN_AN';case.mkdir();xml=case/'record.xml';xml.write_text('<ROOT><HO_TEN>NGUYEN VAN AN</HO_TEN></ROOT>')
        index=build_case_xml_index(case)
        with patch('xml.etree.ElementTree.fromstring',side_effect=AssertionError('parsed again')):
            for i in range(50):self.assertIn('NGUYEN VAN AN',extract_case_seeds(case,xml_index=index)['PATIENT_NAME'])

    def test_watermark_stream_shared_with_unselected_page_is_not_mutated(self):
        doc=fitz.open();first=doc.new_page(width=600,height=800)
        first.insert_text((200,500),'Ho Thi Minh Chau_20260803161916',rotate=90)
        shared=first.get_contents()[-1]
        second=doc.new_page(width=600,height=800)
        second.insert_text((30,50),'Clinical C34')
        own=second.get_contents()[0]
        doc.xref_set_key(second.xref,'Contents',f'[{own} 0 R {shared} 0 R]')
        before=doc[1].get_text()
        rect=e.rotated_watermark_rects(doc[0])[0][1]
        review={'proposals':[{'kind':'WATERMARK_TEXT','selected':True,'clinical_overlap':False,'rects':[rect],'stream_xrefs':[shared]}],'manual_rects':[]}
        e.apply_review_to_page(doc[0],review,1)
        self.assertNotIn('Ho Thi Minh Chau',doc[0].get_text())
        self.assertEqual(doc[1].get_text(),before)
        doc.close()

    def test_private_analysis_json_is_compact_and_round_trips(self):
        directory=self.root/'analysis_private';directory.mkdir()
        payload={'text':'Clinical C34','chars':[[0,0,[1.0,2.0,3.0,4.0],'C']]}
        path=directory/'1.json';e.save_json(path,payload)
        self.assertEqual(json.loads(path.read_text(encoding='utf8')),payload)
        self.assertNotIn('\n',path.read_text(encoding='utf8'))

    def test_native_text_extraction_avoids_image_materialization(self):
        doc=fitz.open();page=doc.new_page(width=500,height=300)
        page.insert_text((30,50),'Clinical C34 / Nguyen Van An')
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,80,50),False);pix.clear_with(180)
        page.insert_image(fitz.Rect(30,100,190,200),stream=pix.tobytes('png'))
        reference=page.get_text('text',sort=False)
        calls=[];original=fitz.Page.get_text
        def capture(p,*args,**kwargs):
            calls.append((args,kwargs))
            return original(p,*args,**kwargs)
        with patch.object(fitz.Page,'get_text',capture):text,chars=e.char_map(page)
        self.assertEqual(text,reference)
        self.assertTrue(all(text[offset]==ch for offset,_,_,ch in chars))
        self.assertFalse(any(args and args[0]=='rawdict' and not kwargs.get('textpage') and kwargs.get('flags',fitz.TEXTFLAGS_RAWDICT)&fitz.TEXT_PRESERVE_IMAGES for args,kwargs in calls))
        doc.close()

    def test_prepare_reuses_native_char_map_per_page(self):
        with patch.object(e,'char_map',wraps=e.char_map) as capture:
            e.prepare(self.pdf(),self.root/'job')
        self.assertEqual(capture.call_count,1)

    def test_diagonal_watermark_over_clinical_ink_matches_clean_pixels(self):
        source=self.root/'diagonal.pdf';clean=self.root/'reference.pdf'
        for path,mark in ((source,True),(clean,False)):
            doc=fitz.open();page=doc.new_page(width=600,height=800)
            page.insert_text((30,120),'Clinical C34 / Glucose 5.2',fontsize=12)
            if mark:
                origin=fitz.Point(20,250)
                page.insert_text(origin,'Ho Thi Minh Chau_20260803161916',fontsize=12,morph=(origin,fitz.Matrix(45)))
            doc.save(path);doc.close()
        job=self.root/'job';data=e.prepare(source,job)
        marks=[q for q in data['pages'][0]['proposals'] if q['kind']=='WATERMARK_TEXT']
        self.assertTrue(marks)
        for q in data['pages'][0]['proposals']:q['selected']=q['kind']=='WATERMARK_TEXT'
        e.save_json(job/'review.json',data);out,_=e.export(job,approve_all=True)
        with fitz.open(out) as result,fitz.open(clean) as reference:
            self.assertEqual(result[0].get_pixmap(dpi=200).samples,reference[0].get_pixmap(dpi=200).samples)

    def test_watermark_before_graphics_and_image_preserves_pixels(self):
        docs=[]
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,80,50),False);pix.clear_with(140)
        for mark in (True,False):
            doc=fitz.open();page=doc.new_page(width=600,height=800)
            if mark:page.insert_text((200,500),'Ho Thi Minh Chau_20260803161916',rotate=90)
            page.insert_text((30,120),'Clinical C34 / Glucose 5.2')
            page.draw_line((30,140),(250,140),color=(0,0,0))
            page.insert_image(fitz.Rect(30,200,110,250),stream=pix.tobytes('png'))
            docs.append(doc)
        actual,reference=docs
        rect=e.rotated_watermark_rects(actual[0])[0][1]
        refs=e.watermark_streams(actual[0],rect)
        self.assertTrue(refs)
        review={'proposals':[{'kind':'WATERMARK_TEXT','selected':True,'clinical_overlap':False,'rects':[rect],'stream_xrefs':refs}],'manual_rects':[]}
        e.apply_review_to_page(actual[0],review,1)
        self.assertEqual(actual[0].get_pixmap(dpi=150).samples,reference[0].get_pixmap(dpi=150).samples)
        actual.close();reference.close()

    def test_watermark_proof_does_not_parse_graphics_only_streams(self):
        doc=fitz.open();page=doc.new_page(width=600,height=800)
        page.insert_text((200,500),'Ho Thi Minh Chau_20260803161916',rotate=90)
        for i in range(40):page.draw_line((30+i*5,140),(33+i*5,145),color=(0,0,0))
        with patch.object(e,'ContentStream',wraps=e.ContentStream) as parsed:
            self.assertTrue(e.watermark_streams(page))
        self.assertEqual(parsed.call_count,1)
        doc.close()

    def test_watermark_proof_only_snapshots_semantics_when_marker_changes(self):
        doc=fitz.open();page=doc.new_page(width=600,height=800)
        page.insert_text((200,500),'Ho Thi Minh Chau_20260803161916',rotate=90)
        for i in range(8):page.insert_text((30,50+i*20),'Clinical result '+str(i))
        original=fitz.Page.get_drawings;calls=[]
        def capture(page,*args,**kwargs):
            calls.append(1)
            return original(page,*args,**kwargs)
        with patch.object(fitz.Page,'get_drawings',capture):self.assertTrue(e.watermark_streams(page))
        self.assertEqual(len(calls),2)
        doc.close()

if __name__=='__main__':unittest.main()
