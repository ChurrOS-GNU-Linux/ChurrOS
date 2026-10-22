# Compilación del Kernel ChurrOS en Windows

Esta carpeta contiene las herramientas para compilar el kernel de **ChurrOS** (`linux-churrosvyper`) de forma 100% automatizada en Windows utilizando **Docker Desktop** o **Podman**.

---

## 🚀 Método 1: Compilar el Kernel en la Laptop con Windows

Si quieres usar la laptop con Windows para compilar todo el kernel y obtener los paquetes listos:

### 1. Requisitos previos en Windows
* Tener **Docker Desktop** (con WSL2 activado) o **Podman Desktop**.
* Si no está instalado, abre una terminal de PowerShell como Administrador e instala Docker con un solo comando:
  ```powershell
  winget install Docker.DockerDesktop
  ```
  *(Luego reinicia la PC si te lo solicita y abre Docker Desktop).*

### 2. Iniciar la compilación
Tienes dos opciones muy sencillas:

* **Opción A (Doble clic):**  
  Haz doble clic en `build-kernel.bat`.

* **Opción B (PowerShell):**  
  Abre PowerShell en esta carpeta y ejecuta:
  ```powershell
  .\build-kernel.ps1
  ```
  *Puedes ajustar la cantidad de núcleos si lo deseas (ejemplo: `.\build-kernel.ps1 -Jobs 8`).*

### 3. Obtener los paquetes compilados
Cuando el script termine, los paquetes generados se guardarán automáticamente en:
```
windows\output\linux-churrosvyper-*.pkg.tar.zst
windows\output\linux-churrosvyper-headers-*.pkg.tar.zst
```

Para usarlos en tu PC con ChurrOS:
1. Pasa esos dos archivos a una memoria USB (o vía red).
2. En tu PC con ChurrOS, cópialos en la carpeta `archiso/packages/`.
3. ¡Listo! Ya no necesitarás volver a compilar el kernel en tu PC.

---

## ⚡ Método 2: Usar la Laptop con Windows como Nodo de Apoyo (Cluster distcc)

Si prefieres lanzar la compilación desde tu PC de escritorio con Linux, pero quieres que la laptop con Windows le preste sus núcleos y compilen en conjunto por la red local:

1. En la laptop con Windows, haz doble clic en `run-distcc-worker.bat` (o ejecuta `.\run-distcc-worker.ps1` en PowerShell).
2. El script te mostrará en pantalla la IP de la laptop y la cantidad de hilos disponibles.
3. En tu PC con ChurrOS, añade esa IP en tu archivo `cluster.conf`:
   ```bash
   NODES=(
       "192.168.1.XX,NUCLEOS"
   )
   ```
4. En tu PC con ChurrOS, compila con:
   ```bash
   ./churros build --cluster
   ```
   Ambas computadoras compilarán el kernel en paralelo.

---

## 💡 ¿Por qué se compila dentro de un contenedor?
* **Rendimiento:** Compilar 50,000 archivos en el sistema de archivos NTFS de Windows puede ser 10 veces más lento. Dentro del contenedor se compila sobre Linux nativo (`ext4`) a máxima velocidad.
* **Compatibilidad de nombres:** El código fuente del kernel Linux tiene archivos que sólo difieren en mayúsculas/minúsculas (`xt_CONNMARK.h` y `xt_connmark.h`). Windows/NTFS no distingue mayúsculas de minúsculas de forma predeterminada y fallaría; el contenedor evita este problema completamente.
* **Sin ensuciar el sistema de tu amiga:** Todo ocurre dentro del contenedor desechable y no instala programas ni librerías innecesarias en Windows.
