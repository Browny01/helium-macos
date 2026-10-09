# Using and upgrading the sidebar-density fork

The everyday app is `/Applications/Helium.app`. It uses the original
`~/Library/Application Support/net.imput.helium` profile and the normal macOS
Keychain. No development profile or mock Keychain is used after installation.

## Apple passkeys and iCloud Passwords limitation

The ad-hoc-signed fork does **not** have the officially distributed app's Apple
signing identity or managed passkey entitlement. It cannot use on-Mac iCloud
passkeys or the official app's Touch ID WebAuthn keychain groups. WebAuthn can
still offer a phone/QR-code authenticator. Ordinary browser password encryption
using the login Keychain is a separate capability.

Apple's iCloud Passwords helper also verifies approved browser identities. Its
allowlist includes official Helium's `net.imput.helium` identifier paired with
the imput LLC signing team `S4Q33XPHB4`. The local fork has no signing team and
does not match that identity. Copying a native-host manifest or rebuilding
Chromium cannot restore this approval.

Check the installed app with:

```sh
./fork.sh doctor
```

A full solution requires legitimate Apple signing and the managed
`com.apple.developer.web-browser.public-key-credential` entitlement, plus
acceptance by Apple's Passwords helper. Apple requires an organization account's
Account Holder to request the browser passkey entitlement. A personal development
certificate alone is insufficient. The official app's signature cannot be reused
after modifying its code. An organization account and signing permissions also do
not grant access to the official app's private Touch ID credential access groups.

For immediate Apple password/passkey compatibility, use the preserved official
Helium app (which does not have the custom density patch), or Safari. Keep the
fork and source patch saved if switching your everyday app back to official
Helium. Installation now stops before replacing an Apple-capable browser with
an ad-hoc package that removes those entitlements.

Sources: [Apple's passkey entitlement requirements](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.web-browser.public-key-credential)
and [Apple's browser helper allowlist policy](https://github.com/apple/password-manager-resources#how-apple-uses-web-browser-extension-distribution-information).

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
