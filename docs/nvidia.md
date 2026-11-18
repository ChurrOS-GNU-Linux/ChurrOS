# Soporte de controladores NVIDIA

Cómo instala ChurrOS el controlador oficial de NVIDIA: qué hay, por qué está hecho así y qué queda
pendiente. Se apoya en el repositorio y en los repositorios reales (Arch, CachyOS, Arch Linux ARM y
Arch Linux 32) consultados el 17 de noviembre de 2026.

## Resumen

ChurrOS arranca en hardware NVIDIA por el camino libre (`nouveau` + NVK, que cubre Turing y
posteriores gracias al firmware de `linux-firmware-nvidia`). El controlador oficial **no va en la
ISO**: se instala desde el instalador, y esta es la pieza que se añadió.

Lo que había antes era infraestructura a medias que **no habría funcionado si se activara**:

1. El grupo NVIDIA de `netinstall.yaml` existía, pero el módulo `netinstall` **no estaba en la
   secuencia**: configuración muerta que ningún usuario veía nunca.
2. Las tres ediciones x86_64 instalan **`linux-cachyos`**, no `linux`. El grupo pedía
   `nvidia-open-dkms`, que no depende de los headers de ese kernel: DKMS se quedaba sin
   `linux-cachyos-headers`, no compilaba el módulo y el sistema arrancaba sin salida gráfica (niri
   26.04 no cae a llvmpipe).
3. `churros-update-utils` ya sabía convivir con un DKMS (`headers_in_use()`, línea 402), lo que
   confirma que el problema se pensó y no se terminó.

## Qué se implementó

| Pieza | Dónde |
|---|---|
| Pantalla «Selección de paquetes» con dos grupos NVIDIA, desmarcados | `installer/calamares/modules/netinstall.yaml` |
| El paso `netinstall` en `show` y `packages` en `exec` | `installer/calamares/settings.conf` |
| Instalación de lo elegido, sin red no hace nada | `installer/calamares/modules/packages.conf` |
| Variante aarch64 sin grupos | `installer/calamares/modules/aarch64/netinstall.yaml` |
| Copia de los grupos por arquitectura | `installer/apply-calamares.sh` |
| Comprobación de que el driver quedó instalado | `archiso/airootfs/usr/share/churros/scripts/verify-install` |
| Perfil de VRAM de niri | `archiso/airootfs/etc/nvidia/nvidia-application-profiles-rc.d/50-limit-free-buffer-pool-in-wayland-compositors.json` |
| Pruebas del contrato | `tests/static/test_nvidia_support.py` |

