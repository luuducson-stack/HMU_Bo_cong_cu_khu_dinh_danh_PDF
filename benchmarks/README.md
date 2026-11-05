# Workflow benchmark

## Real-file HTTP acceptance (2026-10-30)

`benchmark_real_workflow.py` measures fresh upload, preparation/OCR, export, audit, QC, publication and PDF download. Each iteration uses a new job. A private reference review may supply page selections only after matching source SHA, policy, DPI and page geometry; fresh job identity, working fingerprint and OCR analysis remain intact. All real outputs stay DRAFT. Applying the reference stands in for human review and is excluded; machine phases are included. Product and runner hashes are captured before import and verified before/after each run. No profiler or other heavy QA should run concurrently.

```powershell
$sourcePdf = 'E:\private\sample.pdf'
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe -X utf8 HMU_KhuDinhDanh\benchmarks\benchmark_real_workflow.py $sourcePdf --root HMU_KhuDinhDanh\HMU_JOBS\acceptance_new --review-job HMU_KhuDinhDanh\HMU_JOBS\verified_reference --output HMU_KhuDinhDanh\HMU_JOBS\acceptance_new.json --runs 3
```

The user authorized proportional acceptance on the real 71-page sample: 127.8–170.4 seconds corresponds to 180–240 seconds per100 pages. This is an extrapolation, not a real100-page measurement. Report each total, median, maximum and sampled process-tree RAM; do not add phase medians to construct a total. Repeated copies of one case cannot establish p95 across different clinical records or field-level recognition precision/recall.

OCR sweep can also accept a real source and its private 200dpi prerenders: `ocr_worker_sweep.py <output.json> 71 3 1,2,4 <source.pdf> <prerender-dir>`. It verifies exact returned OCR maps across counts. Three real71-page repetitions per count gave median49.732s /31.962s /21.858s for1/2/4 workers. Default4 is used for at least64 OCR pages after the real-file sweep (sampled peak about697MiB); smaller batches remain serial. Prerendering uses at most2 separate processes for at least64 pages and completes before OCR starts. Live PAGE_DONE updates and batch deadline cleanup are covered separately. Timeout is per batch, not per page. CLI entry points must retain their `__main__` guard for Windows process spawning; use the benchmark script rather than an stdin snippet when measuring the renderer pool.

Lossless PDF images use zlib level1; OCR PNGs use lossless RGB level1. The exporter writes white mask rows directly into the rendered RGB buffer because the installed PyMuPDF1.26.6 `set_rect` uses Python channel loops. Exact decoded-raster comparisons, protected ROIs and structure checks are required alongside timings. Private reference corrections and patient data stay under ignored `HMU_JOBS/`; never publish a runtime job as a deliverable.

Run from the repository root with the project's Python:

```powershell
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\benchmark_workflow.py --source-dir HMU_KhuDinhDanh\benchmarks\baseline_source --output HMU_KhuDinhDanh\benchmarks\results\B0_timing.json --runs 3
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\benchmark_workflow.py --output HMU_KhuDinhDanh\benchmarks\results\FINAL_timing.json --runs 3
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\benchmark_workflow.py --cases native10 --runs 1 --profile --output HMU_KhuDinhDanh\benchmarks\results\profile.json
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\ocr_worker_sweep.py HMU_KhuDinhDanh\benchmarks\results\workers.json
```

The benchmark creates only synthetic PDFs in a temporary directory. Sources use fixed PDF dates and omit random PDF document IDs, so matching corpus SHA-256 identifies equivalent inputs. It tests native 10/150 pages, image-only 10/50 pages, mixed 10 pages, a 50-file/two-page case, vector 20 pages and three image-rich pages. The image-rich fixture is not a real high-resolution hospital photograph.

Every run starts with a new job directory. Median/range across three runs includes normal OS cache effects; these are not guaranteed cold filesystem runs. OCR worker sweep compares exact returned page maps at 1/2/4/6 workers, three runs each.

Memory scope: `peak_python_rss_bytes` is the operating system's cumulative peak working set of this Python process. `peak_task_sampled_rss_bytes` sums the current Python process and its live descendant processes, sampled every 100ms. This includes PowerShell OCR children but is a sampled peak, not an exact peak. Descendants that finish between samples can be missed. Memory is comparable only when the same instrumentation/corpus/run order is used.

