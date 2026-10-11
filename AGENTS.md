# AGENTS.md — ChurrOS Development Guide

## Build Commands

```bash
./churros build              # Build ISO (default: niri edition)
./churros build --edition xfce # Build ISO with XFCE edition
./churros build --edition kde   # Build ISO with KDE Plasma edition
./churros build --edition server # Build ISO with the headless server edition
./churros build --arch arm64 # Build the aarch64 ISO (default: host architecture, uname -m; same for run)
./churros build --container  # Same build inside the Arch container (Containerfile; podman or docker, --privileged)
./churros rust               # cargo build/test/clippy of rust/ inside the container (same as CI); --host runs it locally
./churros run                # Build (if needed) and launch QEMU
./churros run --nokvm        # Force software emulation (no /dev/kvm)
./churros run --fresh        # Reset OVMF_VARS.fd so UEFI boots from CD-ROM instead of an existing install
./churros clean              # Remove work/ and out/ (also runs sudo rm -rf)
./churros check              # Static checks: bash, python, package lists, desktop files, Calamares branding, po files
./churros apps               # Open distro apps on the host (GTK preview is dummy; Calamares uses a tmp overlay)
./churros doctor             # Check tools per distro (Arch: mkarchiso & co.; elsewhere: podman/docker for --container)
./install-deps.sh            # Install dev deps with pacman, apt or dnf
./scripts/build-calamares.sh # Build Calamares into archiso/packages/ (.pkg.tar.zst, or .xz)
./scripts/build-aur.sh       # Build python-pywal + yay + wlogout AUR packages
./scripts/build-grub-theme.sh # Regenerate GRUB theme fonts (.pf2) + assets in branding/grub-theme/
```

The `churros` dispatcher is at repo root and `cd`s to its own dir before delegating to `scripts/cli/<cmd>.sh`.

## Build Flow (scripts/cli/build.sh)

Ordered steps, runs from repo root:

1. Copy `branding/customize_airootfs.sh` + `branding/files/` into `archiso/airootfs/root/`.
2. `scripts/build-calamares.sh` (rebuilds if missing, if libpython does not match host/`python` on the ISO, or if `installer/patches/calamares-*.patch` changed), then `scripts/build-aur.sh` if those pkgs are missing. Expect `calamares`, `python-pywal`, `yay` and `wlogout` packages in `archiso/packages/` (`.pkg.tar.zst` or `.pkg.tar.xz`).
3. If Calamares pkg exists: run `installer/apply-calamares.sh` (deploys `settings.conf`, `modules/*.conf`, `modules/*.yaml`, `branding/churros/`, plus a polkit rule `49-calamares.rules` allowing user `churros` to pkexec calamares) and copy all `archiso/packages/*.pkg.tar.*` into `airootfs/root/packages/`.
4. Run `scripts/build-rust.sh`: compiles every crate in `rust/` (release) and deploys binaries into `archiso/airootfs/usr/bin/`. Binary names match crate names (e.g. `churros-welcome`).
5. `sudo rm -rf work out` then `sudo env CHURROS_ARCH=<arch> mkarchiso -v -w work -o out archiso` (`<arch>` comes from `--arch`; `profiledef.sh` reads it).
6. `rm -rf work` and `chown` `out/` back to `$USER`.

A trap on EXIT cleans generated files out of `archiso/airootfs/` (`root/customize_airootfs.sh`, `root/branding`, `root/packages`, `etc/calamares`, `polkit-1/rules.d/49-calamares.rules`, `usr/bin/churros-welcome`). Do not edit those paths directly — they are regenerated each build.

## Build Container

