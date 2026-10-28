import unittest, unicodedata, pathlib
from hmu_recognizers import analyze_hmu_text, analyze_hmu_document, extract_case_seeds

class RecognizerTests(unittest.TestCase):
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
        self.assertEqual(analyze_hmu_text(t), [])

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
        self.assertEqual(fs[0].review_status, 'PENDING_REVIEW')

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

    def test_real_audit_summary_46_pages_trinh_van_huong(self):
        audit_md = pathlib.Path(r'D:\Workspaces\HMU_Bo_cong_cu_khu_dinh_danh_PDF\HMU_KhuDinhDanh\HMU_JOBS\HMU_CASE_0001_1793092042527986000\review\AUDIT_SUMMARY.md')
        if not audit_md.exists():
            return
        raw = audit_md.read_text(encoding='utf-8')
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

if __name__ == '__main__':
    unittest.main()
