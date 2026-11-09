from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXCLUDED_DIR_PREFIXES = ('HMU_JOBS', '.venv')
STATE_FILENAME = 'updater_state.json'
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


def _resolve_repo_and_state(repo_dir: Path | str, state_dir: Path | str | None = None) -> tuple[Path, Path]:
    repo = Path(repo_dir).resolve()
    state = Path(state_dir).resolve() if state_dir is not None else (repo / 'HMU_JOBS')
    return repo, state


def _run_git(
    repo_dir: Path,
    *args: str,
    check: bool = True,
    timeout: int | float | None = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=check,
        timeout=timeout,
    )


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


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_excluded_path(rel_path: str) -> bool:
    norm = rel_path.strip().strip('"').replace('\\', '/')
    while norm.startswith('./'):
        norm = norm[2:]
    for prefix in EXCLUDED_DIR_PREFIXES:
        if norm == prefix or norm.startswith(prefix + '/'):
            return True
    return False


def _get_dirty_files(repo_dir: Path) -> list[str]:
    proc = _run_git(
        repo_dir,
        'status',
        '--porcelain',
        '--untracked-files=all',
        '--',
        '.',
        ':(exclude)HMU_JOBS',
        ':(exclude).venv',
        check=False,
    )
    if proc.returncode != 0:
        return []
    dirty: list[str] = []
    for raw_line in proc.stdout.splitlines():
        if len(raw_line) < 4:
            continue
        path_part = raw_line[3:].strip()
        if ' -> ' in path_part:
            path_part = path_part.split(' -> ', 1)[1].strip()
        path_part = path_part.strip('"')
        if path_part and not _is_excluded_path(path_part):
            dirty.append(path_part)
    return dirty


def _tags_at_commit(repo_dir: Path, commit_ref: str = 'HEAD') -> list[str]:
    proc = _run_git(
        repo_dir,
        'tag',
        '--points-at',
        commit_ref,
        '--sort=-creatordate',
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _ref_exists(repo_dir: Path, ref: str) -> bool:
    proc = _run_git(repo_dir, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}', check=False)
    return proc.returncode == 0


def _resolve_target_branch(
    repo_dir: Path,
    remote: str = 'origin',
    branch: str | None = None,
    current_info: dict[str, Any] | None = None,
    state_data: dict[str, Any] | None = None,
) -> str:
    if branch:
        cleaned = branch.strip()
        if cleaned.startswith(f'{remote}/'):
            cleaned = cleaned[len(remote) + 1 :]
        if cleaned and cleaned != 'HEAD':
            return cleaned

    if current_info and not current_info.get('detached') and current_info.get('branch') not in (None, '', 'HEAD'):
        return str(current_info['branch'])

    if state_data:
        for key in ('target_branch', 'previous_branch'):
            candidate = state_data.get(key)
            if isinstance(candidate, str) and candidate.strip() and candidate.strip() != 'HEAD':
                return candidate.strip()

    for candidate in ('dev', 'main', 'master'):
        if _ref_exists(repo_dir, f'refs/remotes/{remote}/{candidate}') or _ref_exists(repo_dir, f'refs/heads/{candidate}'):
            return candidate
    return 'dev'


def get_current_version_info(repo_dir: Path | str, state_dir: Path | str | None = None) -> dict[str, Any]:
    repo, state_path = _resolve_repo_and_state(repo_dir, state_dir)
    commit = _run_git(repo, 'rev-parse', 'HEAD').stdout.strip()
    short_commit = commit[:7]

    sym_proc = _run_git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False)
    if sym_proc.returncode == 0 and sym_proc.stdout.strip():
        branch = sym_proc.stdout.strip()
        detached = False
    else:
        branch = 'HEAD'
        detached = True

    tags = _tags_at_commit(repo, 'HEAD')
    tag = tags[0] if tags else None

    log_proc = _run_git(repo, 'log', '-1', '--format=%s%x1f%cI', 'HEAD', check=False)
    subject = ''
    committed_at = ''
    if log_proc.returncode == 0 and log_proc.stdout.strip():
        parts = log_proc.stdout.strip().split('\x1f')
        subject = parts[0] if len(parts) > 0 else ''
        committed_at = parts[1] if len(parts) > 1 else ''

    dirty_files = _get_dirty_files(repo)
    state_data = _read_updater_state(state_path)
    previous_commit = state_data.get('previous_commit')
    if not isinstance(previous_commit, str) or not previous_commit.strip():
        previous_commit = None

    remote_proc = _run_git(repo, 'remote', 'get-url', 'origin', check=False)
    remote_url = remote_proc.stdout.strip() if remote_proc.returncode == 0 else ''

    return {
        'commit': commit,
        'short_commit': short_commit,
        'branch': branch,
        'detached': detached,
        'tag': tag,
        'tags': tags,
        'subject': subject,
        'committed_at': committed_at,
        'dirty': bool(dirty_files),
        'dirty_files': dirty_files,
        'previous_commit': previous_commit,
        'can_rollback': bool(previous_commit and previous_commit != commit),
        'remote_url': remote_url,
    }


