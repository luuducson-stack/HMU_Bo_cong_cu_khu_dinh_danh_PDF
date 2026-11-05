"""Separate instrumented phase/call counts; never use these as headline timings."""
import argparse
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from benchmark_workflow import build_pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.source_dir).resolve() if args.source_dir else Path(__file__).resolve().parents[1]))
    import engine
    import fitz
    import subprocess
    counts = defaultdict(lambda: {'calls': 0, 'cumulative_seconds': 0.0})
    phase = 'prepare'

    def timed(name, function):
        def call(*a, **kw):
            start = time.perf_counter()
            try:
                return function(*a, **kw)
            finally:
                item = counts[phase + '/' + name]
                item['calls'] += 1
                item['cumulative_seconds'] += time.perf_counter() - start
        return call

    output = {'source_dir': str(Path(engine.__file__).parent),
              'scope': 'Instrumented separate diagnostic run. Nested cumulative times overlap; do not add them.',
              'cases': {}}
    with tempfile.TemporaryDirectory(prefix='hmu_phases_') as td, ExitStack() as stack:
        for name in ('sha', 'char_map', 'span_rects', 'extract_case_seeds', 'analyze_hmu_document',
                     'expand_rects_with_pixel_ink', 'ocr_pdf_pages', 'validate_review', 'apply_review_to_page',
                     'generate_audit_markdown'):
            stack.enter_context(patch.object(engine, name, timed(name, getattr(engine, name))))
        for name in ('get_text', 'get_drawings', 'get_pixmap'):
            stack.enter_context(patch.object(fitz.Page, name, timed('Page.' + name, getattr(fitz.Page, name))))
        stack.enter_context(patch.object(subprocess.Popen, 'communicate', timed('OCR.process_communicate', subprocess.Popen.communicate)))
        for kind in ('native', 'scan'):
            root = Path(td) / kind
            root.mkdir()
            source = root / 'synthetic.pdf'
            build_pdf(source, 10, kind)
            counts.clear()
            phase = 'prepare'
            start = time.perf_counter()
            engine.prepare(source, root / 'job', study_id='PHASE')
            prepared = time.perf_counter()
            phase = 'export'
            engine.export(root / 'job', approve_all=True)
            output['cases'][kind] = {'prepare_seconds': prepared - start,
                                     'export_seconds': time.perf_counter() - prepared,
                                     'measurements': dict(counts)}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output))


if __name__ == '__main__':
    main()
