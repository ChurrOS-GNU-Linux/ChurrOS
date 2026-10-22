# ==============================================================================
# ChurrOS — Compilador Automático del Kernel ChurrOSvyper en Windows
# ==============================================================================
# Este script automatiza la compilación del kernel linux-churrosvyper (CachyOS BORE)
# en Windows utilizando Docker Desktop o Podman.
#
# Todo el proceso compila dentro de un contenedor oficial de Arch Linux con
# Clang + ThinLTO + Rust, aislando la compilación de las limitaciones de NTFS
# (como la insensibilidad a mayúsculas/minúsculas y la lentitud de I/O).
#
# Paquetes generados:
#   windows/output/linux-churrosvyper-*.pkg.tar.zst
#   windows/output/linux-churrosvyper-headers-*.pkg.tar.zst
# ==============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [int]$Jobs = 0,

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    [Parameter(Mandatory = $false)]
    [switch]$RebuildImage,

    [Parameter(Mandatory = $false)]
    [switch]$Interactive,

    [Parameter(Mandatory = $false)]
    [switch]$Help
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Show-Usage {
    Write-Host @"
Uso: .\build-kernel.ps1 [-Jobs <hilos>] [-Force] [-RebuildImage] [-Interactive]

Parámetros:
  -Jobs <número>    Cantidad de hilos paralelos (por defecto: automático según CPU).
  -Force            Fuerza la recompilación aunque los paquetes ya existan en output/.
  -RebuildImage     Reconstruye la imagen del contenedor de build desde cero.
  -Interactive      Abre una sesión interactiva bash dentro del contenedor para depuración.
  -Help             Muestra esta ayuda.

Ejemplos:
  .\build-kernel.ps1
  .\build-kernel.ps1 -Jobs 8
  .\build-kernel.ps1 -Force -Jobs 12
"@
    exit 0
}

if ($Help) {
    Show-Usage
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$OutputDir = Join-Path $ScriptDir "output"

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "    ChurrOS — Compilador del Kernel ChurrOSvyper        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detección del motor de contenedores (Docker o Podman)
$Engine = $null

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerCheck = & docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        $Engine = "docker"
    }
}

if (-not $Engine -and (Get-Command podman -ErrorAction SilentlyContinue)) {
    $podmanCheck = & podman info 2>&1
    if ($LASTEXITCODE -eq 0) {
        $Engine = "podman"
    }
}

# Si Docker está instalado pero el daemon no responde, intentar dar tiempo o avisar
if (-not $Engine -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[i] Docker está instalado pero el servicio no responde." -ForegroundColor Yellow
    Write-Host "    Intentando verificar si Docker Desktop se está iniciando..." -ForegroundColor Yellow
    
    $attempts = 0
    while ($attempts -lt 6) {
        Start-Sleep -Seconds 3
        $dockerCheck = & docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            $Engine = "docker"
            break
        }
        $attempts++
    }
}

if (-not $Engine) {
    Write-Host "==========================================================" -ForegroundColor Red
    Write-Host "  Error: No se encontró Docker Desktop ni Podman activo   " -ForegroundColor Red
    Write-Host "==========================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Para compilar el kernel de Arch Linux en Windows se necesita un motor de contenedores."
    Write-Host "Puedes instalar Docker Desktop fácilmente desde una terminal como Administrador:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    winget install Docker.DockerDesktop" -ForegroundColor Green
    Write-Host ""
    Write-Host "O si prefieres Podman:" -ForegroundColor Yellow
    Write-Host "    winget install RedHat.Podman-Desktop" -ForegroundColor Green
    Write-Host ""
    Write-Host "Si ya tienes Docker Desktop instalado, por favor ábrelo desde el menú de inicio y espera"
    Write-Host "a que termine de iniciar antes de volver a ejecutar este script."
    exit 1
}

Write-Host "[✓] Motor de contenedores detectado: $Engine" -ForegroundColor Green

# 2. Detección de recursos del sistema (CPU y RAM)
$cpuCount = [Environment]::ProcessorCount
$ramGB = 8
try {
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    if ($cs -and $cs.TotalPhysicalMemory) {
        $ramGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    }
} catch {}

Write-Host "[i] Recursos detectados en Windows: $cpuCount hilos de CPU, ~$ramGB GB de RAM" -ForegroundColor Gray

if ($Jobs -le 0) {
    # Si tiene 8GB o menos de RAM, limitar a 4 hilos por seguridad contra OOM
    if ($ramGB -le 8.5 -and $cpuCount -gt 4) {
        $Jobs = 4
        Write-Host "[!] Memoria ajustada: limitando a 4 hilos para evitar saturación de RAM con LTO" -ForegroundColor Yellow
    } else {
        $Jobs = $cpuCount
    }
}

Write-Host "[i] Hilos de compilación configurados: $Jobs" -ForegroundColor Cyan

