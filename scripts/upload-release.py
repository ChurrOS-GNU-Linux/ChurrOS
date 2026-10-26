#!/usr/bin/env python3
"""
scripts/upload-release.py — Sube ficheros de release (ISOs y bundles OTA)
al servidor FileBrowser de ChurrOS (https://download.churroslinux.org/upload)
usando el protocolo TUS para soportar ficheros de cualquier tamaño a través de Cloudflare.
"""

import argparse
import base64
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


def login(base_url: str, username: str, password: str) -> str:
    login_url = f"{base_url.rstrip('/')}/api/login"
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        login_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ChurrOS-ReleaseUploader/1.4"},
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
            "User-Agent": "ChurrOS-ReleaseUploader/1.4",
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
                            "User-Agent": "ChurrOS-ReleaseUploader/1.4",
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
    parser.add_argument("--password", default=os.getenv("CHURROS_UPLOAD_PASSWORD", "X_40Loataimado"), help="Contraseña")
    parser.add_argument("--ota-only", action="store_true", help="Solo subir bundles OTA (/churros/)")
    parser.add_argument("--iso-only", action="store_true", help="Solo subir ISOs y sumas a la raíz (/)")
    parser.add_argument("--file", help="Subir un fichero específico")
    parser.add_argument("--dest", default="", help="Directorio remoto de destino para --file (def: raíz)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

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

    # Subida de OTA bundles a /churros/
    if not args.iso_only:
        ota_dir = repo_root / "release"
        ota_files = [
            ota_dir / "updates.json",
            ota_dir / "churros-utils-1.4-x86_64.tar.zst",
            ota_dir / "churros-utils-niri-1.4-x86_64.tar.zst",
            ota_dir / "churros-utils-xfce-1.4-x86_64.tar.zst",
        ]
        print("\n==> Subiendo bundles de actualización OTA a /churros/...")
        for p in ota_files:
            if p.is_file():
                upload_tus(args.url, token, p, "churros")
            else:
                print(f"  ! Aviso: {p.name} no encontrado en {ota_dir}")

    # Subida de ISOs a la raíz (/)
    if not args.ota_only:
        iso_dir = repo_root / "release" / "iso"
        if not iso_dir.is_dir():
            print(f"\n! Aviso: {iso_dir} no existe todavía.")
        else:
            files = sorted(list(iso_dir.glob("ChurrOS-*.iso")) + list(iso_dir.glob("SHA256SUMS*")))
            if not files:
                print(f"\n! Aviso: no hay ISOs en {iso_dir} todavía.")
            else:
                print("\n==> Subiendo ISOs y sumas de verificación a /...")
                for p in files:
                    upload_tus(args.url, token, p, "")

    print("\n✓ Proceso de subida finalizado con éxito.")


if __name__ == "__main__":
    main()
