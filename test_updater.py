import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import updater


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ['git', *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


class UpdaterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.remote_dir = self.base / 'remote.git'
        self.work_dir = self.base / 'work'
        _git(self.base, 'init', '--bare', str(self.remote_dir))
        _git(self.base, 'clone', str(self.remote_dir), str(self.work_dir))
        _git(self.work_dir, 'config', 'user.email', 'dev@hmu.edu.vn')
        _git(self.work_dir, 'config', 'user.name', 'HMU Dev')
        _git(self.work_dir, 'checkout', '-b', 'dev')
        (self.work_dir / 'app.py').write_text('VERSION = "3.1.0"\n', encoding='utf-8')
        (self.work_dir / 'requirements.txt').write_text('pymupdf>=1.24.0\n', encoding='utf-8')
        _git(self.work_dir, 'add', 'app.py', 'requirements.txt')
        _git(self.work_dir, 'commit', '-m', 'feat: initial v3.1.0 release')
        _git(self.work_dir, 'tag', 'v3.1.0')
        _git(self.work_dir, 'push', '-u', 'origin', 'dev', '--tags')
        self.v1_sha = _git(self.work_dir, 'rev-parse', 'HEAD')

    def tearDown(self):
        self.tmp.cleanup()

    def _clone_peer(self) -> Path:
        peer_dir = self.base / 'peer'
        _git(self.base, 'clone', '-b', 'dev', str(self.remote_dir), str(peer_dir))
        _git(peer_dir, 'config', 'user.email', 'peer@hmu.edu.vn')
        _git(peer_dir, 'config', 'user.name', 'HMU Peer')
        return peer_dir

    def test_check_for_updates_and_list_versions_detect_remote_commits_and_tags(self):
        peer_dir = self._clone_peer()
        (peer_dir / 'app.py').write_text('VERSION = "3.2.0"\n', encoding='utf-8')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'feat: add batch retry improvements')
        _git(peer_dir, 'tag', 'v3.2.0')
        _git(peer_dir, 'push', 'origin', 'dev', '--tags')
        v2_sha = _git(peer_dir, 'rev-parse', 'HEAD')

        (self.work_dir / 'HMU_JOBS').mkdir(exist_ok=True)
        (self.work_dir / 'HMU_JOBS' / 'last_session.json').write_text('{"job": 1}', encoding='utf-8')
        (self.work_dir / '.venv').mkdir(exist_ok=True)
        (self.work_dir / '.venv' / 'pyvenv.cfg').write_text('home = /usr/bin\n', encoding='utf-8')

        cur = updater.get_current_version_info(self.work_dir)
        self.assertEqual(cur['commit'], self.v1_sha)
        self.assertEqual(cur['branch'], 'dev')
        self.assertFalse(cur['detached'])
        self.assertEqual(cur['tag'], 'v3.1.0')
        self.assertIn('v3.1.0', cur['tags'])
        self.assertFalse(cur['dirty'])
        self.assertEqual(cur['dirty_files'], [])

        info = updater.check_for_updates(self.work_dir, fetch=True)
        print(
            f"[TEST LOG] check_for_updates: current={info['current']['short_commit']} "
            f"remote={info['remote_short_commit']} behind={info['behind']} status={info['status']}"
        )
        self.assertEqual(info['current']['commit'], self.v1_sha)
        self.assertEqual(info['remote_commit'], v2_sha)
        self.assertEqual(info['behind'], 1)
        self.assertEqual(info['ahead'], 0)
        self.assertTrue(info['update_available'])
        self.assertEqual(info['status'], 'behind')
        self.assertFalse(info['offline'])
        self.assertEqual(len(info['incoming_commits']), 1)
        self.assertIn('batch retry improvements', info['incoming_commits'][0]['subject'])

        versions = updater.list_versions(self.work_dir)
        tag_names = [t['name'] for t in versions['tags']]
        self.assertIn('v3.2.0', tag_names)
        self.assertIn('v3.1.0', tag_names)
        commit_shas = [c['commit'] for c in versions['commits']]
        self.assertIn(v2_sha, commit_shas)
        self.assertIn(self.v1_sha, commit_shas)
        by_sha = {c['commit']: c for c in versions['commits']}
        self.assertTrue(by_sha[self.v1_sha]['is_current'])
        self.assertTrue(by_sha[v2_sha]['is_remote_head'])

    def test_check_for_updates_ahead_diverged_and_offline_states(self):
        # Local commit ahead of origin/dev
        (self.work_dir / 'app.py').write_text('VERSION = "3.1.1-local"\n', encoding='utf-8')
        _git(self.work_dir, 'add', 'app.py')
        _git(self.work_dir, 'commit', '-m', 'feat: local ahead commit')
        ahead_info = updater.check_for_updates(self.work_dir, fetch=False)
        self.assertEqual(ahead_info['ahead'], 1)
        self.assertEqual(ahead_info['behind'], 0)
        self.assertEqual(ahead_info['status'], 'ahead')
        self.assertFalse(ahead_info['update_available'])

        # Remote also advances -> diverged
        peer_dir = self._clone_peer()
        (peer_dir / 'app.py').write_text('VERSION = "3.2.0-remote"\n', encoding='utf-8')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'feat: remote diverged commit')
        _git(peer_dir, 'push', 'origin', 'dev')

        div_info = updater.check_for_updates(self.work_dir, fetch=True)
        self.assertEqual(div_info['ahead'], 1)
        self.assertEqual(div_info['behind'], 1)
        self.assertEqual(div_info['status'], 'diverged')
        self.assertTrue(div_info['update_available'])

        # Offline fallback when remote URL is unreachable
        _git(self.work_dir, 'remote', 'set-url', 'origin', str(self.base / 'non_existent_remote.git'))
        offline_info = updater.check_for_updates(self.work_dir, fetch=True, timeout=5)
        print(f"[TEST LOG] offline check: offline={offline_info['offline']} error={offline_info['fetch_error']}")
        self.assertTrue(offline_info['offline'])
        self.assertIsNotNone(offline_info['fetch_error'])
        versions = updater.list_versions(self.work_dir)
        self.assertIn('v3.1.0', [t['name'] for t in versions['tags']])

    def test_switch_version_stashes_dirty_files_preserves_hmu_jobs_and_rolls_back(self):
        peer_dir = self._clone_peer()
        (peer_dir / 'app.py').write_text('VERSION = "3.1.5"\n', encoding='utf-8')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'feat: release v3.1.5')
        _git(peer_dir, 'tag', 'v3.1.5')
        v15_sha = _git(peer_dir, 'rev-parse', 'HEAD')

        (peer_dir / 'app.py').write_text('VERSION = "3.2.0"\n', encoding='utf-8')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'feat: release v3.2.0')
        _git(peer_dir, 'tag', 'v3.2.0')
        _git(peer_dir, 'push', 'origin', 'dev', '--tags')
        v2_sha = _git(peer_dir, 'rev-parse', 'HEAD')

        # Simulate patient jobs in HMU_JOBS/ and .venv/ plus local dirty edits
        jobs_dir = self.work_dir / 'HMU_JOBS'
        jobs_dir.mkdir(exist_ok=True)
        session_file = jobs_dir / 'last_session.json'
        session_payload = '{"patient_case": "BN_001", "page": 3}'
        session_file.write_text(session_payload, encoding='utf-8')

        venv_dir = self.work_dir / '.venv'
        venv_dir.mkdir(exist_ok=True)
        venv_marker = venv_dir / 'pyvenv.cfg'
        venv_marker.write_text('home = /usr/bin\n', encoding='utf-8')

        (self.work_dir / 'app.py').write_text('VERSION = "3.1.0-dirty-user-edit"\n', encoding='utf-8')
        (self.work_dir / 'local_note.txt').write_text('temporary note\n', encoding='utf-8')

        cur_before = updater.get_current_version_info(self.work_dir)
        self.assertTrue(cur_before['dirty'])
        self.assertIn('app.py', cur_before['dirty_files'])
        self.assertIn('local_note.txt', cur_before['dirty_files'])

        res = updater.switch_version(
            self.work_dir,
            'latest',
            run_pip=False,
            smoke_modules=('app',),
        )
        print(
            f"[TEST LOG] switch_version(latest): {res['from_commit'][:7]} -> {res['to_commit'][:7]} "
            f"stashed={res['stashed']} detached={res['detached']}"
        )
        self.assertEqual(res['status'], 'switched')
        self.assertTrue(res['stashed'])
        self.assertIsNotNone(res['stash_ref'])
        self.assertEqual(res['from_commit'], self.v1_sha)
        self.assertEqual(res['to_commit'], v2_sha)
        self.assertFalse(res['detached'])
        self.assertEqual(_git(self.work_dir, 'rev-parse', 'HEAD'), v2_sha)
        self.assertEqual(session_file.read_text(encoding='utf-8'), session_payload)
        self.assertTrue(venv_marker.is_file())
        self.assertFalse((self.work_dir / 'local_note.txt').exists())

        # Rollback to previous version (v1_sha)
        rb = updater.rollback_previous(
            self.work_dir,
            run_pip=False,
            smoke_modules=('app',),
        )
        print(f"[TEST LOG] rollback_previous: -> {rb['to_commit'][:7]} detached={rb['detached']}")
        self.assertEqual(rb['status'], 'switched')
        self.assertEqual(rb['to_commit'], self.v1_sha)
        self.assertTrue(rb['detached'])
        self.assertEqual(_git(self.work_dir, 'rev-parse', 'HEAD'), self.v1_sha)
        self.assertEqual(session_file.read_text(encoding='utf-8'), session_payload)

        # Switch to a specific Tag ('v3.1.5')
        res_tag = updater.switch_version(
            self.work_dir,
            'v3.1.5',
            run_pip=False,
            smoke_modules=('app',),
        )
        self.assertEqual(res_tag['to_commit'], v15_sha)
        self.assertTrue(res_tag['detached'])
        self.assertEqual(res_tag['current']['tag'], 'v3.1.5')

        # From Detached HEAD at v3.1.5, switch to 'latest' -> must exit Detached HEAD and return to 'dev' at v2_sha
        res_latest = updater.switch_version(
            self.work_dir,
            'latest',
            run_pip=False,
            smoke_modules=('app',),
        )
        self.assertEqual(res_latest['to_commit'], v2_sha)
        self.assertFalse(res_latest['detached'])
        self.assertEqual(res_latest['current']['branch'], 'dev')
        self.assertEqual(_git(self.work_dir, 'symbolic-ref', '--short', 'HEAD'), 'dev')

    def test_switch_version_auto_reverts_when_smoke_test_fails(self):
        peer_dir = self._clone_peer()
        # Push a broken commit with null-byte corruption in app.py
        (peer_dir / 'app.py').write_bytes(b'VERSION = "3.2.0-corrupt"\n\x00raise SyntaxError("bad")\n')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'chore: accidental corrupted commit')
        _git(peer_dir, 'push', 'origin', 'dev')

        with self.assertRaises(RuntimeError) as ctx:
            updater.switch_version(
                self.work_dir,
                'latest',
                run_pip=False,
                run_smoke_test=True,
                smoke_modules=('app',),
            )
        print(f"[TEST LOG] auto-revert on null-byte corruption: {ctx.exception}")

        # Verify HEAD and branch automatically reverted to v1_sha
        after = updater.get_current_version_info(self.work_dir)
        self.assertEqual(after['commit'], self.v1_sha)
        self.assertEqual(after['branch'], 'dev')
        self.assertFalse(after['detached'])
        self.assertIn('3.1.0', (self.work_dir / 'app.py').read_text(encoding='utf-8'))

        # Now push a commit with valid syntax & no null bytes, but runtime ImportError on import
        (peer_dir / 'app.py').write_text('import non_existent_hmu_module_xyz\n', encoding='utf-8')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'chore: broken import commit')
        _git(peer_dir, 'push', 'origin', 'dev')

        with self.assertRaises(RuntimeError) as ctx2:
            updater.switch_version(
                self.work_dir,
                'latest',
                run_pip=False,
                run_smoke_test=True,
                smoke_modules=('app',),
            )
        print(f"[TEST LOG] auto-revert on import failure: {ctx2.exception}")
        after2 = updater.get_current_version_info(self.work_dir)
        self.assertEqual(after2['commit'], self.v1_sha)
        self.assertEqual(after2['branch'], 'dev')

    def test_switch_version_runs_real_venv_pip_only_when_requirements_change(self):
        # Create a real executable python wrapper inside .venv/Scripts/python.exe
        venv_scripts = self.work_dir / '.venv' / 'Scripts'
        venv_scripts.mkdir(parents=True, exist_ok=True)
        pip_log = self.work_dir / 'HMU_JOBS' / 'pip_calls.log'
        fake_py = venv_scripts / 'python.exe'
        fake_py.write_text(
            f'#!{sys.executable}\n'
            'import pathlib, sys\n'
            f'log_file = pathlib.Path({str(pip_log)!r})\n'
            'log_file.parent.mkdir(parents=True, exist_ok=True)\n'
            'with log_file.open("a", encoding="utf-8") as fh:\n'
            '    fh.write(" ".join(sys.argv[1:]) + "\\n")\n',
            encoding='utf-8',
        )
        fake_py.chmod(fake_py.stat().st_mode | stat.S_IEXEC)

        peer_dir = self._clone_peer()
        # Commit 1: requirements.txt changed
        (peer_dir / 'requirements.txt').write_text('pymupdf>=1.24.0\nrequests>=2.31.0\n', encoding='utf-8')
        (peer_dir / 'app.py').write_text('VERSION = "3.2.0"\n', encoding='utf-8')
        _git(peer_dir, 'add', 'requirements.txt', 'app.py')
        _git(peer_dir, 'commit', '-m', 'build: add requests dependency')
        _git(peer_dir, 'push', 'origin', 'dev')
        v2_sha = _git(peer_dir, 'rev-parse', 'HEAD')

        res1 = updater.switch_version(
            self.work_dir,
            'latest',
            run_pip=True,
            run_smoke_test=True,
            smoke_modules=('app',),
        )
        self.assertEqual(res1['to_commit'], v2_sha)
        self.assertTrue(res1['pip_installed'])
        self.assertTrue(pip_log.is_file())
        logged_lines = pip_log.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(logged_lines), 1)
        self.assertIn('-m pip install -r', logged_lines[0])

        # Commit 2: requirements.txt unchanged
        (peer_dir / 'app.py').write_text('VERSION = "3.2.1"\n', encoding='utf-8')
        _git(peer_dir, 'add', 'app.py')
        _git(peer_dir, 'commit', '-m', 'fix: bump patch without requirements change')
        _git(peer_dir, 'push', 'origin', 'dev')
        v3_sha = _git(peer_dir, 'rev-parse', 'HEAD')

        res2 = updater.switch_version(
            self.work_dir,
            'latest',
            run_pip=True,
            run_smoke_test=True,
            smoke_modules=('app',),
        )
        self.assertEqual(res2['to_commit'], v3_sha)
        self.assertFalse(res2['pip_installed'])
        self.assertEqual(len(pip_log.read_text(encoding='utf-8').splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
