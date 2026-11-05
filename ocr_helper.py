"""Offline OCR helper using Windows built-in Windows.Media.Ocr.OcrEngine.

Converts textless/scanned/vector-curve PDF pages into (text, chars) maps
compatible with engine.char_map(page) and engine.span_rects(chars, a, b).
"""
import concurrent.futures
import functools
import hashlib
import json
import math
import struct
import queue
import time
import collections
import os
import platform
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
import fitz


@functools.lru_cache(maxsize=8)
def ocr_settings_fingerprint(dpi=200):
    """Fingerprint the current runtime once; a new app process rechecks its OCR language."""
    query = """Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language('en-US')))}
if ($null -eq $engine) {throw 'OCR unavailable'}
[Console]::WriteLine($engine.RecognizerLanguage.LanguageTag)
[Console]::WriteLine([Windows.Media.Ocr.OcrEngine]::MaxImageDimension)
"""
    try:
        result = subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,text=True,timeout=15,check=True)
        language = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        language = 'OCR_UNAVAILABLE'
    data = [hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),dpi,platform.platform(),language]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()

_PS_OCR_SCRIPT = r"""
param(
    [Parameter(Mandatory=$true)][string]$ManifestPath,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $lang = New-Object Windows.Globalization.Language('en-US')
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}
if ($null -eq $engine) { throw 'No Windows OCR engine/language is installed' }

$raw = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$items = if ($raw -is [System.Array]) { $raw } else { @($raw) }
$out = @{}

foreach ($item in $items) {
    if ($null -eq $item) { continue }
    $pno = [string]$item.page
    $imgPath = [string]$item.path
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    if ($bitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $bitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { throw 'OCR tile exceeds Windows OCR maximum image dimension' }
    $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $words = New-Object System.Collections.Generic.List[object]
    foreach ($line in $res.Lines) {
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            $words.Add(@{
                t = $w.Text
                x = [double]$r.X
                y = [double]$r.Y
                w = [double]$r.Width
                h = [double]$r.Height
            })
        }
    }
    $out[[string]$item.key] = $words
    $stream.Dispose()
    $bitmap.Dispose()
    [Console]::Out.WriteLine("PAGE_DONE:$pno")
    [Console]::Out.Flush()
}

$json = $out | ConvertTo-Json -Depth 6 -Compress
[System.IO.File]::WriteAllText($OutputPath, $json, [System.Text.Encoding]::UTF8)
"""


def _group_words_into_visual_lines(words: List[dict], sx: float, sy: float) -> List[List[dict]]:
    """Group OCR words into visual horizontal rows sorted top-to-bottom, left-to-right."""
    scaled = []
    for w in words:
        text = str(w.get("t", "")).strip()
        if not text:
            continue
        x0 = float(w["x"]) * sx
        y0 = float(w["y"]) * sy
        x1 = (float(w["x"]) + float(w["w"])) * sx
        y1 = (float(w["y"]) + float(w["h"])) * sy
        yc = 0.5 * (y0 + y1)
        scaled.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "yc": yc, "h": max(1.0, y1 - y0)})

    scaled.sort(key=lambda item: (item["yc"], item["x0"]))
    rows: List[List[dict]] = []
    row_centers: List[float] = []
    for item in scaled:
        placed = False
        tol = max(5.5, item["h"] * 0.55)
        for idx, rc in enumerate(row_centers):
            if abs(item["yc"] - rc) <= tol:
                rows[idx].append(item)
                # Update running row center
                row_centers[idx] = sum(x["yc"] for x in rows[idx]) / len(rows[idx])
                placed = True
                break
        if not placed:
            rows.append([item])
            row_centers.append(item["yc"])

    for r in rows:
        r.sort(key=lambda item: item["x0"])
    return rows


def build_char_map_from_ocr_words(
    words: List[dict], page_width: float, page_height: float, pix_width: int, pix_height: int
) -> Tuple[str, List[Tuple[int, int, Tuple[float, float, float, float], str]]]:
    sx = page_width / max(1, pix_width)
    sy = page_height / max(1, pix_height)
    rows = _group_words_into_visual_lines(words, sx, sy)
    text_parts: List[str] = []
    chars: List[Tuple[int, int, Tuple[float, float, float, float], str]] = []
    offset = 0
    for line_id, row in enumerate(rows):
        for w_idx, w in enumerate(row):
            if w_idx > 0:
                prev = row[w_idx - 1]
                space_bbox = (prev["x1"], min(prev["y0"], w["y0"]), max(prev["x1"] + 1.0, w["x0"]), max(prev["y1"], w["y1"]))
                chars.append((offset, line_id, space_bbox, " "))
                text_parts.append(" ")
                offset += 1
            w_text = w["text"]
            n_ch = max(1, len(w_text))
            ch_w = (w["x1"] - w["x0"]) / n_ch
            for c_idx, ch in enumerate(w_text):
                cx0 = max(0.0, min(page_width - 0.01, w["x0"] + c_idx * ch_w))
                cx1 = min(page_width, max(cx0 + 0.01, w["x0"] + (c_idx + 1) * ch_w))
                cy0 = max(0.0, min(page_height - 0.01, w["y0"]))
                cy1 = min(page_height, max(cy0 + 0.01, w["y1"]))
                chars.append((offset, line_id, (cx0, cy0, cx1, cy1), ch))
                text_parts.append(ch)
                offset += 1
        last = row[-1]
        nl_bbox = (min(page_width,last["x1"]), max(0,min(page_height,last["y0"])), min(page_width, last["x1"] + 1.0), min(page_height,last["y1"]))
        chars.append((offset, line_id, nl_bbox, "\n"))
        text_parts.append("\n")
        offset += 1
    return "".join(text_parts), chars


