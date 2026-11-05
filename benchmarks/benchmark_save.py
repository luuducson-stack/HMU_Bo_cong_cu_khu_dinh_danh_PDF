"""Compare legacy full-document save with revision-checked per-page save over HTTP."""
import argparse
import json
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fitz
import engine
from app import create_server


def request(url, body=None, token=None):
    raw = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-HMU-Token'] = token
    with urllib.request.urlopen(urllib.request.Request(url, raw, headers), timeout=60) as response:
        return json.load(response), len(raw or b'')


def measure(base, count, modern):
    state, _ = request(base + '/state')
    data, token = state['review'], state['token']
    durations, payloads = [], []
    for n in range(count + 1):
        page = data['pages'][n % len(data['pages'])]
        page['note'] = f'Synthetic benchmark note {n}'
        if modern:
            body = dict(job_id=data['job_id'], revision=data['revision'], page=page['page'],
                        reviewed=page['reviewed'], manual_rects=page['manual_rects'], note=page['note'],
                        selections=[dict(id=q['id'], selected=q['selected']) for q in page['proposals']])
        else:
            body = data
        start = time.perf_counter()
        result, size = request(base + ('/save_page' if modern else '/save'), body, token)
        elapsed = time.perf_counter() - start
        assert result['saved']
        if modern:
            data['revision'] = result['revision']
        if n:
            durations.append(elapsed)
            payloads.append(size)
    return dict(samples=count, median_seconds=statistics.median(durations),
                p95_seconds=sorted(durations)[int(.95 * (count - 1))],
                median_request_bytes=statistics.median(payloads))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--samples', type=int, default=30)
    args = ap.parse_args()
    if args.samples < 20:
        ap.error('At least 20 samples required for p95')
    baseline = ROOT / 'benchmarks/baseline_source'
    if not (baseline / 'app.py').exists():
        ap.error('Preserved original app.py is required')
    with tempfile.TemporaryDirectory(prefix='hmu_save_benchmark_') as td:
        root = Path(td)
        source = root / 'synthetic.pdf'
        with fitz.open() as doc:
            for _ in range(150):
                p = doc.new_page(width=500, height=300)
                p.insert_text((30, 50), 'Ho ten: Nguyen Van An')
                p.insert_text((30, 100), 'Clinical C34 / Glucose 5.2')
            doc.save(source)
        # Build each job with its own source revision; no test or production data.
        subprocess.run([sys.executable, str(baseline / 'engine.py'), 'prepare', str(source),
                        '--job', str(root / 'old')], check=True, capture_output=True)
        engine.prepare(source, root / 'new')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(baseline / 'app.py'), '--no-browser',
                                 '--port', str(port), '--job', str(root / 'old'), '--root', str(root / 'jobs')],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        server = create_server(root / 'jobs', root / 'new', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError(proc.stderr.read().decode(errors='replace'))
                try:
                    request(f'http://127.0.0.1:{port}/state')
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(.05)
            else:
                raise RuntimeError('Legacy HTTP server did not start')
            result = dict(pages=150, warmup_per_method=1, scope='Loopback HTTP save; UI rendering not measured',
                          before=measure(f'http://127.0.0.1:{port}', args.samples, False),
                          after=measure(f'http://127.0.0.1:{server.server_port}', args.samples, True))
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            proc.terminate()
            proc.communicate(timeout=10)


if __name__ == '__main__':
    main()