La elección se instala con `netinstall` y no con `packagechooser` porque `packagechooser` **no está
compilado** en el Calamares del proyecto: el PKGBUILD lo quita con `-DSKIP_MODULES` y la prueba
`test_calamares_config.py` lo tiene apuntado en `AUR_SKIPPED_MODULES`. Ver [Decisión B](#decisión-b--elegir-en-calamares-con-netinstall-no-con-packagechooser).

El resultado: quien tenga NVIDIA marca un grupo, el instalador baja el módulo compilado por CachyOS
para `linux-cachyos` y el driver arranca con `modeset` ya activado por defecto desde `nvidia-utils`
560.35.03-5. Quien no marque nada se queda exactamente como hoy.

## Qué hay hoy, verificado

| Pieza | Estado real | Dónde |
|---|---|---|
| Kernel de las ediciones x86_64 | `linux-cachyos` (no `linux`) | `archiso/packages.x86_64:39`, `packages.xfce.x86_64:33`, `packages.server.x86_64:67` |
| Kernel aarch64 / i686 | `linux-aarch64` / `linux` | `archiso/packages.aarch64`, `archiso/packages.i686` |
| Pila gráfica | Mesa + `vulkan-virtio` + `vulkan-icd-loader`; sin `nvidia-*` | `archiso/packages.*` |
| Firmware | `linux-firmware`, que depende de `linux-firmware-nvidia` | `archiso/packages.*` |
| Módulo `nouveau` en el kernel propio | `CONFIG_DRM_NOUVEAU=m`; `CONFIG_DRM_NOVA` sin activar | `pkgs/linux-churrosvyper/config` |
| Driver en la ISO | Ninguno. El Live arranca con `nouveau`/NVK | `archiso/packages.*` |
| Grupo NVIDIA del instalador | `nvidia-open-dkms`, `nvidia-utils`, `nvidia-settings`, `nvidia-prime`, `critical: true` | `installer/calamares/modules/netinstall.yaml` |
| ¿Se ve ese grupo? | **No**: `netinstall` no aparece ni en `instances` ni en `sequence` | `installer/calamares/settings.conf` |
| `packages.conf` | Configurado (`backend: pacman`, `skip_if_no_internet: true`, `needed_only: true`) pero **no está en `exec`** | `installer/calamares/modules/packages.conf` |
| Guarda sobre Xorg | Falla si un `Device` fuerza `Driver "modesetting"` «que rompe el driver NVIDIA que ofrece netinstall» | `scripts/cli/check.sh` (~1549) |
| Actualizador | `headers_in_use()` conserva `linux-cachyos-headers` si hay un `*-dkms` instalado | `archiso/airootfs/usr/bin/churros-update-utils:402` |
| `churros-settings` | Lee el driver activo de `/sys/class/drm/cardN/device/driver` («i915, amdgpu, nvidia…») | `rust/preferences/src/services/system.rs` |
| Documentación | «GPU AMD e Intel con Mesa desde la ISO. Los controladores propietarios de NVIDIA no vienen» | `docs/vision.md:30` |

Consecuencia de lo anterior: **un usuario con NVIDIA puede usar el Live**, porque `nouveau` y el
firmware GSP de `linux-firmware-nvidia` están en la ISO, pero el sistema instalado repite ese mismo
camino libre, sin aceleración propietaria, y no hay ninguna vía en el instalador para cambiarlo.

## Hechos externos que condicionan el diseño

Comprobados contra los repositorios y contra la documentación de Arch y de niri. Son la base de las
decisiones de la sección siguiente.

**Arch (extra, 17-11-2026)**

- `nvidia-utils` 620.70.06 · `nvidia-open` 620.70.06 · `nvidia-open-dkms` 620.70.06 ·
  `nvidia-settings` 620.70.06 · `nvidia-prime` 1.0 · `lib32-nvidia-utils` (multilib).
- **`nvidia` y `nvidia-dkms` ya no existen**: el driver pasó a módulos abiertos. Cualquier
  documentación o configuración que los nombre está rota.
- `nvidia-open` **depende de `linux`**. En ChurrOS eso arrastraría el kernel de Arch, que no es el
  que se usa: es la trampa más fácil de caer al «arreglar» el grupo del instalador.
- `nvidia-open-dkms` depende solo de `dkms` y `nvidia-utils`; **no** de headers ni de compilador.
- Licencias: `nvidia-open` y `nvidia-open-dkms`, «MIT AND GPL-2.0-only». `nvidia-utils`,
  `LicenseRef-NVIDIA-Driver-License-Agreement`.
- Tamaños instalados: `nvidia-utils` 1012 MiB (337 MiB comprimido), `nvidia-open-dkms` 109 MiB.

**CachyOS (`[cachyos]`, el repo que ya usa el proyecto)**

- `linux-cachyos-nvidia-open` 7.3.3-1 — descripción literal: *«nvidia open modules of 620.70.06
  driver for the linux-cachyos kernel»*. Depende de `linux-cachyos=7.3.3-1`, `nvidia-utils=620.70.06`
  y `libglvnd`; provee `NVIDIA-MODULE`; choca con `linux-cachyos-nvidia` y
  `linux-cachyos-nvidia-580xx`. Ocupa **9,5 MiB comprimido**.
- `linux-cachyos-nvidia-580xx` 7.3.3-1 — driver 580.196.07 para Maxwell, Pascal y Volta; depende de
  `nvidia-580xx-utils=580.196.07`, que **solo existe en `[cachyos]`**.
- `linux-cachyos-headers` 7.3.3-1 — 345 MiB instalados, y depende de `clang`, `llvm` y `lld`
  (~290 MiB más). Es el coste real del camino DKMS con este kernel.
- `nvidia-580xx-utils`, `nvidia-580xx-settings`, `lib32-nvidia-580xx-utils`, `nvidia-580xx-dkms`,
  `nvidia-580xx-open-dkms` también están ahí.

**Arch Linux ARM (aarch64)**

- `nvidia-open-dkms` y `nvidia-utils` 620.70.06 en `extra`, más `dkms` y `egl-wayland`.
- **No hay módulo precompilado** para `linux-aarch64`: el camino sería DKMS.

**Arch Linux 32 (i686)**

- Solo `nvidia-prime`. **No hay `nvidia-utils` ni módulos**: el driver no es instalable.

**Parámetros del kernel**

- Desde `nvidia-utils` 560.35.03-5, `modeset` y `fbdev` están activados por defecto. **No hace falta
  añadir `nvidia_drm.modeset=1`** a la línea de comandos; el wiki de Arch lo deja claro y da el
  comando de verificación (`cat /sys/module/nvidia_drm/parameters/modeset` → `Y`).
- Cargar los módulos en el initramfs sí es necesario solo en casos concretos, y **rompe la
  hibernación** (preservación de VRAM). No debe ser el valor por defecto.

**niri + NVIDIA**

- Consumo de VRAM desmedido si no se aplica el perfil `GLVidHeapReuseRatio = 0` al proceso `niri`,
  mediante un JSON en `/etc/nvidia/nvidia-application-profiles-rc.d/`. Está documentado por niri y
  por el wiki de Arch, y es un fichero de configuración, no un programa.
- El problema de parpadeo de screencast que aparecía en versiones antiguas está corregido en niri;
  no hay que añadir `debug { wait-for-frame-completion-in-pipewire }`.

## Los cuatro problemas que había

Ordenados por lo que rompía. Los cuatro están cubiertos por el cambio; el cuarto (ciclo de vida) está
documentado y es lo único que puede requerir atención en el futuro.

**P1 — No existía un módulo que cargara con `linux-cachyos`.** `nvidia-open-dkms` sin
`linux-cachyos-headers` no compila nada, y el fallo era silencioso: pacman termina bien, el módulo no
existe y el primer arranque no tiene salida gráfica. Era el bloqueante real, no el grupo del
instalador.

**P2 — El instalador no ofrecía la elección.** `netinstall` no estaba en la secuencia, así que la
decisión no existía para el usuario. `packages.conf` estaba configurado pero tampoco se ejecutaba.

**P3 — Sin módulo, el primer arranque es una pantalla negra.** niri 26.04 descarta los renderizadores
EGL por software (está documentado en `docs/vm.md`), de modo que un driver mal instalado no degrada:
deja el sistema sin interfaz. Por eso `critical: true` aborta la instalación y `verify-install`
comprueba el módulo antes de reiniciar.

**P4 — Ciclo de vida.** Un módulo precompilado va atado a `linux-cachyos` y a `nvidia-utils` en
versiones exactas. Si `[cachyos]` aún no ha reconstruido el módulo cuando Arch sube el driver,
`pacman -Syu` falla por dependencia: se niega la transacción, el sistema sigue arrancando. Con DKMS el
riesgo es el simétrico (compilador y headers en cada kernel) y el modo de fallo es quedarse sin salida
gráfica.

## Diseño



### Decisión A — Módulo precompilado de CachyOS, no DKMS

| | `linux-cachyos-nvidia-open` | `nvidia-open-dkms` + headers |
|---|---|---|
| Descarga / instalado | 9,5 MiB / ~10 MiB | 13 MiB / ~110 MiB + 345 MiB headers + ~290 MiB clang/llvm |
| Compilador en el destino | No | Sí |
| Recompila en cada kernel | No (lo hace CachyOS) | Sí |
| Atado a versión | `linux-cachyos=7.3.3-1`, `nvidia-utils=620.70.06` | Solo a headers presentes |
| Si el repo va por detrás | `pacman -Syu` falla y no rompe el sistema | Compila y sigue |
| Interacción con `churros-update-utils` | Ninguna: no instala headers | Ya contemplada (`headers_in_use()`) |

**Se elige el precompilado** para x86_64 con `linux-cachyos`. Motivos: no mete un compilador de
~290 MiB en un escritorio, no deja el sistema sin salida si falla una compilación, y su modo de fallo
es un `pacman -Syu` que se niega en lugar de un arranque negro. DKMS se queda como plan B documentado
para quien cambie de kernel, y es la única vía en aarch64.

Efecto secundario bueno: con el precompilado **no se instalan headers**, así que la reparación de
`churros-update-utils` que conserva `linux-cachyos-headers` no se activa y el caso «pahole de CachyOS
bloquea la actualización» no aparece.

### Decisión B — Elegir en Calamares con `netinstall`, no con `packagechooser`

El plan inicial proponía `packagechooser`. **No es posible**: `packagechooser` está en
`AUR_SKIPPED_MODULES` de `tests/static/test_calamares_config.py`, porque el PKGBUILD de Calamares que
usa el proyecto lo compila con `-DSKIP_MODULES` y el módulo **no existe** en la ISO
(`ModuleManager::loadModules` falla con «not found in module search paths»). Ponerlo en la secuencia
rompería el instalador.

La pantalla se hace con `netinstall`, que sí está compilado y ya leía `netinstall.yaml`. Calamares
resuelve la selección en `finalizeGlobalStorage` y la deja en `packageOperations`, que el módulo
`packages` instala después en una sola transacción de pacman. Eso importa: con DKMS los headers
tendrían que ir en la **misma** transacción que el driver o el hook no encuentra nada que compilar.

La secuencia queda así (solo se añaden dos pasos, ninguna instancia nueva):

```
show: welcome, locale, keyboard, partition, users, netinstall, summary
exec: … shellprocess@pacman-init → packages → initcpiocfg → …
```

`packages` va **después de `shellprocess@pacman-init`** (sin el llavero no se pueden verificar las
firmas de los repos) y **después de `unpackfs`** (instala dentro del destino). Y va antes de
`initcpiocfg`, que reescribe las líneas de `/etc/mkinitcpio.conf`: si en el futuro se quiere tocar
`MODULES` según haya driver, ese cambio va en `fix-boot`, que corre más tarde.

Sigue sin haber un sexto `shellprocess`, así que la invariante de cinco instancias de `AGENTS.md`
continúa siendo cierta.

Dos grupos **hermanos**, ambos desmarcados:

| Grupo | Paquetes |
|---|---|
| NVIDIA (GTX 16xx / RTX 20xx y posteriores) | `linux-cachyos-nvidia-open`, `nvidia-utils`, `nvidia-settings`, `nvidia-prime`, `lib32-nvidia-utils` |
| NVIDIA heredado (GTX 10xx y anteriores) | `linux-cachyos-nvidia-580xx`, `nvidia-580xx-utils`, `nvidia-580xx-settings`, `lib32-nvidia-580xx-utils` |

Tres detalles que decide el código de Calamares, no el gusto:

- **`selected: false` es obligatorio en cada grupo.** El nodo raíz del árbol nace marcado
  (`PackageTreeItem`, `<root>` con `Qt::Checked`) y los hijos heredan el estado del padre
  (`parentCheckState`): un grupo sin `selected` se instalaría a todo el mundo.
- **Los grupos no pueden anidarse.** Marcar un grupo marca a sus hijos, así que con el heredado dentro
  del moderno, elegir «NVIDIA» instalaría las dos familias. `nvidia-utils` y `nvidia-580xx-utils`
  ocupan las mismas rutas y, con `critical: true`, eso aborta la instalación.
- **aarch64 no lleva grupos.** `installer/calamares/modules/aarch64/netinstall.yaml` deja la lista
  vacía y `apply-calamares.sh` lo copia encima del común.

No se autodetecta la familia de la GPU: haría falta un programa nuevo (detección por `lspci` y
`pci.ids`) y la [regla para programas nuevos](principios.md#regla-para-programas-nuevos) exige un
issue aprobado. Las etiquetas describen el hardware para que el usuario decida, que es lo que ya hace
el resto del instalador.

`nvidia-prime` y `lib32-nvidia-utils` van dentro del grupo y no como opción aparte: sin `lib32-*`
Steam y Wine no tienen 32 bits, y `nvidia-prime` no hace nada en un equipo de una sola GPU. Multilib
ya está activado en el sistema instalado (`shellprocess-cleanup.conf` descomenta `[multilib]`).

### Decisión C — Fuera de la ISO (por ahora)

El controlador **no** se añade a `archiso/packages.*`:

- `nvidia-utils` instalado son 1012 MiB; en la ISO, ~337 MiB comprimidos que no se pueden quitar
  después del arranque.
- `nvidia-utils` incluye un `modprobe.d` que **bloquea `nouveau`**. Si el driver entra en la ISO, el
  Live deja de poder arrancar por el camino libre cuando el propietario no carga, que es justo la red
  de seguridad que hoy evita la pantalla negra.
- El Live ya funciona con `nouveau`/NVK en Turing y posteriores gracias a `linux-firmware-nvidia`.

Consecuencia obligatoria: **la instalación del driver necesita internet**. `packages.conf` ya tiene
`skip_if_no_internet: true`, así que sin red el paso se salta en silencio; por eso el plan incluye una
comprobación en `verify-install` y un aviso al usuario en lugar de dejarlo pasar.

Queda como fase posterior, con un flag de build (`--with-nvidia`), decidir si conviene una ISO con el
driver dentro para equipos sin red. No se hace ahora.

### Decisión D — Solo x86_64 en la primera fase

- **aarch64**: no hay módulo precompilado para `linux-aarch64`; solo DKMS, que en una Raspberry Pi no
  aplica (`packages.pi.aarch64` es labwc sobre VideoCore, y las GPU NVIDIA en ARM son Grace/Jetson,
  otro caso de uso). La edición `pi` no lo necesita. Queda fuera hasta que haya demanda real.
- **i686**: `nvidia-utils` no existe en Arch Linux 32 y esa edición no lleva Calamares.

### Decisión E — Ficheros de configuración en el airootfs, no en un `shellprocess`

Dos ajustes son ficheros estáticos y `unpackfs` los copia al sistema instalado sin lógica de
instalación:

- `/etc/nvidia/nvidia-application-profiles-rc.d/50-limit-free-buffer-pool-in-wayland-compositors.json`
  — el perfil `GLVidHeapReuseRatio = 0` para `niri` (Decisión P4 de niri; sin él, varios cientos de
  MiB de VRAM ociosos).
- `/etc/modprobe.d/nvidia-power-management.conf` con `NVreg_PreserveVideoMemoryAllocations=1`, solo si
  se decide soportar suspensión en portátiles híbridos (los servicios `nvidia-suspend/resume` los
  trae `nvidia-utils`).

Ventaja: no hay que añadir un sexto `shellprocess` ni saber en el instalador si el driver se instaló.
Inconveniente a verificar: hay que comprobar que `nvidia-utils` no es dueño de esas rutas, para que
pacman no dé conflicto de ficheros al instalar el driver después. Va como prueba de contenedor.

## Trabajo realizado

### Hecho en este cambio

| Qué | Ficheros |
|---|---|
| Dos grupos NVIDIA hermanos, desmarcados y `critical` | `installer/calamares/modules/netinstall.yaml` |
| `netinstall` en `show`, `packages` en `exec` tras `pacman-init` | `installer/calamares/settings.conf` |
| `packages.conf` sin el `try_remove` heredado de archiso | `installer/calamares/modules/packages.conf` |
| Variante aarch64 vacía y su copia por arquitectura | `modules/aarch64/netinstall.yaml`, `apply-calamares.sh` |
| `verify-install` comprueba el módulo y `nvidia-utils` | `usr/share/churros/scripts/verify-install` |
| Perfil `GLVidHeapReuseRatio = 0` para niri | `etc/nvidia/nvidia-application-profiles-rc.d/*.json` |
| Lista blanca de paquetes solo-destino y comprobación estática | `tests/static/test_calamares_config.py` |
| Seis pruebas del contrato y cuatro mutaciones | `tests/static/test_nvidia_support.py`, `tests/mutations/mutations.toml` |

El `try_remove` de `packages.conf` (archinstall, clonezilla, gpm, irssi, lynx, mc, testdisk, wvdial)
se retiró: estaba pensado para el Calamares de archiso y llevaba inerte desde d6b9dab. Activarlo tal
cual habría quitado esas herramientas a todo el mundo, que no tiene relación con NVIDIA y no estaba
probado. Si se quiere recuperar, va en su propio cambio con su prueba.

### Pendiente, en orden

1. **Probar en hardware real.** Nada de esto se ha ejecutado con una GPU NVIDIA: el arranque del Live
   y del sistema instalado sigue siendo prueba manual, como la instalación completa de Calamares
   ([#297](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/297)). Es el paso que convierte el
   diseño en soporte.
2. **Confirmar los nombres en el contenedor.** `tests/container/test_arch_repos.py` resuelve los
   paquetes contra los repos de verdad; en el equipo donde se escribió esto no hay podman ni pacman,
   así que esa capa no se ejecutó (ver [Verificación](#verificación)).
3. **Suspensión en portátiles híbridos**, si se decide soportarla: `NVreg_PreserveVideoMemoryAllocations=1`
   en `/etc/modprobe.d/`. `nvidia-utils` ya trae `nvidia-suspend.service` y `nvidia-resume.service`.
4. **Opcional**: `--with-nvidia` en `packages.*` para una ISO con el driver dentro, pensada para
   equipos sin red. Requiere resolver antes el `modprobe.d` que bloquea `nouveau`, o el Live deja de
   tener red de seguridad.
5. **Opcional**: autodetección de la familia de GPU en el instalador (programa nuevo: issue aprobado).

## Verificación

Ejecutado en el equipo donde se escribió esto, sobre la rama `nvidia-support`:

| Capa | Comando | Resultado |
|---|---|---|
| Estática | `./churros check` | **311 pruebas**, todo en verde |
| Mutaciones | `python3 tests/mutations/run_mutations.py -k nvidia` | **4/4 detectadas** |
| Contenedor | `./churros test --container` | **no ejecutado**: no hay podman ni pacman en el equipo |
| ISO | `./churros test --iso` | **no ejecutado**: no se construyó la ISO |
| Arranque | `./churros test --boot` | **no ejecutado** |

Lo que la capa estática **no** puede comprobar, y por eso queda en manos del contenedor y de la
prueba manual:

- que `linux-cachyos-nvidia-open` y los demás existan en los repos con esas versiones;
- que `nvidia-utils` no instale un fichero en la ruta del perfil de VRAM (se comprobó que no tiene
  nada bajo `etc/`, pero eso fue una consulta puntual, no una prueba);
- que el driver cargue y que niri pinte con él.

## Matriz de pruebas

| Qué puede romperse | Qué lo detecta | Capa |
|---|---|---|
| Un nombre de paquete que no existe | `test_arch_repos.py` | contenedor |
| Un módulo para el kernel equivocado (`nvidia-open` → `linux`) | prueba estática nueva (1.3) | estática |
| DKMS sin headers | prueba estática nueva (1.3) | estática |
| `packages` en el orden equivocado | `test_calamares_config.py` (secuencia y escritores del destino) | estática |
| Vista nueva sin `.conf` o con claves inválidas | `test_calamares_config.py` | estática |
| Instalación sin driver tras pedirlo | `test_verify_install.py` (2.2) | estática |
| Fichero del airootfs que choca con el paquete | prueba de contenedor (2.4) | contenedor |
| Driver colado en la ISO por error | `check_iso.py` (2.5) | ISO |
| El sistema no arranca con NVIDIA real | **manual**, documentado | — |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| `[cachyos]` no ha reconstruido el módulo y `pacman -Syu` falla | media | El sistema no se rompe: la transacción se niega. Documentar la espera y cómo saltarla (`IgnorePkg` temporal del módulo) sin tocar el kernel. |
| El módulo carga y aun así no hay salida | media | Diagnóstico en 3.2; volver a `nouveau` desinstalando el módulo. `verify-install` cubre el caso «no se instaló», no el «no funciona». |
| Portátil híbrido: niri elige la dGPU | media | Documentar `nvidia-prime` y el arranque por iGPU; la suspensión necesita la Decisión E. |
| Instalación sin red deja el sistema igual que hoy | alta | Aviso explícito (2.3). |
| Regresión del Live por tocar `MODULES` del initramfs | baja | No se toca por defecto; cargar los módulos pronto rompe además la hibernación. |

## Decisiones de proyecto

1. **Licencia.** `nvidia-utils` es propietario (`LicenseRef-NVIDIA-Driver-License-Agreement`). Su
   cláusula 2.1.2 permite copiar y redistribuir los binarios para Linux sin modificarlos, así que el
   [principio 1](principios.md#1-libre-y-redistribuible) se cumple en su letra; los módulos abiertos
   son MIT/GPL-2.0. Es la razón de que el driver se instale en el destino y no viaje en la ISO.
2. **Mantenedor.** Lo aporta el autor del cambio; el ciclo de vida del módulo (P4) es lo que hay que
   mantener, y sigue el de `linux-cachyos` en `[cachyos]`.

## Diagnóstico rápido

Para quien ya tenga el driver instalado:

```bash
lspci -k -d ::03xx                              # familia y driver en uso
pacman -Q linux-cachyos linux-cachyos-nvidia-open nvidia-utils
cat /sys/module/nvidia_drm/parameters/modeset   # debe ser Y (por defecto desde 560.35.03)
nvidia-smi                                      # el módulo responde
```

Volver al camino libre, si algo falla:

```bash
sudo pacman -Rns linux-cachyos-nvidia-open nvidia-utils
sudo mkinitcpio -P && sudo reboot
```

Cargar los módulos en el initramfs solo si el driver aparece tarde y la pantalla queda negra, sabiendo
que eso rompe la hibernación:

```
MODULES=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)
```
