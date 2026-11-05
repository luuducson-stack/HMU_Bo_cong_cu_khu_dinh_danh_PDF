"""Publish completed PDF folders and export a reviewed local case."""
from contextlib import contextmanager
import json
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import time

import engine
from engine import export, save_json


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
    items=json.loads(manifest_path.read_text(encoding='utf8'))['files'] if is_case else [dict(index=1,sub_job='')]
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
    if not approved:return dict(directory=None,outputs=[],count=0,pending=pending)
    records=[]
    with publish_folder(dest) as (staging,folder):
        for job,name in approved:
            out,qc=export(job,draft=False,output_path=staging/name,progress_cb=progress_cb)
            if engine.sha(out)!=qc['output_sha256']:raise ValueError('Output hash mismatch')
            records.append(dict(pdf=name,qc=out.with_suffix('.qc.json').name,output_sha256=qc['output_sha256'],
                job_id=qc['job_id'],revision=qc['revision'],pages=qc['pages'],status=qc['status']))
        save_json(staging/'manifest.json',dict(files=records))
    return dict(directory=str(folder),outputs=[str(folder/r['pdf']) for r in records],count=len(records),pending=pending)
