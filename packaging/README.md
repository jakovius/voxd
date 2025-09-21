## VOXD packaging (deb, rpm, arch)

This folder contains the assets to build native Linux packages using nfpm.

What you get
- deb (Debian/Ubuntu)
- rpm (Fedora/openSUSE)
- pkg.tar.zst (Arch)

Contents
- `nfpm.yaml` – single config for all packagers
- `voxd.wrapper` – installed to `/usr/bin/voxd`
- `99-uinput.rules` – udev rule for `/dev/uinput` access (group `input`)
- `postinstall.sh` / `postremove.sh` – maintainer scripts (root-safe)

Build locally
```bash
# From repo root
go install github.com/goreleaser/nfpm/v2/cmd/nfpm@latest

export VERSION=1.3.1   # no leading 'v'
for ARCH in amd64 arm64; do
  export ARCH
  nfpm pkg --packager deb       -f packaging/nfpm.yaml --target dist/
  nfpm pkg --packager rpm       -f packaging/nfpm.yaml --target dist/
  nfpm pkg --packager archlinux -f packaging/nfpm.yaml --target dist/
done

ls -lh dist/
```

Install (example)
```bash
# Prefer cross-distro helper (resolves dependencies)
bash packaging/install_voxd.sh dist/voxd_*_amd64.deb

# Or native commands:
sudo apt install -y ./dist/voxd_*_amd64.deb     # Debian/Ubuntu (pulls deps)
sudo dnf install -y dist/voxd-*x86_64.rpm       # Fedora
sudo zypper --non-interactive install --force-resolution dist/voxd-*x86_64.rpm  # openSUSE
sudo pacman -U dist/voxd-*-x86_64.pkg.tar.zst   # Arch
```

Post-install
- Maintainer script creates `input` group (if missing) and reloads udev.
- First run of `voxd` performs per-user setup (`voxd --setup`).
- If you want to skip per-user setup (e.g., on CI images), run `voxd --setup` later.

CI release
- Manual workflow builds all three package types for `amd64` and `arm64` and publishes to GitHub Releases.
- See `.github/workflows/release-packages.yml`.


