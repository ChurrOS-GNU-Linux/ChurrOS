"""Canal de actualización de utilidades: build-churros-release.sh -> churros-update-utils.

scripts/build-churros-release.sh empaqueta las apps Rust, scripts de la ISO
y /usr/share/churros en churros-utils-*-<arch>.tar.zst y escribe
updates.json. churros-update-utils (root, vía churros-pkexec) lee
${BASE}updates.json, descarga ${BASE}<file>, comprueba el sha256, valida el
tarball y lo instala sobre /. Un error aquí llega a todas las instalaciones a
la vez, sin ISO nueva de por medio.

La prueba ejecuta el script de release real (las tres arquitecturas) sobre una
copia limpia del repo (los ficheros de git, como un clon recién hecho), con un
cargo falso que deja un ELF mínimo por binario de cada crate (nombres de
testlib.crates(), máquina ELF del destino que compilaría cargo de verdad).
Después:

- parsea cada updates.json con json y con parse_manifest del cliente;
  comprueba que los ficheros que nombra están a su lado con ese sha256;
- abre cada bundle: binario de cada crate desplegable, sus assets idénticos a
  rust/<crate>/assets, máquina ELF de la arquitectura del bundle, ficheros
  que el script comprueba con [ -f ] en el airootfs (traza de bash -x),
  validate_tarball del cliente y modos que dejaría install_stage frente a
  file_permissions de profiledef.sh;
- simula un cliente de cada arquitectura (uname -m falso, curl falso que sirve
  la salida de release/) ejecutando el main real de churros-update-utils
  contra un root falso, y mira qué máquina ELF queda instalada;
- repite el build con CARGO_TARGET_DIR, que exporta scripts/lib/container.sh;
- firma: clave pública, minisign en las ediciones y updates.json.minisig.

No duplica scripts/test-privileged-helpers.py (install_stage, member_allowed,
validate_tarball con tarballs a mano, orden manifiesto -> firma): aquí se
prueba lo que produce el script de release y cómo lo consume el cliente.

Uso: python3 -m unittest tests.static.test_release_bundle -v
Necesita zstd y python3 (SKIP en local; fallo con CHURROS_STRICT=1 o CI=true).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

from tests import testlib

RELEASE_SCRIPT = Path("scripts/build-churros-release.sh")
CLIENT = testlib.AIROOTFS / "usr/bin/churros-update-utils"
VERSION = testlib.read_text(testlib.ROOT / "VERSION").strip()

# e_machine y clase ELF (1 = 32 bits, 2 = 64 bits) de cada arquitectura de
# ChurrOS (elf.h: EM_X86_64 = 62, EM_AARCH64 = 183, EM_386 = 3).
ELF_MACHINES = {"x86_64": (62, 2), "aarch64": (183, 2), "i686": (3, 1)}
MACHINE_NAMES = {machine: arch for arch, (machine, _) in ELF_MACHINES.items()}

# Equipo que publica la release: `cargo build` sin --target compila para él.
# Fijo, para que el resultado no dependa del runner que pasa la prueba.
RELEASE_HOST = "x86_64"

FAKE_CARGO = r'''#!@PYTHON@
"""cargo falso de tests/static/test_release_bundle.py: no compila nada.

