#!/usr/bin/env python3
"""
scripts/upload-release.py — Sube ficheros de release (ISOs y bundles OTA)
al servidor FileBrowser de ChurrOS (https://download.churroslinux.org/upload)
usando el protocolo TUS para soportar ficheros de cualquier tamaño a través de Cloudflare.
"""

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://download.churroslinux.org/upload"
DEFAULT_USER = "Hoyuse"
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks (matches Cloudflare-safe limits)
# Versión de la distro (VERSION): nombres de los bundles OTA y User-Agent.
VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
USER_AGENT = f"ChurrOS-ReleaseUploader/{VERSION}"


def login(base_url: str, username: str, password: str) -> str:
    login_url = f"{base_url.rstrip('/')}/api/login"
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        login_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8").strip('"')


def upload_tus(base_url: str, token: str, local_path: Path, remote_dest_path: str, chunk_size: int = DEFAULT_CHUNK_SIZE):
    file_size = local_path.stat().st_size
    file_name = local_path.name
    dest_path = f"{remote_dest_path.rstrip('/')}/{file_name}".lstrip("/")

    tus_endpoint = f"{base_url.rstrip('/')}/api/tus/{dest_path}?override=true"
    
    print(f"\n[upload] Subiendo: {file_name} ({file_size / (1024*1024):.2f} MB)")
    print(f"         Destino: /{dest_path}")

    # 1. Crear sesión TUS
    req = urllib.request.Request(
        tus_endpoint,
        method="POST",
        headers={
            "X-Auth": token,
            "Tus-Resumable": "1.0.0",
            "Upload-Length": str(file_size),
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            location = resp.headers.get("Location")
            if not location:
                raise RuntimeError("El servidor no devolvió cabecera Location en TUS POST")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Error al iniciar subida TUS ({e.code}): {body}")

    patch_url = location if location.startswith("http") else urllib.parse.urljoin(base_url, location)

    # 2. Subir chunks secuenciales con PATCH
    offset = 0
    start_time = time.time()
    with open(local_path, "rb") as f:
        while offset < file_size:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            chunk_len = len(chunk)

            retries = 3
            while retries > 0:
                try:
                    patch_req = urllib.request.Request(
                        patch_url,
                        data=chunk,
                        method="PATCH",
                        headers={
                            "X-Auth": token,
                            "Tus-Resumable": "1.0.0",
                            "Upload-Offset": str(offset),
                            "Content-Type": "application/offset+octet-stream",
                            "Content-Length": str(chunk_len),
                            "User-Agent": USER_AGENT,
                        },
                    )
                    with urllib.request.urlopen(patch_req) as patch_resp:
                        new_offset_hdr = patch_resp.headers.get("Upload-Offset")
                        if new_offset_hdr:
                            offset = int(new_offset_hdr)
                        else:
                            offset += chunk_len
                    break
                except Exception as err:
                    retries -= 1
                    if retries == 0:
                        raise RuntimeError(f"Error subiendo chunk en offset {offset}: {err}")
                    time.sleep(2)

            percent = (offset / file_size) * 100
            elapsed = time.time() - start_time
            speed_mb = (offset / (1024 * 1024)) / elapsed if elapsed > 0 else 0
            sys.stdout.write(
                f"\r  Progreso: {percent:6.2f}% | {offset / (1024*1024):.1f}/{file_size / (1024*1024):.1f} MB | {speed_mb:.2f} MB/s"
            )
            sys.stdout.flush()

    total_time = time.time() - start_time
    print(f"\n  ✓ Completado en {total_time:.1f} s ({file_name})")


def iso_sums_files(directory: Path, version: str, text: str) -> list[Path]:
    """Escribe en `directory` las sumas de las ISO de `version`.

    `SHA256SUMS` es el de la versión actual (docs/release.md) y se reemplaza
    en cada publicación; `SHA256SUMS-<versión>` no lo pisa ninguna otra, así
    que las ISO de versiones anteriores, que siguen enlazadas en el historial
    de la web, se pueden seguir verificando. Antes solo se subía SHA256SUMS y
    las sumas de la 1.5 desaparecieron al publicar la 1.5.5. Devuelve las dos
    rutas en el orden de subida: la versionada primero.
    """
    versioned = directory / f"SHA256SUMS-{version}"
    current = directory / "SHA256SUMS"
    for path in (versioned, current):
        path.write_text(text, encoding="utf-8")
    return [versioned, current]


def iso_sums_text(files: list[Path]) -> str:
    """Contenido de SHA256SUMS para `files`: «<sha256>  <nombre>» por línea."""
    import hashlib
    lines = []
    for p in files:
        digest = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        lines.append(f"{digest.hexdigest()}  {p.name}\n")
    return "".join(lines)


# ChurrOS-<versión>-<edición>-<arch>.iso (docs/release.md).
ISO_NAME = re.compile(r"ChurrOS-(?P<version>\d+(?:\.\d+)+)-(?P<edition>[a-z]+)-(?P<arch>x86_64|aarch64|i686)\.iso")
EDITIONS = ("niri", "xfce", "server", "pi")


def read_iso_identity(iso: Path) -> dict:
    """Lo que dice la propia ISO, sin montarla ni extraerla (#344).

    airootfs.sfs está contiguo dentro de la imagen ISO 9660: xorriso da su
    primer bloque y unsquashfs lee ficheros sueltos con ese desplazamiento.
    Devuelve {"archs": [arquitecturas con airootfs.sfs], "version": VERSION_ID
    de os-release, "edition": /etc/churros-edition} (None si falta).
    """
    report = subprocess.run(["xorriso", "-indev", str(iso), "-find", "/", "-name", "airootfs.sfs",
                             "-exec", "report_lba", "--"], capture_output=True, text=True).stdout
    sfs = {path.split("/")[-2]: int(lba) for lba, path in
           re.findall(r"File data lba:\s*\d+\s*,\s*(\d+)\s*,\s*\d+\s*,\s*\d+\s*,\s*'(/[^']+/airootfs\.sfs)'", report)}
    identity = {"archs": sorted(sfs), "version": None, "edition": None}
    if len(sfs) != 1:
        return identity

    def cat(path: str) -> str | None:
        result = subprocess.run(["unsquashfs", "-o", str(next(iter(sfs.values())) * 2048), "-cat", str(iso), path],
                                capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else None

    os_release = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', cat("/etc/os-release") or "", re.M))
    identity["version"] = os_release.get("VERSION_ID")
    identity["edition"] = (cat("/etc/churros-edition") or "").strip() or None
    return identity


def iso_problems(name: str, version: str, identity: dict) -> list[str]:
    """Qué no cuadra entre el nombre de la ISO, la versión que se publica y su contenido."""
    match = ISO_NAME.fullmatch(name)
    if not match:
        return [f"{name}: el nombre no es ChurrOS-<versión>-<edición>-<arch>.iso"]
    problems = []
    if match["version"] != version:
        problems.append(f"{name}: el nombre dice {match['version']}, pero se publica la {version}")
    if match["edition"] not in EDITIONS:
        problems.append(f"{name}: edición desconocida '{match['edition']}' (válidas: {', '.join(EDITIONS)})")
    if identity["archs"] != [match["arch"]]:
        problems.append(f"{name}: dentro hay airootfs para {identity['archs'] or 'ninguna arquitectura'}, "
                        f"no solo para {match['arch']}")
    if identity["version"] != match["version"]:
        problems.append(f"{name}: su os-release dice VERSION_ID={identity['version']}")
    if identity["edition"] != match["edition"]:
        problems.append(f"{name}: su /etc/churros-edition dice {identity['edition']}")
    return problems


def sums_problems(text: str, names: list[str]) -> list[str]:
    """SHA256SUMS: cada ISO que se sube exactamente una vez y nada más."""
    problems, seen = [], []
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
        if not match:
            problems.append(f"SHA256SUMS: línea mal formada: {line!r}")
            continue
        seen.append(match[2])
    for name in sorted(set(seen)):
        if seen.count(name) > 1:
            problems.append(f"SHA256SUMS: {name} aparece {seen.count(name)} veces")
        if name not in names:
            problems.append(f"SHA256SUMS: {name} no está entre las ISO que se suben")
    problems += [f"SHA256SUMS: falta {name}" for name in names if name not in seen]
    return problems


DOWNLOAD_BASE = "https://download.churroslinux.org/"
EDITION_TITLES = {"niri": "Niri", "xfce": "XFCE", "server": "Server", "pi": "Raspberry Pi Lite"}


def probe(url: str, method: str = "HEAD", attempts: int = 4) -> tuple[int, str, int]:
    """(código HTTP, cuerpo si es GET, Content-Length) de una URL del servidor.

    Un 5xx se reintenta con espera: el servidor da 503 cuando está ocupado y eso
    no significa que falte el fichero. Un 404 se devuelve tal cual.
    """
    status, body, length = 0, "", 0
    for attempt in range(attempts):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status = response.status
                length = int(response.headers.get("Content-Length") or 0)
                body = response.read().decode("utf-8", "replace") if method == "GET" else ""
        except urllib.error.HTTPError as error:
            status, body, length = error.code, "", 0
        except (urllib.error.URLError, TimeoutError) as error:
            status, body, length = 0, str(error), 0
        if 0 < status < 500:
            break
        time.sleep(5 * (attempt + 1))
    return status, body, length


def human_size(size: int) -> str:
    return f"{size / 1024 ** 3:.1f} GiB".replace(".", ",")


def release_notes(version: str, isos: list[tuple[str, int]], sums: str, probe=probe) -> tuple[str, list[str]]:
    """Sección «Descargas» de las notas de la GitHub Release (#340).

    Las ISO no caben en GitHub (2 GiB): la release las enlaza en el servidor
    oficial, la única ubicación fuente, nunca en artefactos de un workflow.
    Antes de escribir nada comprueba que cada enlace existe con el tamaño de la
    ISO local y que el SHA256SUMS-<versión> del servidor es el local. Devuelve
    (markdown, problemas); con algún problema el markdown va vacío.
    """
    names = [name for name, _ in isos]
    problems = sums_problems(sums, names)
    digests = {name: digest for digest, name in (line.split("  ", 1) for line in sums.splitlines() if "  " in line)}
    rows = []
    for name, size in isos:
        match = ISO_NAME.fullmatch(name)
        if not match or match["version"] != version:
            problems.append(f"{name}: no es una ISO de la versión {version} (ChurrOS-{version}-<edición>-<arch>.iso)")
            continue
        url = DOWNLOAD_BASE + urllib.parse.quote(name)
        status, _, length = probe(url, "HEAD")
        if status != 200:
            problems.append(f"{url}: HTTP {status or 'sin respuesta'}")
        elif length != size:
            problems.append(f"{url}: el servidor tiene {length} bytes y la ISO local {size}")
        rows.append(f"| {EDITION_TITLES.get(match['edition'], match['edition'])} | {match['arch']} "
                    f"| [{name}]({url}) | {human_size(size)} | `{digests.get(name, '?')}` |")
    sums_name = f"SHA256SUMS-{version}"
    sums_url = DOWNLOAD_BASE + sums_name
    status, served, _ = probe(sums_url, "GET")
    if status != 200:
        problems.append(f"{sums_url}: HTTP {status or 'sin respuesta'}")
    elif served != sums:
        problems.append(f"{sums_url}: no coincide con las sumas de las ISO locales")
    if problems:
        return "", problems
    notes = f"""## Descargas

Las ISO pesan más de 2 GiB, el límite de GitHub Releases: se descargan del servidor oficial y esta release solo las enlaza.

| Edición | Arquitectura | ISO | Tamaño | SHA-256 |
|---|---|---|---|---|
{chr(10).join(rows)}

Sumas de esta versión: [{sums_name}]({sums_url}). Para comprobar la descarga, con la ISO y ese fichero en la misma carpeta:

```bash
sha256sum -c {sums_name} --ignore-missing
```

> **Las sumas no van firmadas.** Detectan una descarga corrupta, pero no prueban que la ISO sea de ChurrOS: quien pudiera cambiar la ISO en el servidor podría cambiar también su suma. La firma independiente está pendiente ([#315](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/315)).
"""
    return notes, []


def main():
    parser = argparse.ArgumentParser(description="Sube ficheros de release a download.churroslinux.org")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL base de FileBrowser (def: {DEFAULT_URL})")
    parser.add_argument("--user", default=DEFAULT_USER, help=f"Usuario (def: {DEFAULT_USER})")
    # Nunca una contraseña por defecto en el código: el repositorio es público.
    parser.add_argument("--password", default=os.getenv("CHURROS_UPLOAD_PASSWORD"),
                        help="Contraseña (o CHURROS_UPLOAD_PASSWORD; si falta, se pregunta)")
    parser.add_argument("--arch", default="x86_64", help="Arquitectura de los bundles OTA (def: x86_64)")
    parser.add_argument("--ota-only", action="store_true", help="Solo subir bundles OTA (/churros/)")
    parser.add_argument("--iso-only", action="store_true", help="Solo subir ISOs y sumas a la raíz (/)")
    parser.add_argument("--file", help="Subir un fichero específico")
    parser.add_argument("--dest", default="", help="Directorio remoto de destino para --file (def: raíz)")
    parser.add_argument("--release-notes", action="store_true",
                        help="No sube nada: comprueba en el servidor las ISO de esta versión y escribe en la "
                             "salida la sección «Descargas» de las notas de la GitHub Release")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    if args.release_notes:
        files = sorted((repo_root / "release" / "iso").glob(f"ChurrOS-{VERSION}-*.iso"))
        if not files:
            print(f"Error: no hay ISO de la {VERSION} en release/iso/", file=sys.stderr)
            sys.exit(1)
        print(f"==> Calculando el SHA-256 de {len(files)} ISO y comprobando el servidor...", file=sys.stderr)
        notes, problems = release_notes(VERSION, [(p.name, p.stat().st_size) for p in files], iso_sums_text(files))
        if problems:
            print("Error: no se escriben las notas:\n  " + "\n  ".join(problems), file=sys.stderr)
            sys.exit(1)
        print(notes, end="")
        return

    if not args.password:
        args.password = getpass.getpass(f"Contraseña de {args.user} en {args.url}: ")

    print(f"==> Conectando a {args.url} como '{args.user}'...")
    token = login(args.url, args.user, args.password)
    print("✓ Autenticación exitosa.")

    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"Error: {path} no existe", file=sys.stderr)
            sys.exit(1)
        upload_tus(args.url, token, path, args.dest)
        return

    # Bundles OTA (scripts/build-churros-release.sh -> release/<arch>/).
    # churros-update-utils 1.5+ los lee de /churros/<arch>/ y exige
    # updates.json.minisig. La 1.4 (sin clave pública) lee /churros/ y solo
    # comprueba el sha256: se publica también ahí para que pueda actualizar.
    if not args.iso_only:
        ota_dir = repo_root / "release" / args.arch
        manifest = ota_dir / "updates.json"
        signature = ota_dir / "updates.json.minisig"
        bundles = [ota_dir / f"churros-utils{edition}-{VERSION}-{args.arch}.tar.zst"
                   for edition in ("", "-niri", "-xfce")]
        missing = [p.name for p in (manifest, signature, *bundles) if not p.is_file()]
        if missing:
            print(f"Error: faltan en {ota_dir}: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        if json.loads(manifest.read_text(encoding="utf-8")).get("version") != VERSION:
            print(f"Error: {manifest} no es de la versión {VERSION}", file=sys.stderr)
            sys.exit(1)
        destinations = [f"churros/{args.arch}"] + (["churros"] if args.arch == "x86_64" else [])
        for dest in destinations:
            print(f"\n==> Subiendo bundles OTA a /{dest}/...")
            # El manifiesto al final: nadie lo ve antes de que estén los bundles.
            for p in (*bundles, signature, manifest):
                upload_tus(args.url, token, p, dest)

    # Subida de ISOs a la raíz (/)
    if not args.ota_only:
        iso_dir = repo_root / "release" / "iso"
        if not iso_dir.is_dir():
            print(f"\n! Aviso: {iso_dir} no existe todavía.")
        else:
            # Solo las ISO de esta versión (ChurrOS-<versión>-<edición>-<arch>.iso).
            files = sorted(iso_dir.glob(f"ChurrOS-{VERSION}-*.iso"))
            if not files:
                print(f"\n! Aviso: no hay ISOs en {iso_dir} todavía.")
            else:
                # SHA256SUMS cubre solo las ISO de esta versión (docs/release.md):
                # se genera aquí para no subir el de una versión anterior.
                import tempfile
                lines = iso_sums_text(files).splitlines(keepends=True)
                # Antes de subir nada: cada ISO es lo que dice su nombre (#344).
                problems = []
                for p in files:
                    problems += iso_problems(p.name, VERSION, read_iso_identity(p))
                problems += sums_problems("".join(lines), [p.name for p in files])
                if problems:
                    print("\nError: no se sube ninguna ISO:\n  " + "\n  ".join(problems), file=sys.stderr)
                    sys.exit(1)
                print(f"✓ {len(files)} ISO comprobadas: nombre, versión, edición y arquitectura cuadran con su contenido")
                print("\n==> Subiendo ISOs y sumas de verificación a /...")
                for p in files:
                    upload_tus(args.url, token, p, "")
                with tempfile.TemporaryDirectory() as tmp:
                    print("".join(lines), end="")
                    for sums in iso_sums_files(Path(tmp), VERSION, "".join(lines)):
                        upload_tus(args.url, token, sums, "")

    print("\n✓ Proceso de subida finalizado con éxito.")


if __name__ == "__main__":
    main()
