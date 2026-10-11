# Auditoría de la edición KDE Plasma

Fecha: 4 de octubre de 2026 (America/Bogota). Base: `3ce269439c9c30aec3c3db7f1dd51fd672b74d2a`, igual a `origin/main` al comenzar. Rama: `codex/kde-edition-audit`. Revisión realizada en un worktree aislado.

## Resultado y alcance

La edición tiene una ruta de build/instalación propia y coherente en cuanto a selección de paquetes, identificación de edición y comando de sesión. Sin embargo, la base revisada rompe el acceso a los ajustes de Plasma, puede cambiar el autologin a Niri y fuerza portales GTK. Se corrigen cinco defectos concretos en esta rama. **El funcionamiento gráfico, el arranque de la sesión y el ciclo Live → instalado → actualizado quedan sin validar en VM.** Esta auditoría no acredita una ISO lista para publicar.

Se revisaron paquetes y dependencias, build y limpieza, greetd/PAM/D-Bus, portales, apps Rust y ajustes, panel, temas, Calamares, archivos conservados y bundles de actualización. No se modificaron Tour, gaming, rutas protegidas de branding/skel, ni el checkout principal. No se instalaron paquetes ni se construyó una ISO para esta auditoría.

Evidencia:

- **Estática:** lectura de código, configuración y dependencias; permite demostrar decisiones y contradicciones, no la apariencia final.
- **Ejecución aislada:** scripts reales y `kwriteconfig6` con configuración temporal; servicio de usuarios compilado con rutas y helpers sustituidos exclusivamente en una copia temporal.
- **Runtime pendiente:** compositor, login, KCM, portales y Calamares en una ISO nueva. Los componentes Plasma disponibles en el host se leyeron; no se ejecutó ni modificó su sesión.

Severidades: P1 impide una función esencial; P2 degrada una función o su conservación; P3 documentación/cobertura. Un riesgo condicionado se indica expresamente y no se presenta como fallo observado.

## Defectos corregidos

### K1 — P1: `systemsettings` sustituido y oculto

En la base, `root/scripts/desktop.sh:86–100` mueve `/usr/bin/systemsettings` a `.kde-orig`, lo enlaza a ChurrOS y oculta su desktop. La última orden de `shellprocess-cleanup.conf` vuelve a sustituirlo después de instalar. Además, `/usr/local/bin/systemsettings` ya intercepta el comando desde PATH. Corregir solo una de estas tres capas deja el problema activo.

Los botones de [pantalla](../rust/preferences/src/pages/display.rs) (líneas 35–48), [entrada](../rust/preferences/src/pages/input.rs) (54–67), [atajos](../rust/preferences/src/pages/keyboard.rs) (158–171) y [apariencia](../rust/preferences/src/pages/appearance.rs) (259–289 y 337–349) llaman a `systemsettings kcm_*`. Antes reciben otra instancia de ChurrOS o argumentos que su app no maneja; no llegan al KCM solicitado.

Reproducción previa en una ISO KDE: pulsar Pantalla → Abrir Ajustes de Pantalla; comparar `command -v systemsettings`, `readlink -f /usr/bin/systemsettings` y el `Exec`/`Hidden` del desktop nativo. No se ejecutó este paso gráfico aquí.

Cambio: el build KDE conserva el binario y desktop nativos; Calamares evita el enlace en KDE; el wrapper de `/usr/local/bin` delega al ejecutable nativo en KDE y conserva los argumentos. Niri/XFCE/server conservan su atajo anterior. Verificado con fixtures del wrapper y ejecución aislada de la orden real de Calamares. Esto beneficia instalaciones nuevas; **no restaura instalaciones antiguas ya alteradas**.

### K2 — P1: activar autologin selecciona Niri en KDE

[UsersService::set_auto_login](../rust/preferences/src/services/users.rs), líneas 168–189, solo distingue XFCE del resto en la base. KDE recibe `command = "niri"`, aunque la lista KDE no instala Niri. El build y `configure-greetd-session` sí seleccionan Plasma, por lo que el defecto aparece al cambiar el ajuste después de instalar.

Reproducción previa: en KDE, activar inicio automático desde ChurrOS, inspeccionar `[initial_session]` y reiniciar. El efecto tras reiniciar es una inferencia del comando incorrecto, no un arranque observado.

Cambio: añadir selección `startplasma-wayland` para KDE. La prueba compila el archivo completo del servicio, activa/desactiva/reactiva autologin y comprueba el TOML para KDE, XFCE y Niri sin privilegios. La negociación real de la sesión D-Bus sigue pendiente (R1).