Profiling is intentionally separate from timed runs: Python profiler overhead can otherwise overstate gains from replacing Python loops with native calls. The `.prof` file is readable with stdlib `pstats`.

The benchmark reports prepare/export/total wall-clock times and job bytes. It does not claim browser interaction p95 or per-OCR-phase timing. Use HTTP/UI traces for those metrics. Do not interpret `approve_all=True` inside this synthetic harness as an approved real medical-record workflow; this is only fixture setup for measuring export.

The initial baseline source checkpoint is private benchmark infrastructure and must stay ignored along with results and generated data. Do not copy patient data into these directories or share an entire runtime job directory.

## Measurement snapshots from this implementation

- `results/B0_timing.json`: original source, original eight corpora, three measurements each, no explicit warmup, no profiler. Preserve this historical baseline.
- `results/B1_corrected_initialopts.json`: first corrected implementation with some small optimizations already included. This is **not** a reconstructed pure-correctness-before-any-optimization baseline. Same original eight corpus hashes.
- `results/FINAL_timing.json`: latest frozen implementation measured on the original eight corpora under the matching historical protocol. Check source hashes and report generation date before reusing.
- `results/workers.json`: preliminary ten-page 1/2/4/6 worker comparison.
- `results/workers50_confirm.json`: isolated fifty-page confirmation, three measurements at one and six workers; exact OCR maps checked equal. Invoke `ocr_worker_sweep.py <output.json> 50 3 1,6` to reproduce.
- `results/SAVE_timing.json`: separate loopback HTTP save benchmark owned by the integration work; it does not measure canvas/browser rendering p95.
- `benchmark_phases.py`: separately instrumented stage/count evidence; do not mix its instrumented timings into unprofiled end-to-end speed claims.

Extended representative cases are available with `--cases watermark10,largephoto2 --warmup 1 --runs 3`. Run original and revised source into distinct extended output files, compare only matching extended hashes. These cases include diagonal watermark crossing clinical text plus 400 vector strokes per page, and 2400×3200 pixel images on 1200×1600-point pages. Ground-truth assertions check selected patient-name regions are white and specified clinical text/image regions stay within mean per-channel pixel error1.0. These checks do not certify all pixels contain no PII.

For comparison:

```powershell
.\HMU_KhuDinhDanh\.venv\Scripts\python.exe HMU_KhuDinhDanh\benchmarks\compare_measurements.py <before.json> <after.json> <comparison.json>
```

The comparison refuses missing/different corpus groups or mismatched corpus SHA-256. Negative percentage change means improvement. A correct mixed-page implementation necessarily performs OCR that the original skipped; a slowdown in that group must be reported with that explanation, not hidden or normalized away.

## Batch và QC đầu ra (31/10/2026)

`benchmark_batch.py --manifest <private.json> --destination <new-directory> --jobs 2 --ocr-workers 1 --render-workers 1` dùng manifest có `cases: [{case_id, source_path_private, source_sha256}]`. Mỗi lần đo cần thư mục mới để không dùng lại job cache. Clock gồm đọc/hash nguồn, enqueue, copy, prepare/OCR, export/audit và OCR kiểm chính PDF đầu ra. OS cache không được kiểm soát. RAM là RSS cây tiến trình lấy mẫu100ms, có báo khoảng lấy mẫu lớn nhất.

`exported_files_per_hour` chỉ là công suất tạo PDF chờ duyệt. `machine_clear_files_per_hour` chỉ đếm các hồ sơ duy nhất QC máy PASS; còn cảnh báo/thiếu trang không được tính đạt. `ready_files_per_hour` cần duyệt và bàn giao thực. Không lấy số attempt hoặc bản sao PDF làm số bệnh án độc lập. Các phép so pixel/ROI độc lập chạy sau cửa sổ đo; thời gian này phải được báo riêng nếu đưa vào quy trình nghiệm thu vận hành.

`benchmark_accuracy.py` tính vùng thiếu một phần là FN, union các proposal cùng lớp, kiểm mask ăn vùng giữ. Kiểm actual-PDF trắng trong vùng nhãn chỉ áp dụng vùng được gắn nhãn; precision và bảo toàn lâm sàng toàn diện cần nhãn âm độc lập đầy đủ. Hai mẫu hồi quy không thay corpus30/holdout15/pilot100.
