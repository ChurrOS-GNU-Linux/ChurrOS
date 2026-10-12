#!/usr/bin/env python3
"""Regression checks for ChurrOS network ownership in Live and installed systems."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


units_file = ROOT / "installer/calamares/modules/services-systemd.conf"
units_text = units_file.read_text(encoding="utf-8")
unit_actions = dict(
    re.findall(r'-\s*name:\s*"([^"]+)"\s*\n\s*action:\s*"([^"]+)"', units_text)
)
require(unit_actions.get("NetworkManager.service") == "enable", "installed system must enable NetworkManager")
require(unit_actions.get("systemd-resolved.service") == "enable", "installed system must keep systemd-resolved for DNS")
for unit in ("iwd.service", "systemd-networkd.service", "systemd-networkd.socket", "systemd-networkd-wait-online.service"):
    require(unit_actions.get(unit) == "disable", f"installed system must disable {unit}")
for unit in (
    "hv_fcopy_daemon.service",
    "hv_kvp_daemon.service",
    "hv_vss_daemon.service",
    "vboxservice.service",
    "vmtoolsd.service",
    "vmware-vmblock-fuse.service",
):
    require(unit_actions.get(unit) == "disable", f"installed system must disable host-specific guest unit {unit}")

wants = ROOT / "archiso/airootfs/etc/systemd/system/multi-user.target.wants"
for unit in (
    "iwd.service",
    "systemd-networkd.service",
    "hv_fcopy_daemon.service",
    "hv_kvp_daemon.service",
    "hv_vss_daemon.service",
    "vboxservice.service",
    "vmtoolsd.service",
    "vmware-vmblock-fuse.service",
):
    require(not (wants / unit).exists() and not (wants / unit).is_symlink(), f"Live profile must not enable {unit}")

networkd_socket = ROOT / "archiso/airootfs/etc/systemd/system/sockets.target.wants/systemd-networkd.socket"
require(not networkd_socket.exists() and not networkd_socket.is_symlink(), "Live profile must not activate systemd-networkd through its socket")
networkd_dbus_alias = ROOT / "archiso/airootfs/etc/systemd/system/dbus-org.freedesktop.network1.service"
require(not networkd_dbus_alias.exists() and not networkd_dbus_alias.is_symlink(), "Live profile must not retain the systemd-networkd D-Bus activation alias")

networkd_files = (
    "archiso/airootfs/etc/systemd/network/20-ethernet.network",
    "archiso/airootfs/etc/systemd/network/20-wlan.network",
    "archiso/airootfs/etc/systemd/network/20-wwan.network",
    "archiso/airootfs/etc/systemd/networkd.conf.d/ipv6-privacy-extensions.conf",
    "archiso/airootfs/etc/systemd/system/systemd-networkd-wait-online.service.d/wait-for-only-one-interface.conf",
)
for rel in networkd_files:
    require(not (ROOT / rel).exists(), f"stale networkd configuration must be removed: {rel}")

services = (ROOT / "archiso/airootfs/root/scripts/services.sh").read_text(encoding="utf-8")
require(
    "enable_unit NetworkManager.service" in services and 'systemctl enable "$unit"' in services,
    "Live must enable NetworkManager",
)
require("systemctl mask systemd-networkd-wait-online.service" not in services, "Live must not pass a networkd-wait-online mask to the installed system")

nm_conf_path = ROOT / "archiso/airootfs/etc/NetworkManager/conf.d/20-churros-dns.conf"
nm_conf = nm_conf_path.read_text(encoding="utf-8") if nm_conf_path.exists() else ""
require(re.search(r"(?m)^dns=systemd-resolved\s*$", nm_conf) is not None, "NetworkManager must publish DNS through systemd-resolved")
packages = (ROOT / "archiso/packages.x86_64").read_text(encoding="utf-8")
require(re.search(r"(?m)^wpa_supplicant\s*$", packages) is not None, "Live package list must include the NetworkManager Wi-Fi backend")

resolv = ROOT / "archiso/airootfs/etc/resolv.conf"
require(resolv.is_symlink() and resolv.readlink().as_posix() == "/run/systemd/resolve/stub-resolv.conf", "/etc/resolv.conf must keep the systemd-resolved stub target")
systemd = ROOT / "archiso/airootfs/etc/systemd/system"
for rel in (
    "multi-user.target.wants/systemd-resolved.service",
    "dbus-org.freedesktop.resolve1.service",
    "multi-user.target.wants/ModemManager.service",
):
    path = systemd / rel
    require(path.is_symlink(), f"Live profile must preserve required systemd/NetworkManager integration: {rel}")

cleanup = (ROOT / "installer/calamares/modules/shellprocess-cleanup.conf").read_text(encoding="utf-8")
for expected in (
    "systemctl unmask NetworkManager-wait-online.service",
    "systemctl enable NetworkManager-wait-online.service",
    "systemctl unmask NetworkManager-wait-online.service systemd-networkd-wait-online.service systemd-time-wait-sync.service",
    "/etc/systemd/network/20-wlan.network",
    "/etc/systemd/networkd.conf.d/ipv6-privacy-extensions.conf",
    "/etc/systemd/system/dbus-org.freedesktop.network1.service",
):
    require(expected in cleanup, f"installed-system cleanup must include {expected}")

verify = (ROOT / "archiso/airootfs/usr/share/churros/scripts/verify-install").read_text(encoding="utf-8")
for expected in (
    "NetworkManager habilitado",
    "systemd-resolved habilitado para DNS",
    "NetworkManager-wait-online habilitado y sin máscara",
    "configuración heredada de systemd-networkd retirada",
    "alias D-Bus de systemd-networkd retirado",
):
    require(expected in verify, f"post-install verification must check {expected}")

if errors:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    raise SystemExit(1)
print("Network service ownership regression checks passed.")
