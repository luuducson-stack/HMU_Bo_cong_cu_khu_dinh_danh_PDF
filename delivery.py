"""Publish completed PDF folders and export a reviewed local case."""
from contextlib import contextmanager
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import sys
import time

import engine
from engine import export, save_json

_WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}


def is_valid_workspace_name(name: str) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    trimmed = name.strip()
    if trimmed in {'.', '..'} or '..' in trimmed:
        return False
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', trimmed):
        return False
    if trimmed.endswith('.') or trimmed.endswith(' '):
        return False
    base = trimmed.split('.')[0].upper()
    if base in _WINDOWS_RESERVED_NAMES:
        return False
    return True


def resolve_desktop_path(override_base: Path | None = None) -> Path:
    if override_base is not None:
        return Path(override_base).resolve()
    env_desktop = os.environ.get("HMU_DESKTOP_PATH")
    if env_desktop:
        return Path(env_desktop).resolve()

    if os.name == 'nt' or sys.platform == 'win32':
        # 1. Windows Shell SHGetKnownFolderPath (FOLDERID_Desktop: {B4BFCC3A-DB2C-424C-B029-7FE99A87C641})
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8)
                ]

            desktop_guid = GUID(
                0xB4BFCC3A,
                0xDB2C,
                0x424C,
                (wintypes.BYTE * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)
            )
            p_path = wintypes.LPWSTR()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(desktop_guid), 0, None, ctypes.byref(p_path)) == 0:
                if p_path.value:
                    val = Path(p_path.value).resolve()
                    ctypes.windll.ole32.CoTaskMemFree(p_path)
                    return val
        except Exception:
            pass

        # 2. OneDrive environment variables
        for env_key in ('OneDriveCommercial', 'OneDriveConsumer', 'OneDrive', 'ONEDRIVE'):
            od = os.environ.get(env_key)
            if od:
                cand = Path(od) / 'Desktop'
                if cand.is_dir():
                    return cand.resolve()

        # 3. USERPROFILE fallback
        userprofile = os.environ.get('USERPROFILE')
        if userprofile:
            od_cand = Path(userprofile) / 'OneDrive' / 'Desktop'
            if od_cand.is_dir():
                return od_cand.resolve()
            dt_cand = Path(userprofile) / 'Desktop'
            if dt_cand.is_dir():
                return dt_cand.resolve()

    home = Path.home()
    if (home / 'Desktop').is_dir():
        return (home / 'Desktop').resolve()
    return home / 'Desktop'


def init_desktop_workspace(workspace_name: str, *, internal_root: Path, desktop_base: Path | None = None) -> dict:
    if not isinstance(workspace_name, str) or not workspace_name.strip():
        raise ValueError('Vui lòng nhập tên Workspace')
    name = workspace_name.strip()
    if not is_valid_workspace_name(name):
        raise ValueError(f'Tên Workspace không hợp lệ: {name}')

    desktop = resolve_desktop_path(desktop_base)
    workspace_dir = desktop / name
    data_root = workspace_dir / 'Data_Root'
    data_deidentified = workspace_dir / 'Data_Deidentified'

    data_root.mkdir(parents=True, exist_ok=True)
    data_deidentified.mkdir(parents=True, exist_ok=True)

    config = {
        'workspace_name': name,
        'workspace_dir': str(workspace_dir.resolve()),
        'data_root': str(data_root.resolve()),
        'data_deidentified': str(data_deidentified.resolve()),
    }

    internal_root = Path(internal_root).resolve()
    internal_root.mkdir(parents=True, exist_ok=True)
    cfg_file = internal_root / 'workspace_config.json'
    save_json(cfg_file, config)
    return config


def get_workspace_config(internal_root: Path) -> dict | None:
    p = Path(internal_root).resolve()
    candidates = (
        p / 'workspace_config.json',
        p / 'HMU_JOBS' / 'workspace_config.json',
        p / 'jobs' / 'workspace_config.json',
        p.parent / 'workspace_config.json',
        p.parent / 'jobs' / 'workspace_config.json',
    )
    for cand in candidates:
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding='utf-8'))
            except Exception:
                pass
    return None


