#!/usr/bin/env python3
"""Build, package, and update this personal Helium fork without losing its patches."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'build/fork'
STATE = WORK / 'source.json'
UPSTREAM = 'https://github.com/imputnet/helium-macos.git'
PROFILE = Path.home() / 'Library/Application Support/net.imput.helium'
DEST = Path('/Applications/Helium.app')
PATCH = ROOT / 'patches/helium/macos/vertical-tab-density.patch'
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}


def run(args, cwd=None, capture=False, **kwargs):
    print('+ ' + ' '.join(str(a) for a in args), flush=True) if not capture else None
    result = subprocess.run([str(a) for a in args], cwd=ROOT if cwd is None else cwd, check=True,
                            text=True, stdout=subprocess.PIPE if capture else None, **kwargs)
    return result.stdout.strip() if capture else None


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def fingerprint():
    """Only source inputs count; documentation and workflow edits don't invalidate builds."""
    digest = hashlib.sha256()
    digest.update(run(['git', '-C', ROOT / 'helium-chromium', 'rev-parse', 'HEAD'], capture=True).encode())
    files = [ROOT / 'flags.macos.gn', ROOT / 'revision.txt', ROOT / 'downloads.ini']
    files += [p for p in (ROOT / 'patches').rglob('*') if p.is_file() and p.name != 'series.merged']
    files += [p for p in (ROOT / 'resources').rglob('*') if p.is_file()]
    for path in sorted(files):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def check_patch():
    if not PATCH.is_file() or 'helium/macos/vertical-tab-density.patch' not in (ROOT / 'patches/series').read_text().splitlines():
        raise RuntimeError('The sidebar patch is missing. Stop before building or installing.')
    run(['bash', ROOT / 'devutils/check_patch_files.sh'])


def require_clean():
    for repo in [ROOT, ROOT / 'helium-chromium']:
        if run(['git', '-C', repo, 'status', '--porcelain'], capture=True):
            raise RuntimeError(f'Commit or stash changes in {repo} before updating. Nothing was overwritten.')


def latest_release():
    output = run(['git', 'ls-remote', '--tags', UPSTREAM], capture=True)
    tags = {}
    for line in output.splitlines():
        sha, ref = line.split()
        match = re.fullmatch(r'refs/tags/(\d+\.\d+\.\d+\.\d+)(\^\{\})?', ref)
        if match:
            # Peeled commits win over annotated tag objects regardless of order.
            key = tuple(map(int, match[1].split('.')))
            if match[2] or key not in tags:
                tags[key] = (match[1], sha)
    if not tags:
        raise RuntimeError('No stable Helium release tags were found.')
    return tags[max(tags)]


def check():
    tag, sha = latest_release()
    print(f'Latest upstream release: {tag} ({sha[:12]})')
    present = subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'HEAD'], cwd=ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    print('Already included in this fork.' if present else 'To merge and install it: ./fork.sh upgrade')
    print('Sidebar patch: ' + ('present' if PATCH.is_file() else 'MISSING'))


def update():
    require_clean()
    check_patch()
    tag, sha = latest_release()
    # Merge the published platform release, including its pinned Chromium submodule.
    # Do not rebase, force-push, or independently update the Chromium submodule.
    run(['git', 'fetch', '--no-tags', UPSTREAM, f'refs/tags/{tag}'])
    if run(['git', 'rev-parse', 'FETCH_HEAD^{commit}'], capture=True) != sha:
        raise RuntimeError('Upstream tag changed during the check. Run update again.')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'HEAD'], cwd=ROOT,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        print(f'Upstream {tag} is already included.')
        return
    backup = 'fork-backup/' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    run(['git', 'branch', backup])
    run(['git', 'merge', '--no-edit', 'FETCH_HEAD'])
    run(['git', 'submodule', 'update', '--init', '--recursive'])
    check_patch()
    print(f'Upstream {tag} merged. Previous code is preserved at {backup}.')


def source_state():
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if state['fingerprint'] == fingerprint():
            return state
    return None


def adopt(path):
    """Explicitly register an already patched and validated development source tree."""
    check_patch()
    path = path.resolve()
    applied = path / '.pc/applied-patches'
    if not applied.is_file() or 'helium/macos/vertical-tab-density.patch' not in applied.read_text().splitlines():
        raise RuntimeError('Existing tree does not have the sidebar patch applied.')
    version = (ROOT / 'helium-chromium/chromium_version.txt').read_text().strip()
    values = dict(line.split('=', 1) for line in (path / 'chrome/VERSION').read_text().splitlines())
    if '.'.join(values[k] for k in ('MAJOR', 'MINOR', 'BUILD', 'PATCH')) != version:
        raise RuntimeError('Existing Chromium version does not match the fork.')
    save(STATE, {'fingerprint': fingerprint(), 'source': str(path), 'output': str(path / 'out/Default'),
                 'adopted': True})
    print('Existing build registered. Package it with ./fork.sh package.')