def _parse_log_entries(repo_dir: Path, rev_args: list[str]) -> list[dict[str, Any]]:
    proc = _run_git(
        repo_dir,
        'log',
        *rev_args,
        '--format=%H%x1f%h%x1f%s%x1f%cI%x1f%an',
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('\x1f')
        if len(parts) < 5:
            continue
        sha, short_sha, subject, committed_at, author = parts[:5]
        if sha in seen:
            continue
        seen.add(sha)
        entries.append(
            {
                'commit': sha,
                'short_commit': short_sha or sha[:7],
                'subject': subject,
                'committed_at': committed_at,
                'author': author,
                'tags': _tags_at_commit(repo_dir, sha),
            }
        )
    return entries


def check_for_updates(
    repo_dir: Path | str,
    remote: str = 'origin',
    branch: str | None = None,
    state_dir: Path | str | None = None,
    fetch: bool = True,
    timeout: int = 15,
) -> dict[str, Any]:
    repo, state_path = _resolve_repo_and_state(repo_dir, state_dir)
    current = get_current_version_info(repo, state_dir=state_path)
    state_data = _read_updater_state(state_path)
    target_branch = _resolve_target_branch(repo, remote=remote, branch=branch, current_info=current, state_data=state_data)

    offline = False
    fetch_error: str | None = None
    if fetch:
        try:
            fetch_proc = _run_git(repo, 'fetch', '--tags', '--prune', remote, check=False, timeout=timeout)
            if fetch_proc.returncode != 0:
                offline = True
                fetch_error = (fetch_proc.stderr or fetch_proc.stdout or 'git fetch failed').strip()
        except (subprocess.TimeoutExpired, OSError) as exc:
            offline = True
            fetch_error = str(exc)

    current = get_current_version_info(repo, state_dir=state_path)
    target_branch = _resolve_target_branch(repo, remote=remote, branch=branch, current_info=current, state_data=state_data)

    remote_ref = f'{remote}/{target_branch}'
    remote_commit = ''
    remote_short_commit = ''
    ahead = 0
    behind = 0
    incoming_commits: list[dict[str, Any]] = []

    if _ref_exists(repo, f'refs/remotes/{remote_ref}') or _ref_exists(repo, remote_ref):
        remote_commit = _run_git(repo, 'rev-parse', f'{remote_ref}^{{commit}}').stdout.strip()
        remote_short_commit = remote_commit[:7]
        counts_proc = _run_git(
            repo,
            'rev-list',
            '--left-right',
            '--count',
            f'HEAD...{remote_ref}',
            check=False,
        )
        if counts_proc.returncode == 0 and counts_proc.stdout.strip():
            parts = counts_proc.stdout.strip().split()
            if len(parts) == 2:
                ahead = int(parts[0])
                behind = int(parts[1])
        if behind > 0:
            incoming_commits = _parse_log_entries(repo, [f'HEAD..{remote_ref}'])

    update_available = behind > 0
    if behind > 0 and ahead > 0:
        status = 'diverged'
    elif behind > 0:
        status = 'behind'
    elif ahead > 0:
        status = 'ahead'
    elif current['detached']:
        status = 'detached'
    elif offline and not remote_commit:
        status = 'offline'
    else:
        status = 'up_to_date'

    return {
        'current': current,
        'target_branch': target_branch,
        'remote_commit': remote_commit,
        'remote_short_commit': remote_short_commit,
        'ahead': ahead,
        'behind': behind,
        'update_available': update_available,
        'status': status,
        'offline': offline,
        'fetch_error': fetch_error,
        'incoming_commits': incoming_commits,
    }


def list_versions(
    repo_dir: Path | str,
    remote: str = 'origin',
    branch: str | None = None,
    limit: int = 30,
    state_dir: Path | str | None = None,
) -> dict[str, Any]:
    repo, state_path = _resolve_repo_and_state(repo_dir, state_dir)
    current = get_current_version_info(repo, state_dir=state_path)
    state_data = _read_updater_state(state_path)
    target_branch = _resolve_target_branch(repo, remote=remote, branch=branch, current_info=current, state_data=state_data)

    current_commit = current['commit']
    previous_commit = current['previous_commit']

    remote_ref = f'{remote}/{target_branch}'
    remote_head = ''
    if _ref_exists(repo, f'refs/remotes/{remote_ref}') or _ref_exists(repo, remote_ref):
        remote_head = _run_git(repo, 'rev-parse', f'{remote_ref}^{{commit}}').stdout.strip()

    tags_list: list[dict[str, Any]] = []
    tag_proc = _run_git(repo, 'tag', '--sort=-creatordate', check=False)
    if tag_proc.returncode == 0:
        for raw_tag in tag_proc.stdout.splitlines():
            tag_name = raw_tag.strip()
            if not tag_name:
                continue
            sha_proc = _run_git(repo, 'rev-list', '-n', '1', tag_name, check=False)
            if sha_proc.returncode != 0 or not sha_proc.stdout.strip():
                continue
            tag_sha = sha_proc.stdout.strip()
            meta_proc = _run_git(repo, 'log', '-1', '--format=%s%x1f%cI', tag_sha, check=False)
            subject = ''
            committed_at = ''
            if meta_proc.returncode == 0 and meta_proc.stdout.strip():
                parts = meta_proc.stdout.strip().split('\x1f')
                subject = parts[0] if len(parts) > 0 else ''
                committed_at = parts[1] if len(parts) > 1 else ''
            tags_list.append(
                {
                    'name': tag_name,
                    'commit': tag_sha,
                    'short_commit': tag_sha[:7],
                    'subject': subject,
                    'committed_at': committed_at,
                    'is_current': tag_sha == current_commit,
                    'is_previous': bool(previous_commit and tag_sha == previous_commit),
                }
            )

    log_refs: list[str] = []
    if remote_head:
        log_refs.append(remote_ref)
    if _ref_exists(repo, f'refs/heads/{target_branch}'):
        log_refs.append(target_branch)
    log_refs.append('HEAD')
    log_refs.append('--tags')

    raw_commits = _parse_log_entries(repo, [f'-n{max(1, int(limit))}', '--date-order', *log_refs])
    commits_list: list[dict[str, Any]] = []
    for item in raw_commits:
        sha = item['commit']
        commits_list.append(
            {
                **item,
                'is_current': sha == current_commit,
                'is_previous': bool(previous_commit and sha == previous_commit),
                'is_remote_head': bool(remote_head and sha == remote_head),
            }
        )

    return {
        'current_commit': current_commit,
        'previous_commit': previous_commit,
        'target_branch': target_branch,
        'tags': tags_list,
        'commits': commits_list,
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


def _restore_previous_git_state(
    repo_dir: Path,
    old_commit: str,
    old_branch: str,
    old_detached: bool,
    stashed: bool,
) -> None:
    if not old_detached and old_branch and old_branch != 'HEAD':
        _run_git(repo_dir, 'checkout', '-f', '-B', old_branch, old_commit, check=False)
    else:
        _run_git(repo_dir, 'checkout', '-f', '--detach', old_commit, check=False)
    if stashed:
        _run_git(repo_dir, 'stash', 'pop', check=False)


def switch_version(
    repo_dir: Path | str,
    target: str,
    remote: str = 'origin',
    branch: str | None = None,
    state_dir: Path | str | None = None,
    run_pip: bool = True,
    run_smoke_test: bool = True,
    smoke_modules: tuple[str, ...] | None = ('app',),
) -> dict[str, Any]:
    repo, state_path = _resolve_repo_and_state(repo_dir, state_dir)
    old_info = get_current_version_info(repo, state_dir=state_path)
    old_commit = old_info['commit']
    old_branch = old_info['branch']
    old_detached = old_info['detached']
    old_req_hash = _file_sha256(repo / 'requirements.txt')

    state_data = _read_updater_state(state_path)
    target_branch = _resolve_target_branch(
        repo,
        remote=remote,
        branch=branch,
        current_info=old_info,
        state_data=state_data,
    )

    # Step 1: Auto-stash dirty files outside HMU_JOBS/ and .venv/
    dirty_files = _get_dirty_files(repo)
    stashed = False
    stash_ref: str | None = None
    if dirty_files:
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        stash_msg = f'hmu-auto-backup-{ts}'
        stash_proc = _run_git(
            repo,
            'stash',
            'push',
            '--include-untracked',
            '-m',
            stash_msg,
            '--',
            '.',
            ':(exclude)HMU_JOBS',
            ':(exclude).venv',
            check=False,
        )
        if stash_proc.returncode == 0 and 'No local changes to save' not in (stash_proc.stdout or ''):
            stashed = True
            ref_proc = _run_git(repo, 'rev-parse', '--verify', '--quiet', 'refs/stash', check=False)
            stash_ref = ref_proc.stdout.strip() if ref_proc.returncode == 0 and ref_proc.stdout.strip() else 'stash@{0}'

    # Step 2: Resolve target and checkout (exiting Detached HEAD when switching to 'latest' or branch)
    target_str = (target or 'latest').strip()
    is_branch_target = (
        target_str == 'latest'
        or target_str == target_branch
        or target_str == f'{remote}/{target_branch}'
        or target_str in ('dev', 'main', 'master')
        and (
            _ref_exists(repo, f'refs/remotes/{remote}/{target_str}')
            or _ref_exists(repo, f'refs/heads/{target_str}')
        )
    )

    if is_branch_target:
        checkout_branch = (
            target_branch
            if target_str in ('latest', f'{remote}/{target_branch}')
            else target_str.removeprefix(f'{remote}/')
        )
        _run_git(repo, 'fetch', '--tags', '--prune', remote, check=False, timeout=15)
        remote_branch_ref = f'{remote}/{checkout_branch}'
        if _ref_exists(repo, f'refs/remotes/{remote_branch_ref}') or _ref_exists(repo, remote_branch_ref):
            _run_git(repo, 'checkout', '-f', '-B', checkout_branch, remote_branch_ref)
        elif _ref_exists(repo, f'refs/heads/{checkout_branch}'):
            _run_git(repo, 'checkout', '-f', '-B', checkout_branch, f'refs/heads/{checkout_branch}')
        else:
            _restore_previous_git_state(repo, old_commit, old_branch, old_detached, stashed)
            raise ValueError(f'Không tìm thấy nhánh cập nhật: {checkout_branch}')
    else:
        if not _ref_exists(repo, target_str):
            _run_git(repo, 'fetch', '--tags', '--prune', remote, check=False, timeout=15)
        sha_proc = _run_git(repo, 'rev-parse', '--verify', '--quiet', f'{target_str}^{{commit}}', check=False)
        if sha_proc.returncode != 0 or not sha_proc.stdout.strip():
            _restore_previous_git_state(repo, old_commit, old_branch, old_detached, stashed)
            raise ValueError(f'Không tìm thấy phiên bản hoặc mã commit: {target_str}')
        resolved_sha = sha_proc.stdout.strip()
        _run_git(repo, 'checkout', '-f', '--detach', resolved_sha)

    # Step 3: Sync requirements.txt if changed and run smoke-test; auto-revert on failure
    new_req_hash = _file_sha256(repo / 'requirements.txt')
    pip_installed = False
    try:
        if run_pip and new_req_hash is not None and new_req_hash != old_req_hash:
            _install_requirements(repo)
            pip_installed = True
        if run_smoke_test:
            _run_smoke_test(repo, smoke_modules=smoke_modules)
    except Exception as exc:
        _restore_previous_git_state(repo, old_commit, old_branch, old_detached, stashed)
        raise RuntimeError(
            f'Kiểm tra an toàn phiên bản thất bại, đã tự động khôi phục về {old_commit[:7]}: {exc}'
        ) from exc

    # Step 4: Persist rollback state in HMU_JOBS/updater_state.json
    new_commit = _run_git(repo, 'rev-parse', 'HEAD').stdout.strip()
    new_sym = _run_git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD', check=False)
    new_detached = not (new_sym.returncode == 0 and new_sym.stdout.strip())

    changed = (new_commit != old_commit) or (new_detached != old_detached)
    status = 'switched' if changed else 'noop'

    now_iso = datetime.now(timezone.utc).isoformat()
    history = list(state_data.get('history') or []) if isinstance(state_data.get('history'), list) else []
    prev_to_save = old_commit if new_commit != old_commit else (state_data.get('previous_commit') or old_commit)
    history.append(
        {
            'from_commit': old_commit,
            'to_commit': new_commit,
            'target': target_str,
            'stashed': stashed,
            'stash_ref': stash_ref,
            'pip_installed': pip_installed,
            'timestamp': now_iso,
        }
    )
    updated_state = {
        **state_data,
        'previous_commit': prev_to_save,
        'previous_branch': old_branch if not old_detached else state_data.get('previous_branch', target_branch),
        'target_branch': target_branch,
        'current_commit': new_commit,
        'last_switched_at': now_iso,
        'last_stash_ref': stash_ref,
        'history': history[-50:],
    }
    _write_updater_state(state_path, updated_state)

    current = get_current_version_info(repo, state_dir=state_path)
    return {
        'status': status,
        'from_commit': old_commit,
        'to_commit': new_commit,
        'target': target_str,
        'detached': current['detached'],
        'stashed': stashed,
        'stash_ref': stash_ref,
        'pip_installed': pip_installed,
        'current': current,
    }


def rollback_previous(
    repo_dir: Path | str,
    state_dir: Path | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    repo, state_path = _resolve_repo_and_state(repo_dir, state_dir)
    state_data = _read_updater_state(state_path)
    prev_commit = state_data.get('previous_commit')
    if not isinstance(prev_commit, str) or not prev_commit.strip():
        reflog_proc = _run_git(repo, 'rev-parse', '--verify', '--quiet', 'HEAD@{1}^{commit}', check=False)
        if reflog_proc.returncode == 0 and reflog_proc.stdout.strip():
            prev_commit = reflog_proc.stdout.strip()
        else:
            raise ValueError('Không tìm thấy phiên bản trước đó để quay lại (rollback).')
    return switch_version(repo, target=prev_commit.strip(), state_dir=state_path, **kwargs)
