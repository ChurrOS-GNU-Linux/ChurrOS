# Soporte de controladores NVIDIA

Auditoría del estado actual y plan de desarrollo técnico para que ChurrOS arranque e instale con
controladores NVIDIA. Se apoya en el repositorio y en los repositorios reales (Arch, CachyOS,
Arch Linux ARM y Arch Linux 32) consultados el 17 de noviembre de 2026.

Este documento no implementa nada: describe qué hay hoy, qué falta y en qué orden conviene hacerlo.
El cambio de código va en su propio PR y, por la [regla para programas nuevos](principios.md#regla-para-programas-nuevos),
necesita un issue aprobado antes de empezar (ver [Decisiones que faltan](#decisiones-que-faltan)).

## Resumen

ChurrOS arranca hoy en hardware NVIDIA por el camino libre (`nouveau` + NVK), pero no instala el
controlador oficial. La infraestructura para instalarlo está a medias y en un estado que **no
funcionaría si se activara**:

1. El grupo NVIDIA de `installer/calamares/modules/netinstall.yaml` existe, pero el módulo
   `netinstall` **no está en la secuencia** de `installer/calamares/settings.conf`: es configuración
   muerta que ningún usuario ve nunca.
2. Las tres ediciones x86_64 instalan **`linux-cachyos`**, no `linux`. El grupo pide
   `nvidia-open-dkms`, que no depende de los headers de ese kernel: DKMS se queda sin
   `linux-cachyos-headers`, no compila el módulo y el sistema instalado arranca sin salida gráfica
   (niri 26.04 no cae a llvmpipe).
3. `docs/vision.md` afirma que los controladores propietarios «no vienen en la ISO ni los instala
   Calamares», y eso es cierto; pero `scripts/cli/check.sh` mantiene una comprobación cuyo
   comentario justifica el diseño diciendo que sí se ofrecen.
4. El actualizador `archiso/airootfs/usr/bin/churros-update-utils` **ya sabe** convivir con un
   DKMS (`headers_in_use()`, línea 402), lo que confirma que el problema se pensó y no se terminó.

La buena noticia: la solución no requiere código nuevo. `packagechooser` + `packages` son módulos
de Calamares que el proyecto ya tiene configurados (`packages.conf`) y que las pruebas ya reconocen.
Y para el kernel de ChurrOS existe un módulo **precompilado** que evita todo el problema de los
headers.

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

## Los cuatro problemas a resolver

Ordenados por lo que rompe si se ignoran.

**P1 — No existe un módulo que cargue con `linux-cachyos`.** `nvidia-open-dkms` sin
`linux-cachyos-headers` no compila nada, y el fallo es silencioso: pacman termina bien, el módulo no
existe y el primer arranque no tiene salida gráfica. Es el bloqueante real, no el grupo del
instalador.

**P2 — El instalador no ofrece la elección.** `netinstall` no está en la secuencia, así que la decisión
no existe para el usuario. `packages.conf` está configurado pero tampoco se ejecuta.

**P3 — Sin módulo, el primer arranque es una pantalla negra.** niri 26.04 descarta los renderizadores
EGL por software (está documentado en `docs/vm.md`), de modo que un driver mal instalado no degrada:
deja el sistema sin interfaz. Cualquier fallo tiene que detectarse antes de salir del instalador.

**P4 — Ciclo de vida.** Un módulo precompilado va atado a `linux-cachyos=7.3.3-1` y a
`nvidia-utils=620.70.06`. Si `[cachyos]` aún no ha reconstruido el módulo cuando Arch sube el driver,
`pacman -Syu` falla por dependencia. Con DKMS el riesgo es el simétrico: cada actualización de kernel
necesita headers, compilador y tiempo. Hay que elegir y documentar el modo de fallo de cada uno.

## Diseño propuesto

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

### Decisión B — Elegir en Calamares con `packagechooser` + `packages`

Ambos módulos ya existen en Calamares 3.4 y en la tabla de tipos que usan las pruebas
(`tests/static/test_calamares_config.py`): `packagechooser` es `view`, `packages` es `job`. No hace
falta ningún `shellprocess` nuevo, así que **la invariante de «cinco instancias» de `AGENTS.md` sigue
siendo cierta** y no hay que tocar ese contrato.

`packagechooser` con `method: packages` escribe en GlobalStorage lo que el módulo `packages` instala
después, en una sola transacción de pacman. Eso importa: con DKMS los headers tienen que ir en la
**misma** transacción que el driver o el hook de DKMS no encuentra nada con lo que compilar.

Tres opciones en la vista, sin autodetección:

| Id | Etiqueta | Paquetes |
|---|---|---|
| `none` (por defecto) | Sin controlador NVIDIA | — |
| `open` | NVIDIA: GTX 16xx / RTX 20xx y posteriores | `linux-cachyos-nvidia-open`, `nvidia-utils`, `nvidia-settings`, `nvidia-prime`, `lib32-nvidia-utils` |
| `legacy` | NVIDIA: GTX 10xx y anteriores (Maxwell, Pascal, Volta) | `linux-cachyos-nvidia-580xx`, `nvidia-580xx-utils`, `nvidia-580xx-settings`, `lib32-nvidia-580xx-utils` |

No se autodetecta la familia de la GPU en esta fase: haría falta un programa nuevo (detección por
`lspci`/`pci.ids`) y la [regla para programas nuevos](principios.md#regla-para-programas-nuevos)
exige un issue aprobado. Las etiquetas describen el hardware de forma que el usuario pueda decidir,
que es lo que ya hace el resto del instalador.

`nvidia-prime` y `lib32-nvidia-utils` van con el grupo y no como opción aparte: sin `lib32-*` Steam y
Wine no tienen 32 bits, y `nvidia-prime` solo molesta a quien no tiene gráficos híbridos (no hace
nada en un equipo de una sola GPU). Multilib ya está activado en el sistema instalado
(`shellprocess-cleanup.conf` descomenta `[multilib]`).

Dos detalles de implementación que la vista arrastra:

- **`packagechooser` no puede declararse en `instances`.** `tests/static/test_calamares_config.py`
  exige que el conjunto de `instances` sea exactamente el de las cinco de `shellprocess`
  (`EXPECTED_DONT_CHROOT`), y que cada `module` de una instancia sea `shellprocess`. Declarar
  `packagechooser` como instancia hace fallar la prueba. Sin instancia, Calamares abre
  `<módulo>.conf`, así que el fichero tiene que llamarse **`packagechooser.conf`**, no
  `packagechooser-nvidia.conf`.
- Los ítems genéricos de `packagechooser` exigen `id`, `name`, `description` y **`screenshot`**; sin la
  captura, el ítem no se pinta. Calamares la busca primero como ruta absoluta y, si no existe, dentro
  del directorio de branding.
- Esa segunda vía **no se puede usar aquí**: `installer/calamares/branding/churros/` está en la lista
  de [lo que no se modifica](../AGENTS.md). Las capturas van junto al `.conf` del módulo, en ruta
  absoluta dentro del airootfs.
- `mode: required` con una opción explícita «sin controlador» es lo que se quiere: exactamente una de
  las tres, y una de ellas es no instalar nada.

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

## Plan de desarrollo técnico

Cinco fases. Cada una es un PR independiente, con su prueba y su mutación, según
[Contributing](contributing.md#pruebas-según-el-tipo-de-cambio).

### Fase 0 — Limpiar lo que hoy es falso

Sin cambio de comportamiento; quita ruido y deja el terreno honesto.

| Tarea | Ficheros | Criterio de aceptación |
|---|---|---|
| 0.1 Retirar el grupo NVIDIA muerto, o dejar claro que es muerto | `installer/calamares/modules/netinstall.yaml`, `netinstall.conf` | `netinstall` no está en la secuencia: o se borra el grupo, o se borra el par de ficheros. No se deja configuración que nadie lee. |
| 0.2 Corregir el comentario de la guarda de Xorg | `scripts/cli/check.sh` (~1549) | La guarda se queda (sigue siendo correcta si alguien instala el driver a mano), pero el motivo deja de citar `netinstall`. |
| 0.3 Actualizar la visión | `docs/vision.md:30` | Describe el estado real y enlaza a este documento. |
| 0.4 Prueba: ninguna conf del instalador nombra paquetes muertos | `tests/container/test_arch_repos.py` | `nvidia-dkms`, `nvidia` y `nvidia-open` fallan con un mensaje que explica que el primero ya no existe y que el segundo arrastra `linux`. |

Mutación de 0.4: cambiar `nvidia-open-dkms` por `nvidia-open` en el YAML debe hacer fallar la prueba.

### Fase 1 — Instalar el driver correcto para el kernel que se instala

Es el núcleo del cambio.

| Tarea | Ficheros | Criterio de aceptación |
|---|---|---|
| 1.1 Vista de selección | `installer/calamares/modules/packagechooser.conf` (nuevo), `settings.conf` (`show`) | Tres opciones; `none` preseleccionada; `method: packages`; `mode: required`. **Sin entrada en `instances`** y con ese nombre exacto de fichero (ver nota). |
| 1.2 Instalación de los paquetes | `settings.conf` (`exec`: `packages`), `packages.conf` | `packages` va **después** de `shellprocess@pacman-init` (el llavero tiene que estar listo para verificar firmas) y **después** de `unpackfs` (instala dentro del destino). |
| 1.3 Regla del kernel | prueba estática nueva en `tests/static/test_calamares_config.py` | Si una opción instala un módulo, el paquete de módulo tiene que ser de `linux-cachyos`, y con DKMS la lista tiene que incluir `linux-cachyos-headers`. |
| 1.4 Resolución real de los nombres | `tests/container/test_arch_repos.py` | Cada paquete de cada opción resuelve en Arch + `[cachyos]` + multilib para x86_64. |
| 1.5 Exclusiones | `tests/static/test_editions.py` (o prueba nueva) | La vista no se ofrece en i686 ni en aarch64. |

Posición en la secuencia, que es lo que más fácil se rompe:

```
mount → shellprocess@boot-nocow → unpackfs → … → shellprocess@pacman-init → packages → initcpiocfg → shellprocess@fix-boot → initcpio → …
```

`packages` **no** puede ir antes de `unpackfs` (escribiría en el aire) ni antes de `pacman-init` (sin
llavero no hay firmas). Y **no** hay que ponerlo después de `shellprocess@fix-boot` si en el futuro se
decide tocar `MODULES` de forma condicional a que el driver esté instalado: `fix-boot` puede
consultar `pacman -Q` porque corre después.

Mutación de 1.3: quitar `linux-cachyos-headers` de la opción DKMS debe hacer fallar la prueba.

### Fase 2 — No entregar un sistema sin salida gráfica

| Tarea | Ficheros | Criterio de aceptación |
|---|---|---|
| 2.1 Verificar el resultado | `archiso/airootfs/usr/share/churros/scripts/verify-install` | Si se eligió un driver y no hay módulo `.ko*` en `/usr/lib/modules/*/` ni `pacman -Q` del paquete, `verify-install` falla y lo escribe en stdout (Calamares solo enseña stdout). |
| 2.2 Prueba de `verify-install` | `tests/static/test_verify_install.py` | Root falso con y sin módulo; el caso «driver pedido, módulo ausente» falla con el mensaje esperado. |
| 2.3 Aviso sin internet | `finished.conf` o el texto de la vista | Si la instalación se saltó `packages` por falta de red, el usuario lo sabe antes de reiniciar. |
| 2.4 Perfil de VRAM de niri | `archiso/airootfs/etc/nvidia/nvidia-application-profiles-rc.d/…json` (nuevo) | El JSON valida; se instala en el destino; no choca con `nvidia-utils`. |
| 2.5 Auditoría de la ISO | `tests/iso/check_iso.py` | El JSON está en el squashfs y **no** hay `nvidia*.ko*` en la ISO mientras no se active el flag de la Fase 4. |

Mutación de 2.2: hacer que `verify-install` no compruebe el módulo debe hacer fallar la prueba.

### Fase 3 — Documentación y diagnóstico

| Tarea | Ficheros | Criterio de aceptación |
|---|---|---|
| 3.1 Documento de uso | este fichero + `docs/README.md` | Indexado; enlaces relativos resueltos (`./churros check`). |
| 3.2 Guía de problemas | este fichero, sección de diagnóstico | `modeset` → `Y`; `nvidia-smi`; qué hacer si `-Syu` falla por versión; cómo volver a `nouveau`. |
| 3.3 Instalador | `docs/installer.md` | Documenta la vista nueva y su posición en la secuencia. |

### Fase 4 — Opcional, solo con issue aprobado

- `--with-nvidia` en `scripts/cli/build.sh` para meter el driver en la ISO y cubrir equipos sin red.
  Requiere resolver el `modprobe.d` que bloquea `nouveau` (el Live tiene que seguir arrancando si el
  propietario no carga).
- Autodetección de la familia de GPU en el instalador (programa nuevo: issue aprobado).
- aarch64 con DKMS, si aparece demanda real.
- Prueba de arranque con GPU NVIDIA real: hoy `tests/vm/boot_smoke.py` solo da virgl y no puede
  cubrirlo. Se queda como prueba manual documentada, igual que la instalación completa.

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

## Decisiones que faltan

Tres cosas que este documento **no** decide porque necesitan a los mantenedores:

1. **¿Licencia?** `nvidia-utils` es propietario (`LicenseRef-NVIDIA-Driver-License-Agreement`). Su
   cláusula 2.1.2 permite copiar y redistribuir los binarios para Linux sin modificarlos, así que el
   [principio 1](principios.md#1-libre-y-redistribuible) se cumple en su letra. Los módulos abiertos son
   MIT/GPL-2.0. Aun así, es una decisión de proyecto: por eso la Fase 1 instala solo en el destino y
   la ISO no lo lleva.
2. **¿Issue de aprobación?** Es una funcionalidad nueva de la ISO y del instalador. Según
   [Cómo se decide](principios.md#cómo-se-decide) y la regla para programas nuevos, hace falta un issue
   aprobado por dos mantenedores antes de la Fase 1. Las fases 0 y 3 no lo necesitan.
3. **¿Mantenedor?** `MAINTAINERS` asigna `/installer/` y `/archiso/`; conviene que quien apruebe figure
   como responsable de esta ruta, porque el ciclo de vida (Fase 4) es lo que se mantiene para siempre.

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