def prepare():
    check_patch()
    state = source_state()
    if state:
        return state
    identity = fingerprint()
    source = WORK / 'sources' / identity / 'src'
    if source.exists():
        raise RuntimeError(f'An incomplete source preparation already exists at {source}. '
                           'Move it aside before retrying; it will not be deleted automatically.')
    if shutil.disk_usage(ROOT).free < 45 * 2**30:
        raise RuntimeError('A new Chromium source/build needs at least 45 GiB free. '
                           'Keep the installed app and free build/archive space before retrying.')
    environment = os.environ.copy()
    environment['HELIUM_SOURCE_DIR'] = str(source)
    environment['HELIUM_OUTPUT_DIR'] = str(source / 'out/ForkRelease')
    run(['bash', '-euo', 'pipefail', '-c', 'source "$1/devutils/shared.sh"; prepare_sources "$_arch" true', 'fork', ROOT],
        env=environment)
    state = {'fingerprint': identity, 'source': str(source),
             'output': str(source / 'out/ForkRelease'), 'adopted': False}
    save(STATE, state)
    return state


def build(jobs):
    state = prepare()
    source, output = Path(state['source']), Path(state['output'])
    # Non-debug, non-component local release. Skip PGO/ThinLTO and official SDK
    # requirements so a personal fork can build using the installed Xcode.
    # Keep adopted component output separate from this release configuration.
    output = source / 'out/ForkRelease'
    output.mkdir(parents=True, exist_ok=True)
    flags = (ROOT / 'helium-chromium/flags.gn').read_text() + '\n' + (ROOT / 'flags.macos.gn').read_text()
    flags = re.sub(r'^is_official_build\s*=.*$', 'is_official_build=false', flags, flags=re.M)
    flags += '\nis_component_build=false\nenable_sparkle=false\nenable_precompiled_headers=false\n'
    flags += f'target_cpu="{"arm64" if os.uname().machine == "arm64" else "x64"}"\n'
    (output / 'args.gn').write_text(flags)
    environment = os.environ.copy()
    environment['HELIUM_SOURCE_DIR'] = str(source)
    environment['HELIUM_OUTPUT_DIR'] = str(output)
    environment['SISO_PATH'] = str(source / 'third_party/siso/cipd/siso')
    run(['bash', '-euo', 'pipefail', '-c',
         'source "$1/devutils/shared.sh"; ___helium_install_cipd_deps; ___helium_configure_siso',
         'fork', ROOT], env=environment)
    run([source / 'buildtools/mac/gn', 'gen', output, '--fail-on-unused-args'], cwd=source, env=environment)
    run(['nice', '-n', '10', sys.executable, source / 'third_party/depot_tools/autoninja.py',
         '-C', output, '-j', jobs, 'chrome'], cwd=source, env=environment)
    state['output'] = str(output)
    state['adopted'] = False
    save(STATE, state)


def machos(app):
    result = []
    for path in app.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as file:
                if file.read(4) in MAGIC:
                    result.append(path)
    return sorted(result)


def dependencies(path):
    lines = run(['/usr/bin/otool', '-m', '-L', path], capture=True).splitlines()[1:]
    return [line.strip().split(' (compatibility version')[0] for line in lines]


def load_paths(path):
    text = run(['/usr/bin/otool', '-m', '-l', path], capture=True)
    return re.findall(r'cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset', text)


def is_system(path):
    return path.startswith(('/usr/lib/', '/System/Library/'))


