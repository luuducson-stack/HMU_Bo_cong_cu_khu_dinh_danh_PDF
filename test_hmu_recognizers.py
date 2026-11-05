import unittest, unicodedata, pathlib
from hmu_recognizers import analyze_hmu_text, analyze_hmu_document, extract_case_seeds

class RecognizerTests(unittest.TestCase):
    def test_partial_staff_aliases_do_not_turn_clinical_phrases_into_names(self):
        seeds={'HEALTHCARE_STAFF_NAME':['Nguyen Van Hai','Le Kim Canh','Tran Ngoc Linh','Le Yeu Cau']}
        texts=['Ho van hai la: Khong. Hep van hai la: Khong.',
               'Vat tu y te: Kim canh budm; dung mot lan kim canh btr&m; kim canh bu•am.',
               'Su dung thuoc, vat tu y te va dich vu theo you cau',
               '(Viet bang chi: Chin trieu met tram nam mu•ai lam nghin sciu tram linh sciu dong)']
        findings,_=analyze_hmu_document(texts,external_seeds=seeds)
        for text,fs in zip(texts,findings):
            with self.subTest(text=text):self.assertFalse(any(f.rule.startswith(('memorized_staff_mid_given','memorized_staff_sur_given')) for f in fs),fs)

    def test_partial_staff_name_at_person_label_is_kept_next_to_clinical_terms(self):
        text='Bac si:\nKim Canh\nVat tu: kim canh buom'
        fs,_=analyze_hmu_document([text],external_seeds={'HEALTHCARE_STAFF_NAME':['Le Kim Canh']})
        self.assertTrue(any(f.start==text.index('Kim Canh') and f.review_status!='CONTEXT_REQUIRED' for f in fs[0]))
        self.assertFalse(any(f.start==text.index('kim canh') and f.entity_type=='HEALTHCARE_STAFF_NAME' for f in fs[0]))

    def test_person_label_overrides_identical_valve_words(self):
        text='Bac si:\nVan Hai La\nSieu am: van hai la'
        fs,_=analyze_hmu_document([text],external_seeds={'HEALTHCARE_STAFF_NAME':['Nguyen Van Hai']})
        self.assertTrue(any(f.start==text.index('Van Hai') and f.review_status!='CONTEXT_REQUIRED' for f in fs[0]))
        self.assertFalse(any(f.start==text.index('van hai') and f.entity_type=='HEALTHCARE_STAFF_NAME' for f in fs[0]))

    def test_staff_alias_followed_by_narrative_la_is_not_a_valve(self):
        for text in ('Người thực hiện: Văn Hải\nLà người trực tiếp lấy mẫu',
                     'Người thực hiện: Văn Hải là người trực tiếp lấy mẫu',
                     'Người lấy bệnh phẩm: Văn Hải là điều dưỡng trực',
                     'Điều dưỡng phụ trách: Văn Hải là người trực tiếp lấy mẫu'):
            with self.subTest(text=text):
                fs,_=analyze_hmu_document([text],external_seeds={'HEALTHCARE_STAFF_NAME':['Nguyễn Văn Hải']})
                self.assertTrue(any(f.text=='Văn Hải' for f in fs[0]),fs[0])

    def test_card_label_stub_is_not_an_address_but_real_address_still_is(self):
        self.assertFalse(any(f.entity_type=='ADDRESS_VN' for f in analyze_hmu_text('Dia chi: S6 thé BHVT: 2383812345678')))
        self.assertTrue(any(f.entity_type=='ADDRESS_VN' and 'Ngo The Chung' in f.text for f in analyze_hmu_text('Dia chi: So 6 Ngo The Chung Ha Noi')))

    def test_insurance_missing_prefix_requires_card_label_and_does_not_seed_record_id(self):
        text='S6 thé BHVT: 2 38 38 12345678\nMa HS: 2383812345678'
        fs,known=analyze_hmu_document([text])
        cards=[f for f in fs[0] if f.entity_type=='HEALTH_INSURANCE_ID']
        self.assertEqual(len(cards),1);self.assertEqual(cards[0].text,'2 38 38 12345678')
        self.assertNotIn('2383812345678',known.get('HEALTH_INSURANCE_ID',[]))
        self.assertFalse(any(f.entity_type=='HEALTH_INSURANCE_ID' for f in analyze_hmu_text('Ma HS: 2383812345678\nBHYT thanh toan: 2383812345678\nSo the BHYT: Gia tri den 01/04/2026')))

    def test_explicit_chau_relative_name_is_not_dropped(self):
        self.assertTrue(any(f.entity_type=='RELATIVE_NAME' and f.text=='LE VAN BINH' for f in analyze_hmu_text('Chåu: LE VAN BINH(Ngon cai trai)')))

    def test_consent_identity_keeps_offsets_after_nonbreaking_space(self):
        text='Lå nguöi bénh/ doi diGn gia dinh nguöi bénh.•\u00a0TRAN VAN AN'
        f=next(f for f in analyze_hmu_text(text) if f.rule=='explicit_consent_identity_field')
        self.assertEqual(text[f.start:f.end],f.text)

    def test_titled_surname_can_contain_rn_ocr_digraph_and_one_missing_letter(self):
        self.assertTrue(any(f.entity_type=='HEALTHCARE_STAFF_NAME' and f.text=='Ph.rn Thi Quang' for f in analyze_hmu_text('B.SC • . Ph.rn Thi Quang')))

    def test_ocr_patient_label_with_va_and_consent_identity(self):
        for text in ('Ho va bénh nhån: TRAN VAN AN Tuoi: 60','Lå nguöi bénh/ doi diGn gia dinh nguöi bénh.• TRAN VAN AN\nTuoi: 60'):
            self.assertTrue(any(f.text=='TRAN VAN AN' and f.review_status!='CONTEXT_REQUIRED' for f in analyze_hmu_text(text)))

    def test_spaced_ocr_doctor_title_is_not_part_of_name(self):
        for title in ('BSC KII.','BSC','B.SC • .'):
            fs=analyze_hmu_text(title+' Tran Van An')
            self.assertTrue(any(f.entity_type=='HEALTHCARE_STAFF_NAME' and f.text=='Tran Van An' for f in fs))

    def test_known_person_before_fingerprint_descriptor_has_identity_context(self):
        from hmu_recognizers import _person_name_context
        text="TRAN THI BINH(Ngön cåi tråi)"
        self.assertTrue(_person_name_context(text,0,'TRAN THI BINH'))
        self.assertFalse(_person_name_context('kim canh trong truyen dich',0,'kim canh'))

    def test_ocr_birth_year_labels_do_not_need_a_preceding_name(self):
        fs=analyze_hmu_text('Tén töi lå: TRAN VAN AN Sinh näm: 1964\nNäm sinh: 1935\nDieu tri nam 2026')
        self.assertEqual({f.text for f in fs if f.entity_type=='YEAR_OF_BIRTH'},{'1964','1935'})

    def test_doctor_name_keeps_words_after_embedded_ocr_punctuation(self):
        for value in ('Tran T! Kim Binh','Ph*m Van An'):
            fs=analyze_hmu_text('BSCKI. '+value)
            self.assertTrue(any(f.entity_type=='HEALTHCARE_STAFF_NAME' and f.text==value for f in fs))

    def test_birth_year_after_identity_is_detected_without_masking_treatment_year(self):
        from hmu_recognizers import analyze_hmu_text
        fs=analyze_hmu_text('TRAN VAN AN Sinh näm: 1964\nDa dung khang sinh nam 2026')
        self.assertTrue(any(f.entity_type=='YEAR_OF_BIRTH' and f.text=='1964' for f in fs))
        self.assertFalse(any(f.entity_type=='YEAR_OF_BIRTH' and f.text=='2026' for f in fs))
    def test_explicit_doctor_title_accepts_one_ocr_error_in_surname(self):
        from hmu_recognizers import analyze_hmu_text
        fs=analyze_hmu_text('BSCKII. Lim Quang Hung')
        self.assertTrue(any(f.entity_type=='HEALTHCARE_STAFF_NAME' and f.text=='Lim Quang Hung' and f.review_status!='CONTEXT_REQUIRED' for f in fs))
        self.assertFalse(any(f.entity_type=='HEALTHCARE_STAFF_NAME' for f in analyze_hmu_text('BSCKII. Chup X Quang')))
    def test_name_immediately_before_birth_field_and_explicit_relative_label(self):
        from hmu_recognizers import analyze_hmu_text
        text='01/04/2026 TRAN VAN AN Sinh nam: 1964\nCon trai: LE VAN BINH (Ngon cai trai)'
        fs=analyze_hmu_text(text)
        self.assertTrue(any(f.text=='TRAN VAN AN' and f.review_status!='CONTEXT_REQUIRED' for f in fs))
        self.assertTrue(any(f.text=='LE VAN BINH' and f.review_status!='CONTEXT_REQUIRED' for f in fs))
        self.assertFalse(any(f.entity_type=='PERSON_NAME' and f.review_status!='CONTEXT_REQUIRED' for f in analyze_hmu_text('HEN PHE QUAN Sinh nam: 1964')))
    def test_lab_operator_inline_after_time_is_confirmed(self):
        from hmu_recognizers import analyze_hmu_text
        fs=analyze_hmu_text('Thoi gian duyet KQ: 01/04/2026 08:50 Nguöi XN: Vu Van An')
        self.assertTrue(any(f.entity_type=='HEALTHCARE_STAFF_NAME' and f.text=='Vu Van An' and f.review_status!='CONTEXT_REQUIRED' for f in fs))

    def test_patient_label_without_ten_is_confirmed(self):
        from hmu_recognizers import analyze_hmu_text
        self.assertTrue(any(f.entity_type=='PATIENT_NAME' and f.text=='TRAN THI BINH' for f in analyze_hmu_text('Ho bénh nhån: TRAN THI BINH Tuoi: 60')))
    def test_address_part_stops_before_age_and_clinical_fields_after_long_value(self):
        from hmu_recognizers import analyze_hmu_text
        text='Xa, phuong: Phuong Thanh Xuan Trung Ha Noi Tuoi: 60 Chan doan: Viem phoi'
        found=[f.text for f in analyze_hmu_text(text) if f.entity_type=='ADDRESS_VN']
        self.assertTrue(found)
        self.assertFalse(any('Tuoi' in f or 'Chan doan' in f for f in found))
    def test_ocr_patient_label_comma_and_ton(self):
        from hmu_recognizers import analyze_hmu_text
        fs=analyze_hmu_text('HQ ton ngu,öi bénh: TRAN THI BINH Tuöi: 60')
        self.assertTrue(any(f.entity_type=='PATIENT_NAME' and f.text=='TRAN THI BINH' and f.review_status!='CONTEXT_REQUIRED' for f in fs))
    def test_cover_address_values_do_not_include_printed_part_labels(self):
        from hmu_recognizers import analyze_hmu_text
        text='7-Dia chi: Sd nha Thon, ph6 Thon 12 Xa, phuong: Phuong An Binh\nTinh- ffanh ph6 Tinh Nam Dinh'
        found=[f.text for f in analyze_hmu_text(text) if f.entity_type=='ADDRESS_VN']
        self.assertTrue(any('Thon 12' in f for f in found))
        self.assertTrue(any('Tinh Nam Dinh' in f for f in found))
        self.assertFalse(any('Sd nha' in f or 'Xa, phuong' in f or 'ffanh ph6' in f for f in found))

    def test_ocr_lab_operator_label_is_a_confirmed_name(self):
        from hmu_recognizers import analyze_hmu_text
        found=analyze_hmu_text('Nguöi XN: Vu Van An')
        self.assertTrue(any(f.text=='Vu Van An' and f.entity_type=='HEALTHCARE_STAFF_NAME' and f.review_status!='CONTEXT_REQUIRED' for f in found))
    def test_ocr_patient_label_with_question_mark_is_confirmed(self):
        from hmu_recognizers import analyze_hmu_document
        texts=['HQ ten nguö•i b?nh: TRAN THI BINH Tuöi: 63 Nam/Nü: Nü']
        found,_=analyze_hmu_document(texts)
        self.assertTrue(any(f.entity_type=='PATIENT_NAME' and f.text=='TRAN THI BINH' and f.review_status!='CONTEXT_REQUIRED' for f in found[0]))

    def test_ocr_doctor_titles_split_names_before_next_column_title(self):
        from hmu_recognizers import analyze_hmu_text
        found=analyze_hmu_text('B.SCKIL Tran Van Minh CS. Le Thi Hoa')
        names=[f.text for f in found if f.entity_type=='HEALTHCARE_STAFF_NAME' and f.review_status!='CONTEXT_REQUIRED']
        self.assertIn('Tran Van Minh',names);self.assertIn('Le Thi Hoa',names)
        self.assertFalse(any('CS.' in n or n.startswith('L ') for n in names))

    def test_request_heading_cannot_seed_staff_name(self):
        from hmu_recognizers import _valid
        self.assertFalse(_valid('HEALTHCARE_STAFF_NAME','Yéu cåu'))
    def test_colonless_numbered_patient_name_stops_before_birth_field(self):
        text='1 .HQ tén TRAN THI BINH 2.Sinh ngay: 01/02/1952 Tuoi: 74'
        fs=analyze_hmu_text(text)
        self.assertTrue(any(f.entity_type=='PATIENT_NAME' and f.text=='TRAN THI BINH' and f.review_status!='CONTEXT_REQUIRED' for f in fs))

    def test_relative_name_and_explicit_address_are_separate_findings(self):
        text='Họ tên, địa chỉ người nhà: Con Trần Văn Minh D/C: 12 Phố Mới, Phường An Bình'
        fs=analyze_hmu_text(text)
        self.assertTrue(any(f.entity_type=='RELATIVE_NAME' and f.text=='Con Trần Văn Minh' for f in fs))
        self.assertTrue(any(f.entity_type=='ADDRESS_VN' and f.text=='12 Phố Mới, Phường An Bình' for f in fs))
        self.assertFalse(any('D/C' in f.text for f in fs if f.entity_type=='RELATIVE_NAME'))

    def test_patient_label_without_ho_confirms_name_before_age(self):
        text='- ten benh nhan: TRAN THI BINH Tuoi: 74 tuoi Gioi tinh: Nu'
        fs=analyze_hmu_text(text)
        self.assertTrue(any(f.entity_type=='PATIENT_NAME' and f.text=='TRAN THI BINH' and f.review_status!='CONTEXT_REQUIRED' for f in fs))
        self.assertFalse(any('Tuoi' in f.text for f in fs if 'NAME' in f.entity_type))

    def test_staff_name_stops_before_ocr_secretary_label(self):
        text='- Chu toa: BSCKII. TRAN VAN MINH Thu Icy: BS. LE THI HOA'
        fs=analyze_hmu_text(text)
        names=[f.text for f in fs if f.entity_type=='HEALTHCARE_STAFF_NAME' and f.review_status!='CONTEXT_REQUIRED']
        self.assertIn('TRAN VAN MINH',names)
        self.assertIn('LE THI HOA',names)
        self.assertFalse(any('Thu Icy' in n for n in names))

    def test_ocr_signature_name_label_without_colon_inside_table_row(self):
        fs=analyze_hmu_text('- Sieu am 2 HQ tan Luu Van Minh')
        self.assertTrue(any(f.text=='Luu Van Minh' and 'NAME' in f.entity_type and f.review_status!='CONTEXT_REQUIRED' for f in fs))
        negative=analyze_hmu_text('Ho tan mau do viem phoi; dieu tri khang sinh')
        self.assertFalse(any(f.review_status!='CONTEXT_REQUIRED' and 'NAME' in f.entity_type for f in negative))

    def test_inline_verbose_birth_label_keeps_name_and_clinical_dates_separate(self):
        text='(1) Họ tên người bệnh: NGUYỄN VĂN AN Ngåy, thång, näm sinh: 14/02/1984 Giới tính: Nam\nGiá trị từ 01/01/2026 đến 31/12/2028\nNgày điều trị: 20/03/2026'
        fs=analyze_hmu_text(text)
        self.assertIn('NGUYỄN VĂN AN',{f.text for f in fs if f.entity_type=='PATIENT_NAME'})
        self.assertEqual({f.text for f in fs if f.entity_type=='DATE_OF_BIRTH'},{'14/02/1984'})
        self.check_offsets(text,fs)

    def test_inline_short_birth_label(self):
        text='BỆNH VIỆN MẪU PHIẾU CÔNG KHAI Ngåy sinh: 14/02/1984 Giới tính: Nam'
        fs=analyze_hmu_text(text)
        self.assertEqual({f.text for f in fs if f.entity_type=='DATE_OF_BIRTH'},{'14/02/1984'})
        self.check_offsets(text,fs)

    def test_noisy_current_address_stops_at_next_numbered_field(self):
        text='(2) Dia chi hi$n toi; Thôn 7, Phường Minh An, Tỉnh Bắc Ninh (3) Mä khu (K1, K2, K3):'
        fs=analyze_hmu_text(text)
        self.assertIn('Thôn 7, Phường Minh An, Tỉnh Bắc Ninh',{f.text for f in fs if f.entity_type=='ADDRESS_VN'})
        self.assertFalse(any('Mä khu' in f.text for f in fs if f.entity_type=='ADDRESS_VN'))
        self.check_offsets(text,fs)

    def test_address_label_sequences_are_not_values(self):
        from hmu_recognizers import _valid
        for value in ('Sd nhå Thön, ph6 Xä, phüöng:','Xä, phüöng','Số nhà/Thôn, phố Xã, phường','Địa chỉ','Địa chỉ hiện tại'):
            self.assertFalse(_valid('ADDRESS_VN',value),value)
        for value in ('Thôn 7, Phường Minh An','Phường Minh An','Xã Tân Hòa'):
            self.assertTrue(_valid('ADDRESS_VN',value),value)

    def check_offsets(self, text, fs):
        for f in fs:
            self.assertEqual(text[f.start:f.end], f.text)

    def test_bhyt_split_exact(self):
        t = 'Số thẻ BHYT\nCB\n2\n24\n2421370238\n27010'
        fs = analyze_hmu_text(t)
        bh = [f for f in fs if f.entity_type == 'HEALTH_INSURANCE_ID']
        self.assertEqual(len(bh), 1)
        self.assertEqual(bh[0].text, 'CB\n2\n24\n2421370238')
        self.check_offsets(t, fs)

    def test_original_offsets_unicode_newlines(self):
        t = unicodedata.normalize('NFD', 'Họ tên: Nguyễn Văn An\r\nMã hồ sơ: 1234567890')
        fs = analyze_hmu_text(t)
        self.assertTrue(fs)
        self.check_offsets(t, fs)
        pages, _ = analyze_hmu_document([t, t])
        self.check_offsets(t, pages[1])

    def test_titles_and_short_names(self):
        t = 'ThS.BSNT Nguyễn Văn Minh\nPGS Huy - BS Mạnh.\nBSCKII. Nguyễn Văn Thuyền\nC.N. Dương Thị Phương\nBS CK UB\nBÁC SĨ KHÁM BỆNH'
        fs = analyze_hmu_text(t)
        vals = {f.text for f in fs}
        self.assertTrue({'Nguyễn Văn Minh', 'Huy', 'Mạnh', 'Nguyễn Văn Thuyền', 'Dương Thị Phương'} <= vals)
        self.assertFalse({'CK UB', 'KHÁM BỆNH'} & vals)
        self.check_offsets(t, fs)

    def test_signature_heading_doctor_names(self):
        t = (
            'Giám đốc bệnh viện\nLê Văn Lâm\n'
            'Trưởng khoa\nLÊ TIẾN\n'
            'Trưởng khoa Xét Nghiệm/ Người được ủy quyền duyệt KQ\nBùi Ngọc Hoàng\n'
            'Người kí: Lê Tiến\n'
            'Ký số bởi: LÊ HOÀN\n'
        )
        fs = analyze_hmu_text(t)
        self.check_offsets(t, fs)
        staff = {f.text for f in fs if f.entity_type in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME_UNCLASSIFIED'}}
        self.assertTrue({'Lê Văn Lâm', 'LÊ TIẾN', 'Bùi Ngọc Hoàng', 'Lê Tiến', 'LÊ HOÀN'} <= staff)

    def test_watermark_not_treated_as_patient_name(self):
        p1 = 'Hồ Thị Minh Châu_20260803161916\n1. Họ và tên (In hoa):\nCAO THỊ SƯƠNG\nHồ Thị Minh Châu_20260803161916'
        pages, known = analyze_hmu_document([p1])
        self.assertEqual(known.get('PATIENT_NAME'), ['CAO THỊ SƯƠNG'])
        wm = [f for f in pages[0] if f.entity_type == 'WATERMARK_TEXT']
        self.assertEqual(len(wm), 2)

    def test_staff_propagation_word_boundary(self):
        pages, _ = analyze_hmu_document(['Người in: Nguyễn Văn Minh', 'Nguyễn Văn Minh; XNguyễn Văn MinhY'])
        self.assertEqual(sum(f.text == 'Nguyễn Văn Minh' for f in pages[1]), 1)

    def test_clinical_and_id_preservation(self):
        t = (
            'BỆNH VIỆN ĐẠI HỌC Y HÀ NỘI\n'
            'Số lưu trữ: BA260608783\n'
            'Mã y tế: 45/010/26/025448\n'
            'Mã người bệnh: 1234567890\n'
            'Mã hồ sơ: 2603040231\n'
            'Tuổi: 68 tuổi\nGiới tính: Nữ\n'
            'Chẩn đoán C34 C71.9 D38.1\npH 7.4; Creatinin 95 µmol/L; Ivermectin 3mg\nNgày điều trị: 09/03/2026'
        )
        self.assertEqual([(f.entity_type, f.text) for f in analyze_hmu_text(t)], [('PATIENT_AGE', '68')])

    def test_dob_conflict_not_dropped(self):
        pages, _ = analyze_hmu_document(['Năm sinh: 1960\nNgày sinh: 01/02/1961'])
        dob = [f for f in pages[0] if f.entity_type == 'DATE_OF_BIRTH']
        self.assertEqual(len(dob), 1)
        self.assertIn('CONFLICT', dob[0].rule)

    def test_no_cross_field(self):
        self.assertEqual(analyze_hmu_text('Họ tên:\nGiới tính: Nam\nĐịa chỉ:\nPHIẾU KHÁM CHUYÊN KHOA'), [])

    def test_unlabelled_name_candidate_and_no_fixed_case_names(self):
        fs = analyze_hmu_text('ĐỖ VĂN HẢI')
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].entity_type, 'PERSON_NAME_UNCLASSIFIED')
        self.assertEqual(fs[0].review_status, 'CONTEXT_REQUIRED')

    def test_patient_not_duplicated_as_staff(self):
        pages, _ = analyze_hmu_document(['Họ tên:\nNGUYỄN VĂN AN', 'NGUYỄN VĂN AN'])
        self.assertEqual(len(pages[1]), 1)
        self.assertEqual(pages[1][0].entity_type, 'PATIENT_NAME')

    def test_administrative_fields_and_ocr_variants(self):
        t = (
            'Mã người bệnh: 1234567890\nMã hồ sơ: 2234567890\n'
            'Họ tên: Nguyễn Văn An\nNgày sinh: 01/02/1960\n'
            'CCCD: 012345678901\nĐiện thoại người bệnh: 0901 234 567\n'
            'Điện thoại số: 0865414324\n'
            'Họ tên người nhà: Nguyễn Thị Mai\n'
            '11.Họ tên, địa chỉ người nhà khi cần báo tin: con: phạm văn huy-quảng nhân\n'
            'Địa chỉ: Phường Minh Khai, Hà Nội\n'
            'Xã, phường: Xã Quảng Ninh\n'
            'Tỉnh, thành phố: Tỉnh Thanh Hóa\n'
            'Bác sỹ chỉ định: Trần Văn Bình\nNgười lấy mẫu: Phạm Thị Hoa\n'
        )
        fs = analyze_hmu_text(t)
        self.check_offsets(t, fs)
        types = {f.entity_type for f in fs}
        self.assertTrue({
            'PATIENT_NAME', 'DATE_OF_BIRTH', 'NATIONAL_ID', 'PHONE_NUMBER_VN',
            'RELATIVE_NAME', 'ADDRESS_VN', 'HEALTHCARE_STAFF_NAME'
        } <= types)
        self.assertFalse({'PATIENT_ID', 'MEDICAL_RECORD_ID'} & types)
        texts = {f.text for f in fs}
        self.assertIn('0865414324', texts)
        self.assertIn('Xã Quảng Ninh', texts)
        self.assertIn('Tỉnh Thanh Hóa', texts)
        self.assertTrue(any('phạm văn huy' in x for x in texts))

    def test_extract_case_seeds_from_real_database(self):
        bvqt_case = pathlib.Path(r'D:\Workspaces\Database (Test-Case1)\3.BVQT\HH\pdf\2600012287 TRẦN THỊ BẢN\2600012287 TRẦN THỊ BẢN.pdf')
        if not bvqt_case.exists():
            self.skipTest('Private hospital fixture is not installed on this machine')
        if bvqt_case.exists():
            seeds = extract_case_seeds(bvqt_case)
            self.assertIn('TRẦN THỊ BẢN', seeds.get('PATIENT_NAME', []))
            self.assertIn('10/10/1958', seeds.get('DATE_OF_BIRTH', []))
            self.assertIn('1958', seeds.get('YEAR_OF_BIRTH', []))
            self.assertTrue(any('Quảng Ninh' in a for a in seeds.get('ADDRESS_VN', [])))
            self.assertIn('Phạm Bá Quế', seeds.get('HEALTHCARE_STAFF_NAME', []))

    def test_ocr_degraded_ho_va_ten_and_memorized_token_propagation(self):
        pages = [
            # Page 1: Scanned cover sheet with OCR noise on header, "I.Hovatén fin hoa):", and merged/OCR-corrupted patient name
            'TRUONG DS I Y NOI BENH AN NOI MS: 01/BV-01\n'
            'I.Hovatén fin hoa): TRINHVÅNHVdNG 2. Sinh ngay:\n'
            'Trang I\n',
            # Page 2: Standard OCR page with spaced patient name
            'I.Ho tén: TRINH VAN HUONG 2.Sinh ngåy: 10 03 1955\n',
            # Page 3: X-ray page with OCR-corrupted H->II and missing "nguời" in label
            'HQ ten bénh: TRINH VAN IIUÖNG Tuöi: 71 tuöi Nam/nü: Nam\n',
            # Page 4: Cost sheet with "(1) benh:" and patient signature "*f1UöNG"
            '(1) benh: TRINH VAN HUONG Ngåy, thång , sinh: 10/03/1955\n'
            'xÅc MIAN cÜA NGtCÖ1 BENH\n'
            '*f1UöNG\n',
        ]
        doc_findings, known = analyze_hmu_document(pages)
        # 1. Verify no false positive on hospital header "TRUONG DS I Y NOI BENH AN NOI MS" or "Trang I"
        p1_texts = {f.text for f in doc_findings[0]}
        self.assertNotIn('I Y NOI BENH AN NOI MS', p1_texts)
        self.assertNotIn('Trang I', p1_texts)
        # 2. Verify "TRINHVÅNHVdNG" on Page 1 is caught as PATIENT_NAME
        p1_patients = [f.text for f in doc_findings[0] if f.entity_type == 'PATIENT_NAME']
        self.assertIn('TRINHVÅNHVdNG', p1_patients)
        # 3. Verify "TRINH VAN IIUÖNG" on Page 3 is caught as PATIENT_NAME
        p3_patients = [f.text for f in doc_findings[2] if f.entity_type == 'PATIENT_NAME']
        self.assertIn('TRINH VAN IIUÖNG', p3_patients)
        # 4. Verify "(1) benh: TRINH VAN HUONG" and "*f1UöNG" on Page 4 are caught
        p4_patients = [f.text for f in doc_findings[3] if f.entity_type == 'PATIENT_NAME']
        self.assertIn('TRINH VAN HUONG', p4_patients)
        self.assertTrue(any('f1UöNG' in t for t in p4_patients))

    def test_doctor_and_nurse_wrapped_or_ocr_corrupted_names(self):
        pages = [
            # Page 1 establishes known staff names:
            'Bác sĩ điều trị: BSCKI. Đồng Mạnh Cường\n'
            'Người làm XN: CN. Nguyễn Thị Ngọc\n'
            'Điều dưỡng thực hiện: Đào Thị Thắm\n'
            'Người lập phiếu: Nguyễn Thị Hoài\n',
            # Page 2 has OCR-corrupted and line-wrapped occurrences of these staff names:
            'BSCKI. Döng Mqnh Cuöng\n'
            'BSCKI. Döng\nManh Cubng\n'
            'WSCKI. Daug Cuong\n'
            'Nguyén Thi\nN gqc\n'
            'Nguye\nn Thi\nHOåi\n'
            'Dåo\nThäm\n'
            'Dinh luqng CRP 3,9 0-10 mg/L\n'
            'Dinh Jurong CRP\n',
        ]
        doc_findings, known = analyze_hmu_document(pages)
        p2_staff = [f.text for f in doc_findings[1] if f.entity_type in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME_UNCLASSIFIED'}]
        joined = ' | '.join(p2_staff)
        self.assertIn('Döng Mqnh Cuöng', joined)
        self.assertIn('Manh Cubng', joined)
        self.assertIn('Daug Cuong', joined)
        self.assertIn('N gqc', joined)
        self.assertIn('HOåi', joined)
        self.assertIn('Thäm', joined, f"KNOWN={known}, P1={[f.text for f in doc_findings[0]]}, P2={p2_staff}")
        # Ensure clinical lab line "Dinh Jurong CRP" is never misclassified as a person name
        self.assertFalse(any('CRP' in t for t in p2_staff))

    def test_reconstructed_ocr_fragments_from_prior_audit(self):
        # Reconstruct approximate raw text of Page 1, Page 10, Page 18, Page 43 from the case
        p1 = (
            'TRUONG DS I Y NOI BENH AN NOI MS:\n'
            'BE-NH il TRUSG VONG KHOA S; lu•u trü-.\n'
            'I.Hovatén fin hoa): TRINHVÅNHVdNG 2. Sinh ngay:\n'
            'Trang I\n'
        )
        p3 = 'I.Ho tén TRINH VAN HUONG 2.Sinh ngåy: 1 0 0 3 1 9 5 5\n'
        p10 = 'HQ ten bénh: TRINH VAN IIUÖNG Tuöi: 71 tuöi Nam/nü: Nam\n'
        p43 = '(1) benh: TRINH VAN HUONG Ngåy, thång , sinh: 10/03/1955\n*f1UöNG\n'
        fs, known = analyze_hmu_document([p1, p3, p10, p43])
        self.assertIn('TRINHVÅNHVdNG', [f.text for f in fs[0] if f.entity_type == 'PATIENT_NAME'])
        self.assertNotIn('I Y NOI BENH AN NOI MS', [f.text for f in fs[0]])
        self.assertNotIn('Trang I', [f.text for f in fs[0]])
        self.assertIn('TRINH VAN IIUÖNG', [f.text for f in fs[2] if f.entity_type == 'PATIENT_NAME'])
        self.assertTrue(any('f1UöNG' in f.text for f in fs[3] if f.entity_type == 'PATIENT_NAME'))

    def test_edge_case_labels_and_corrupted_fields(self):
        # 1. Bulleted address like Page 6: "- Dia chi: Phú Lương, Xã Vạn Lộc, Tỉnh Thanh Hóa"
        t_addr = "- Dia chi: Phú Lương, Xã Vạn Lộc, Tỉnh Thanh Hóa\nTuổi: 71"
        fs_addr = analyze_hmu_text(t_addr)
        addr_texts = [f.text for f in fs_addr if f.entity_type == "ADDRESS_VN"]
        self.assertTrue(any("Phú Lương" in a and "Vạn Lộc" in a for a in addr_texts), f"Got: {addr_texts}")

        # 2. Relative info without full 'khi cần báo tin' suffix (Page 3 row 11)
        t_rel = "I I.HQ ten, dia chi ngu&i nhå: VO Nguyễn Thị Nhân D/C: Hung löc ,häu löc\nSö dien thoai"
        fs_rel = analyze_hmu_text(t_rel)
        rel_texts = [f.text for f in fs_rel if f.entity_type in {"RELATIVE_NAME", "PERSON_NAME_UNCLASSIFIED"}]
        self.assertTrue(any("Nguyễn Thị Nhân" in r or "Nhân" in r for r in rel_texts), f"Got: {rel_texts}")

        # 3. Doctor name with lower-case 'van' or digits/noise (BSCKI. van Tuån, BSCKI. Đồng M4nh Cuirng)
        t_doc = "BSCKI. van Tuån\nBSCKI. Dng M4nh Cuirng"
        fs_doc = analyze_hmu_text(t_doc)
        doc_texts = [f.text for f in fs_doc if f.entity_type == "HEALTHCARE_STAFF_NAME"]
        self.assertTrue(any("Tuån" in d for d in doc_texts), f"Got: {doc_texts}")

        # 4. OCR misread BHVT and 12-14 digits (Page 8)
        t_bh = "så thé BHVT: KC238382244463"
        fs_bh = analyze_hmu_text(t_bh)
        bh_texts = [f.text for f in fs_bh if f.entity_type == "HEALTH_INSURANCE_ID"]
        self.assertTrue(bool(bh_texts), f"Expected BHVT to be caught, got: {fs_bh}")

    def test_false_positives_elimination_and_clinical_protection(self):
        # Multi-page test with doctors Pham Van Thang and Le Kim Long
        p1 = (
            "BỆNH VIỆN 71 TRUNG ƯƠNG\n"
            "I. Họ tên bệnh nhân: ĐOÀN NHƯ SIÊU\n"
            "Bác sĩ điều trị: Phạm Văn Thắng\n"
            "Bác sỹ chỉ định: Lê Kim Long\n"
            "KTV thực hiện: Nguyễn Tuấn Anh\n"
            "Ngày 10 tháng 03 năm 2026\n"
        )
        p2 = (
            "Chụp X-quang ngực thẳng\n"
            "Kỹ thuật: ngvc thäng\n"
            "Kết quả: Tim phổi không thấy tổn thương bất thường\n"
            "Triệu chứng: Người bệnh bồn chồn, Io läng, hồi hộp\n"
            "Bệnh nhân có thể dé aua cơn đau nhẹ\n"
            "Xét nghiệm vi sinh: nuOi cay đờm tìm vi khuẩn\n"
            "Ngày 12 thång 03 năm 2026\n"
            "thång\n"
            "Bác sĩ: Phạm Văn Thắng\n"
        )
        p3 = (
            "ĐƠN THUỐC ĐIỀU TRỊ\n"
            "1. Paracetamol 500mg: 2 viên / ngày\n"
            "Cách dùng: UONG sau ăn\n"
            "uong 1 viên khi sốt trên 38.5\n"
            "Uong\n"
            "Bác sĩ chỉ định: Lê Kim Long\n"
        )
        p4 = (
            "PHIẾU THEO DÕI CHỨC NĂNG\n"
            "Kỹ thuật viên thuc hién CN\n"
            "Kết quả hiQn tại ổn định, cho chuy viện\n"
            "Chuy\n"
            "Bệnh nhân: DOAN SIEU ký xác nhận\n"
        )

        doc_findings, known = analyze_hmu_document([p1, p2, p3, p4])

        # All staff findings across all pages
        all_staff_texts = [
            f.text.lower() for fs in doc_findings
            for f in fs if f.entity_type in {'HEALTHCARE_STAFF_NAME', 'PERSON_NAME_UNCLASSIFIED'}
        ]

        # 1. Ensure true doctors ARE found
        self.assertTrue(any('thắng' in t or 'thang' in t for t in all_staff_texts), f"Doctor Pham Van Thang should be detected, got: {all_staff_texts}")
        self.assertTrue(any('long' in t for t in all_staff_texts), f"Doctor Le Kim Long should be detected, got: {all_staff_texts}")

        # 2. Ensure false positive clinical terms are NEVER classified as staff
        bad_words = ['thång', 'tháng', 'ngvc thäng', 'ngực thẳng', 'nuoi cay', 'nuoi', 'lo läng', 'io läng', 'lo lắng', 'dé aua', 'uong', 'chuy', 'hiqn']
        for bad in bad_words:
            self.assertFalse(any(bad == t or (len(bad) >= 4 and bad in t) for t in all_staff_texts), f"Forbidden false positive '{bad}' found in staff findings: {all_staff_texts}")

        # 3. Ensure patient DOAN SIEU is classified as PATIENT_NAME on page 4
        p4_patients = [f.text for f in doc_findings[3] if f.entity_type == 'PATIENT_NAME']
        self.assertTrue(any('DOAN' in p or 'SIEU' in p for p in p4_patients), f"Patient name on p4 missing: {doc_findings[3]}")

    def test_xml_index_normalizes_decomposed_case_identity(self):
        import tempfile
        from hmu_recognizers import build_case_xml_index
        name='NGUYỄN VĂN AN'
        with tempfile.TemporaryDirectory() as td:
            for index,form in enumerate(('NFC','NFD')):
                case=pathlib.Path(td)/str(index)/unicodedata.normalize(form,name)
                case.mkdir(parents=True)
                xml=case/(name+'.xml')
                xml.write_text('<ROOT><HO_TEN>'+name+'</HO_TEN><DIEN_THOAI>0912345678</DIEN_THOAI></ROOT>',encoding='utf8')
                parsed=build_case_xml_index(case)
                self.assertEqual(len(parsed),1)
                self.assertIn('0912345678',extract_case_seeds(case,xml_index=parsed)['PHONE_NUMBER_VN'])

if __name__ == '__main__':
    unittest.main()