def _tile_origins(length, limit=4096, overlap=256):
    # shortcut: tokens wider than 256px can cross tiles; increase overlap for unusually large text.
    if length <= limit:
        return [0]
    return sorted(set(list(range(0, length - limit, limit - overlap)) + [length - limit]))


def _deduplicate_words(words):
    kept = []
    for word in words:
        rect = fitz.Rect(word['x'], word['y'], word['x']+word['w'], word['y']+word['h'])
        if any(word['t'].casefold() == previous['t'].casefold() and
               (rect & other).get_area() / max(1, min(rect.get_area(), other.get_area())) >= .8
               for previous, other in kept):
            continue
        kept.append((word, rect))
    return [word for word, _ in kept]


def _read_ocr_process(proc, timeout, on_line):
    events=queue.Queue(); errors=[]
    def stdout():
        try:
            for line in proc.stdout: events.put(line)
        finally: events.put(None)
    def stderr():
        errors.extend(proc.stderr.readlines())
    readers=[threading.Thread(target=stdout,daemon=True),threading.Thread(target=stderr,daemon=True)]
    for reader in readers: reader.start()
    deadline=time.monotonic()+timeout
    try:
        while True:
            line=events.get(timeout=max(.001,deadline-time.monotonic()))
            if line is None: break
            on_line(line.strip())
        proc.wait(timeout=max(.001,deadline-time.monotonic()))
    except (queue.Empty,subprocess.TimeoutExpired):
        proc.kill();proc.wait()
        raise RuntimeError(f'OCR batch exceeded {timeout}s')
    except Exception:
        if proc.poll() is None: proc.kill()
        proc.wait()
        raise
    finally:
        for reader in readers: reader.join(timeout=5)
    return ''.join(errors)


