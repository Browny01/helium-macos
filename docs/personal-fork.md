# Using and upgrading the sidebar-density fork

The everyday app is `/Applications/Helium.app`. It uses the original
`~/Library/Application Support/net.imput.helium` profile and the normal macOS
Keychain. No development profile or mock Keychain is used after installation.

## Check for a new upstream release

From this checkout, run:

```sh
./fork.sh check
```

This checks the published stable release tags without modifying your checkout.
There is no scheduled task or recurring update checker.

## Upgrade, keeping the sidebar additions

Commit or stash any local source changes first, then run:

```sh
./fork.sh upgrade
```

You can also double-click `Upgrade Helium Fork.command` in this checkout in
Finder. It opens Terminal and runs the same workflow.

The command merges the latest published Helium macOS release into the current
branch, updates the Chromium submodule to the version pinned by that release,
prepares sources in a separate directory, builds with **two jobs**, packages the
app, backs up the original profile and installed app, and installs the result.
The existing app remains available throughout compilation. Installation quits
Helium gracefully and reopens it with the previous session.

The sidebar changes remain in
`patches/helium/macos/vertical-tab-density.patch`. An upstream change can conflict
with this patch or its entries in `patches/series`. If a Git merge or source patch
fails, the workflow stops before installation; resolve the reported conflict
before continuing. Retaining the patch does not guarantee compatibility with
every future Chromium release.

The update command creates a `fork-backup/<timestamp>` Git branch before merging.
It does not force-push, submit upstream PRs, or modify upstream repositories.
You can save successful updates to your personal fork with a normal `git push`.

## Individual steps

```sh
./fork.sh update       # merge the latest upstream release
./fork.sh build        # compile a local standalone release with two jobs
./fork.sh package      # bundle, sign, and verify the resulting app
./fork.sh install      # back up, install, and reopen
```

`build` uses optimized, non-debug, non-component binaries without PGO/ThinLTO or
the official release's exact SDK requirement. The first such build and future
Chromium version changes require extensive recompilation, potentially many hours
at two jobs. Subsequent builds with the same source inputs reuse their output.
Preparing a new Chromium source generation requires at least 45 GiB free.
Old source directories are preserved, never automatically removed.

The first installed package can also be made from the already verified,
optimized development build using `adopt-source` followed by `package`. In that
case its component libraries are embedded inside the app and all external build
directory search paths are removed. This is self-contained but is not the
monolithic build produced by `build`. The package manifest records the difference.

Signing is **ad-hoc for local use**, not Apple Developer ID signing or
notarization for public distribution. Upstream automatic binary updates are
disabled so that they cannot replace the sidebar fork.

## Backups and rollback

Installation preserves the previous app and a closed-profile backup in:

```text
~/Library/Application Support/Helium Fork Backups/<timestamp>/
```

The profile backup does not copy your macOS Keychain; saved passwords remain in
the Keychain. Keep the backup private.

To roll back, quit Helium and move the backed-up `Helium.app` into
`/Applications`. Normally keep your current profile. If a newer browser has
migrated its profile format, use the matching closed-profile backup as well,
preserving the newer profile before replacing it.

The installed app contains its libraries and can run after build/source folders
are removed. Keep this Git checkout to rebuild and maintain your sidebar patch.
