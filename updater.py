from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = 'luuducson-stack/HMU_Bo_cong_cu_khu_dinh_danh_PDF'
BRANCH = 'dev'
REFS_URL = f'https://github.com/{REPO}.git/info/refs?service=git-upload-pack'
ZIP_URL = f'https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}'
USER_AGENT = {'User-Agent': 'hmu-updater'}

EXCLUDED_DIR_PREFIXES = ('HMU_JOBS', '.venv')
STATE_FILENAME = 'updater_state.json'
BACKUP_DIRNAME = 'update_backup'
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
DEFAULT_CORE_MODULES = (
    'app',
    'engine',
    'hmu_recognizers',
    'ocr_helper',
    'output_qc',
    'batch',
    'batch_runtime',
    'batch_worker',
    'delivery',
    'error_pipeline',
    'updater',
)


class UpdateError(RuntimeError):
    """A user-facing update failure; the message is Vietnamese and safe to show as is."""


def _read_updater_state(state_dir: Path) -> dict[str, Any]:
    state_file = state_dir / STATE_FILENAME
    if not state_file.is_file():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_updater_state(state_dir: Path, data: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / STATE_FILENAME
    tmp_file = state_dir / f'{STATE_FILENAME}.tmp'
    tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp_file.replace(state_file)


def _is_excluded_path(rel_path: str) -> bool:
    norm = rel_path.strip().strip('"').replace('\\', '/')
    while norm.startswith('./'):
        norm = norm[2:]
    for prefix in EXCLUDED_DIR_PREFIXES:
        if norm == prefix or norm.startswith(prefix + '/'):
            return True
    return False


def _fetch(url: str, timeout: int | float, limit: int, attempts: int = 3) -> bytes:
    # Observed 2026-11-12: codeload.github.com sometimes stalls a read for the whole timeout, then the next request takes 0.6s.
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=timeout) as resp:
                data = resp.read(limit + 1)
            break
        except (OSError, ValueError) as exc:  # URLError, HTTPError and timeouts are all OSError
            if attempt == attempts - 1:
                raise UpdateError('Không kết nối được GitHub. Hãy kiểm tra Internet rồi thử lại.') from exc
    if len(data) > limit:
        raise UpdateError('Phản hồi từ GitHub quá lớn, đã hủy để đảm bảo an toàn.')
    return data


def latest_commit(timeout: int | float = 10) -> str:
    text = _fetch(REFS_URL, timeout, 1 << 20).decode('utf-8', 'replace')
    found = re.search(rf'([0-9a-f]{{40}}) refs/heads/{re.escape(BRANCH)}\n', text)
    if not found:
        raise UpdateError(f'Không tìm thấy nhánh {BRANCH} trên GitHub.')
    return found.group(1)


def current_version(state_dir: Path | str) -> dict[str, Any]:
    state_dir = Path(state_dir)
    state = _read_updater_state(state_dir)
    commit = state.get('commit')
    commit = commit if isinstance(commit, str) and SHA_RE.match(commit) else None
    return {
        'commit': commit,
        'short_commit': commit[:7] if commit else '',
        'installed_at': state.get('installed_at'),
        'can_rollback': (state_dir / BACKUP_DIRNAME / 'manifest.json').is_file(),
    }


def check_for_updates(state_dir: Path | str, timeout: int | float = 10) -> dict[str, Any]:
    current = current_version(state_dir)
    latest = latest_commit(timeout)
    return {
        'current': current,
        'latest_commit': latest,
        'latest_short_commit': latest[:7],
        'update_available': current['commit'] != latest,
    }


def _get_pip_python_executable(repo_dir: Path) -> str:
    win_py = repo_dir / '.venv' / 'Scripts' / 'python.exe'
    if win_py.is_file() and (os.name == 'nt' or os.access(win_py, os.X_OK)):
        return str(win_py)
    posix_py = repo_dir / '.venv' / 'bin' / 'python'
    if posix_py.is_file() and os.access(posix_py, os.X_OK):
        return str(posix_py)
    return sys.executable