def relocate_rpaths(file, desired, app=None):
    """Rewrite LC_RPATH strings in place without growing lld's compact headers.

    Apple's install_name_tool rejects these framework headers, and LLVM's tool
    does not support their LC_REEXPORT_DYLIB commands. Preserve every command,
    its size, and all segment offsets; replace only the padded rpath strings.
    """
    data = bytearray(file.read_bytes())
    if data[:4] != b'\xcf\xfa\xed\xfe':
        raise RuntimeError(f'Expected a thin little-endian 64-bit Mach-O: {file}')
    count, size = struct.unpack_from('<II', data, 16)
    position, end = 32, 32 + size
    found = False
    used = set()
    anchor = False
    for _ in range(count):
        command, length = struct.unpack_from('<II', data, position)
        if length < 8 or position + length > end:
            raise RuntimeError(f'Invalid Mach-O load command: {file}')
        if command == 0x8000001C:  # LC_RPATH
            offset = struct.unpack_from('<I', data, position + 8)[0]
            capacity = length - offset
            if offset < 12 or capacity < len('@loader_path') + 1:
                raise RuntimeError(f'Invalid Mach-O rpath command: {file}')
            old = bytes(data[position + offset:position + length]).split(b'\0', 1)[0].decode()
            # Keep valid paths to embedded Libraries directories in monolithic
            # releases. Only output-directory paths must be redirected.
            expanded = Path(old.replace('@loader_path', str(file.parent)).replace(
                '@executable_path', str(app / 'Contents/MacOS') if app else str(file.parent)))
            if not anchor and len(desired.encode()) + 1 <= capacity:
                value = desired
                anchor = True
            elif app and expanded.resolve().is_relative_to(app.resolve()):
                value = old
            else:
                value = desired if len(desired.encode()) + 1 <= capacity else '@loader_path'
            if value in used:
                alternatives = [value + '/.' * n for n in range(1, 8)]
                alternatives += ['@loader_path' + '/.' * n for n in range(8)]
                value = next((candidate for candidate in alternatives
                              if candidate not in used and len(candidate.encode()) + 1 <= capacity), None)
                if value is None:
                    raise RuntimeError(f'No room for a unique internal rpath: {file}')
            used.add(value)
            canonical = Path(desired.replace('@loader_path', str(file.parent))).resolve()
            target = Path(value.replace('@loader_path', str(file.parent)).replace(
                '@executable_path', str(app / 'Contents/MacOS') if app else str(file.parent))).resolve()
            found |= target == canonical
            encoded = value.encode() + b'\0'
            data[position + offset:position + length] = encoded.ljust(capacity, b'\0')
        position += length
    if position != end:
        raise RuntimeError(f'Invalid Mach-O header size: {file}')
    if not found and any(value.startswith('@rpath/') for value in dependencies(file)):
        raise RuntimeError(f'No room for an internal Frameworks search path: {file}')
    file.write_bytes(data)


def audit(app):
    """Require every non-system dependency and search path to stay inside the app."""
    app = app.resolve()
    executable_dir = app / 'Contents/MacOS'
    def inside(path):
        return path.resolve().is_relative_to(app)
    def expand(value, file):
        return Path(value.replace('@loader_path', str(file.parent))
                    .replace('@executable_path', str(executable_dir)))
    def inspect(file):
        raw_paths = load_paths(file)
        if len(raw_paths) != len(set(raw_paths)):
            raise RuntimeError(f'Duplicate LC_RPATH entries: {file}')
        paths = [expand(value, file) for value in raw_paths]
        for path in paths:
            if not inside(path):
                raise RuntimeError(f'External library search path: {file}: {path}')
        for dependency in dependencies(file):
            if is_system(dependency):
                continue
            if dependency.startswith('@rpath/'):
                candidates = [path / dependency[len('@rpath/'):] for path in paths]
            else:
                candidates = [expand(dependency, file)]
            if not any(path.exists() and inside(path) for path in candidates):
                raise RuntimeError(f'Unbundled dependency: {file}: {dependency}')
    binaries = machos(app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(inspect, binaries))
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', app])
    print(f'Verified {len(binaries)} binaries; all non-system libraries are inside the app.')


def package():
    state = source_state()
    if not state:
        raise RuntimeError('No build matching these source inputs. Run ./fork.sh build first.')
    check_patch()
    output = Path(state['output'])
    original = output / 'Helium.app'
    if not original.is_dir():
        raise RuntimeError('The build has not produced Helium.app yet.')
    args = (output / 'args.gn').read_text()
    if re.search(r'^is_debug\s*=\s*true', args, re.M) or re.search(r'^enable_sparkle\s*=\s*true', args, re.M):
        raise RuntimeError('Use an optimized build with upstream automatic updates disabled.')
    archive = WORK / 'packages' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + fingerprint())
    app = archive / 'Helium.app'
    archive.mkdir(parents=True)
    run(['/usr/bin/ditto', original, app])
    frameworks = app / 'Contents/Frameworks'
    frameworks.mkdir(exist_ok=True)
    pending = machos(app)
    copied = set()
    # Recursively include only required component libraries, never build/test resources.
    while pending:
        with ThreadPoolExecutor(max_workers=2) as pool:
            required = list(pool.map(dependencies, pending))
        pending = []
        for dependency in {d for group in required for d in group}:
            if dependency.startswith('@rpath/'):
                relative = dependency[len('@rpath/'):]
                library = output / relative
                if library.is_file() and relative not in copied:
                    destination = frameworks / relative
                    if not destination.exists():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(library, destination)
                        pending.append(destination)
                    copied.add(relative)
    binaries = machos(app)
    def relocate(file):
        relative = os.path.relpath(frameworks, file.parent)
        desired = '@loader_path' if relative == '.' else '@loader_path/' + relative
        run(['/usr/bin/codesign', '--remove-signature', file], capture=True, stderr=subprocess.DEVNULL)
        relocate_rpaths(file, desired, app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(relocate, binaries))
    def sign_file(file):
        # Signing a CFBundleExecutable signs its enclosing bundle. Leave those
        # until the nested libraries and helpers have all been sealed.
        if file.parent.name != 'MacOS' and file.name != 'Helium Framework':
            run(['/usr/bin/codesign', '--force', '--sign', '-', file], capture=True,
                stderr=subprocess.STDOUT)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(sign_file, binaries))
    # Sign from the inside out. Renderer helpers need the existing JIT entitlement.
    # Ad-hoc signing is for this Mac, not Developer ID signing/notarization.
    entitlements = archive / 'jit-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps({'com.apple.security.cs.allow-jit': True}))
    bundles = [p for p in app.rglob('*') if p.is_dir() and not p.is_symlink()
               and p.suffix in {'.app', '.framework'}]
    for bundle in sorted(bundles, key=lambda p: len(p.parts), reverse=True) + [app]:
        command = ['/usr/bin/codesign', '--force', '--sign', '-']
        if 'Renderer' in bundle.name:
            command += ['--entitlements', entitlements]
        command += [bundle]
        run(command, capture=True, stderr=subprocess.STDOUT)
    manifest = {'fingerprint': fingerprint(), 'commit': run(['git', 'rev-parse', 'HEAD'], capture=True),
                'chromium_commit': run(['git', '-C', ROOT / 'helium-chromium', 'rev-parse', 'HEAD'], capture=True),
                'component_build': bool(re.search(r'^is_component_build\s*=\s*true', args, re.M)),
                'source': str(original), 'bundled_libraries': len(copied),
                'signed': 'ad-hoc', 'created': datetime.now().isoformat()}
    save(archive / 'manifest.json', manifest)
    audit(app)
    save(WORK / 'package.json', {'app': str(app), **manifest})
    print(f'Standalone app ready: {app}')