def preclone_patient_folders(
    input_paths: list[Path],
    destination_root: Path,
    *,
    data_root: Path | None = None
) -> dict:
    destination_root = Path(destination_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    resolved_data_root = Path(data_root).resolve() if data_root is not None else None

    norm_paths = [Path(p).resolve() for p in (input_paths if isinstance(input_paths, (list, tuple)) else [input_paths])]

    if resolved_data_root is None:
        for p in norm_paths:
            if p.is_dir() and p.name == 'Data_Root':
                resolved_data_root = p
                break

    cloned_folders = set()
    mappings = {}

    def _discover_pdfs(folder: Path) -> list[Path]:
        excluded = {'hmu_jobs', '.git', '.venv', 'exports', '.export_staging', 'data_deidentified'}
        result = []
        for directory, children, files in os.walk(folder, followlinks=False):
            children[:] = [n for n in sorted(children) if n.lower() not in excluded and not Path(directory, n).is_symlink()]
            for name in sorted(files):
                p = Path(directory, name)
                if p.suffix.lower() == '.pdf' and not p.is_symlink() and p.resolve().is_relative_to(folder):
                    result.append(p.resolve())
        return result

    for item in norm_paths:
        if not item.exists():
            continue
        if item.is_file() and item.suffix.lower() == '.pdf':
            if resolved_data_root and item.is_relative_to(resolved_data_root):
                rel = item.relative_to(resolved_data_root)
                folder_name = rel.parts[0] if len(rel.parts) > 1 else ''
            else:
                folder_name = item.parent.name
            target_dir = (destination_root / folder_name).resolve() if folder_name else destination_root
            target_dir.mkdir(parents=True, exist_ok=True)
            cloned_folders.add(str(target_dir))
            mappings[str(item)] = str(target_dir)

        elif item.is_dir():
            if resolved_data_root and item == resolved_data_root:
                for child in sorted(item.iterdir()):
                    if child.is_dir() and not child.name.startswith(('.', 'HMU_JOBS', 'Data_Deidentified')):
                        target_dir = (destination_root / child.name).resolve()
                        target_dir.mkdir(parents=True, exist_ok=True)
                        cloned_folders.add(str(target_dir))
                pdfs = _discover_pdfs(item)
                for pdf in pdfs:
                    rel = pdf.relative_to(resolved_data_root)
                    folder_name = rel.parts[0] if len(rel.parts) > 1 else ''
                    target_dir = (destination_root / folder_name).resolve() if folder_name else destination_root
                    target_dir.mkdir(parents=True, exist_ok=True)
                    cloned_folders.add(str(target_dir))
                    mappings[str(pdf)] = str(target_dir)
            else:
                if resolved_data_root and item.is_relative_to(resolved_data_root):
                    rel = item.relative_to(resolved_data_root)
                    folder_name = rel.parts[0]
                else:
                    folder_name = item.name
                target_dir = (destination_root / folder_name).resolve() if folder_name else destination_root
                target_dir.mkdir(parents=True, exist_ok=True)
                cloned_folders.add(str(target_dir))
                pdfs = _discover_pdfs(item)
                for pdf in pdfs:
                    mappings[str(pdf)] = str(target_dir)

    res = {
        'cloned_folders': sorted(cloned_folders),
        'mappings': mappings,
        'target_folders': mappings,
        'mapping': mappings,
    }
    for k, v in mappings.items():
        res[k] = v
    return res


def open_in_explorer(target_path: Path | str) -> bool:
    target_path = Path(target_path).resolve()
    if not target_path.exists():
        raise ValueError(f'Đường dẫn không tồn tại: {target_path}')
    if sys.platform == 'win32':
        import subprocess
        subprocess.Popen(['explorer', str(target_path)])
        return True
    else:
        try:
            import subprocess
            cmd = 'xdg-open' if sys.platform != 'darwin' else 'open'
            subprocess.Popen([cmd, str(target_path)])
            return True
        except Exception:
            return True


@contextmanager
def publish_folder(destination):
    destination.mkdir(parents=True, exist_ok=True)
    suffix = time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(8)
    staging = destination / ('.pending_' + suffix)
    folder = destination / ('BAN_GIAO_' + suffix)
    staging.mkdir()
    try:
        yield staging, folder
        staging.rename(folder)
    finally:
        if (staging.exists() and staging.resolve().parent == destination
                and not staging.is_symlink() and not staging.is_junction()):
            shutil.rmtree(staging)


def resolve_target_folder_with_copy(
    base_dest: Path,
    folder_name: str,
    expected_pdfs: list[str] | None = None
) -> tuple[Path, bool, str | None]:
    """Resolve destination folder, using base_dest/folder_name if empty, or creating _CopyN if colliding."""
    base_dest = Path(base_dest).resolve()
    base_dest.mkdir(parents=True, exist_ok=True)

    if folder_name and base_dest.name != folder_name:
        target = (base_dest / folder_name).resolve()
        parent_dir = base_dest
        clean_name = folder_name
    else:
        target = base_dest
        parent_dir = base_dest.parent
        clean_name = base_dest.name

    def _has_exported_contents(folder: Path) -> bool:
        if not folder.exists() or not folder.is_dir():
            return False
        if (folder / 'manifest.json').exists():
            return True
        try:
            for child in folder.iterdir():
                if child.suffix.lower() == '.pdf':
                    return True
                if expected_pdfs and child.name in expected_pdfs:
                    return True
        except OSError:
            pass
        return False

    if not _has_exported_contents(target):
        return target, False, None

    orig_str = str(target)
    idx = 1
    while True:
        candidate = (parent_dir / f"{clean_name}_Copy{idx}").resolve()
        if not _has_exported_contents(candidate):
            return candidate, True, orig_str
        idx += 1


def source_pdf_name(name):
    filename=PureWindowsPath(name)
    if (filename.name!=name or filename.suffix.lower()!='.pdf' or filename.is_reserved()
            or re.search(r'[<>:"/\\|?*\x00-\x1f]',name)):
        raise ValueError('Tên PDF nguồn không hợp lệ để xuất')
    return name


def export_reviewed_folder(owner, destination, *, internal_root, progress_cb=None):
    if not isinstance(destination,str) or not destination.strip().strip('"'):
        raise ValueError('Nhập thư mục nhận PDF đã duyệt')
    owner=Path(owner).resolve();dest=Path(destination.strip().strip('"')).resolve()
    internal=Path(internal_root).resolve()
    if dest.is_relative_to(internal) and not dest.is_relative_to(internal/'delivered'):
        raise ValueError('Chọn thư mục nhận nằm ngoài dữ liệu làm việc nội bộ')
    if dest.is_relative_to(owner):raise ValueError('Không xuất vào dữ liệu làm việc đang mở')
    manifest_path=owner/'case_manifest.json';is_case=manifest_path.exists()
    case_manifest_data = json.loads(manifest_path.read_text(encoding='utf8')) if is_case else None
    items = case_manifest_data['files'] if is_case else [dict(index=1,sub_job='')]
    approved=[];pending=[];indices=set();names=set()
    for item in items:
        index=item['index'];job=(owner/item['sub_job']).resolve()
        if type(index) is not int or index<1 or index in indices:raise ValueError('Invalid case file index')
        if not job.is_relative_to(owner) or (is_case and job==owner):raise ValueError('Invalid sub-job path')
        indices.add(index);name=item.get('source_name','PDF đang mở')
        try:
            review=engine.ensure_job(job)
            name=item.get('source_name',review.get('original_name',review.get('source_file',name)))
            if not all(p['reviewed'] for p in review['pages']):raise ValueError('Cần duyệt tất cả trang trước khi xuất')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',review['study_id']):raise ValueError('Invalid research ID')
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            pending.append(dict(index=index if is_case else None,source_name=name,reason=str(exc)))
            continue
        source_pdf_name(name)
        if name.casefold() in names:raise ValueError('Trùng tên PDF nguồn; không thể xuất chung mà giữ nguyên tên')
        names.add(name.casefold())
        approved.append((job,name))
    if not approved:
        return dict(directory=None,outputs=[],count=0,pending=pending,copied_for_comparison=False,original_directory=None)

    folder_name = ''
    if is_case and case_manifest_data:
        if case_manifest_data.get('target_folder'):
            folder_name = Path(case_manifest_data['target_folder']).name
        elif case_manifest_data.get('source_path'):
            src_p = Path(case_manifest_data['source_path'])
            folder_name = src_p.name if (src_p.is_dir() or not src_p.suffix) else src_p.parent.name
        else:
            folder_name = owner.name
    else:
        job, _ = approved[0]
        review = engine.ensure_job(job)
        if review.get('target_folder'):
            folder_name = Path(review['target_folder']).name
        elif review.get('source_path'):
            src_p = Path(review['source_path'])
            folder_name = src_p.parent.name if src_p.parent.name else src_p.stem
        else:
            folder_name = review.get('original_name', '')
            if folder_name.lower().endswith('.pdf'):
                folder_name = Path(folder_name).stem

    expected_names = [name for _, name in approved]
    target_folder, copied, copied_from = resolve_target_folder_with_copy(dest, folder_name, expected_names)

    staging_parent = target_folder.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = staging_parent / ('.pending_' + target_folder.name + '_' + secrets.token_hex(6))
    staging.mkdir(parents=True, exist_ok=True)

    records = []
    try:
        for job, name in approved:
            out, qc = export(job, draft=False, output_path=staging / name, progress_cb=progress_cb)
            if engine.sha(out) != qc['output_sha256']:
                raise ValueError('Output hash mismatch')
            records.append(dict(
                pdf=name,
                qc=out.with_suffix('.qc.json').name,
                output_sha256=qc['output_sha256'],
                job_id=qc['job_id'],
                revision=qc['revision'],
                pages=qc['pages'],
                status=qc['status'],
            ))
        save_json(staging / 'manifest.json', dict(files=records))

        if target_folder.exists():
            try:
                target_folder.rmdir()
            except OSError:
                pass
        staging.rename(target_folder)
    finally:
        if (staging.exists() and staging.resolve().parent == staging_parent
                and not staging.is_symlink() and not staging.is_junction()):
            shutil.rmtree(staging)

    return dict(
        directory=str(target_folder),
        outputs=[str(target_folder / r['pdf']) for r in records],
        count=len(records),
        pending=pending,
        copied_for_comparison=copied,
        original_directory=copied_from,
    )