def _install_requirements(repo_dir: Path) -> None:
    req_file = repo_dir / 'requirements.txt'
    if not req_file.is_file():
        return
    py_exe = _get_pip_python_executable(repo_dir)
    proc = subprocess.run(
        [py_exe, '-m', 'pip', 'install', '-r', str(req_file)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=300,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or 'pip install failed').strip()
        raise RuntimeError(f'Lỗi cài đặt requirements.txt: {err}')


def _run_smoke_test(repo_dir: Path, smoke_modules: tuple[str, ...] | None = None) -> None:
    bad_files: list[str] = []
    for py_file in sorted(repo_dir.rglob('*.py')):
        try:
            rel = py_file.relative_to(repo_dir).as_posix()
        except ValueError:
            continue
        if _is_excluded_path(rel):
            continue
        raw = py_file.read_bytes()
        if b'\x00' in raw or raw.startswith(b'\xff'):
            bad_files.append(rel)
            continue
        try:
            compile(raw, str(py_file), 'exec')
        except SyntaxError as exc:
            raise RuntimeError(f'Lỗi cú pháp trong {rel}: {exc}') from exc

    if bad_files:
        raise RuntimeError(
            f'Phát hiện file mã nguồn bị hỏng (0xFF/null bytes): {", ".join(bad_files)}'
        )

    if smoke_modules is None:
        modules_to_test = tuple(
            mod for mod in DEFAULT_CORE_MODULES if (repo_dir / f'{mod}.py').is_file()
        )
    else:
        modules_to_test = tuple(smoke_modules)

    if modules_to_test:
        import_stmt = 'import ' + ', '.join(modules_to_test)
        proc = subprocess.run(
            [sys.executable, '-c', import_stmt],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or 'smoke-test import failed').strip()
            raise RuntimeError(f'Smoke-test import thất bại ({import_stmt}): {err}')


MAX_ZIP_BYTES = 64 << 20
MAX_UNPACKED_BYTES = 256 << 20


def _is_protected(rel: str) -> bool:
    """Paths the updater must never write: patient data, the venv, and the launcher that is running right now."""
    low = rel.lower()  # Windows paths ignore case and trailing dots/spaces, so compare in that normal form
    top = low.split('/', 1)[0].rstrip('. ')
    return low == 'mo_cong_cu.bat' or top.startswith(('hmu_jobs', 'ket_qua_test')) or top in ('.venv', '.git', '.superpowers')


def _read_release(data: bytes) -> tuple[str, dict[str, bytes]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UpdateError('Gói cập nhật tải về bị lỗi. Hãy thử lại.') from exc
    sha = archive.comment.decode('ascii', 'ignore')
    if not SHA_RE.match(sha):
        raise UpdateError('Không xác minh được gói cập nhật (thiếu mã commit). Đã hủy.')
    if sum(i.file_size for i in archive.infolist()) > MAX_UNPACKED_BYTES:
        raise UpdateError('Gói cập nhật lớn bất thường. Đã hủy để đảm bảo an toàn.')
    files: dict[str, bytes] = {}
    for info in archive.infolist():
        name = info.filename.replace('\\', '/')
        parts = name.split('/')
        if name.startswith('/') or ':' in name or '..' in parts:  # ':' = drive letter or NTFS stream
            raise UpdateError('Gói cập nhật không hợp lệ (đường dẫn nguy hiểm). Đã hủy.')
        rel = '/'.join(parts[1:])  # parts[0] is the GitHub root folder
        if info.is_dir() or not rel or _is_protected(rel):
            continue
        files[rel] = archive.read(info)
    return sha, files


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _restore(repo: Path, backup_dir: Path) -> dict[str, Any]:
    manifest = json.loads((backup_dir / 'manifest.json').read_text(encoding='utf-8'))
    for rel in manifest['replaced']:
        _write_atomic(repo / rel, (backup_dir / 'files' / rel).read_bytes())
    for rel in manifest['added']:
        (repo / rel).unlink(missing_ok=True)
    return manifest


def apply_update(
    repo_dir: Path | str,
    state_dir: Path | str,
    run_pip: bool = True,
    run_smoke_test: bool = True,
    smoke_modules: tuple[str, ...] | None = ('app',),
    timeout: int | float = 20,
) -> dict[str, Any]:
    repo, state_dir = Path(repo_dir), Path(state_dir)
    sha, files = _read_release(_fetch(ZIP_URL, timeout, MAX_ZIP_BYTES))
    old = current_version(state_dir)['commit']
    if sha == old:
        return {'status': 'noop', 'from_commit': old, 'to_commit': sha, 'pip_installed': False, 'changed_files': 0}

    changed = {rel: data for rel, data in files.items() if not (repo / rel).is_file() or (repo / rel).read_bytes() != data}
    backup_new = state_dir / (BACKUP_DIRNAME + '.new')
    shutil.rmtree(backup_new, ignore_errors=True)
    replaced = [rel for rel in changed if (repo / rel).is_file()]
    for rel in replaced:
        (backup_new / 'files' / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, backup_new / 'files' / rel)
    manifest = {'from_commit': old, 'to_commit': sha, 'replaced': replaced, 'added': [rel for rel in changed if rel not in replaced]}
    backup_new.mkdir(parents=True, exist_ok=True)
    (backup_new / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')

    pip_installed = False
    try:
        for rel, data in changed.items():
            _write_atomic(repo / rel, data)
        if run_pip and 'requirements.txt' in changed:
            _install_requirements(repo)  # shortcut: newly installed packages are not uninstalled on restore, harmless
            pip_installed = True
        if run_smoke_test:
            _run_smoke_test(repo, smoke_modules)
    except Exception as exc:
        _restore(repo, backup_new)
        shutil.rmtree(backup_new, ignore_errors=True)
        raise UpdateError(f'Cập nhật thất bại, đã khôi phục bản cũ: {exc}') from exc
    # shortcut: files deleted on dev stay on disk (harmless); upgrade if a stale module ever breaks an import

    shutil.rmtree(state_dir / BACKUP_DIRNAME, ignore_errors=True)
    os.replace(backup_new, state_dir / BACKUP_DIRNAME)
    _write_updater_state(state_dir, {'commit': sha, 'previous_commit': old, 'installed_at': datetime.now(timezone.utc).isoformat()})
    return {'status': 'updated', 'from_commit': old, 'to_commit': sha, 'pip_installed': pip_installed, 'changed_files': len(changed)}


def rollback(
    repo_dir: Path | str,
    state_dir: Path | str,
    run_pip: bool = True,
    run_smoke_test: bool = True,
    smoke_modules: tuple[str, ...] | None = ('app',),
) -> dict[str, Any]:
    repo, state_dir = Path(repo_dir), Path(state_dir)
    backup = state_dir / BACKUP_DIRNAME
    if not (backup / 'manifest.json').is_file():
        raise UpdateError('Không có bản trước để quay lại.')
    manifest = _restore(repo, backup)
    try:
        if run_pip and 'requirements.txt' in manifest['replaced']:
            _install_requirements(repo)
        if run_smoke_test:
            _run_smoke_test(repo, smoke_modules)
    except Exception as exc:
        raise UpdateError(f'Quay lại bản trước thất bại: {exc}') from exc
    shutil.rmtree(backup, ignore_errors=True)
    _write_updater_state(state_dir, {'commit': manifest['from_commit'], 'installed_at': datetime.now(timezone.utc).isoformat()})
    return {'status': 'rolled_back', 'to_commit': manifest['from_commit']}