`Containerfile` (repo root) is the Arch build environment: archiso, base-devel, grub, gtk4, libadwaita, rust, lld, nodejs, python. `scripts/lib/container.sh` builds it as `localhost/churros-builder` (rebuilt when the Containerfile changes or the image is older than 7 days) and runs commands with the repo mounted at `/churros`; `scripts/container-entrypoint.sh` creates `builder` with the host UID/GID (makepkg refuses root; build.sh uses passwordless sudo inside). The engine runs as real root (`sudo podman` or the docker daemon) because pacstrap mounts devtmpfs/proc. In the container `CARGO_TARGET_DIR=rust/target/container` (`build-rust.sh` honours it). `scripts/lib/host.sh` detects the distro family from `/etc/os-release` (never by `command -v pacman`: Debian ships a game with that name). `.github/workflows/rust.yml` builds the image from the Containerfile on every PR and weekly, then runs `./churros rust` on x86_64 and on an arm64 runner (`ubuntu-24.04-arm`, `CHURROS_CONTAINER_BASE=docker.io/menci/archlinuxarm:latest`; a cross `cargo check --target aarch64` from x86_64 fails in glib-sys's pkg-config). That ARM rust image does not install archiso. The aarch64 ISO is a different image: `Containerfile.aarch64` (`localhost/churros-builder-aarch64`, `--platform linux/arm64`, base `docker.io/menci/archlinuxarm:latest`). `./churros build --container --arch arm64` runs local packages, Rust and mkarchiso inside it. On x86_64 that needs qemu-user-static binfmt with the `C` (credentials) flag (`./churros doctor --arch arm64` reads `/proc/sys/fs/binfmt_misc/qemu-aarch64` and rejects `POF`); on an aarch64 host the same container is native. The image forces `PKGEXT='.pkg.tar.zst'` because ALARM defaults to `.pkg.tar.xz`; the build scripts still accept either extension when reusing a package. Bazaar links `libdex>=1.2` (ALARM ships 1.1.0, so `build-bazaar.sh` builds and publishes libdex 1.2 into the local repo). Cargo for that build goes to `rust/target/container-aarch64` and local packages to `archiso/packages/aarch64/`. The x86_64 container path is unchanged. `.github/workflows/iso-arm64.yml` builds that ISO on `ubuntu-24.04-arm` (workflow_dispatch, and PRs that touch the arm64 profile).

## Testing

There are no unit tests yet. Two layers of verification exist today.

`./churros check` runs the static checks (`scripts/cli/check.sh`): bash syntax, shellcheck at error level, Python syntax, duplicate entries in `packages.x86_64`, commands spawned by niri that resolve to a binary/crate/package, desktop `Exec`/`TryExec` resolution, Calamares exec order and shellprocess configs, Calamares branding (`componentName`, slideshow API 2, image files), Calamares host preview (`./churros apps calamares`), local AUR extras listed in `netinstall.yaml`, and `msgfmt --check` on `po/*.po`. It needs no ISO build and runs in seconds. The same script runs in CI (`.github/workflows/ci.yml`) on every push to `main` and every pull request.

`./churros check` also runs the privileged-execution tests (see `docs/privileged-execution.md`): `scripts/test-polkit-rules.js` (Node, no dependencies; skipped with a notice if `node` is missing) checks every decision of the polkit rule and that each real caller still uses the argv the rule allows; `scripts/test-privileged-helpers.py` runs `churros-update-utils` against a fake root, `churros-write-root-config` and the edition → session table without root. CI also runs `scripts/test-polkit-pkexec.sh` (`.github/workflows/polkit.yml`) against real polkitd and pkexec in an Arch container; it needs root, so do not run it on your machine. If you change a pkexec caller, change `50-churros-store.rules` and the caller table in `scripts/test-polkit-rules.js` with it.

Behaviour on the live system is verified in QEMU:

```bash
./churros run
```

- ISO output: `out/*.iso`
- VM disk: `vm/ChurrOS.qcow2` (64G qcow2, created on first run)
- EFI vars: `vm/OVMF_VARS.fd` (copied from `/usr/share/edk2/x64/OVMF_VARS.4m.fd`)
- Serial log: `vm_serial.log` (in root, gitignored)
- 4 GB RAM, 4 cores + `-cpu host` with KVM (2 cores, plain q35 without). niri needs 3D: build.sh picks `virtio-vga-gl` if `/dev/dri` exists, else `virtio-gpu` (niri falls back to llvmpipe).

## Project Layout

```
churros                       Bash dispatcher -> scripts/cli/<cmd>.sh
rust/                         Rust workspace (apps portadas a gtk4-rs/libadwaita)
  churros-welcome/            Crate de la app de bienvenida (port completo)
  preferences/                Crate de ajustes (binario churros-settings)
  services/                   Crate de servicios (wpctl, nmcli, bluetoothctl, brightnessctl…)
  popups/                     Crate de los popups (binario churros-popup + toggle nativo)
  control-center/             Crate del control center (binario churros-control-center)
  churros-tour/               Crate del recorrido guiado (binario churros-tour)
scripts/
  cli/                        build.sh, run.sh, clean.sh, check.sh, doctor.sh, apps.sh, info.sh, version.sh, logo.sh
  build-calamares.sh          Produces archiso/packages/calamares-*.pkg.tar.*
  build-aur.sh                Produces python-pywal + yay + wlogout pkgs
  build-rust.sh               Compiles rust/* crates -> archiso/airootfs/usr/bin/
archiso/                      ArchISO profile root
  profiledef.sh               iso metadata, arch (CHURROS_ARCH), bootmodes, squashfs options, file_permissions map
  pacman.x86_64.conf          Bootstrap repos for x86_64 (Arch Linux, host mirrorlist)
  pacman.aarch64.conf         Bootstrap repos for aarch64 (Arch Linux ARM)
  packages/                   Local pacman repo (built pkgs + repo db live here)
  airootfs/                   Squashfs root overlay
    etc/skel/.config/          niri, waybar, noctalia, foot, fuzzel — DO NOT MODIFY
    root/scripts/             Live-ISO runtime scripts (users, services, desktop, cleanup)
    usr/share/churros/        Assets runtime de las apps Rust (welcome, preferences, control-center, tour) + scripts
branding/                     Visual identity
  customize_airootfs.sh       Runs at live boot: applies os-release/issue/motd, creates live user, installs Calamares via bsdtar, configures local [churros] pacman repo
  files/                      os-release, issue, motd, logos, wallpapers
installer/
  calamares/settings.conf     Instance + sequence definition (see below)
  calamares/modules/*.conf    One .conf per Calamares module
  calamares/modules/*.yaml    netinstall package groups
  calamares/preview/          Host-only overlay for ./churros apps calamares (not copied to the ISO)
  apply-calamares.sh          Copies config + polkit rule into airootfs
docs/                         Project documentation
```

## Conventions

- **Git workflow**: every change starts on a new branch (never on `main`). Create the branch, make and verify the changes there, and only merge back into `main` once everything works.
- Shell scripts: `#!/usr/bin/env bash`, `set -e`, shellcheck-compliant.
- Calamares modules: `.conf` (and `.yaml` for netinstall) in `installer/calamares/modules/`. Arch-specific variants (`unpackfs.conf`, `shellprocess-fixboot.conf`, `shellprocess-pacman.conf`) live in `installer/calamares/modules/<arch>/` and `apply-calamares.sh` copies them over the common ones.
- Package lists: one package per line in `archiso/packages.x86_64`.
- File mode map (not git): declared in `archiso/profiledef.sh` `file_permissions` (e.g. `/usr/bin/churros-*` 0755).
- Bootstrap uses `pacman.<arch>.conf`, chosen in `profiledef.sh` from `CHURROS_ARCH` (default: host arch); airootfs squashfs zstd on x86_64 and xz on aarch64; bootstrap tarball zstd.

## Calamares Sequence

`installer/calamares/settings.conf` defines five `shellprocess` instances and the exec order. The exec sequence IS order-sensitive — keypin requirements:

- `shellprocess@boot-nocow` runs after `mount` and **MUST** come before `unpackfs`: `chattr +C` + `compression=none` on the target `/boot` so vmlinuz is never stored as btrfs zstd (GRUB `premature end of file`).
- `shellprocess@pacman-init` (keyring init) **MUST** come before `shellprocess@fix-boot` (mkinitcpio preset rewrite + kernel modules) — both already ordered this way; do not reorder.
- There is **no** `shellprocess@churros-repo`. The `[churros]` repo (`Server = file:///root/packages`) is declared in `archiso/pacman.<arch>.conf`, so it is already in the live environment's pacman.conf and Calamares carries it into the target; that is how `netinstall` resolves yay/wlogout/python-pywal. It is removed again by `shellprocess@post-install` (unanchored `sed /churros/d` is forbidden — use the anchored `[churros]` block removal).
- `shellprocess@post-install` (cleanup: drops `[churros]`, `userdel -r churros`, removes live-only `/root` artifacts) is the last exec step before `umount`.
- `shellprocess@grub-theme` runs right after `bootloader`: copies `branding/grub-theme` (deployed to `/usr/share/churros/grub-theme/` at live boot) into `/boot/grub/themes/churros/`, appends `GRUB_THEME` to the target's `/etc/default/grub`, reruns `grub-mkconfig -o /boot/grub/grub.cfg`, then `make-boot-grub-readable` so GRUB can read `/boot` on btrfs+zstd.

Config files per instance: `shellprocess-pacman.conf`, `shellprocess-fixboot.conf`, `shellprocess-grub-theme.conf`, `shellprocess-cleanup.conf`, `shellprocess-boot-nocow.conf`. Module IDs in `instances:` are `pacman-init`, `fix-boot`, `grub-theme`, `post-install`, `boot-nocow` — five, no more.

## Key Architecture

- **Live user**: `churros` (wheel, audio, video, input, storage, network), NOPASSWD sudo — created by `archiso/airootfs/root/scripts/users.sh`.
- **Compositor**: Niri (Wayland scrollable-tiling). Requires 3D accel in QEMU (see Testing).
- **Display Manager**: greetd (regreet, autologin en Live y sesión niri nativa).
- **Shell**: Noctalia v5 (paquete `noctalia` de [extra], binario `noctalia`, IPC `noctalia msg …`) para barra, notificaciones, OSD y widgets. Config en `~/.config/noctalia/config.toml` (skel + copia en `usr/share/churros/defaults/noctalia/`); lo que se cambia desde su UI va a `~/.local/state/noctalia/settings.toml`. Waybar / Fuzzel / Mako / wlogout se mantienen instalados como alternativa.
- **Terminal**: foot.
- **Apps**: portadas a Rust (gtk4-rs + libadwaita-rs) en `rust/`: `churros-welcome`, `churros-settings` (preferences), `churros-popup` (6 popups en un binario con toggle nativo vía pidfiles en `/tmp/churros/`), `churros-control-center` y `churros-tour` (recorrido guiado, se limpia al instalar). Sus binarios se despliegan en `/usr/bin/churros-*` por `build-rust.sh` (crates con `deploy = true`); los assets runtime viven en `/usr/share/churros/<app>/` (los crates resuelven a `assets/` local en desarrollo). Las traducciones gettext (`po/*.po`) siguen siendo las que usa el resto del sistema; las apps Rust llevan sus cadenas en el codigo.
- **Installer**: Calamares with custom `churros` branding (slideshow, QSS stylesheet).
- **Boot modes** (from `profiledef.sh`): `bios.syslinux` + `uefi.grub` on x86_64, `uefi.grub` on aarch64. No systemd-boot, no Limine (mkarchiso del host no lo soporta).
- **Audio**: PipeWire + WirePlumber.
- **Build system**: archiso (`mkarchiso`).

## What NOT to Modify

- `installer/calamares/branding/churros/` — branding, slideshow, QSS.
- `branding/` — colors, typography, logo guidelines, mascot.
- `archiso/airootfs/etc/skel/.config/` — niri, waybar, noctalia, foot, fuzzel themes.
- Bootloader graphics and splash images.

## Notes

- `customize_airootfs.sh` lives in `branding/`, not in `archiso/`. It is copied into `airootfs/root/` on every build; editing the copy has no effect.
- `scripts/build-calamares.sh` and `scripts/build-aur.sh` run on the host (Arch Linux assumed) and produce pacman packages in `archiso/packages/`. `build.sh` always calls `build-calamares.sh` (it no-ops if libpython and `installer/patches` already match). `build-aur.sh` is skipped if those pkgs already exist.
- README and most `docs/*.md` are in Spanish; code and shell scripts are in English.
