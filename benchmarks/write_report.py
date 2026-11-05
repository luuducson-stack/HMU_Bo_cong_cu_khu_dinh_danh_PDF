"""Build the local handoff report from preserved measurements and final test log."""
import ast
import ctypes
import hashlib
import json
import os
import re
import statistics
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / 'HMU_KhuDinhDanh'
RESULTS = PROJECT / 'benchmarks/results'


def load(name):
    return json.loads((RESULTS / name).read_text(encoding='utf-8'))


def main():
    base, final = load('B0_timing.json'), load('FINAL_timing.json')
    middle = load('B1_corrected_initialopts.json')
    ext, extmid, proof = load('B0_extended.json'), load('B1_extended_initialproof.json'), load('FINAL_watermark_proofopt.json')
    save = load('SAVE_FINAL_timing.json')
    workers = load('workers50_confirm.json')
    warm_old = load('B0_native10_confirm.json')['cases']['native10']
    warm_new = load('FINAL_native10_confirm.json')['cases']['native10']
    log = (ROOT / 'FULL_TEST_FINAL.log').read_text(encoding='utf-8-sig')
    match = re.search(r'Ran (\d+) tests in ([\d.]+)s', log)
    assert match and 'OK (skipped=1)' in log, 'Final test evidence missing'
    assert 'PASS' in (ROOT/'UI_TEST_FINAL.log').read_text(encoding='utf-8-sig')
    assert 'No broken requirements' in (ROOT/'PIP_CHECK_FINAL.log').read_text(encoding='utf-8-sig')
    hashes = {name: hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()
              for name in ('engine.py', 'hmu_recognizers.py', 'ocr_helper.py', 'app.py', 'review.html')}
    assert all(proof['source_hashes'][name] == hashes[name] for name in proof['source_hashes'])
    evidence = {'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
                'source_sha256': hashes, 'tests': {'total': int(match[1]), 'passed': int(match[1])-1,
                'skipped': 1, 'seconds': float(match[2])},
                'provenance': 'Historical8 measured before final NFC/watermark-only fixes; recorded source hashes retained. Those branches are absent from the historical8 corpora. Final watermark benchmark matches current engine/hmu/OCR byte hashes. Largephoto result uses the previous build but no watermark or XML branch.'}
    evidence['ocr_runtime'] = load('OCR_RUNTIME.json')
    evidence['processor_identifier'] = os.environ.get('PROCESSOR_IDENTIFIER')
    evidence['logical_cpu_count'] = os.cpu_count()
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ('total_phys','avail_phys','total_pagefile','avail_pagefile','total_virtual','avail_virtual','avail_extended')]
        status = Memory(); status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            evidence['physical_ram_bytes'] = status.total_phys
    (ROOT/'IMPLEMENTATION_EVIDENCE_2026-10-28.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    tasks = [
        ('F01','Batch chỉ prepare, không tự duyệt/xuất; chọn từng PDF và xuất sau duyệt','HTTP batch/open/select tests'),
        ('F02','Watermark xóa bằng đối tượng có proof; giữ opacity, graphics, ảnh và trang chưa chọn','Pixel reference 45°, graphics/image, shared stream, unsafe state tests'),
        ('F03','Hộp mực dừng ở khoảng trắng đầu, không lan sang cột kế','Initial-gap và ink-expansion tests'),
        ('F04','Không coi ảnh cuối trang là chữ ký chỉ vì vị trí','Small-bottom-image và logo/clinical/signature tests'),
        ('F05','OCR mixed và ảnh nhỏ; ghép native/OCR, xử lý crop/xoay/tile','Real OCR phone/name/address seam, rotation/crop và bounds tests'),
        ('F06','Tên PDF/QC theo study ID + chỉ số, không theo PII nguồn','Batch names, Unicode và study ID 64 ký tự'),
        ('F07','PDF+QC trong generation bất biến, publish bằng pointer nguyên tử','QC/pointer failure, uniqueness và missing-review tests'),
        ('F08','Upload chỉ ghi source_private.pdf trong job mới','Absolute/UNC/traversal HTTP tests'),
        ('F09','Job ID/revision/khóa/task snapshot; không mất edit lúc chuyển trang','Stale tab, concurrent revision, busy export, progress + Node delayed-save'),
        ('F10','Kiểm ICD cho cả mask cuối cùng và ảnh xóa bằng đối tượng','Manual-ICD và protected-image removal tests'),
        ('F11','Audit theo mask/snapshot thực, có revision/draft/fingerprint; recover đúng SHA','Deselect/manual/image/rotation audit + source recovery tests'),
        ('F12','Hợp span giao nhau, không hở phần đuôi','Overlapping union regression'),
        ('F13','Bỏ test xanh giả, thêm HTTP/pixel/OCR/engine regression','Full suite; fixture riêng tư thiếu ghi SKIP'),
        ('F14','Bỏ taskkill, exclusive bind cổng trên Windows','Occupied-port test giữ listener cũ'),
        ('F15','Hướng dẫn v2 nhất quán, v1/QC cũ giữ làm lịch sử','Docs update; installer chạy unittest discover')]
    labels = {'native10':'Native 10 trang','native150':'Native 150 trang','scan10':'Scan 10 trang',
              'scan50':'Scan 50 trang','mixed10':'Mixed 10 trang','case50':'50 PDF × 2 trang',
              'vector20':'Vector 20 trang','large3':'3 trang ảnh đơn giản'}
    rows = []
    for key, old in base['cases'].items():
        new = final['cases'][key]
        assert old['corpus_sha256'] == new['corpus_sha256']
        b, n = old['median_total_seconds'], new['median_total_seconds']
        rows.append(f'| {labels[key]} | {b:.3f} | {n:.3f} | {(n/b-1)*100:+.1f}% |')
    p95old, p95new = (save[k]['p95_seconds']*1000 for k in ('before','after'))
    memory = lambda doc: statistics.median(r['peak_task_sampled_rss_bytes'] for r in doc['cases']['scan50']['measurements'])/1024**2
    oldmem, newmem = memory(base), memory(final)
    worker_memory = {key:statistics.median(r['peak_task_sampled_rss_bytes'] for r in workers[key]['runs'])/1024**2 for key in ('1','6')}
    wmold, wmfirst, wmnew = (doc['cases']['watermark10']['median_total_seconds'] for doc in (ext, extmid, proof))
    photo_old, photo_new = (doc['cases']['largephoto2']['median_total_seconds'] for doc in (ext, extmid))
    counts = []
    for path in sorted(PROJECT.glob('test_*.py')):
        count = sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))))
        counts.append(f'- `{path.name}`: {count} test.')
    report = f'''# Báo cáo triển khai và benchmark — 28/10/2026

## Kết quả bàn giao

Đã xử lý đủ 15 nhóm vấn đề trong phạm vi source và các fixture nghiệm thu tổng hợp. Đã sửa thêm các lỗi phát hiện khi review/benchmark: mất số điện thoại ở mép tile, bỏ qua ảnh scan nhỏ, watermark làm đổi graphics state, xóa ảnh chứa ICD, audit xoay sai tọa độ, stream dùng chung giữa trang, metadata seqno gây từ chối nhầm và XML Unicode phân rã.

**Kiểm thử cuối: {match[1]} test, {int(match[1])-1} PASS, 1 SKIP, 0 FAIL/ERROR, {match[2]} giây.** JavaScript chống mất edit PASS; pip check đạt. 14 test workflow gốc tiếp tục đạt. SKIP duy nhất là fixture bệnh viện riêng tư không có trên máy.

Nhánh `{evidence['branch']}`, base commit `{evidence['base_commit']}`. Hash bản bàn giao ở [evidence JSON](IMPLEMENTATION_EVIDENCE_2026-10-28.json). Không ghi đè bệnh án nguồn. Dùng Superpowers để triển khai/TDD/review/verification và Ponytail để sửa trong cấu trúc hiện có.

## Checklist 15 vấn đề

| ID | Kết quả | Kiểm chứng |
|---|---|---|
'''+''.join(f'| {key} [x] | {description} | {tests} |\n' for key,description,tests in tasks)+f'''
Các dấu hoàn tất áp dụng cho hành vi và fixture đã kiểm; không thay thế nghiệm thu bệnh án thật hay chứng nhận phát hiện mọi PII.

## Kiểm thử và chạy lại

{chr(10).join(counts)}
- Node `test_ui_save.js`: save chậm + edit đến trong lúc chuyển trang; lưu đủ edit ở trang cũ trước điều hướng.
- UI smoke qua browser trên PDF giả: mở → duyệt → xuất → hiện link tải/generation. [Ảnh kiểm chứng](UI_SMOKE_2026-10-28.png).
- [Log kiểm thử cuối](FULL_TEST_FINAL.log).

```powershell
cd HMU_KhuDinhDanh
.\\.venv\\Scripts\\python.exe -m unittest discover -p 'test_*.py' -v
node test_ui_save.js
.\\.venv\\Scripts\\python.exe -m pip check
```

## Phương pháp đo

Windows build 26200, 8 CPU logic, Python 3.10.11, PyMuPDF 1.26.6, pypdf 6.10.0. RAM/CPU identifier được ghi trong evidence JSON. Windows OCR thực tế chọn `{evidence['ocr_runtime']['language']}`, giới hạn ảnh runtime {evidence['ocr_runtime']['max_image_dimension']}px; bản này dùng tile4096px và overlap256px. Dữ liệu sinh giả, không dùng bệnh án thật.

- B0: source trước sửa; 8 nhóm ×3 lần, không profiler, không warm-up tường minh.
- Bản trung gian: sửa lỗi kèm tối ưu cơ học đầu tiên; không gọi đây là baseline thuần correctness trước mọi tối ưu.
- Bản tối ưu: cùng 8 corpus hash. Các fix sau đo chỉ nằm ở nhánh XML Unicode/watermark không có trong 8 corpus. Giữ source hashes và scope trong provenance, không giả mọi lần đo dùng cùng byte source.
- Mở rộng: watermark10 có 400 nét vector/trang; largephoto2 có ảnh 2400×3200 trong trang lớn. Warm-up1 +3 lần mỗi bản. Kiểm vùng tên trắng và vùng chuyên môn đối chứng có sai khác kênh trung bình <=1; không chứng nhận mọi pixel của mọi bệnh án.
- HTTP save: 150 trang, warm-up1 +30 thao tác/phương pháp; không bao gồm browser render.
- RAM: lấy mẫu 100ms Python + tiến trình con OCR; không phải peak tuyệt đối hoặc RAM toàn hệ thống. Python OS peak lũy kế được ghi riêng. Không có CI cấu hình máy đích hoặc đặc tả storage đầy đủ.

## Tổng thời gian prepare + export: trung vị giây

Số âm là nhanh hơn. Giữ cả các nhóm còn chậm hơn.

| Corpus | B0 | Sau tối ưu | Thay đổi |
|---|---:|---:|---:|
{chr(10).join(rows)}

Native10 của lượt3 lần dao động mạnh: 5,587 /3,743 /2,609 giây. Đối chiếu thêm warm-up1 +5 lần mỗi bản, cùng hash: **{warm_old['median_total_seconds']:.3f} → {warm_new['median_total_seconds']:.3f}s ({(warm_new['median_total_seconds']/warm_old['median_total_seconds']-1)*100:+.1f}%)**. Không ghi đè kết quả cũ hoặc gộp hai protocol; native chưa nhanh hơn B0.

## Tối ưu có số đo rõ

| Hạng mục | Trước | Sau | Kết quả |
|---|---:|---:|---|
| Prepare native150, so bản trung gian | {middle['cases']['native150']['median_prepare_seconds']:.3f}s | {final['cases']['native150']['median_prepare_seconds']:.3f}s | {(1-final['cases']['native150']['median_prepare_seconds']/middle['cases']['native150']['median_prepare_seconds'])*100:.1f}% nhanh hơn; chưa nhanh hơn B0 |
| Tổng scan50, so B0 | {base['cases']['scan50']['median_total_seconds']:.3f}s | {final['cases']['scan50']['median_total_seconds']:.3f}s | {(1-final['cases']['scan50']['median_total_seconds']/base['cases']['scan50']['median_total_seconds'])*100:.1f}% nhanh hơn |
| RAM lấy mẫu scan50 | {oldmem:.1f} MiB | {newmem:.1f} MiB | {(1-newmem/oldmem)*100:.1f}% giảm |
| p95 lưu HTTP, đo lại độc lập | {p95old:.2f}ms | {p95new:.2f}ms | {(1-p95new/p95old)*100:.1f}% giảm |
| Payload lưu trung vị | {save['before']['median_request_bytes']:.1f} byte | {save['after']['median_request_bytes']:.0f} byte | Không gửi lại cả review |
| Watermark10, so proof trước tối ưu | {wmfirst:.3f}s | {wmnew:.3f}s | {(1-wmnew/wmfirst)*100:.1f}% nhanh hơn, giữ proof/pixel guards |

Worker50 trang,3 lần/cấu hình và page maps bằng nhau: 6 worker {workers['6']['median_seconds']:.3f}s →1 worker {workers['1']['median_seconds']:.3f}s; RAM lấy mẫu trung vị **{worker_memory['6']:.1f} → {worker_memory['1']:.1f} MiB**. Chọn mặc định1; API còn cho đặt1–6.

Đã tối ưu: hash streaming1MiB, span bisect, ngừng quét khi đủ dark pixel, dùng chung drawings/XML parse, một native char map/trang, tránh materialize byte ảnh chỉ để lấy text/bbox, analysis JSON compact, save_page tuần tự và audit theo revision. Proof watermark giảm parse graphics-only41→1, semantic snapshot18→2 trong regression tương ứng.

## Phần chưa đạt và giới hạn

- Watermark/vector: B0 **{wmold:.3f}s**, proof an toàn ban đầu **{wmfirst:.3f}s**, sau tối ưu **{wmnew:.3f}s**; vẫn **{(wmnew/wmold-1)*100:+.1f}%** so B0. B0 bóc sớm và có ít proof an toàn hơn; chưa đạt tăng tốc tổng.
- Ảnh màu lớn: **{photo_old:.3f} → {photo_new:.3f}s ({(photo_new/photo_old-1)*100:+.1f}%)**. Bản mới OCR phần ảnh bản cũ bỏ qua; đây là tăng việc bắt buộc, không phải chiến thắng tốc độ. Oracles vùng chuyên môn đạt.
- Native/batch/vector chưa đồng loạt nhanh hơn B0; điều kiện không hồi quy >10% mọi nhóm chưa đạt theo số liệu quan sát. Các kiểm tra và source analysis được giữ lại.
- Chưa đo p95 chuyển trang/render UI thực; p95 trên chỉ là HTTP save. Chưa tách hoàn toàn WinRT Recognize khỏi startup PowerShell; phase diagnostic là thời gian/call counts lồng nhau, không cộng cumulative time thành tổng.
- RAM không giảm25% ở mọi corpus. Không thêm shard/export đa tiến trình khi chưa chứng minh có lợi; giảm RAM OCR là lợi ích đã đo.
- Chưa nghiệm thu bệnh viện thật, chữ viết tay tùy ý, hoặc cài sạch trên máy HMU khác. Fixture riêng tư thiếu báo SKIP.
- Chưa nghiệm thu OCR ảnh chữ Việt có dấu bằng corpus bệnh viện; runtime hiện tại chọn en-US. Các fixture OCR nhận diện tên/địa chỉ ở dạng Latin không dấu, không thay thế đánh giá dữ liệu tiếng Việt thực.
- Overlap256px giải quyết seam fixtures đã kiểm; token dài/lớn hơn overlap vẫn là giới hạn ghi shortcut trong source.
- Watermark không tách an toàn và ảnh giao ICD bị chặn để người duyệt xử lý. Nội dung đã mất từ nguồn hỏng không thể tự khôi phục.

## Dữ liệu đo và tái lập

Raw JSON ở `HMU_KhuDinhDanh/benchmarks/results/` giữ từng lần đo/corpus SHA/phiên bản/scope:

- `B0_timing.json`, `B1_corrected_initialopts.json`, `FINAL_timing.json`, `B0_vs_FINAL.json`, `B1_vs_FINAL.json`.
- `B0_extended.json`, `B1_extended_initialproof.json`, `FINAL_watermark_proofopt.json`.
- `B0_native10_confirm.json`, `FINAL_native10_confirm.json`, `SAVE_FINAL_timing.json`, `workers50_confirm.json`.
- `B0_phases.json`, `FINAL_phases.json`; profiler là lượt riêng, không dùng thời gian profiler làm headline.

`B0.json` là exploratory có profiler/chưa đủ nhóm, không dùng tuyên bố tốc độ. Xem [README benchmark](HMU_KhuDinhDanh/benchmarks/README.md). Baseline source/results sinh tự động được git-ignore; tái lập theo base commit và source hashes trước khi dọn workspace.

## Kết luận

15 nhóm lỗi đã được xử lý bằng source và regression tests. Kết quả rõ nhất: vòng duyệt/xuất an toàn hơn, OCR mixed, giảm RAM OCR, giảm độ trễ/payload lưu và tăng tốc scan. Mục tiêu tốc độ mọi nhóm chưa đạt; số đo trên không phải cam kết tăng tốc đồng đều hoặc chứng nhận khử định danh mọi bệnh án.
'''
    (ROOT/'BAO_CAO_TRIEN_KHAI_2026-10-28.md').write_text(report, encoding='utf-8')
    print(f'Report written: {match[1]} tests; measured watermark build hashes match current source.')


if __name__ == '__main__':
    main()