def ocr_pdf_pages(
    pdf_path,
    page_numbers: List[int],
    dpi: int = 200,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    pre_rendered_dir: Optional[Path] = None,
    *, max_workers: Optional[int] = None, timeout: int = 120,
) -> Dict[int, Tuple[str, List[Tuple[int, int, Tuple[float, float, float, float], str]]]]:
    if max_workers is not None and (type(max_workers) is not int or not 1 <= max_workers <= 6):
        raise ValueError('OCR workers must be between 1 and 6')
    pdf_path = Path(pdf_path)
    if not page_numbers:
        return {}
    total = len(page_numbers)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        manifest = []
        page_dims = {}
        with fitz.open(pdf_path) as doc:
            for pno in page_numbers:
                page = doc[pno - 1]
                rotation = page.rotation
                # OCR upright pixels; return native PDF coordinates even for rotated pages.
                page.set_rotation(0)
                pre_img = Path(pre_rendered_dir) / f"{pno}.png" if pre_rendered_dir and not rotation else None
                if pre_img and pre_img.is_file():
                    with pre_img.open('rb') as png: header = png.read(24)
                    if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
                        raise ValueError('Invalid prerendered PNG')
                    width, height = struct.unpack('>II', header[16:24])
                    if not width or not height: raise ValueError('Empty prerendered PNG')
                    pix = fitz.Pixmap(str(pre_img)) if width > 4096 or height > 4096 else None
                else:
                    pix = page.get_pixmap(dpi=dpi, alpha=False)
                    img_path = tmp / f"p_{pno}.png"
                    pix.save(img_path)
                    pre_img = img_path
                    width, height = pix.width, pix.height
                page_dims[pno] = (page.rect.width, page.rect.height, width, height)
                for y in _tile_origins(height):
                    for x in _tile_origins(width):
                        key = f'{pno}_{x}_{y}'
                        path = pre_img
                        if width > 4096 or height > 4096:
                            bounds = fitz.IRect(x,y,min(x+4096,pix.width),min(y+4096,pix.height))
                            tile = fitz.Pixmap(pix.colorspace, bounds, pix.alpha)
                            tile.copy(pix, bounds)
                            tile.set_origin(0, 0)
                            path = tmp / f'{key}.png'
                            tile.save(path)
                        manifest.append({'page':pno, 'key':key, 'x':x, 'y':y, 'path':str(path.resolve())})

        script_path = tmp / "run_ocr.ps1"
        script_path.write_text(_PS_OCR_SCRIPT, encoding="utf-8")

        # Keep short jobs serial; 2 workers reduced real71 median OCR from49.73s to31.96s.
        max_workers = min(max_workers or (4 if total >= 64 else 1), len(manifest))
        batches = [manifest[i::max_workers] for i in range(max_workers) if manifest[i::max_workers]]

        lock = threading.Lock()
        completed_keys = set()
        completed_tiles = collections.Counter()
        needed_tiles = collections.Counter(item['page'] for item in manifest)

        def _run_batch(b_idx: int, batch_items: list) -> dict:
            m_path = tmp / f"manifest_{b_idx}.json"
            o_path = tmp / f"ocr_out_{b_idx}.json"
            m_path.write_text(json.dumps(batch_items, ensure_ascii=False), encoding="utf-8")
            with subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path),
                 "-ManifestPath", str(m_path), "-OutputPath", str(o_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            ) as proc:
                def live_progress(line):
                    if not line.startswith('PAGE_DONE:'): return
                    pno=int(line.split(':',1)[1])
                    if pno not in needed_tiles: raise RuntimeError('Unexpected OCR page')
                    with lock:
                        completed_tiles[pno]+=1
                        cur=sum(completed_tiles[p] >= count for p,count in needed_tiles.items())
                    if progress_cb: progress_cb(cur,total)
                stderr_txt = _read_ocr_process(proc, timeout, live_progress)
                ret = proc.returncode
            if ret != 0:
                raise RuntimeError(f"OCR PowerShell failed (exit {ret}): {stderr_txt.strip()}")
            result = json.loads(o_path.read_text(encoding="utf-8-sig"))
            if set(result) != {item['key'] for item in batch_items}:
                raise RuntimeError('OCR returned incomplete page tiles')
            with lock:
                completed_keys.update(result)
                cur = sum(all(item['key'] in completed_keys for item in manifest if item['page'] == pno) for pno in page_numbers)
            if progress_cb:
                progress_cb(cur, total)
            return result

        raw_out = {}
        if len(batches) == 1:
            raw_out.update(_run_batch(0, batches[0]))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batches)) as pool:
                futures = [pool.submit(_run_batch, idx, b) for idx, b in enumerate(batches)]
                for fut in concurrent.futures.as_completed(futures):
                    raw_out.update(fut.result())

    results = {}
    for pno in page_numbers:
        words = []
        page_tiles = [item for item in manifest if item['page'] == pno]
        for item in page_tiles:
            for word in raw_out[item['key']] or []:
                words.append({**word,'x':word['x']+item['x'],'y':word['y']+item['y']})
        pw, ph, pix_w, pix_h = page_dims[pno]
        text, chars = build_char_map_from_ocr_words(_deduplicate_words(words) if len(page_tiles)>1 else words, pw, ph, pix_w, pix_h)
        # Pages were rendered at rotation 0, so these already are native coordinates.
        results[pno] = (text, chars)
    return results


def ocr_pdf_regions(pdf_path, regions, *, dpi=200, progress_cb=None, max_workers=None):
    """Retry bounded regions through the same OCR backend; return native PDF boxes."""
    if not regions:
        return {}
    if type(dpi) is not int or not 150 <= dpi <= 600:
        raise ValueError('OCR DPI must be between 150 and 600')
    transforms=[];keys=set()
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'regions.pdf'
        with fitz.open(pdf_path) as source, fitz.open() as tiles:
            for region in regions:
                key=region['key'];pn=region['page'];rotation=region['rotation'];values=region['rect']
                if not isinstance(key,str) or not key or key in keys or type(pn) is not int or not 1<=pn<=len(source):
                    raise ValueError('Invalid OCR region identity')
                if rotation not in (0,90,270) or len(values)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
                    raise ValueError('Invalid OCR region geometry')
                page=source[pn-1];page.set_rotation(0);rect=fitz.Rect(values)
                if rect.is_empty or not page.rect.contains(rect):
                    raise ValueError('OCR region outside page')
                matrix=fitz.Matrix(dpi/72,dpi/72).prerotate(rotation)
                pix=page.get_pixmap(matrix=matrix,clip=rect,alpha=False)
                tile=tiles.new_page(width=pix.width*72/dpi,height=pix.height*72/dpi)
                tile.insert_image(tile.rect,stream=pix.tobytes('png'))
                transforms.append((key,matrix,pix.x,pix.y));keys.add(key)
            tiles.save(path)
        maps=ocr_pdf_pages(path,list(range(1,len(regions)+1)),dpi=dpi,progress_cb=progress_cb,max_workers=max_workers)
    results={}
    for pn,(key,matrix,x,y) in enumerate(transforms,1):
        text,chars=maps[pn]
        to_pixels=fitz.Matrix(dpi/72,0,0,dpi/72,x,y)
        results[key]=(text,[(off,line,tuple(fitz.Rect(bb)*to_pixels*~matrix),ch) for off,line,bb,ch in chars])
    return results
