import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

import fitz

# Ensure HMU_KhuDinhDanh.V3 is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import app
import batch
import batch_worker
import delivery
import engine
import output_qc


class RealWorkspaceE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.jobs_dir = self.root / 'jobs'
        self.server = app.create_server(self.jobs_dir, None, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        code, state = self.req('GET', '/state')
        self.assertEqual(code, 200)
        self.token = state['token']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        h = {'X-HMU-Token': getattr(self, 'token', '')}
        h.update(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode('utf-8')
            h.setdefault('Content-Type', 'application/json')
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        raw = r.read()
        code = r.status
        ctype = r.getheader('Content-Type', '')
        c.close()
        return code, json.loads(raw.decode('utf-8')) if 'json' in ctype else raw

    def create_real_patient_pdf(self, path: Path, title: str, name: str, birth_year: int, address: str, doctor: str, extra_text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        page = doc.new_page(width=595, height=842) # A4 size

        # Insert realistic hospital header and patient info
        page.insert_text((50, 50), "BỆNH VIỆN ĐẠI HỌC Y HÀ NỘI", fontsize=14)
        page.insert_text((50, 70), "KHOA TIM MẠCH - CAN THIỆP", fontsize=12)
        page.insert_text((200, 100), title, fontsize=16)

        page.insert_text((50, 140), f"Họ và tên người bệnh: {name}", fontsize=12)
        page.insert_text((50, 165), f"Năm sinh: {birth_year} (Tuổi: {2026 - birth_year})", fontsize=12)
        page.insert_text((50, 190), f"Địa chỉ liên hệ: {address}", fontsize=12)
        page.insert_text((50, 215), f"Bác sĩ điều trị: {doctor}", fontsize=12)
        page.insert_text((50, 240), f"Số điện thoại: 0912345678", fontsize=12)

        page.insert_text((50, 280), "CHẨN ĐOÁN VÀ ĐIỀU TRỊ:", fontsize=13)
        page.insert_text((50, 310), extra_text, fontsize=11)

        doc.save(path)
        doc.close()
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_full_desktop_workspace_real_e2e_pipeline_and_report_extraction(self):
        desktop_dir = self.root / 'Mock_Windows11_Desktop'
        desktop_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------------------------------------------
        # 1. Desktop Workspace Manager: Khởi tạo Workspace động ngoài Desktop
        # ---------------------------------------------------------------------
        ws_name = "HMU_Dot1_TimMach_RealTest"
        code, ws_init = self.req('POST', '/workspace/init', {
            'workspace_name': ws_name,
            'desktop_base': str(desktop_dir)
        })
        self.assertEqual(code, 200, ws_init)
        self.assertEqual(ws_init['workspace_name'], ws_name)

        data_root = Path(ws_init['data_root'])
        data_deid = Path(ws_init['data_deidentified'])

        self.assertTrue(data_root.is_dir(), "Data_Root must be created on Desktop")
        self.assertTrue(data_deid.is_dir(), "Data_Deidentified must be created on Desktop")

        # Verify persisted workspace_config.json
        cfg_path = self.jobs_dir / 'workspace_config.json'
        self.assertTrue(cfg_path.is_file(), "workspace_config.json must be persisted")
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        self.assertEqual(cfg['workspace_name'], ws_name)
        self.assertEqual(cfg['data_root'], str(data_root.resolve()))
        self.assertEqual(cfg['data_deidentified'], str(data_deid.resolve()))

        # ---------------------------------------------------------------------
        # 2. Tạo dữ liệu PDF test case thật trong Data_Root
        #    Case 1: BN01_NguyenVanAn (2 files: to_bia.pdf, xet_nghiem.pdf)
        #    Case 2: BN02_TranThiBinh (1 file: to_bia.pdf - TRÙNG TÊN FILE VỚI CASE 1)
        #    Case 3: BN03_PhamVanChung (1 file: ho_so.pdf - dành cho test Local Single Case)
        # ---------------------------------------------------------------------
        ba1_dir = data_root / 'BN01_NguyenVanAn'
        ba2_dir = data_root / 'BN02_TranThiBinh'
        ba3_dir = data_root / 'BN03_PhamVanChung'

        ba1_pdf1 = ba1_dir / 'to_bia.pdf'
        ba1_pdf2 = ba1_dir / 'xet_nghiem.pdf'
        ba2_pdf1 = ba2_dir / 'to_bia.pdf'
        ba3_pdf1 = ba3_dir / 'ho_so.pdf'

        hash_ba1_pdf1 = self.create_real_patient_pdf(
            ba1_pdf1, "BỆNH ÁN NỘI KHOA", "NGUYỄN VĂN AN", 1985,
            "Số 1 Tôn Thất Tùng, Đống Đa, Hà Nội", "ThS. BS. Trần Văn Bình",
            "Tăng huyết áp nguyên phát I10. Xơ vữa mạch vành."
        )
        hash_ba1_pdf2 = self.create_real_patient_pdf(
            ba1_pdf2, "PHIẾU XÉT NGHIỆM SINH HÓA", "NGUYỄN VĂN AN", 1985,
            "Số 1 Tôn Thất Tùng, Đống Đa, Hà Nội", "BS. Lê Quốc Cường",
            "Đường huyết: 5.2 mmol/L. Triglycerid: 1.8 mmol/L. Men gan bình thường."
        )
        hash_ba2_pdf1 = self.create_real_patient_pdf(
            ba2_pdf1, "BỆNH ÁN NỘI TIẾT", "TRẦN THỊ BÌNH", 1990,
            "Phường Hàng Bài, Hoàn Kiếm, Hà Nội", "PGS. TS. Nguyễn Thu Cúc",
            "Đái tháo đường type 2 E11. Chỉ định theo dõi đường huyết mao mạch."
        )
        hash_ba3_pdf1 = self.create_real_patient_pdf(
            ba3_pdf1, "HỒ SƠ KHÁM TIM MẠCH", "PHẠM VĂN CHUNG", 1978,
            "Quận Cầu Giấy, Hà Nội", "BS. Vũ Hải Nam",
            "Thiếu máu cơ tim cục bộ I25. Đang dùng aspirin và statin."
        )

        self.assertNotEqual(hash_ba1_pdf1, hash_ba2_pdf1, "Two to_bia.pdf files must have distinct source hashes")

        # ---------------------------------------------------------------------
        # 3. Pre-Clone Empty Folder Engine: Nạp Data_Root qua /batch/enqueue
        # ---------------------------------------------------------------------
        # Nạp 2 bệnh án BN01 và BN02 vào batch
        batch_inputs = [str(ba1_dir), str(ba2_dir)]
        code, enq_res = self.req('POST', '/batch/enqueue', {
            'paths': batch_inputs,
            'destination': str(data_deid)
        })
        self.assertEqual(code, 200, enq_res)
        self.assertEqual(len(enq_res['ids']), 3, "Must enqueue 3 PDF files from 2 patient cases")

        # Kiểm tra Pre-clone: Các folder bệnh án trong Data_Deidentified ĐÃ PHẢI TỒN TẠI VÀ RỖNG
        self.assertIn('cloned_folders', enq_res)
        target_ba1_dir = data_deid / 'BN01_NguyenVanAn'
        target_ba2_dir = data_deid / 'BN02_TranThiBinh'

        self.assertTrue(target_ba1_dir.is_dir(), "Pre-cloned BN01 folder must exist")
        self.assertTrue(target_ba2_dir.is_dir(), "Pre-cloned BN02 folder must exist")
        self.assertEqual(len(list(target_ba1_dir.iterdir())), 0, "Pre-cloned BN01 must be completely empty before export")
        self.assertEqual(len(list(target_ba2_dir.iterdir())), 0, "Pre-cloned BN02 must be completely empty before export")

        # Kiểm tra SQLite jobs table: target_folder được map chính xác 1:1
        batch_db = self.jobs_dir / 'batch' / 'queue.sqlite3'
        self.assertTrue(batch_db.is_file())
        jobs = batch.list_jobs(batch_db, details=True)
        self.assertEqual(len(jobs), 3)

        for j in jobs:
            if 'BN01_NguyenVanAn' in j['source_path']:
                self.assertEqual(Path(j['target_folder']).resolve(), target_ba1_dir.resolve())
            elif 'BN02_TranThiBinh' in j['source_path']:
                self.assertEqual(Path(j['target_folder']).resolve(), target_ba2_dir.resolve())
            else:
                self.fail(f"Unexpected source path in job: {j['source_path']}")

        # ---------------------------------------------------------------------
        # 4. Chạy Worker Thật (batch_worker.process_job) & Engine Thật
        # ---------------------------------------------------------------------
        processed_count = 0
        while True:
            row = batch.claim_next(batch_db)
            if not row:
                break
            processed_count += 1
            # Run real engine processing: prepare, OCR, redactions, draft export, output QC
            res = batch_worker.process_job(row, ocr_workers=1, render_workers=1)
            self.assertIn('verification', res)
            self.assertIn('output', res)
            self.assertTrue(Path(res['output']).is_file())

            # Finish worker in SQLite
            batch.finish_worker(batch_db, row['id'], res)

            # Approve all pages for the job so it meets QC requirements for release
            job_review_dir = Path(row['job_dir']) / 'review'
            approved_state = engine.approve_all_pages(job_review_dir)

            # Resolve any findings through the real HTTP API endpoint
            findings = res['verification'].get('findings', [])
            for f in findings:
                code, rf_res = self.req('POST', '/batch/resolve_finding', {
                    'queue_id': row['id'],
                    'revision': approved_state['revision'],
                    'finding_id': f['id'],
                    'reason': 'Đã đối chiếu hồ sơ gốc và xác nhận an toàn',
                    'reviewer': 'Bác sĩ kiểm duyệt HMU'
                })
                self.assertEqual(code, 200, rf_res)

            for pn in res['verification'].get('unreadable_pages', []):
                code, rf_res = self.req('POST', '/batch/resolve_finding', {
                    'queue_id': row['id'],
                    'revision': approved_state['revision'],
                    'finding_id': f'unreadable:{pn}',
                    'reason': 'Đã kiểm tra thủ công toàn trang scan',
                    'reviewer': 'Bác sĩ kiểm duyệt HMU'
                })
                self.assertEqual(code, 200, rf_res)

            # Verify AUDIT_SUMMARY.md was generated by engine
            audit_file = job_review_dir / 'AUDIT_SUMMARY.md'
            self.assertTrue(audit_file.is_file(), f"AUDIT_SUMMARY.md must be generated at {audit_file}")
            audit_content = audit_file.read_text(encoding='utf-8')
            self.assertIn("# Báo Cáo Khử Định Danh Bệnh Án", audit_content)

        self.assertEqual(processed_count, 3, "All 3 jobs must be processed by real engine")

        # ---------------------------------------------------------------------
        # 5. Xuất Hàng Loạt Lần 1: Định tuyến 1:1 về đúng folder đã clone
        # ---------------------------------------------------------------------
        code, rel_res = self.req('POST', '/batch/release_folder', {
            'paths': [str(data_root)],
            'destination': str(data_deid)
        })
        self.assertEqual(code, 200, rel_res)
        self.assertEqual(rel_res['pending'], [], f"Pending items: {rel_res.get('pending')}")
        self.assertEqual(len(rel_res['exported']), 3)
        self.assertFalse(rel_res.get('comparisons'), "First export should have no comparisons")

        # Kiểm tra đường dẫn xuất:
        # File thuộc BN01 đổ đúng về Data_Deidentified/BN01_NguyenVanAn
        # File thuộc BN02 đổ đúng về Data_Deidentified/BN02_TranThiBinh
        # Không có subfolder BAN_GIAO_<hex>
        out_ba1_pdf1 = target_ba1_dir / 'to_bia.pdf'
        out_ba1_pdf2 = target_ba1_dir / 'xet_nghiem.pdf'
        out_ba2_pdf1 = target_ba2_dir / 'to_bia.pdf'

        self.assertTrue(out_ba1_pdf1.is_file(), "BN01 to_bia.pdf must be placed in BN01 folder")
        self.assertTrue(out_ba1_pdf2.is_file(), "BN01 xet_nghiem.pdf must be placed in BN01 folder")
        self.assertTrue(out_ba2_pdf1.is_file(), "BN02 to_bia.pdf must be placed in BN02 folder")

        # Hai file to_bia.pdf trùng tên ở 2 bệnh án khác nhau KHÔNG ĐƯỢC ĐÈ NHAU
        hash_out_ba1_pdf1 = hashlib.sha256(out_ba1_pdf1.read_bytes()).hexdigest()
        hash_out_ba2_pdf1 = hashlib.sha256(out_ba2_pdf1.read_bytes()).hexdigest()
        self.assertNotEqual(hash_out_ba1_pdf1, hash_out_ba2_pdf1, "Deidentified to_bia.pdf of BN01 and BN02 must be distinct")

        # ---------------------------------------------------------------------
        # 6. Trích Xuất & Kiểm Chứng Báo Cáo Nghiệm Thu Thật Trên Đĩa (100% Thật)
        # ---------------------------------------------------------------------
        manifest_ba1_path = target_ba1_dir / 'manifest.json'
        manifest_ba2_path = target_ba2_dir / 'manifest.json'
        qc_ba1_path = target_ba1_dir / 'qc.json'
        qc_ba2_path = target_ba2_dir / 'qc.json'

        self.assertTrue(manifest_ba1_path.is_file(), "BN01 manifest.json must exist")
        self.assertTrue(manifest_ba2_path.is_file(), "BN02 manifest.json must exist")
        self.assertTrue(qc_ba1_path.is_file(), "BN01 qc.json must exist")
        self.assertTrue(qc_ba2_path.is_file(), "BN02 qc.json must exist")

        manifest_ba1 = json.loads(manifest_ba1_path.read_text(encoding='utf-8'))
        manifest_ba2 = json.loads(manifest_ba2_path.read_text(encoding='utf-8'))
        qc_ba1 = json.loads(qc_ba1_path.read_text(encoding='utf-8'))
        qc_ba2 = json.loads(qc_ba2_path.read_text(encoding='utf-8'))

        # Kiểm chứng chuỗi SHA-256 từ file PDF thật trên đĩa với manifest.json
        files_ba1 = {f['file']: f for f in manifest_ba1['files']}
        self.assertIn('to_bia.pdf', files_ba1)
        self.assertIn('xet_nghiem.pdf', files_ba1)
        self.assertEqual(files_ba1['to_bia.pdf']['output_hash'], hash_out_ba1_pdf1)
        self.assertEqual(files_ba1['xet_nghiem.pdf']['output_hash'], hashlib.sha256(out_ba1_pdf2.read_bytes()).hexdigest())

        files_ba2 = {f['file']: f for f in manifest_ba2['files']}
        self.assertIn('to_bia.pdf', files_ba2)
        self.assertEqual(files_ba2['to_bia.pdf']['output_hash'], hash_out_ba2_pdf1)

        # QC reports verification
        self.assertTrue(len(qc_ba1.get('files', [])) >= 2)
        self.assertTrue(all(f['status'] == 'HUMAN_REVIEWED' for f in qc_ba1['files']))
        self.assertTrue(all(f['structural_ok'] for f in qc_ba1['files']))

        self.assertTrue(len(qc_ba2.get('files', [])) >= 1)
        self.assertTrue(all(f['status'] == 'HUMAN_REVIEWED' for f in qc_ba2['files']))
        self.assertTrue(all(f['structural_ok'] for f in qc_ba2['files']))

        # ---------------------------------------------------------------------
        # 7. Kiểm Thử Cơ Chế Bản Sao Đối Chiếu (Collision Copy) Khi Xuất Lại Lần 2
        # ---------------------------------------------------------------------
        code, rel_res2 = self.req('POST', '/batch/release_folder', {
            'paths': [str(data_root)],
            'destination': str(data_deid)
        })
        self.assertEqual(code, 200, rel_res2)
        self.assertEqual(len(rel_res2['exported']), 3)

        # Kiểm tra phản hồi comparisons
        comparisons = rel_res2.get('comparisons', [])
        self.assertTrue(len(comparisons) >= 2, f"Must have at least 2 comparison records: {comparisons}")

        copy_ba1_dir = data_deid / 'BN01_NguyenVanAn_Copy1'
        copy_ba2_dir = data_deid / 'BN02_TranThiBinh_Copy1'

        self.assertTrue(copy_ba1_dir.is_dir(), "BN01_Copy1 folder must be created on collision")
        self.assertTrue(copy_ba2_dir.is_dir(), "BN02_Copy1 folder must be created on collision")

        # Bản gốc cũ VẪN PHẢI NGUYÊN VẸN 100%
        self.assertEqual(hashlib.sha256(out_ba1_pdf1.read_bytes()).hexdigest(), hash_out_ba1_pdf1)
        self.assertEqual(hashlib.sha256(out_ba2_pdf1.read_bytes()).hexdigest(), hash_out_ba2_pdf1)

        # Bản sao đối chiếu Copy1 chứa đầy đủ các file đã xuất
        self.assertTrue((copy_ba1_dir / 'to_bia.pdf').is_file())
        self.assertTrue((copy_ba1_dir / 'xet_nghiem.pdf').is_file())
        self.assertTrue((copy_ba1_dir / 'manifest.json').is_file())
        self.assertTrue((copy_ba1_dir / 'qc.json').is_file())

        self.assertTrue((copy_ba2_dir / 'to_bia.pdf').is_file())
        self.assertTrue((copy_ba2_dir / 'manifest.json').is_file())
        self.assertTrue((copy_ba2_dir / 'qc.json').is_file())

        # ---------------------------------------------------------------------
        # 8. Kiểm thử Single-Case Local Workflow (/open_path & /export_folder)
        # ---------------------------------------------------------------------
        code, open_res = self.req('POST', '/open_path', {
            'path': str(ba3_dir),
            'study_id': 'CASE_BN03',
            'destination': str(data_deid)
        })
        self.assertEqual(code, 200, open_res)
        target_ba3_dir = data_deid / 'BN03_PhamVanChung'
        self.assertTrue(target_ba3_dir.is_dir(), "Pre-cloned BN03 folder must exist")
        self.assertEqual(len(list(target_ba3_dir.iterdir())), 0, "Pre-cloned BN03 must be empty initially")

        # Approve all pages
        review_state = open_res['review']
        code, app_res = self.req('POST', '/approve_all', {
            'job_id': review_state['job_id'],
            'revision': review_state['revision']
        })
        self.assertEqual(code, 200, app_res)
        approved_review = app_res['review']

        # Xuất folder lần 1
        code, exp_res1 = self.req('POST', '/export_folder', {
            'job_id': approved_review['job_id'],
            'revision': approved_review['revision'],
            'destination': str(data_deid)
        })
        self.assertEqual(code, 200, exp_res1)
        self.assertEqual(Path(exp_res1['directory']).resolve(), target_ba3_dir.resolve())
        self.assertFalse(exp_res1.get('copied_for_comparison', False))
        self.assertTrue((target_ba3_dir / 'ho_so.pdf').is_file())
        self.assertTrue((target_ba3_dir / 'manifest.json').is_file())

        # Xuất folder lần 2 -> tạo bản sao BN03_PhamVanChung_Copy1
        code, exp_res2 = self.req('POST', '/export_folder', {
            'job_id': approved_review['job_id'],
            'revision': approved_review['revision'],
            'destination': str(data_deid)
        })
        self.assertEqual(code, 200, exp_res2)
        copy_ba3_dir = data_deid / 'BN03_PhamVanChung_Copy1'
        self.assertEqual(Path(exp_res2['directory']).resolve(), copy_ba3_dir.resolve())
        self.assertTrue(exp_res2.get('copied_for_comparison', False))
        self.assertEqual(exp_res2.get('original_directory'), str(target_ba3_dir.resolve()))
        self.assertTrue((copy_ba3_dir / 'ho_so.pdf').is_file())

        # ---------------------------------------------------------------------
        # 9. In Báo Cáo Nghiệm Thu Trích Xuất 100% Từ File Thật Trên Ổ Đĩa
        # ---------------------------------------------------------------------
        print("\n" + "=" * 90)
        print("BÁO CÁO NGHIỆM THU E2E THỰC TẾ TỪ TEST CASE THẬT (TRÍCH XUẤT 100% TỪ ĐĨA)")
        print("=" * 90)
        print(f"📁 Workspace: {ws_name}")
        print(f"📁 Data_Root: {data_root}")
        print(f"📁 Data_Deidentified: {data_deid}")
        print("-" * 90)

        for p_name, p_dir in [("Bệnh án 1", target_ba1_dir), ("Bệnh án 2", target_ba2_dir), ("Bệnh án 3 (Local)", target_ba3_dir)]:
            m_file = p_dir / 'manifest.json'
            q_file = p_dir / 'qc.json'
            m_data = json.loads(m_file.read_text(encoding='utf-8')) if m_file.exists() else {}
            q_data = json.loads(q_file.read_text(encoding='utf-8')) if q_file.exists() else {}

            print(f"[*] {p_name} ({p_dir.name}):")
            print(f"    - Study ID: {m_data.get('study_id')}")
            print(f"    - Thời gian xuất: {m_data.get('created')}")
            if 'files' in q_data:
                qc_summary = ", ".join(f.get('status', 'OK') for f in q_data['files'])
            else:
                qc_summary = q_data.get('status', 'HUMAN_REVIEWED')
            print(f"    - Trạng thái QC: {qc_summary}")
            print(f"    - Danh sách tệp & SHA-256 đối chiếu thực tế:")
            for f in m_data.get('files', []):
                fname = f.get('file') or f.get('pdf')
                expected_hash = f.get('output_hash') or f.get('output_sha256')
                actual_path = p_dir / fname
                actual_hash = hashlib.sha256(actual_path.read_bytes()).hexdigest()
                hash_match = "✓ TRÙNG KHỚP 100%" if actual_hash == expected_hash else "✗ KHÔNG KHỚP"
                print(f"      + {fname}: {actual_hash} [{hash_match}] (Gốc: {f.get('source_file') or f.get('pdf')})")

        print("-" * 90)
        print("BẢN SAO ĐỐI CHIẾU KHI XUẤT TRÙNG (COLLISION COPIES):")
        print(f"  - BN01_NguyenVanAn_Copy1: {copy_ba1_dir.exists()} (Giữ nguyên gốc: {target_ba1_dir.exists()})")
        print(f"  - BN02_TranThiBinh_Copy1: {copy_ba2_dir.exists()} (Giữ nguyên gốc: {target_ba2_dir.exists()})")
        print(f"  - BN03_PhamVanChung_Copy1: {copy_ba3_dir.exists()} (Giữ nguyên gốc: {target_ba3_dir.exists()})")
        print("=" * 90 + "\n")


if __name__ == '__main__':
    unittest.main()
