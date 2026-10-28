"""Offline OCR helper using Windows built-in Windows.Media.Ocr.OcrEngine.

Converts textless/scanned/vector-curve PDF pages into (text, chars) maps
compatible with engine.char_map(page) and engine.span_rects(chars, a, b).
"""
import concurrent.futures
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
import fitz

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
    $out[$pno] = $words
    $stream.Dispose()
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
                cx0 = max(0.0, min(page_width, w["x0"] + c_idx * ch_w))
                cx1 = max(cx0 + 0.5, min(page_width, w["x0"] + (c_idx + 1) * ch_w))
                cy0 = max(0.0, min(page_height, w["y0"]))
                cy1 = max(cy0 + 0.5, min(page_height, w["y1"]))
                chars.append((offset, line_id, (cx0, cy0, cx1, cy1), ch))
                text_parts.append(ch)
                offset += 1
        last = row[-1]
        nl_bbox = (last["x1"], last["y0"], min(page_width, last["x1"] + 1.0), last["y1"])
        chars.append((offset, line_id, nl_bbox, "\n"))
        text_parts.append("\n")
        offset += 1
    return "".join(text_parts), chars


def ocr_pdf_pages(
    pdf_path,
    page_numbers: List[int],
    dpi: int = 200,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    pre_rendered_dir: Optional[Path] = None,
) -> Dict[int, Tuple[str, List[Tuple[int, int, Tuple[float, float, float, float], str]]]]:
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
                pre_img = Path(pre_rendered_dir) / f"{pno}.png" if pre_rendered_dir else None
                if pre_img and pre_img.is_file():
                    pix = fitz.Pixmap(str(pre_img))
                    manifest.append({"page": pno, "path": str(pre_img.resolve())})
                    page_dims[pno] = (page.rect.width, page.rect.height, pix.width, pix.height)
                else:
                    pix = page.get_pixmap(dpi=dpi, alpha=False)
                    img_path = tmp / f"p_{pno}.png"
                    pix.save(img_path)
                    manifest.append({"page": pno, "path": str(img_path)})
                    page_dims[pno] = (page.rect.width, page.rect.height, pix.width, pix.height)

        script_path = tmp / "run_ocr.ps1"
        script_path.write_text(_PS_OCR_SCRIPT, encoding="utf-8")

        max_workers = min(6, max(1, (os.cpu_count() or 4) - 2), total)
        batches = [manifest[i::max_workers] for i in range(max_workers) if manifest[i::max_workers]]

        lock = threading.Lock()
        done_count = 0

        def _run_batch(b_idx: int, batch_items: list) -> dict:
            nonlocal done_count
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
                assert proc.stdout is not None
                for line in proc.stdout:
                    if line.startswith("PAGE_DONE:"):
                        with lock:
                            done_count += 1
                            cur = done_count
                        if progress_cb:
                            progress_cb(cur, total)
                stderr_txt = proc.stderr.read() if proc.stderr else ""
                ret = proc.wait()
            if ret != 0:
                raise RuntimeError(f"OCR PowerShell failed (exit {ret}): {stderr_txt.strip()}")
            return json.loads(o_path.read_text(encoding="utf-8-sig"))

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
        words = raw_out.get(str(pno), []) or []
        pw, ph, pix_w, pix_h = page_dims[pno]
        results[pno] = build_char_map_from_ocr_words(words, pw, ph, pix_w, pix_h)
    return results