`cargo build` deja, por cada binario del workspace, un ELF mínimo con la
máquina del destino: la de --target (o CARGO_BUILD_TARGET) o, sin él, la del
equipo que publica. Rutas como las de cargo:
<target-dir>[/<triple>]/<perfil>/<bin>, con --target-dir, CARGO_TARGET_DIR o
<workspace>/target.
"""
import json, os, struct, sys
from pathlib import Path

BINS = json.loads(@BINS@)
HOST = @HOST@
MACHINES = json.loads(@MACHINES@)
VALUE_OPTIONS = {"--manifest-path", "--target", "--target-dir", "--jobs", "-j", "--profile",
                 "--package", "-p", "--features", "-F", "--color", "--config", "-Z", "--bin",
                 "--message-format"}


def fail(message):
    sys.exit(f"cargo falso (tests/static/test_release_bundle.py): {message}")


args, options, positional, i = sys.argv[1:], {}, [], 0
while i < len(args):
    arg = args[i]
    if arg.startswith("--") and "=" in arg:
        key, value = arg.split("=", 1)
        options.setdefault(key, []).append(value)
    elif arg in VALUE_OPTIONS:
        if i + 1 >= len(args):
            fail(f"{arg} sin valor")
        options.setdefault(arg, []).append(args[i + 1])
        i += 1
    elif arg.startswith("-"):
        options.setdefault(arg, []).append("")
    else:
        positional.append(arg)
    i += 1
if positional[:1] not in (["build"], ["b"]):
    fail(f"solo se emula `cargo build`, no `cargo {' '.join(args)}`")
workspace = Path(options.get("--manifest-path", ["Cargo.toml"])[-1]).resolve().parent
profile = options.get("--profile", ["release" if "--release" in options else "dev"])[-1]
profile_dir = {"dev": "debug", "test": "debug", "bench": "release"}.get(profile, profile)
target_dir = options.get("--target-dir", [os.environ.get("CARGO_TARGET_DIR", "")])[-1]
target_dir = Path(target_dir).resolve() if target_dir else workspace / "target"
triple = options.get("--target", [os.environ.get("CARGO_BUILD_TARGET", "")])[-1]
if triple:
    cpu = triple.split("-", 1)[0]
    arch = {"i386": "i686", "i586": "i686"}.get(cpu, cpu)
    if arch not in MACHINES:
        fail(f"destino desconocido: {triple}")
    out = target_dir / triple / profile_dir
else:
    arch, out = HOST, target_dir / profile_dir
packages = options.get("--package", []) + options.get("-p", [])
machine, elf_class = MACHINES[arch]
out.mkdir(parents=True, exist_ok=True)
stamp = os.environ.get("CHURROS_FAKE_CARGO_STAMP", "")
for package, bins in BINS.items():
    if packages and package not in packages:
        continue
    for name in bins:
        header = b"\x7fELF" + bytes([elf_class, 1, 1]) + bytes(9) + struct.pack("<HHI", 3, machine, 1)
        path = out / name
        path.write_bytes(header + f"\nbinario falso {name} {arch} {stamp}\n".encode())
        path.chmod(0o755)
if os.environ.get("CHURROS_FAKE_CARGO_LOG"):
    with open(os.environ["CHURROS_FAKE_CARGO_LOG"], "a") as handle:
        handle.write(f"{out}\n")
'''

# Stubs del cliente simulado. Solo cambian lo que depende del equipo
# (arquitectura y red); el resto de comandos son los reales.
CURL_STUB = r'''#!/usr/bin/env bash
# curl falso: sirve $CHURROS_TEST_SERVER como si fuera $CHURROS_TEST_BASE.
out=""; url=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o|--output) out="$2"; shift 2 ;;
        --proto|--connect-timeout|--max-time|-m|--retry) shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
echo "$url" >> "$CHURROS_TEST_LOG"
case "$url" in
    "$CHURROS_TEST_BASE"*) rel="${url#"$CHURROS_TEST_BASE"}" ;;
    *) echo "curl falso: URL fuera del servidor de releases: $url" >&2; exit 6 ;;
esac
src="$CHURROS_TEST_SERVER/$rel"
[ -f "$src" ] || { echo "curl: (22) The requested URL returned error: 404 ($url)" >&2; exit 22; }
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
'''

UNAME_STUB = r'''#!/usr/bin/env bash
# uname falso: la máquina del cliente simulado; lo demás, el uname real.
case "$*" in
    -m|--machine|-p|--processor|-i|--hardware-platform) printf '%s\n' "$CHURROS_TEST_ARCH" ;;
    *) exec @UNAME@ "$@" ;;
esac
'''

ARCH_STUB = '#!/bin/sh\nprintf \'%s\\n\' "$CHURROS_TEST_ARCH"\n'

# minisign falso (solo si el repo publica clave): acepta una firma no vacía.
MINISIGN_STUB = r'''#!/usr/bin/env bash
sig=""
while [ "$#" -gt 0 ]; do
    case "$1" in -x) sig="$2"; shift 2 ;; *) shift ;; esac
done
[ -s "$sig" ]
'''

# main real de churros-update-utils contra un root falso: se carga con
# `source` (main no corre solo) y se redirigen las rutas del sistema.
CLIENT_DRIVER = r'''
set -euo pipefail
source "$CHURROS_CLIENT"
VERSION_FILE="$FAKE_ROOT/etc/churros-version"
EDITION_FILE="$FAKE_ROOT/etc/churros-edition"
PUBKEY="$FAKE_ROOT$PUBKEY"
if ! declare -F install_stage >/dev/null || ! declare -F main >/dev/null; then
    echo "churros-update-utils ya no define install_stage/main: adapta tests/static/test_release_bundle.py" >&2
    exit 90
fi
# install_stage instala en $FAKE_ROOT, nunca en /.
eval "churros_real_install_stage() $(declare -f install_stage | tail -n +2)"
install_stage() { churros_real_install_stage "$1" "$FAKE_ROOT"; }
# El stage va a /run (solo root): aquí, a un directorio de la prueba. Es una
# función y no un mktemp en PATH porque install_stage lo llama por fichero.
mktemp() {
    local arg args=()
    for arg in "$@"; do
        case "$arg" in
            /run) arg="$CHURROS_TEST_RUN" ;;
            /run/*) arg="$CHURROS_TEST_RUN/${arg#/run/}" ;;
        esac
        args+=("$arg")
    done
    command mktemp "${args[@]}"
}
main
'''


# ------------------------------------------------------------------ utilidades

def executable(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)
    return path


def client(function_call: str, *args, env=None) -> subprocess.CompletedProcess:
    """Ejecuta funciones de churros-update-utils cargadas con `source`.

    $0 no es la ruta del script, así que su main no corre; los argumentos
    llegan como $1, $2...
    """
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift\n{function_call}', "prueba", str(CLIENT), *map(str, args)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, timeout=120,
    )


def client_var(name: str) -> str:
    result = client(f'printf "%s" "${name}"')
    if result.returncode != 0:
        raise AssertionError(f"no se pudo cargar {testlib.rel(CLIENT)}:\n{result.stderr}")
    return result.stdout


def elf_machine(head: bytes) -> str | None:
    """'x86_64', 'aarch64', 'i686', 'e_machine=N' o None si no es ELF."""
    if len(head) < 20 or not head.startswith(b"\x7fELF"):
        return None
    (machine,) = struct.unpack(("<" if head[5] == 1 else ">") + "H", head[18:20])
    return MACHINE_NAMES.get(machine, f"e_machine={machine}")


def fake_elf(arch: str, text: str) -> bytes:
    """Cabecera ELF mínima (ident + e_type + e_machine + e_version) y un texto."""
    machine, elf_class = ELF_MACHINES[arch]
    return b"\x7fELF" + bytes([elf_class, 1, 1]) + bytes(9) + struct.pack("<HHI", 3, machine, 1) + text.encode()


def link(source: Path, target: Path) -> None:
    """Enlace duro (los bundles pesan ~13 MB); copia si no se puede."""
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def no_duplicate_keys(pairs):
    # json.loads se queda con la última clave repetida sin avisar (el cliente
    # también): en un heredoc escrito a mano es siempre un error de copia.
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ValueError(f"claves repetidas: {', '.join(duplicated)}")
    return dict(pairs)


def manifest_entries(data: dict):
    """(dónde, fichero, sha256) de cada bundle que nombra el manifiesto."""
    if "file" in data or "sha256" in data:
        yield "file", data.get("file"), data.get("sha256")
    editions = data.get("editions")
    if isinstance(editions, dict):
        for name, entry in editions.items():
            entry = entry if isinstance(entry, dict) else {}
            yield f"editions.{name}", entry.get("file"), entry.get("sha256")


def fake_bins() -> dict[str, list[str]]:
    """Binarios que produce `cargo build` en el workspace: [[bin]] o src/main.rs."""
    bins = {}
    for crate in testlib.crates():
        names = [name for name in crate.bins if name]
        if not names and (crate.directory / "src/main.rs").is_file():
            names = [crate.name]
        bins[crate.name] = names
    return bins


def deploy_crates() -> list[testlib.Crate]:
    return [crate for crate in testlib.crates() if crate.deploy]


def copy_checkout(dest: Path) -> Path:
    """Copia de los ficheros del repo (git, sin ignorados): un clon limpio.

    Sin rust/target ni los assets que build-rust.sh deja en el airootfs
    durante un build de ISO (.gitignore), que en un árbol de trabajo pueden
    estar o no, y viejos.
    """
    for path in testlib.repo_files():
        target = dest / path.relative_to(testlib.ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            target.symlink_to(os.readlink(path))
        else:
            shutil.copy2(path, target)
    return dest


class Bundle:
    """Un .tar.zst descomprimido: miembros normalizados (sin ./ ni / final)."""

    def __init__(self, path: Path, workdir: Path):
        self.path = path
        plain = workdir / f"{path.parent.name}-{path.name[:-len('.zst')]}"
        subprocess.run(["zstd", "-q", "-d", "-f", "-o", str(plain), str(path)], check=True,
                       stdout=subprocess.DEVNULL)
        self.tar = tarfile.open(plain)
        self.members = {}
        for member in self.tar.getmembers():
            name = member.name[2:] if member.name.startswith("./") else member.name
            self.members[name.rstrip("/")] = member

    def files(self) -> dict[str, tarfile.TarInfo]:
        return {name: m for name, m in self.members.items() if m.isfile()}

    def read(self, name: str, size: int = -1) -> bytes:
        with self.tar.extractfile(self.members[name]) as handle:
            return handle.read(size)


# ---------------------------------------------------------------------- pruebas

class ReleaseBundle(unittest.TestCase):
    """Salida de build-churros-release.sh y cómo la consume churros-update-utils."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="churros-release-test-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.built = None

    # ------------------------------------------------------------- preparación

    def require(self):
        testlib.require_tool(self, "zstd")
        testlib.require_tool(self, "python3")
        if not hasattr(self, "_bins_dir"):
            type(self)._bins_dir = self.fake_cargo_dir()

    def fake_cargo_dir(self) -> Path:
        bin_dir = self.tmp / "cargo-bin"
        source = (FAKE_CARGO.replace("@PYTHON@", sys.executable)
                  .replace("@BINS@", repr(json.dumps(fake_bins())))
                  .replace("@HOST@", repr(RELEASE_HOST))
                  .replace("@MACHINES@", repr(json.dumps(ELF_MACHINES))))
        executable(bin_dir / "cargo", source)
        return bin_dir

    def release_env(self, **extra) -> dict:
        # Sin CARGO_* del entorno (p. ej. CARGO_TARGET_DIR del contenedor):
        # cada prueba fija el suyo.
        env = {key: value for key, value in os.environ.items() if not key.startswith("CARGO_")}
        stage_tmp = self.tmp / "stage-tmp"
        stage_tmp.mkdir(exist_ok=True)
        env.update(PATH=f"{self._bins_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                   TMPDIR=str(stage_tmp), PS4="+ ", LC_ALL="C")
        env.update(extra)
        return env

    def run_release(self, project: Path, arch: str, env: dict) -> list[list[str]]:
        """Ejecuta el script con bash -x; devuelve los `[ ... ]` de la traza."""
        result = subprocess.run(["bash", "-x", str(project / RELEASE_SCRIPT), arch], cwd=project, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
        if result.returncode != 0:
            self.fail(f"{RELEASE_SCRIPT} {arch} salió con {result.returncode}:\n"
                      f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
        tests = []
        for line in result.stderr.splitlines():
            if not line.startswith("+"):
                continue
            try:
                words = shlex.split(line.lstrip("+").strip())
            except ValueError:
                continue
            if words and words[0] in ("[", "[[", "test"):
                tests.append(words)
        return tests

    def release(self) -> dict:
        """Release de las tres arquitecturas sobre una copia limpia (una vez)."""
        self.require()
        if isinstance(type(self).built, str):
            self.fail(type(self).built)
        if type(self).built is None:
            project = copy_checkout(self.tmp / "project")
            tests = []
            for arch in testlib.ARCHES:
                try:
                    tests += self.run_release(project, arch, self.release_env())
                except AssertionError as error:
                    # Un build roto falla todas las pruebas, sin repetirlo en cada una.
                    type(self).built = str(error)
                    raise
            out = project / "release"
            bundles, workdir = {}, self.tmp / "bundles"
            workdir.mkdir()
            for arch in testlib.ARCHES:
                # Un bundle por contenido distinto (los de edición son copias).
                seen = {}
                for path in sorted((out / arch).glob("*.tar.zst")):
                    seen.setdefault(sha256(path), path)
                bundles[arch] = [Bundle(path, workdir) for path in seen.values()]
                for bundle in bundles[arch]:
                    type(self).addClassCleanup(bundle.tar.close)
            type(self).built = {"project": project, "out": out, "tests": tests, "bundles": bundles}
        return type(self).built

    def all_bundles(self):
        for arch, bundles in self.release()["bundles"].items():
            for bundle in bundles:
                yield arch, bundle

    # ------------------------------------------------------------ manifiestos

    def test_manifests_are_what_the_client_reads(self):
        """Cada updates.json es JSON, el parse_manifest del cliente lo acepta y
        los bundles que nombra están a su lado con ese sha256."""
        built = self.release()
        out = built["out"]
        findings = {}
        manifests = sorted(out.rglob("updates.json"))
        for arch in testlib.ARCHES:
            if not (out / arch / "updates.json").is_file():
                findings[f"release:manifest:missing:{arch}"] = (
                    f"{RELEASE_SCRIPT} {arch} no dejó release/{arch}/updates.json")
        editions = sorted({item.name for item in testlib.EDITIONS} | {"niri"})
        for manifest in manifests:
            rel = manifest.relative_to(out).as_posix()
            try:
                data = json.loads(manifest.read_text(), object_pairs_hook=no_duplicate_keys)
                if not isinstance(data, dict):
                    raise ValueError("no es un objeto JSON")
            except ValueError as error:
                findings[f"release:manifest:json:{rel}"] = (
                    f"release/{rel} no es JSON válido ({error}); churros-update-utils aborta con "
                    f"'updates.json mal formado' en todas las instalaciones")
                continue
            # Lo que saca el cliente, con su propio parse_manifest, para cada
            # edición que puede tener /etc/churros-edition.
            for edition in editions:
                result = client('parse_manifest "$1" "$2"', manifest, edition)
                if result.returncode != 0:
                    findings[f"release:manifest:client:{rel}"] = (
                        f"parse_manifest de churros-update-utils rechaza release/{rel} (edición {edition}): "
                        f"{result.stderr.strip()}")
                    break
                version = result.stdout.strip().split("|")[0]
                if version != VERSION:
                    findings[f"release:manifest:version:{rel}"] = (
                        f"release/{rel} anuncia la versión {version!r}, pero el bundle es de VERSION={VERSION!r}")
            # El cliente descarga ${BASE}<file>: el mismo directorio que el
            # manifiesto (churros-update-utils: fetch_manifest y main).
            problems = []
            for where, name, digest in manifest_entries(data):
                if not isinstance(name, str) or "/" in name or not name:
                    problems.append(f"{where}: nombre de fichero inválido {name!r}")
                    continue
                target = manifest.parent / name
                if not target.is_file():
                    folder = Path(rel).parent.as_posix()
                    problems.append(f"{where}: {name} no está en release/{'' if folder == '.' else folder + '/'}")
                elif digest != sha256(target):
                    problems.append(f"{where}: sha256 {digest!r} no es el de {name} ({sha256(target)})")
            if not list(manifest_entries(data)):
                problems.append("no nombra ningún bundle (ni 'file' ni 'editions')")
            if problems:
                findings[f"release:manifest:files:{rel}"] = (
                    f"release/{rel}: el cliente descarga ${{BASE}}<file> junto al manifiesto y "
                    f"comprueba su sha256: " + "; ".join(problems))
            # Manifiesto de una arquitectura: su campo arch es esa.
            arch = Path(rel).parent.name
            if arch in ELF_MACHINES and data.get("arch") != arch:
                findings[f"release:manifest:arch:{rel}"] = (
                    f"release/{rel} dice arch={data.get('arch')!r}, no {arch!r}")
        testlib.assert_findings(self, "release:manifest", findings)

    # ---------------------------------------------------------------- bundles

    def test_bundle_has_every_deploy_crate(self):
        """usr/bin/<crate> ejecutable, para cada crate con deploy = true."""
        findings = {}
        for arch, bundle in self.all_bundles():
            files = bundle.files()
            for crate in deploy_crates():
                member = files.get(f"usr/bin/{crate.name}")
                if member is None or not member.mode & 0o111:
                    state = "no está" if member is None else f"no es ejecutable ({oct(member.mode)})"
                    findings.setdefault(f"release:crate:{crate.name}", f"usr/bin/{crate.name} {state} en")
                    findings[f"release:crate:{crate.name}"] += f" {arch}/{bundle.path.name}"
        for key in findings:
            findings[key] += (" (crate con deploy = true en rust/; el script lo salta en silencio si "
                              "no encuentra el binario donde lo busca)")
        testlib.assert_findings(self, "release:crate", findings)

    def test_bundle_binaries_match_its_arch(self):
        """Todo ELF del bundle <arch> es de esa máquina."""
        findings = {}
        for arch, bundle in self.all_bundles():
            wrong = []
            for name, member in sorted(bundle.files().items()):
                machine = elf_machine(bundle.read(name, 64))
                if machine is not None and machine != arch:
                    wrong.append(f"{name} ({machine})")
            if wrong:
                findings[f"release:bundle-elf:{arch}"] = (
                    f"{arch}/{bundle.path.name} lleva binarios de otra máquina: {', '.join(wrong)}. "
                    f"`cargo build --release` sin --target compila para el equipo que publica "
                    f"({RELEASE_HOST} en esta prueba)")
        testlib.assert_findings(self, "release:bundle-elf", findings)

    def test_bundle_assets_match_crates(self):
        """usr/share/churros/<crate>/assets/** es idéntico a rust/<crate>/assets/**.

        Las apps leen ahí sus assets en runtime (RUNTIME_ROOT en rust/*/src).
        """
        sources = {}
        for path in testlib.repo_files():
            for crate in deploy_crates():
                assets = crate.directory / "assets"
                if path.is_file() and assets in path.parents:
                    sources.setdefault(crate.name, {})[path.relative_to(assets).as_posix()] = path
        problems = {}
        for arch, bundle in self.all_bundles():
            files = bundle.files()
            for name, expected in sorted(sources.items()):
                prefix = f"usr/share/churros/{name}/assets/"
                shipped = {member[len(prefix):] for member in files if member.startswith(prefix)}
                missing = sorted(set(expected) - shipped)
                stale = sorted(shipped - set(expected))
                differ = sorted(rel for rel in set(expected) & shipped
                                if bundle.read(prefix + rel) != expected[rel].read_bytes())
                parts = []
                if missing:
                    parts.append(f"faltan {len(missing)} de {len(expected)} (p. ej. {missing[0]})")
                if stale:
                    parts.append(f"sobran {len(stale)} que ya no están en el crate (p. ej. {stale[0]})")
                if differ:
                    parts.append(f"{len(differ)} distintos del crate (p. ej. {differ[0]})")
                if parts:
                    problems.setdefault(name, ("; ".join(parts), []))[1].append(f"{arch}/{bundle.path.name}")
        findings = {
            f"release:assets:{name}": (
                f"usr/share/churros/{name}/assets/ en {', '.join(bundles)}: {detail}. El script copia "
                f"archiso/airootfs/usr/share/churros tal cual está en disco, y los assets de los crates solo "
                f"los pone ahí build-rust.sh durante un build de ISO")
            for name, (detail, bundles) in problems.items()
        }
        testlib.assert_findings(self, "release:assets", findings)

    def test_bundle_sources_exist(self):
        """Cada fichero del airootfs que el script comprueba con [ -f ] existe y llega al bundle.

        Las listas del script van con `[ -f ]`: un script renombrado o borrado
        desaparece del bundle sin ningún error. La traza de bash -x da las
        rutas ya expandidas, sin parsear el script.
        """
        built = self.release()
        airootfs = built["project"] / "archiso/airootfs"
        members = set()
        for _, bundle in self.all_bundles():
            members |= set(bundle.files())
        findings = {}
        for words in built["tests"]:
            if len(words) < 3 or words[1] != "-f":
                continue
            path = Path(words[2])
            if airootfs not in path.parents:
                continue
            rel = path.relative_to(airootfs).as_posix()
            if not path.is_file():
                findings[f"release:source:{rel}"] = (
                    f"{RELEASE_SCRIPT} copia archiso/airootfs/{rel} solo si existe, y no existe: "
                    f"el bundle sale sin él y sin error")
            elif rel not in members:
                findings[f"release:source:{rel}"] = (
                    f"archiso/airootfs/{rel} existe y el script lo comprueba, pero no está en el bundle como {rel}")
        testlib.assert_findings(self, "release:source", findings)

    def test_bundle_installs_like_the_iso(self):
        """validate_tarball del cliente acepta cada bundle, y el modo que deja
        install_stage (0755 si el miembro es ejecutable, 0644 si no) es el de
        file_permissions en profiledef.sh: lo que tendría la ISO."""
        findings = {}
        for arch, bundle in self.all_bundles():
            result = client('validate_tarball "$1"', bundle.path)
            if result.returncode != 0:
                findings[f"release:bundle:validate:{arch}"] = (
                    f"validate_tarball de churros-update-utils rechaza {arch}/{bundle.path.name}: "
                    f"{result.stderr.strip()}")
            permissions = testlib.profile(arch)["file_permissions"]
            for name, member in sorted(bundle.files().items()):
                spec = permissions.get(f"/{name}")
                if spec is None:
                    continue
                installed = 0o755 if member.mode & 0o111 else 0o644
                wanted = int(spec.rsplit(":", 1)[1], 8)
                if installed != wanted:
                    findings[f"release:bundle:mode:{name}"] = (
                        f"{name}: el bundle lo instalaría con {installed:o} (install_stage) y la ISO lo deja "
                        f"en {wanted:o} (file_permissions de profiledef.sh); en el bundle va con "
                        f"{member.mode:o}, el modo del fichero en git")
        testlib.assert_findings(self, "release:bundle", findings)

    # ---------------------------------------------------------------- cliente

    def server(self) -> Path:
        """Servidor de releases de la prueba: la salida de release/ tal cual.

        El script deja en release/updates.json un alias del manifiesto x86_64
        «para clientes antiguos», pero sus bundles se quedan en release/x86_64/.
        Aquí se ponen al lado (lo que pretende el alias) para que la simulación
        aísle el problema de arquitectura; que el script no lo haga ya lo
        informa test_manifests_are_what_the_client_reads.
        """
        built = self.release()
        server = self.tmp / "server"
        if server.exists():
            return server
        for path in built["out"].rglob("*"):
            if path.is_file():
                target = server / path.relative_to(built["out"])
                target.parent.mkdir(parents=True, exist_ok=True)
                link(path, target)
        try:
            data = json.loads((server / "updates.json").read_text())
        except (OSError, ValueError):
            return server
        alias_arch = data.get("arch") if data.get("arch") in ELF_MACHINES else RELEASE_HOST
        for _, name, _ in manifest_entries(data):
            if isinstance(name, str) and name and "/" not in name and not (server / name).exists():
                if (server / alias_arch / name).is_file():
                    link(server / alias_arch / name, server / name)
        return server

    def start_client(self, arch: str) -> tuple[subprocess.Popen, Path, Path]:
        """Lanza main de churros-update-utils en un cliente `arch` con root falso."""
        server = self.server()
        # URL que sirve release/: la BASE del cliente; si incluye la
        # arquitectura (uname -m al cargarlo), sin ese último componente.
        base = client_var("BASE")
        for name in ELF_MACHINES:
            if base.endswith(f"/{name}/"):
                base = base[:-len(name) - 1]
        pubkey = client_var("PUBKEY")
        home = self.tmp / f"client-{arch}"
        root, run_dir, stubs, log = home / "root", home / "run", home / "bin", home / "curl.log"
        for rel in ("", "usr", "usr/bin", "usr/local", "usr/local/bin", "usr/share", "etc"):
            (root / rel).mkdir(parents=True, exist_ok=True)
            (root / rel).chmod(0o755)
        run_dir.mkdir()
        (home / "tmp").mkdir()
        log.touch()
        (root / "etc/churros-edition").write_text("niri\n")
        (root / "etc/churros-version").write_text("0\n")
        executable(stubs / "curl", CURL_STUB)
        executable(stubs / "uname", UNAME_STUB.replace("@UNAME@", shutil.which("uname") or "/usr/bin/uname"))
        executable(stubs / "arch", ARCH_STUB)
        shipped_key = testlib.airootfs(pubkey)
        if shipped_key.is_file():
            # Una instalación de la ISO tiene la clave del repo: la firma se exige.
            target = root / pubkey.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(shipped_key, target)
            executable(stubs / "minisign", MINISIGN_STUB)
        env = {key: value for key, value in os.environ.items() if not key.startswith("CHURROS_")}
        env.update(PATH=f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}", TMPDIR=str(home / "tmp"),
                   CHURROS_CLIENT=str(CLIENT), FAKE_ROOT=str(root), CHURROS_TEST_ARCH=arch,
                   CHURROS_TEST_SERVER=str(server), CHURROS_TEST_BASE=base, CHURROS_TEST_LOG=str(log),
                   CHURROS_TEST_RUN=str(run_dir), LC_ALL="C")
        process = subprocess.Popen(["bash", "-c", CLIENT_DRIVER], env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        self.addCleanup(lambda: (process.kill(), process.communicate()))
        return process, root, log

    def test_client_installs_binaries_of_its_arch(self):
        """Un cliente x86_64, aarch64 o i686 se actualiza y solo instala ELF de su máquina.

        El cliente se ejecuta entero (main real) con `uname -m` y `arch` falsos
        y un curl que sirve release/; install_stage escribe en un root falso.
        Si un arreglo detecta la arquitectura de otra forma (platform.machine()
        de python, pacman-conf), hay que simularla aquí también.
        """
        # Los tres clientes a la vez: son independientes e install_stage es lento.
        clients = {arch: self.start_client(arch) for arch in testlib.ARCHES}
        findings = {}
        for arch, (process, root, log) in clients.items():
            output, _ = process.communicate(timeout=300)
            urls = log.read_text().split()
            foreign, installed = [], set()
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    rel = path.relative_to(root).as_posix()
                    installed.add(rel)
                    with path.open("rb") as handle:
                        machine = elf_machine(handle.read(64))
                    if machine is not None and machine != arch:
                        foreign.append(f"/{rel} ({machine})")
            fetched = ", ".join(url.rsplit("/", 2)[-2] + "/" + url.rsplit("/", 1)[-1] for url in urls)
            if foreign:
                findings[f"release:client:arch:{arch}"] = (
                    f"un cliente {arch} instaló binarios de otra máquina: {', '.join(foreign[:3])}"
                    f"{' ...' if len(foreign) > 3 else ''} (descargó: {fetched}). churros-update-utils lee "
                    f"siempre ${{BASE}}updates.json, sin arquitectura, y validate_tarball no mira la máquina ELF")
            missing = [crate.name for crate in deploy_crates() if f"usr/bin/{crate.name}" not in installed]
            if process.returncode != 0 or missing:
                why = (f"salió con {process.returncode}: {output.strip().splitlines()[-1:]}"
                       if process.returncode != 0 else f"no instaló {', '.join(missing)}")
                findings[f"release:client:update:{arch}"] = (
                    f"un cliente {arch} no se actualiza con la release recién generada: {why} "
                    f"(descargó: {fetched or 'nada'})")
        testlib.assert_findings(self, "release:client", findings)

    # ----------------------------------------------------- CARGO_TARGET_DIR

    def test_release_ships_what_cargo_just_built(self):
        """Con CARGO_TARGET_DIR (lo exporta scripts/lib/container.sh y lo
        respeta build-rust.sh), el bundle lleva los binarios recién compilados,
        no los que hubiera en rust/target/release de otra compilación."""
        self.require()
        project = copy_checkout(self.tmp / "project-target-dir")
        stale_dir = project / "rust/target/release"
        stale_dir.mkdir(parents=True)
        for crate in deploy_crates():
            stale = stale_dir / crate.name
            stale.write_bytes(fake_elf(RELEASE_HOST, "\ncompilación vieja\n"))
            stale.chmod(0o755)
        target_dir, log = self.tmp / "cargo-target-dir", self.tmp / "cargo-target-dir.log"
        self.run_release(project, RELEASE_HOST, self.release_env(
            CARGO_TARGET_DIR=str(target_dir), CHURROS_FAKE_CARGO_STAMP="recien-compilado",
            CHURROS_FAKE_CARGO_LOG=str(log)))
        # Donde dejó cargo los binarios (con o sin --target).
        built_dir = Path(log.read_text().split()[-1])
        manifest = json.loads((project / "release" / RELEASE_HOST / "updates.json").read_text())
        workdir = self.tmp / "bundles-target-dir"
        workdir.mkdir()
        bundle = Bundle(project / "release" / RELEASE_HOST / manifest["editions"]["niri"]["file"], workdir)
        self.addCleanup(bundle.tar.close)
        problems = []
        for crate in deploy_crates():
            fresh = built_dir / crate.name
            name = f"usr/bin/{crate.name}"
            if name not in bundle.members:
                problems.append(f"{name} falta")
            elif bundle.read(name) != fresh.read_bytes():
                problems.append(f"{name} es el de rust/target/release")
        findings = {}
        if problems:
            findings["release:cargo-target-dir:stale-binaries"] = (
                f"con CARGO_TARGET_DIR={target_dir} el bundle no lleva lo que acaba de compilar cargo: "
                f"{'; '.join(problems)}. {RELEASE_SCRIPT} busca siempre en rust/target/release y salta "
                f"en silencio lo que no encuentra")
        testlib.assert_findings(self, "release:cargo-target-dir", findings)

    # ------------------------------------------------------------------ firma

    def test_manifest_signing(self):
        """Si hay clave pública, la firma se puede verificar de punta a punta.

        verify_manifest (churros-update-utils) sin el fichero $PUBKEY solo
        avisa por stdout y sigue: el manifiesto, y con él el sha256 del bundle
        que root instala, queda sin autenticar. Con clave, exige minisign y
        ${BASE}updates.json.minisig.
        """
        built = self.release()
        pubkey = client_var("PUBKEY").lstrip("/")
        shipped = testlib.airootfs("/" + pubkey).is_file() or any(
            pubkey in bundle.members for _, bundle in self.all_bundles())
        findings = {}
        if not shipped:
            findings["release:signing:unsigned-manifest"] = (
                f"no hay clave pública de releases (/{pubkey}) ni en el airootfs ni en el bundle: "
                f"verify_manifest solo avisa y el cliente instala como root lo que sirva el servidor")
        else:
            for item in testlib.EDITIONS:
                if "minisign" not in testlib.installed(item):
                    findings[f"release:signing:minisign:{item.id}"] = (
                        f"hay clave pública pero {item.package_list} no instala minisign: "
                        f"churros-update-utils aborta con 'falta minisign' en {item.id}")
            for manifest in sorted(built["out"].rglob("updates.json")):
                rel = manifest.relative_to(built["out"]).as_posix()
                if not manifest.with_name("updates.json.minisig").is_file():
                    findings[f"release:signing:minisig:{rel}"] = (
                        f"hay clave pública pero {RELEASE_SCRIPT} no deja release/{rel}.minisig: "
                        f"el cliente aborta con 'no se pudo obtener la firma'")
        testlib.assert_findings(self, "release:signing", findings)


if __name__ == "__main__":
    unittest.main()
