#!/usr/bin/env python3
"""Auditoría del contenido de una ISO ya construida, sin arrancarla.

Lo que las pruebas estáticas deducen del repo, aquí se mira en el producto
final (ISO9660 + airootfs.sfs):

- arranque: etiqueta de volumen, entradas El Torito BIOS/UEFI según la
  arquitectura, kernel e initramfs en churros/boot/<arch>/, el .uuid que
  buscan archisosearchuuid= de GRUB y syslinux, y el sha512 del squashfs;
- permisos: cada entrada de file_permissions tiene ese modo y dueño en el
  squashfs, y todo script versionado en usr/bin, usr/local/bin y
  usr/share/churros/scripts es ejecutable (mkarchiso no conserva el bit +x
  de git: solo vale file_permissions);
- binarios: las apps Rust y Calamares (con sus módulos .so) son ELF de la
  arquitectura y todas sus bibliotecas DT_NEEDED existen en el squashfs.
  Calamares se desempaqueta con bsdtar, sin que pacman resuelva sus
  dependencias: si falta una .so, el instalador no abre;
- sistema: /etc/churros-edition, os-release con VERSION, greetd arranca la
  sesión de la edición con el usuario churros (que existe y tiene una shell
  instalada), customize_airootfs.sh se ejecutó y se borró, todos los
  paquetes de la lista están en pkglist, los enlaces de systemd apuntan a
  unidades que existen y /etc/calamares es el del repo.

Uso: python3 tests/iso/check_iso.py out/ChurrOS-....iso [--edition niri]
Necesita xorriso y unsquashfs (squashfs-tools). Los fallos ya conocidos se
apuntan en tests/known_issues.toml con la categoría iso-<edición>-<arquitectura>.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests import testlib  # noqa: E402

ELF_MACHINE = {"x86_64": 62, "aarch64": 183, "i686": 3}
LIB_DIRS = ("/usr/lib", "/usr/lib64", "/lib", "/lib64")


class Audit:
    def __init__(self):
        self.checks: list[dict] = []
        self.findings: dict[str, str] = {}
        self.facts: dict = {}

    def check(self, name: str, problems: list[tuple[str, str]] | bool, detail: str = "") -> None:
        """problems: lista de (id, mensaje) o un booleano de éxito."""
        if isinstance(problems, bool):
            ok = problems
            problems = [] if ok else [(name, detail or name)]
        else:
            ok = not problems
        for key, message in problems:
            self.findings[key] = message
        self.checks.append({"name": name, "ok": ok})
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}" + ("" if ok else f" ({len(problems)})"), flush=True)
        for _, message in problems[:15]:
            print(f"      - {message}")
        if len(problems) > 15:
            print(f"      ... y {len(problems) - 15} más")


# ------------------------------------------------------------------- squashfs

class Squash:
    """Listado de airootfs.sfs (unsquashfs -lln) más extracción bajo demanda."""

    def __init__(self, sfs: Path, workdir: Path):
        self.sfs, self.workdir = sfs, workdir
        self.root = workdir / "root"
        self.entries: dict[str, dict] = {}
        out = subprocess.run(["unsquashfs", "-lln", "-d", "", str(sfs)], text=True,
                             capture_output=True, check=True).stdout
        line_re = re.compile(r"^(\S{10})\s+(\d+)/(\d+)\s+(\d+(?:,\s*\d+)?)\s+\S+\s+\S+\s+(.*)$")
        for line in out.splitlines():
            match = line_re.match(line)
            if not match:
                continue
            perms, uid, gid, size, rest = match.groups()
            path, target = (rest.split(" -> ", 1) + [None])[:2] if perms[0] == "l" else (rest, None)
            path = "/" + path.lstrip("/")
            self.entries[path] = {"type": perms[0], "perms": perms, "uid": int(uid), "gid": int(gid),
                                  "mode": perm_bits(perms), "target": target}

    def exists(self, path: str) -> bool:
        return self.resolve(path) is not None

    def resolve(self, path: str, depth: int = 0) -> str | None:
        """Sigue enlaces simbólicos dentro del squashfs (también en directorios)."""
        if depth > 40:
            return None
        parts = PurePosixPath(path).parts[1:]
        current = "/"
        for index, part in enumerate(parts):
            candidate = str(PurePosixPath(current) / part)
            entry = self.entries.get(candidate)
            if entry is None:
                return None
            if entry["type"] == "l":
                target = entry["target"]
                base = PurePosixPath(current)
                joined = PurePosixPath(target) if target.startswith("/") else base / target
                rest = PurePosixPath(*parts[index + 1:]) if index + 1 < len(parts) else None
                full = normalize(str(joined / rest) if rest else str(joined))
                return self.resolve(full, depth + 1)
            current = candidate
        return current

    def extract(self, *paths: str) -> Path:
        wanted = [p.lstrip("/") for p in paths if self.exists(p)]
        if wanted:
            subprocess.run(["unsquashfs", "-f", "-no-xattrs", "-q", "-n", "-d", str(self.root), str(self.sfs), *wanted],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self.root

    def read(self, path: str) -> str | None:
        real = self.resolve(path)
        if real is None:
            return None
        self.extract(real)
        local = self.root / real.lstrip("/")
        return local.read_text(errors="replace") if local.is_file() else None


def perm_bits(perms: str) -> int:
    bits = 0
    for index, char in enumerate(perms[1:10]):
        if char not in "-STl":
            bits |= 1 << (8 - index)
    special = {(3, "s"): 0o4000, (3, "S"): 0o4000, (6, "s"): 0o2000, (6, "S"): 0o2000, (9, "t"): 0o1000, (9, "T"): 0o1000}
    for (pos, char), bit in special.items():
        if perms[pos] == char:
            bits |= bit
    return bits


def normalize(path: str) -> str:
    parts = []
    for part in PurePosixPath(path).parts[1:]:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/" + "/".join(parts)


# ------------------------------------------------------------------------ ELF

def elf_info(path: Path) -> dict | None:
    """e_machine, DT_NEEDED y RUNPATH/RPATH de un ELF (32/64 bits, LE)."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        return None
    is64 = data[4] == 2
    if data[5] != 1:
        return None
    machine = struct.unpack_from("<H", data, 18)[0]
    if is64:
        shoff = struct.unpack_from("<Q", data, 0x28)[0]
        shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
        sh_fmt, dyn_fmt = "<IIQQQQIIQQ", "<qQ"
    else:
        shoff = struct.unpack_from("<I", data, 0x20)[0]
        shentsize, shnum = struct.unpack_from("<HH", data, 0x2E)
        sh_fmt, dyn_fmt = "<IIIIIIIIII", "<iI"
    sections = [struct.unpack_from(sh_fmt, data, shoff + i * shentsize) for i in range(shnum)]
    needed, runpath = [], []
    for section in sections:
        sh_type, sh_offset, sh_size, sh_link = section[1], section[4], section[5], section[6]
        if sh_type != 6:  # SHT_DYNAMIC
            continue
        strtab = sections[sh_link]
        str_off = strtab[4]
        def string(offset: int) -> str:
            end = data.index(b"\0", str_off + offset)
            return data[str_off + offset:end].decode()
        size = struct.calcsize(dyn_fmt)
        for index in range(sh_size // size):
            tag, value = struct.unpack_from(dyn_fmt, data, sh_offset + index * size)
            if tag == 0:
                break
            if tag == 1:
                needed.append(string(value))
            elif tag in (15, 29):
                runpath.extend(string(value).split(":"))
    return {"machine": machine, "needed": needed, "runpath": runpath}


# --------------------------------------------------------------------- ISO

def xorriso(iso: Path, *args: str) -> str:
    return subprocess.run(["xorriso", "-indev", str(iso), *args], text=True,
                          capture_output=True).stdout


def iso_files(iso: Path) -> set[str]:
    out = xorriso(iso, "-find", "/", "-type", "f")
    return {line.strip().strip("'") for line in out.splitlines() if line.startswith("'/")}


def extract_from_iso(iso: Path, path: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", path, str(dest)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    dest.chmod(0o644)
    return dest


def audit(iso: Path, edition_name: str | None, audit_: Audit, workdir: Path) -> str:
    match = re.search(r"-(x86_64|aarch64|i686)(?:-|\.iso)", iso.name)
    arch = match.group(1) if match else "x86_64"
    prof = testlib.profile(arch)
    install_dir = prof["install_dir"]
    files = iso_files(iso)

    print("\n== ISO9660 y arranque")
    pvd = xorriso(iso, "-pvd_info")
    volume = re.search(r"Volume Id\s*:\s*(\S+)", pvd)
    audit_.facts["volume_id"] = volume.group(1) if volume else None
    audit_.check("etiqueta de volumen ChurrOS_AAAAMM (iso_label de profiledef.sh)",
                 bool(volume and re.fullmatch(r"ChurrOS_\d{6}", volume.group(1))), str(audit_.facts["volume_id"]))

    torito = xorriso(iso, "-report_el_torito", "plain")
    platforms = set(re.findall(r"El Torito boot img\s*:\s*\d+\s+(BIOS|UEFI)", torito))
    want = {"UEFI"} if arch == "aarch64" else {"BIOS", "UEFI"}
    audit_.check(f"entradas El Torito {sorted(want)}", platforms == want, f"hay {sorted(platforms)}")

    kernel, initrd = ("vmlinuz-linux-aarch64", "initramfs-linux-aarch64.img") if arch == "aarch64" else ("vmlinuz-linux", "initramfs-linux.img")
    boot_problems = [(f"boot-file:{path}", f"falta {path} en la ISO")
                     for path in (f"/{install_dir}/boot/{arch}/{kernel}", f"/{install_dir}/boot/{arch}/{initrd}",
                                  f"/{install_dir}/{arch}/airootfs.sfs")
                     if path not in files]
    audit_.check("kernel, initramfs y airootfs.sfs en su sitio", boot_problems)

    uuid_problems = []
    configs = [f for f in files if re.search(r"/(grub|syslinux)/.*\.cfg$|loopback\.cfg$", f)]
    for config in configs:
        text = extract_from_iso(iso, config, workdir / "iso" / config.lstrip("/")).read_text(errors="replace")
        for uuid in set(re.findall(r"archisosearchuuid=(\S+)", text)):
            if f"/boot/{uuid}.uuid" not in files:
                uuid_problems.append((f"search-uuid:{config}", f"{config}: archisosearchuuid={uuid} sin /boot/{uuid}.uuid"))
        for basedir in set(re.findall(r"archisobasedir=(\S+)", text)):
            if basedir != install_dir:
                uuid_problems.append((f"basedir:{config}", f"{config}: archisobasedir={basedir} (install_dir={install_dir})"))
    audit_.check(f"archisosearchuuid y archisobasedir coherentes ({len(configs)} configs)", uuid_problems)

    sfs = extract_from_iso(iso, f"/{install_dir}/{arch}/airootfs.sfs", workdir / "airootfs.sfs")
    sha_path = f"/{install_dir}/{arch}/airootfs.sha512"
    if sha_path in files:
        expected = extract_from_iso(iso, sha_path, workdir / "airootfs.sha512").read_text().split()[0]
        digest = hashlib.sha512(sfs.read_bytes()).hexdigest()
        audit_.check("airootfs.sha512 coincide", digest == expected)

    squash = Squash(sfs, workdir)
    audit_.facts["squashfs_entries"] = len(squash.entries)
    edition_name = edition_name or (squash.read("/etc/churros-edition") or "").strip() or "niri"
    audit_.facts["edition"] = edition_name
    try:
        item = testlib.edition(edition_name, arch)
    except KeyError:
        audit_.check("edición conocida", False, f"{edition_name}/{arch}")
        return edition_name

    print("\n== Permisos en el squashfs")
    perm_problems = []
    for path, spec in sorted(prof["file_permissions"].items()):
        uid, gid, mode = spec.split(":")
        entry = squash.entries.get(path)
        if entry is None:
            perm_problems.append((f"perm-missing:{path}", f"{path} está en file_permissions pero no en el squashfs"))
        elif (entry["uid"], entry["gid"], entry["mode"]) != (int(uid), int(gid), int(mode, 8)):
            perm_problems.append((f"perm:{path}", f"{path}: {entry['uid']}:{entry['gid']}:{entry['mode']:o}, profiledef pide {spec}"))
    audit_.check(f"file_permissions aplicado ({len(prof['file_permissions'])} rutas)", perm_problems)

    exec_problems = []
    for repo_path in testlib.repo_files():
        relpath = testlib.rel(repo_path)
        if not relpath.startswith("archiso/airootfs/") or not testlib.shebang(repo_path):
            continue
        target = "/" + relpath[len("archiso/airootfs/"):]
        if not re.match(r"/usr/(local/)?bin/|/usr/share/churros/scripts/|/root/\.automated_script\.sh$", target):
            continue
        entry = squash.entries.get(target)
        if entry and not entry["mode"] & 0o111:
            exec_problems.append((f"not-executable:{target}", f"{target} tiene modo {entry['mode']:o} en la ISO (sin entrada en file_permissions)"))
    audit_.check("scripts de usr/bin, usr/local/bin y usr/share/churros/scripts ejecutables", exec_problems)

    print("\n== Binarios y bibliotecas")
    binaries = [f"/usr/bin/{name}" for name in sorted(testlib.deploy_crate_names())]
    if item.installer:
        binaries.append("/usr/bin/calamares")
        binaries += sorted(p for p in squash.entries if re.match(r"/usr/lib/calamares/modules/[^/]+/[^/]+\.so$", p))
        binaries += sorted(p for p in squash.entries if re.match(r"/usr/lib/libcalamares[^/]*\.so[.0-9]*$", p) and squash.entries[p]["type"] == "-")
    missing_bins = [(f"missing-binary:{b}", f"falta {b}") for b in binaries if not squash.exists(b)]
    squash.extract(*[b for b in binaries if squash.exists(b)])
    elf_problems = list(missing_bins)
    ld_dirs = list(LIB_DIRS)
    for conf in [p for p in squash.entries if p.startswith("/etc/ld.so.conf.d/")]:
        ld_dirs += [line.strip() for line in (squash.read(conf) or "").splitlines() if line.startswith("/")]
    for binary in binaries:
        real = squash.resolve(binary)
        if real is None:
            continue
        info = elf_info(squash.root / real.lstrip("/"))
        if info is None:
            elf_problems.append((f"not-elf:{binary}", f"{binary} no es un ELF"))
            continue
        if info["machine"] != ELF_MACHINE[arch]:
            elf_problems.append((f"elf-arch:{binary}", f"{binary} es e_machine={info['machine']}, no {arch}"))
        search = [p.replace("$ORIGIN", str(PurePosixPath(real).parent)) for p in info["runpath"]] + ld_dirs
        for lib in info["needed"]:
            if not any(squash.exists(f"{d.rstrip('/')}/{lib}") for d in search):
                elf_problems.append((f"missing-lib:{PurePosixPath(binary).name}:{lib}", f"{binary} necesita {lib}, que no está en la ISO"))
    audit_.check(f"{len(binaries)} binarios ELF de {arch} con todas sus bibliotecas", elf_problems)

    print("\n== Sistema Live")
    version = testlib.read_text(testlib.ROOT / "VERSION").strip()
    os_release = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', squash.read("/etc/os-release") or "", re.M))
    audit_.facts["os_release"] = os_release
    audit_.check("/etc/churros-edition es la edición", (squash.read("/etc/churros-edition") or "").strip() == item.name)
    audit_.check(f"os-release lleva VERSION_ID={version}", os_release.get("VERSION_ID") == version, str(os_release.get("VERSION_ID")))

    greetd_text = squash.read("/etc/greetd/config.toml") or ""
    try:
        greetd = testlib.tomllib.loads(greetd_text)
    except Exception as exc:  # noqa: BLE001 - se informa el error de sintaxis
        greetd = {}
        audit_.check("greetd config.toml es TOML válido", False, str(exc))
    initial = greetd.get("initial_session", {})
    audit_.facts["greetd_initial_session"] = initial
    audit_.check(f"greetd arranca '{item.session_cmd}' como churros",
                 initial.get("command") == item.session_cmd and initial.get("user") == "churros", str(initial))
    session_bin = item.session_cmd.split()[0]
    session_ok = squash.exists(session_bin) if session_bin.startswith("/") else any(squash.exists(f"/usr/bin/{session_bin}") for _ in [0])
    audit_.check("el comando de sesión existe en la ISO", session_ok, session_bin)

    passwd = {line.split(":")[0]: line.split(":") for line in (squash.read("/etc/passwd") or "").splitlines() if line}
    users_ok = []
    for user in ("churros", "greeter"):
        if user not in passwd:
            users_ok.append((f"user:{user}", f"no existe el usuario {user}"))
        elif not squash.exists(passwd[user][6]) and passwd[user][6] not in ("/usr/bin/nologin", "/sbin/nologin"):
            users_ok.append((f"shell:{user}", f"la shell de {user} ({passwd[user][6]}) no está instalada"))
    audit_.check("usuarios churros y greeter con shell instalada", users_ok)
    audit_.check("customize_airootfs.sh se ejecutó y se borró", not squash.exists("/root/customize_airootfs.sh"))

    pkglist_path = f"/{install_dir}/pkglist.{arch}.txt"
    if pkglist_path in files:
        installed = {line.split()[0] for line in extract_from_iso(iso, pkglist_path, workdir / "pkglist.txt").read_text().splitlines() if line.strip()}
        missing = [(f"pkg:{name}", f"{name} está en {item.package_list} pero no en la ISO") for name in sorted(testlib.packages(item)) if name not in installed]
        audit_.check(f"los {len(testlib.packages(item))} paquetes de la lista están instalados", missing)

    link_problems = []
    for path, entry in sorted(squash.entries.items()):
        if entry["type"] == "l" and re.match(r"/etc/systemd/(system|user)/", path):
            if entry["target"] == "/dev/null":
                continue
            if squash.resolve(path) is None:
                link_problems.append((f"unit-link:{path}", f"{path} -> {entry['target']} no existe"))
    audit_.check("enlaces de unidades systemd resuelven", link_problems)
    dm = squash.entries.get("/etc/systemd/system/display-manager.service")
    audit_.check("display-manager.service es greetd", bool(dm and dm["target"] and dm["target"].endswith("greetd.service")),
                 str(dm and dm["target"]))

    pacman_conf = squash.read("/etc/pacman.conf") or ""
    audit_.facts["pacman_conf_has_churros_repo"] = "[churros]" in pacman_conf

    if item.installer:
        repo_settings = testlib.read_text(testlib.ROOT / "installer/calamares/settings.conf")
        audit_.check("/etc/calamares/settings.conf es el del repo", squash.read("/etc/calamares/settings.conf") == repo_settings)
        overlay_problems = []
        for override in sorted((testlib.ROOT / "installer/calamares/modules" / arch).glob("*")):
            if squash.read(f"/etc/calamares/modules/{override.name}") != testlib.read_text(override):
                overlay_problems.append((f"calamares-overlay:{override.name}", f"/etc/calamares/modules/{override.name} no es la versión de {arch}"))
        audit_.check(f"módulos de Calamares de {arch} aplicados", overlay_problems)
        show = squash.read("/etc/calamares/branding/churros/show.qml") or ""
        audit_.check("show.qml sin @EDITION@", "@EDITION@" not in show)
    return edition_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("iso", type=Path)
    parser.add_argument("--edition", default=None)
    parser.add_argument("--report", type=Path, default=None, help="JSON con el resultado")
    args = parser.parse_args()
    for tool in ("xorriso", "unsquashfs"):
        if not shutil.which(tool):
            print(f"Error: falta {tool} (paquetes libisoburn/xorriso y squashfs-tools)", file=sys.stderr)
            return 2
    audit_ = Audit()
    print(f"== Auditoría de {args.iso.name}")
    with tempfile.TemporaryDirectory(prefix="churros-iso-") as tmp:
        edition_name = audit(args.iso.resolve(), args.edition, audit_, Path(tmp))

    match = re.search(r"-(x86_64|aarch64|i686)(?:-|\.iso)", args.iso.name)
    # Una categoría por edición y arquitectura: la ISO aarch64 no puede dar
    # por arreglado un fallo que solo tiene la x86_64.
    category = f"iso-{edition_name}-{match.group(1) if match else 'x86_64'}"
    findings = {f"{category}:{key}": msg for key, msg in audit_.findings.items()}
    known = {k for k in testlib.known_issues() if k.startswith(category + ":")}
    new = {k: v for k, v in findings.items() if k not in known}
    fixed = sorted(known - set(findings))
    if args.report:
        args.report.write_text(json.dumps({"iso": args.iso.name, "checks": audit_.checks, "findings": findings,
                                           "new": sorted(new), "fixed": fixed, "facts": audit_.facts},
                                          indent=2, ensure_ascii=False) + "\n")
    print()
    if new:
        print(f"{len(new)} problema(s) nuevo(s):")
        for key, message in sorted(new.items()):
            print(f"  - [{key}] {message}")
    if fixed:
        print("Ya no fallan; borra su entrada de tests/known_issues.toml:")
        for key in fixed:
            print(f"  - {key}")
    status = 1 if (new or fixed) else 0
    ok = sum(1 for c in audit_.checks if c["ok"])
    print(f"{'OK' if status == 0 else 'FALLO'}: {ok}/{len(audit_.checks)} comprobaciones sin fallos nuevos")
    return status


if __name__ == "__main__":
    sys.exit(main())