### K3 — P1: el portal global GTK desplaza al backend KDE

[portals.conf global](../archiso/airootfs/etc/xdg/xdg-desktop-portal/portals.conf) usa `default=gtk`, sin ScreenCast ni RemoteDesktop. En `/etc/xdg` tiene precedencia sobre la configuración KDE suministrada en `/usr/share`. El backend GTK disponible tampoco anuncia Secret; el global lo asigna a GTK. Instalar `xdg-desktop-portal-kde` por sí solo no corrige la selección.

La precedencia y los nombres por escritorio están documentados en el [manual primario de portals.conf](https://flatpak.github.io/xdg-desktop-portal/docs/portals.conf.html). También se contrastaron `/usr/share/xdg-desktop-portal/kde-portals.conf` y los archivos `.portal` del host.

Cambio: añadir [kde-portals.conf](../archiso/airootfs/etc/xdg/xdg-desktop-portal/kde-portals.conf) en el mismo directorio, con KDE por defecto, Settings KDE/GTK, Secret KWallet y Notification plasmanotify, como el perfil suministrado por Plasma. Así se conserva el global de las otras ediciones. Una configuración personal de mayor precedencia puede seguir anulándolo.

Reproducción previa pendiente en ISO: con `XDG_CURRENT_DESKTOP=KDE`, solicitar compartir pantalla desde una app que use portal; consultar el journal de `xdg-desktop-portal`. Aquí se verificó selección por configuración y declaraciones de interfaces; **no** una captura real.

### K4 — P2: falta el módulo de ajustes de pantalla

El botón de pantalla solicita `kcm_kscreen`, pero la lista original no incluye `kscreen`. [Arch lo declara como dependencia opcional de plasma-desktop](https://archlinux.org/packages/extra/x86_64/plasma-desktop/); [kscreen suministra la gestión de pantallas](https://archlinux.org/packages/extra/x86_64/kscreen/). Tener `libkscreen` como biblioteca no equivale a tener su KCM.

Cambio: añadir `kscreen` a [packages.kde.x86_64](../archiso/packages.kde.x86_64), línea 74. No se instaló en el host. Pendiente comprobar `systemsettings kcm_kscreen` con la ISO resultante.

### K5 — P2: `configure-kde-panel` no localiza Kickoff

La versión original separa `grep -n` en dos campos, descarta el número de línea y pasa `plugin=...` al rango de `sed`. Después busca una sección `[Applets[` que no corresponde al formato real `[Containments][ID][Applets][ID]`, y escribe siempre en el contenedor `1`.

Reproducción aislada previa con dos paneles: código de salida 0, dos errores `sed: ... unexpected ','`, ninguna escritura de `icon=churros-logo`.

Cambio en [configure-kde-panel](../archiso/airootfs/usr/share/churros/scripts/configure-kde-panel): leer los IDs reales antes de escribir, conservar ambos contenedores, respetar `XDG_CONFIG_HOME` y usar `set -euo pipefail`. Verificado con el `kwriteconfig6` real: contenedores 42/99, applets 7/8, otro applet intacto, repetición idéntica y archivo ausente sin efectos. Esto verifica el archivo persistido, **no** la actualización visible de plasmashell en ejecución (R4).

## Hallazgos pendientes y riesgos

### R1 — P1 condicionado: la sesión presupone D-Bus

Los tres puntos de entrada ejecutan directamente `startplasma-wayland`: [build.sh:148](../scripts/cli/build.sh), [churros-xsession:34–35](../archiso/airootfs/usr/local/bin/churros-xsession) y [configure-greetd-session:25](../archiso/airootfs/usr/share/churros/scripts/configure-greetd-session). El nuevo brazo de autologin sigue ese mismo contrato.

El [lanzador primario de Plasma 6.7](https://raw.githubusercontent.com/KDE/plasma-workspace/Plasma/6.7/startkde/startplasma-wayland.cpp), líneas 61–64, termina si falta `DBUS_SESSION_BUS_ADDRESS`; no crea el bus. El desktop oficial instalado en el host usa `/usr/lib/plasma-dbus-run-session-if-needed /usr/bin/startplasma-wayland`, y ese helper inicia `dbus-run-session` cuando la variable falta.

El PAM del overlay incluye `system-local-login`, pero no establece explícitamente esta variable; `pam_systemd` y la existencia de un socket de bus no demuestran que greetd la entregue al proceso. **No se afirma que toda sesión falle:** hay que observar el entorno real de greetd, tanto con autologin como con ReGreet. Reproducción del caso condicionado en VM: quitar la variable antes de lanzar Plasma y observar su salida. Antes de aprobar el runtime, asegurar una ruta compatible con el helper oficial y probar login/logout/login. No se cambia esta arquitectura sin la prueba gráfica.

### R2 — P2: controles de energía ajenos a Plasma

[PowerService](../rust/preferences/src/services/power.rs), líneas 146–200 y 219–250, lee/escribe esquemas GNOME para apagado de pantalla, suspensión y tapa. Las páginas de [energía](../rust/preferences/src/pages/power.rs), [suspensión](../rust/preferences/src/pages/sleep.rs) y [timeout](../rust/preferences/src/pages/display_timeout.rs) se ofrecen también en KDE, pero no hay backend PowerDevil ni delegación a sus KCM.

Reproducción: cambiar un timeout/tapa en ChurrOS y contrastarlo con Preferencias del Sistema → Energía; un valor guardado por gsettings no demuestra que Plasma lo aplique. Pendiente adaptar u ofrecer acceso al KCM nativo. `powerprofilesctl` también se usa, pero la resolución de dependencias actual no incorpora `power-profiles-daemon`; la página tiene una salida para perfiles ausentes. No confundir ausencia de daemon con una limitación del hardware.

`do-not-suspend.conf` además conserva `HandleLidSwitch/HandleSuspendKey/HandleHibernateKey=ignore` en la instalación. PowerDevil puede manejar estos eventos en una sesión gráfica; el comportamiento en el greeter/sin Plasma debe probarse. No se modificó por ser compartido.

### R3 — P2: branding aplicado sobre archivos de paquetes

[desktop.sh:54–82](../archiso/airootfs/root/scripts/desktop.sh) reemplaza imágenes de Next/Breeze, iconos Breeze/Papirus y templates de Plasma. Calamares copia ese estado mediante unpackfs, pero las actualizaciones de sus paquetes pueden reponer los archivos originales. No hay hook KDE que vuelva a aplicar estas modificaciones. La edición propia en `/etc/churros-edition`, los assets bajo `/usr/share/churros`, el esquema propio y `kdeglobals` del overlay sí se copian; eso no garantiza que cada archivo reemplazado sobreviva.

Reproducción en VM desechable: guardar hashes/enlaces de las rutas afectadas, actualizar o reinstalar los paquetes propietarios, comparar y crear un panel nuevo. El [template primario de Plasma 6.7](https://raw.githubusercontent.com/KDE/plasma-desktop/Plasma/6.7/layout-templates/org.kde.plasma.desktop.defaultPanel/contents/layout.js) conserva el patrón `panel.addWidget("org.kde.plasma.kickoff")` usado por el parche, pero no promete estabilidad futura. Se mantiene el diseño existente; pendiente empaquetar la personalización en rutas propias/defaults compatibles.

### R4 — P2 condicionado: panel en vivo y preferencias personales

El autostart [churros-kde-branding.desktop](../archiso/airootfs/etc/xdg/autostart/churros-kde-branding.desktop) ejecuta el script al iniciar cada sesión. Si todavía no existe el archivo de applets, termina sin reintento. Si plasmashell ya cargó el archivo, una escritura externa no acredita un cambio en vivo y puede competir con su guardado posterior. Además, el script vuelve a imponer el logo en cada login aunque el usuario lo cambie.

Reproducción pendiente: usuario nuevo, dos paneles, login/logout/login, cambio manual de icono y reinicio de plasmashell. La corrección K5 no resuelve ni asegura orden, relectura o política de preferencias. Un mecanismo de configuración mediante la API viva de Plasma y un marcador de primera aplicación merece una prueba separada.

### R5 — P1 para migración: el bundle no entrega todas las correcciones

[build-churros-release.sh:47–75 y 99–102](../scripts/build-churros-release.sh) incluye scripts seleccionados, binarios Rust y `/usr/share/churros`, y copia el bundle común como bundle KDE. No incluye `/usr/local/bin/systemsettings`, `/etc/xdg/xdg-desktop-portal/kde-portals.conf`, el esquema de colores ni una instalación de `kscreen`. El updater [churros-update-utils:40–48](../archiso/airootfs/usr/bin/churros-update-utils) tampoco permite rutas `/etc/xdg` ni `/usr/share/color-schemes`.

Por tanto, publicar un bundle producido por el script actual puede entregar K2/K5, pero no basta para K1/K3/K4 ni para restaurar los archivos KDE ya sustituidos. No existe migración de `systemsettings.kde-orig`, reparación del desktop oculto ni aplicación automática de scripts de `/usr/share/churros/scripts` al actualizar. El bundle común no cambia actualmente el marcador de edición, pero su nombre por edición no significa contenido específico.

Reproducción: listar el tarball de release y comparar las rutas anteriores; en una VM instalada desde la base, actualizar y revisar enlace/desktop/portal/paquete. No se generó ni descargó un bundle. Pendiente diseñar una migración explícita y probarla antes de anunciar estas correcciones para instalaciones existentes.

### R6 — P2: integración KDE incompleta

- `bluez`/`bluez-utils` están presentes, pero `bluedevil` no aparece en la lista ni en la clausura actual de dependencias obligatorias. [Arch lo considera un applet opcional](https://archlinux.org/packages/extra/x86_64/plasma-desktop/). Los controles Bluetooth de ChurrOS no equivalen al applet nativo. Probar hardware/emulación Bluetooth antes de decidir incluirlo.
- `kwallet-pam` está seleccionado, pero [pam.d/greetd](../archiso/airootfs/etc/pam.d/greetd) no integra `pam_kwallet5`. Tener el paquete no asegura desbloqueo automático. Verificar greeter con contraseña y autologin por separado; no es una prueba de fallo de KWallet.
- `kdeglobals` pide Inter; no se encontraron archivos `.ttf/.otf` Inter en el overlay/branding ni `ttf-inter` en la resolución actual. Puede usarse una fuente sustituta. Probar `fc-match Inter` en la ISO. No se alteraron identidad ni fuentes.
- [input.rs:54–67](../rust/preferences/src/pages/input.rs) anuncia ratón y touchpad pero solo abre `kcm_mouse`; no ofrece el KCM de touchpad. [keyboard.rs:158–171](../rust/preferences/src/pages/keyboard.rs) abre atajos (`kcm_keys`), sin acceso propio a distribución de teclado. La ventana completa de ajustes permite navegar manualmente tras K1. Los errores de lanzamiento de los KCM se descartan; falta feedback de fallo.
- Iconos, fuentes y tamaño de cursor se escriben con `kwriteconfig6`, pero no todos notifican/reaplican el cambio en Plasma; escala de fuente usa GTK/GNOME. El fondo y esquema de colores sí tienen llamadas `plasma-apply-*`. Confirmar aplicación inmediata, coherencia Qt/GTK y persistencia en VM.

### R7 — P3: verificaciones y documentación sobreestiman cobertura

[verify-install:86–87](../archiso/airootfs/usr/share/churros/scripts/verify-install) marca como aviso la presencia de `[initial_session]`, aunque el instalador permite autologin legítimo; termina siempre con 0. Comprueba existencia del lanzador/habilitación de greetd, no arranque de Plasma ni acceso a KCM/portales. `./churros check` pasaba en la base pese a K1–K5. Los scripts sin extensión tampoco forman parte de su selección inicial de shellcheck (`git ls-files '*.sh' 'churros'`); se comprobaron aquí explícitamente.

La documentación dice que `plasma-pa` gestiona energía (gestiona audio), y los conteos README están desactualizados. Los defaults/skel compartidos se copian también a KDE; sus páginas exclusivas de Niri están correctamente condicionadas en `window.rs:214–240`, pero eso no elimina las limitaciones de páginas genéricas. El nuevo script de regresión es ejecutable con Python y no se incorporó al workflow CI; `kwriteconfig6`/`rustc` ausentes provocan SKIP explícito en sus pruebas respectivas.

## Cobertura por dominio y diferencias de edición

| Dominio | KDE | Diferencia/resultado |
| --- | --- | --- |
| Paquetes directos | 209 en base; 210 con `kscreen` | Niri 209, XFCE 217, server 185. Listas completas por edición; no herencia de la lista Niri. |
| Dependencias | Plasma/KWin, Breeze, kscreenlocker, KConfig, D-Bus y PowerDevil | PowerDevil es obligatorio transitivo en los metadatos actuales; no se denunció su ausencia por no estar escrito directamente. Bluedevil y power-profiles-daemon siguen ausentes. |
| Sesión live | greetd autologin `startplasma-wayland` | Niri `niri`; XFCE/server `startxfce4`. Entorno específico generado para `/home/churros`; D-Bus pendiente R1. |
| Sesión instalada | Plasma vía dispatcher y `configure-greetd-session` | Server sale del configurador y elimina escritorio/greetd; KDE no pasa por esa eliminación. Autologin posterior corregido K2. |
| Apps | Dolphin, Konsole, Kate, Gwenview, KCalc, Ark, Spectacle; también apps GTK y Thunar | Apps Rust desplegadas para todas las ediciones. GTK4/libadwaita incluidas en KDE. Coexistencia no acredita asociaciones MIME finales; probar `xdg-open`. |
| Ajustes | Ventana ChurrOS y accesos a KCM | Páginas Niri ocultas; acceso nativo recuperado K1/K4. Adaptación de energía/entrada incompleta. |
| Panel/branding | Kickoff, tema naranja/oscuro, Papirus, wallpaper ChurrOS | Diseño preservado; parser corregido K5; persistencia tras login/actualización pendiente R3/R4. |
| Portales | Backend KDE con KWallet/plasmanotify | Perfil específico añadido K3; las otras ediciones conservan selección global existente. |
| Calamares | unpackfs común, users, displaymanager, servicios y limpieza | Secuencia boot-nocow → unpackfs, pacman-init → fix-boot y grub-theme permanece intacta. No se validó instalación real. |
| Actualizaciones | Marcador KDE y lookup por edición | Bundles actualmente idénticos; no entregan/migran toda la personalización KDE (R5). |

La resolución se inspeccionó leyendo las bases oficiales `core.db`/`extra.db` sincronizadas el 4 de octubre del host, siguiendo dependencias obligatorias y proveedores. Los nombres locales/AUR no resueltos allí fueron `python-pywal`, `wlogout` y `yay`, previstos por `build-aur.sh`. No se ejecutó pacstrap ni se fijaron versiones para una ISO: la clausura puede cambiar con Arch rolling release. [Ficha primaria actual de plasma-desktop](https://archlinux.org/packages/extra/x86_64/plasma-desktop/).

## Validación ejecutada

| Verificación | Resultado | Límite |
| --- | --- | --- |
| `./churros check`, base y final | 0; todos los checks pasan, 2 avisos | Sintaxis/coherencia estática; no sesión KDE. |
| `python3 scripts/test-kde-integration.py` | 6 pruebas pasan, 0 SKIP | Panel real con HOME temporal, rutas/helpers de usuarios aislados, wrapper/orden Calamares aislados y perfil portal. |
| `CARGO_TARGET_DIR=/tmp/churros-kde-audit-target cargo check --manifest-path rust/Cargo.toml -p churros-settings --offline` | 0; termina en 36,95 s | Compilación/check del paquete modificado; no ejecución de GUI. |
| `bash -n` y `shellcheck -S warning` sobre desktop.sh, systemsettings y configure-kde-panel | 0 | Incluye scripts sin extensión omitidos por el check general. |
| `git diff --check` | 0 | Formato del diff, no funcionamiento. |
| `./churros doctor` | Herramientas presentes; informa falta de `/dev/kvm` | Su diagnóstico atribuye ausencia a BIOS; no se confirmó independientemente esa causa. |
| ISO, VM, instalación y actualización reales | **No ejecutados** | No existen `out/`, `work/` ni `vm/` en este worktree. |

El fixture panel previo produjo error de sed con salida 0; el nuevo escribe ambas secciones correctas de manera repetible. Las pruebas reproducibles viven en [scripts/test-kde-integration.py](../scripts/test-kde-integration.py).

## Próxima validación necesaria

1. Coordinar una única construcción KDE en este worktree, con caché/local repo propios; comprobar primero `/root/packages` del host. El build usa esa ruta global aunque work/out estén separados. El diff ajeno del checkout principal contiene trabajo sobre aislamiento de mounts y `mkinitcpio-nfs-utils`; no se copió ni se da por integrado aquí. `build.sh` también genera `etc/greetd/config.toml` sin restaurarlo en su trap; no editar su copia generada y revisar ese diff al construir.
2. Arrancar una ISO fresca con disco/EFI propios. Comprobar login automático live, logout/ReGreet, D-Bus/entorno, paneles, monitor, teclado, touchpad, audio/red, KWallet y portales ScreenCast/FileChooser/Secret. En ausencia de KVM, acordar una ejecución soportada antes de atribuir fallos del compositor a KDE.
3. Instalar con Calamares con autologin desactivado y activado en ejecuciones separadas. Validar arranque desde disco, entorno Plasma, eliminación del usuario live/repositorio local y acceso nativo a todos los KCM. Cambiar autologin desde ChurrOS y repetir el arranque.
4. En VM desechable, probar actualización de Plasma/temas y bundle ChurrOS, comparando hashes/enlaces, defaults y preferencias personales. Diseñar/probar la migración R5 antes de publicar correcciones para usuarios existentes.

Los pasos que cambian sistema o reinstalan paquetes son un protocolo para la VM futura; no se realizaron en el host durante esta revisión.