def install():
    state = json.loads((WORK / 'package.json').read_text())
    if state['fingerprint'] != fingerprint():
        raise RuntimeError('Package does not match the current fork. Rebuild/package first.')
    app = Path(state['app'])
    audit(app)
    # Quit every running main Helium process gracefully. Never force-kill the profile.
    processes = run(['ps', '-axo', 'pid=,comm='], capture=True)
    running = [line.strip().split(None, 1) for line in processes.splitlines()
               if re.search(r'/Helium\.app/Contents/MacOS/Helium$', line)]
    pids = [int(pid) for pid, _ in running]
    for _, executable in running:
        application = str(Path(executable).parents[2])
        run(['/usr/bin/osascript', '-e', f'tell application {json.dumps(application)} to quit'])
    deadline = time.monotonic() + 60
    while any(subprocess.run(['kill', '-0', str(pid)], stderr=subprocess.DEVNULL).returncode == 0 for pid in pids):
        if time.monotonic() > deadline:
            raise RuntimeError('Helium is still running. Finish any download/save prompt, quit it, and retry install.')
        time.sleep(1)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backups = Path.home() / 'Library/Application Support/Helium Fork Backups' / timestamp
    backups.mkdir(parents=True)
    if PROFILE.exists():
        run(['/usr/bin/ditto', PROFILE, backups / 'Profile'])
    staged = DEST.parent / f'Helium Fork Staging {timestamp}.app'
    run(['/usr/bin/ditto', app, staged])
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', staged])
    previous = backups / 'Helium.app'
    if DEST.exists():
        # Keep the previous application intact for rollback; do not delete it.
        shutil.move(str(DEST), str(previous))
    try:
        staged.rename(DEST)
    except Exception:
        if previous.exists() and not DEST.exists():
            shutil.move(str(previous), str(DEST))
        raise
    save(WORK / 'installed.json', {'app': str(DEST), 'backup': str(backups),
                                   'fingerprint': fingerprint(), 'time': timestamp})
    run(['/usr/bin/open', '-n', DEST, '--args', '--restore-last-session'])
    print(f'Installed {DEST}. Previous app and profile backup: {backups}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'update', 'build', 'package', 'verify', 'install', 'upgrade', 'adopt-source'])
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/src')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if args.command == 'check':
        check()
        return
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / 'workflow.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another fork build/install is running. Wait for it to finish.')
        if args.command == 'update': update()
        elif args.command == 'adopt-source': adopt(args.source)
        elif args.command == 'build': build(args.jobs)
        elif args.command == 'package': package()
        elif args.command == 'install': install()
        elif args.command == 'verify': audit(Path(json.loads((WORK / 'package.json').read_text())['app']))
        elif args.command == 'upgrade':
            update()
            installed = WORK / 'installed.json'
            if installed.exists() and DEST.exists() and json.loads(installed.read_text())['fingerprint'] == fingerprint():
                print('The installed sidebar fork already includes this release. No rebuild or restart needed.')
                return
            build(args.jobs)
            package()
            install()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'Stopped: {error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stdout:
            print(error.stdout, file=sys.stderr)
        sys.exit(1)
