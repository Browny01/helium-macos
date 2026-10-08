"""Exercise upstream merges in temporary Git repos, never the user's checkout."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('fork_release', Path(__file__).with_name('fork_release.py'))
fork = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fork)


class UpdateTests(unittest.TestCase):
    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True,
                                       stderr=subprocess.STDOUT).strip()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.upstream = base / 'upstream'
        self.upstream.mkdir()
        self.git(self.upstream, 'init', '-b', 'main')
        self.git(self.upstream, 'config', 'user.name', 'Test')
        self.git(self.upstream, 'config', 'user.email', 'test@example.invalid')
        (self.upstream / 'release.txt').write_text('original\n')
        (self.upstream / '.gitignore').write_text('helium-chromium/\nbuild/\n')
        self.git(self.upstream, 'add', '.')
        self.git(self.upstream, 'commit', '-m', 'Initial release')
        self.git(self.upstream, 'tag', '0.1.0.1')
        self.root = base / 'fork'
        subprocess.run(['git', 'clone', '-q', str(self.upstream), str(self.root)], check=True)
        self.git(self.root, 'config', 'user.name', 'Test')
        self.git(self.root, 'config', 'user.email', 'test@example.invalid')
        self.patch = self.root / 'patches/helium/macos/vertical-tab-density.patch'
        self.patch.parent.mkdir(parents=True)
        self.patch.write_text('Personal sidebar patch\n')
        (self.root / 'patches/series').write_text('helium/macos/vertical-tab-density.patch\n')
        tools = self.root / 'devutils'
        tools.mkdir()
        (tools / 'check_patch_files.sh').write_text('exit 0\n')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Sidebar additions')
        sub = self.root / 'helium-chromium'
        sub.mkdir()
        self.git(sub, 'init')
        self.saved = (fork.ROOT, fork.WORK, fork.STATE, fork.UPSTREAM, fork.PATCH)
        fork.ROOT, fork.WORK = self.root, self.root / 'build/fork'
        fork.STATE, fork.UPSTREAM, fork.PATCH = fork.WORK / 'source.json', str(self.upstream), self.patch

    def tearDown(self):
        fork.ROOT, fork.WORK, fork.STATE, fork.UPSTREAM, fork.PATCH = self.saved
        self.temp.cleanup()

    def publish(self, text):
        (self.upstream / 'release.txt').write_text(text)
        self.git(self.upstream, 'add', '.')
        self.git(self.upstream, 'commit', '-m', 'New upstream release')
        self.git(self.upstream, 'tag', '-a', '0.1.1.1', '-m', 'Annotated release')

    def test_annotated_release_merge_preserves_sidebar_and_backup(self):
        previous = self.git(self.root, 'rev-parse', 'HEAD')
        self.publish('new release\n')
        fork.update()
        self.assertEqual((self.root / 'release.txt').read_text(), 'new release\n')
        self.assertEqual(self.patch.read_text(), 'Personal sidebar patch\n')
        self.assertEqual(self.git(self.root, 'status', '--porcelain'), '')
        self.assertIn(previous, self.git(self.root, 'for-each-ref', '--format=%(objectname)', 'refs/heads/fork-backup/'))

    def test_merge_conflict_stops_without_losing_personal_patch(self):
        (self.root / 'release.txt').write_text('personal conflicting change\n')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Personal change')
        self.publish('upstream conflicting change\n')
        with self.assertRaises(subprocess.CalledProcessError):
            fork.update()
        self.assertTrue((self.root / '.git/MERGE_HEAD').exists())
        self.assertEqual(self.patch.read_text(), 'Personal sidebar patch\n')
        self.assertFalse((fork.WORK / 'installed.json').exists())

    def test_dirty_checkout_is_preserved(self):
        self.publish('new release\n')
        before = self.git(self.root, 'rev-parse', 'HEAD')
        self.patch.write_text('Uncommitted sidebar work\n')
        with self.assertRaisesRegex(RuntimeError, 'Commit or stash'):
            fork.update()
        self.assertEqual(self.git(self.root, 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.patch.read_text(), 'Uncommitted sidebar work\n')


if __name__ == '__main__':
    unittest.main()
