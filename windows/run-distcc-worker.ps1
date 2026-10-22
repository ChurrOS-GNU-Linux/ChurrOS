# ==============================================================================
# ChurrOS — Iniciar Nodo Worker de Compilación Distribuida (distcc) en Windows
# ==============================================================================
# Este script inicia un contenedor con distccd en Windows usando Docker o Podman.
# Permite que otra máquina en la misma red local (tu PC con ChurrOS) use los
# núcleos de esta laptop para acelerar la compilación del kernel y paquetes.
# ==============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [int]$Port = 3632,

    [Parameter(Mandatory = $false)]
    [switch]$Help
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($Help) {
    Write-Host "Uso: .\run-distcc-worker.ps1 [-Port 3632]"
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "    ChurrOS — Nodo de Compilación Distribuida (distcc)   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# Detección de Docker / Podman
$Engine = $null
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerCheck = & docker info 2>&1
    if ($LASTEXITCODE -eq 0) { $Engine = "docker" }
}
if (-not $Engine -and (Get-Command podman -ErrorAction SilentlyContinue)) {
    $podmanCheck = & podman info 2>&1
    if ($LASTEXITCODE -eq 0) { $Engine = "podman" }
}

if (-not $Engine) {
    Write-Host "Error: No se encontró Docker Desktop ni Podman activo en Windows." -ForegroundColor Red
    Write-Host "Instálalo con: winget install Docker.DockerDesktop" -ForegroundColor Yellow
    exit 1
}

$ImageName = "churros-distcc-worker"
$imageExists = & $Engine images -q $ImageName 2>$null

if (-not $imageExists) {
    Write-Host "[1/2] Construyendo imagen de distccd ($ImageName)..." -ForegroundColor Cyan
    $containerfilePath = Join-Path $RepoRoot "Containerfile.distccd"
    & $Engine build -t $ImageName -f $containerfilePath $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error al construir la imagen de distccd." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# Detener contenedor previo si ya estaba corriendo
& $Engine rm -f churros-distcc-worker 2>$null | Out-Null

Write-Host "[2/2] Iniciando contenedor worker en el puerto $Port..." -ForegroundColor Cyan
& $Engine run -d --name churros-distcc-worker `
    -p "${Port}:3632" `
    -p "3633:3633" `
    --restart unless-stopped `
    $ImageName `
    --allow 0.0.0.0/0

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error al iniciar el contenedor worker." -ForegroundColor Red
    exit $LASTEXITCODE
}

# Detectar IP local de la máquina Windows
$localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
    $_.InterfaceAlias -notmatch "vEthernet|Loopback|WSL" -and $_.IPAddress -notlike "169.254.*" 
} | Select-Object -First 1).IPAddress

$threads = [Environment]::ProcessorCount

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  ✓ Nodo distcc ACTIVO y listo para recibir tareas        " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dirección IP de esta laptop : $localIP" -ForegroundColor Cyan
Write-Host "  Puerto                      : $Port" -ForegroundColor Cyan
Write-Host "  Hilos de CPU disponibles    : $threads" -ForegroundColor Cyan
Write-Host ""
Write-Host "Cómo conectarte desde tu PC con ChurrOS:" -ForegroundColor Yellow
Write-Host "1. En tu máquina ChurrOS, añade esta línea a 'cluster.conf':" -ForegroundColor White
Write-Host "       `"$localIP,$threads`"" -ForegroundColor Green
Write-Host "2. Ejecuta la compilación con soporte de cluster:" -ForegroundColor White
Write-Host "       ./churros build --cluster" -ForegroundColor Green
Write-Host ""
Write-Host "Para detener este worker cuando termines, ejecuta:" -ForegroundColor Gray
Write-Host "    $Engine rm -f churros-distcc-worker" -ForegroundColor Gray
Write-Host ""