# 3. Verificar si los paquetes ya fueron compilados previamente
$existingPackages = Get-ChildItem -Path $OutputDir -Filter "linux-churrosvyper-*.pkg.tar.zst" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*-headers-*" }
if ($existingPackages -and -not $Force) {
    Write-Host ""
    Write-Host "[skip] El kernel ya se encuentra compilado en:" -ForegroundColor Green
    foreach ($pkg in $existingPackages) {
        Write-Host "       - $($pkg.FullName) ($([math]::Round($pkg.Length / 1MB, 2)) MB)" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Usa '.\build-kernel.ps1 -Force' si deseas forzar la recompilación." -ForegroundColor Gray
    exit 0
}

# 4. Construcción o verificación de la imagen de build
$ImageName = "churros-builder"
$imageExists = & $Engine images -q $ImageName 2>$null

if (-not $imageExists -or $RebuildImage) {
    Write-Host ""
    Write-Host "[1/3] Construyendo imagen de compilación Arch Linux ($ImageName)..." -ForegroundColor Cyan
    Write-Host "      (Esto descarga el toolchain oficial: Clang, LLVM, Rust, binutils, etc.)" -ForegroundColor Gray
    
    $containerfilePath = Join-Path $RepoRoot "Containerfile"
    & $Engine build -t $ImageName -f $containerfilePath $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error al construir la imagen de contenedor." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "[✓] Imagen construida correctamente." -ForegroundColor Green
} else {
    Write-Host "[✓] Imagen $ImageName disponible." -ForegroundColor Green
}

# 5. Ejecutar la compilación dentro del contenedor
Write-Host ""
Write-Host "[2/3] Iniciando compilación de Linux ChurrOSvyper..." -ForegroundColor Cyan
Write-Host "      Los archivos intermedios se compilan en ext4 dentro del contenedor" -ForegroundColor Gray
Write-Host "      para máxima velocidad y evitar errores de nombres en NTFS de Windows." -ForegroundColor Gray
Write-Host ""

# Convertir rutas a formato apto para Docker en Windows
$repoMount = ($RepoRoot -replace '\\', '/').TrimEnd('/')
$outputMount = ($OutputDir -replace '\\', '/').TrimEnd('/')

$forceFlag = ""
if ($Force) { $forceFlag = "--force" }

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

if ($Interactive) {
    Write-Host "[i] Entrando en modo interactivo bash..." -ForegroundColor Yellow
    & $Engine run --rm -it `
        -v "${repoMount}:/churros" `
        -v "${outputMount}:/output" `
        -e "CHURROS_IN_CONTAINER=1" `
        -e "CHURROS_HOST_UID=1000" `
        -e "CHURROS_HOST_GID=1000" `
        -e "CHURROS_KERNEL_WORK_DIR=/tmp/work-kernel" `
        -e "CHURROS_PKG_DIR=/output" `
        -e "NUMJOBS=$Jobs" `
        $ImageName `
        /churros/scripts/container-entrypoint.sh bash
} else {
    & $Engine run --rm `
        -v "${repoMount}:/churros:ro" `
        -v "${outputMount}:/output" `
        -e "CHURROS_IN_CONTAINER=1" `
        -e "CHURROS_HOST_UID=1000" `
        -e "CHURROS_HOST_GID=1000" `
        -e "CHURROS_KERNEL_WORK_DIR=/tmp/work-kernel" `
        -e "CHURROS_PKG_DIR=/output" `
        -e "NUMJOBS=$Jobs" `
        $ImageName `
        /churros/scripts/container-entrypoint.sh bash -c "sudo chmod -R 777 /output 2>/dev/null || true; bash /churros/scripts/build-kernel-vyper.sh $forceFlag"

    $exitCode = $LASTEXITCODE
    $stopwatch.Stop()

    if ($exitCode -ne 0) {
        Write-Host ""
        Write-Host "==========================================================" -ForegroundColor Red
        Write-Host "  Error durante la compilación del kernel (código $exitCode)" -ForegroundColor Red
        Write-Host "==========================================================" -ForegroundColor Red
        exit $exitCode
    }

    Write-Host ""
    Write-Host "[3/3] Compilación completada con éxito en $($stopwatch.Elapsed.ToString('hh\:mm\:ss'))." -ForegroundColor Green
    Write-Host ""
    Write-Host "Paquetes generados en: $OutputDir" -ForegroundColor Green
    Get-ChildItem -Path $OutputDir -Filter "*.pkg.tar.zst" | ForEach-Object {
        Write-Host "  -> $($_.Name) ($([math]::Round($_.Length / 1MB, 2)) MB)" -ForegroundColor Cyan
    }
    Write-Host ""
    Write-Host "Instrucciones para transferir a tu PC con ChurrOS:" -ForegroundColor Yellow
    Write-Host "  1. Copia los archivos *.pkg.tar.zst a una memoria USB."
    Write-Host "  2. En tu PC con ChurrOS, cópialos dentro de 'archiso/packages/'."
    Write-Host "  3. Ejecuta './churros build' o tu comando habitual."
    Write-Host ""
}
