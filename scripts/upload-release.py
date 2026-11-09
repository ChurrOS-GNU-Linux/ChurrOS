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
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

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
                import hashlib
                import tempfile
                lines = []
                for p in files:
                    digest = hashlib.sha256()
                    with p.open("rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b""):
                            digest.update(chunk)
                    lines.append(f"{digest.hexdigest()}  {p.name}\n")
                print("\n==> Subiendo ISOs y sumas de verificación a /...")
                for p in files:
                    upload_tus(args.url, token, p, "")
                with tempfile.TemporaryDirectory() as tmp:
                    sums = Path(tmp) / "SHA256SUMS"
                    sums.write_text("".join(lines), encoding="utf-8")
                    print("".join(lines), end="")
                    upload_tus(args.url, token, sums, "")

    print("\n✓ Proceso de subida finalizado con éxito.")


if __name__ == "__main__":
    main()
