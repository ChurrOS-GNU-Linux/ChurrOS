# Auditoría de ChurrOS — rama `main`

**Repositorio:** [ChurrOS-GNU-Linux/ChurrOS](https://github.com/ChurrOS-GNU-Linux/ChurrOS)
**Rama auditada:** `main` (exacta)
**Commit:** `5f12aad0f6fb44c87d36dbb89a34c5defec5907c` — *Merge pull request #388 from ChurrOS-GNU-Linux/release/1.5.6*
**Fecha del commit:** 2026-11-15
**Versión:** 1.5.6
**Fecha de la auditoría:** 2026-11-16
**Alcance:** 748 ficheros versionados — 149 de Rust (~35.800 líneas), 52 scripts de shell (~10.000 líneas), 59 de Python (~22.200 líneas), 50 documentos Markdown, 10 workflows de CI.

---

## 0. Método y baseline

La auditoría se hizo sobre una copia limpia del repositorio, con `git rev-parse HEAD` == `git rev-parse origin/main` (0 commits de diferencia) y `git status` sin cambios.

Antes de tocar nada se ejecutó la validación que declara el propio proyecto:

```
$ ./churros check
...
All checks passed (5 notices)
EXIT=0
```

Es decir: **305 pruebas estáticas, 401 mutaciones definidas y 276 comprobaciones de polkit pasan en `main`**. Esto es importante para leer este informe: **ningún hallazgo de abajo es un fallo que el CI actual detecte**. Son precisamente los huecos que la suite no modela. Donde un hallazgo es una *ausencia* de cobertura, se dice explícitamente.

Las comprobaciones se hicieron por lectura del código, ejecución de las herramientas disponibles (`shellcheck` 0.10.0, `bash -n`, `python3 -m unittest`, `cargo metadata`) y `cargo test` del crate `churros-services` (50 pruebas, todas en verde), más contraste cruzado de cada afirmación contra el fichero y la línea citados.

**Límite de verificación en Rust:** las apps con interfaz (`preferences`, `popups`, `churros-welcome`, `churros-tour`, `control-center`) no se pudieron compilar en la máquina de auditoría: requieren GTK4 y libadwaita (no instalados) y `rustc` 1.92 (la máquina tiene 1.85.1). Lo que este documento afirma sobre esos crates viene de lectura del código, no de ejecución; el crate `churros-services` sí se compiló y se probó. Se indica cuando aplica.

> **Documento vivo.** Los issues se van resolviendo en la rama `dev` y este fichero se actualiza con cada uno: la tabla de estado de la sección 1 indica qué está corregido y con qué commit.

### Cómo leer los niveles

| Nivel | Significado |
|---|---|
| 🔴 **ROJO** | Fallo crítico. Seguridad, pérdida de datos del usuario, o una función que no hace lo que promete. Requiere corrección antes del siguiente release. |
| 🟡 **AMARILLO** | No es grave hoy, pero puede escalar: deuda con condición de empeoramiento conocida, o impacto real limitado a un escenario concreto. |
| 🟢 **VERDE** | Mejora, higiene o robustez. No hay daño actual. |

Cada issue lleva: evidencia (`archivo:línea`), consecuencia, y una propuesta de corrección verificable.

---

## 1. Resumen ejecutivo

**Total: 19 issues — 3 rojos, 7 amarillos, 9 verdes.**

### Estado de resolución

| # | Nivel | Título | Estado | Commit |
|---|---|---|---|---|
| R1 | 🔴 | Secretos de API en workflows de QA visual | Abierto | — |
| R2 | 🔴 | «Restablecer ajustes» pierde datos y reporta éxito | Abierto | — |
| R3 | 🔴 | Crash con `config.jsonc` de raíz no-objeto | Abierto | — |
| A1 | 🟡 | `do-not-suspend.conf` heredado al instalar | Abierto | — |
| A2 | 🟡 | `systemd-gpt-auto-generator` heredado | Abierto | — |
| A3 | 🟡 | Mirror HTTP en aarch64 | Abierto | — |
| A4 | 🟡 | Bloqueo del hilo de GTK | Abierto | — |
| A5 | 🟡 | Pidfiles de popups sin `O_EXCL`/`flock` | Abierto | — |
| A6 | 🟡 | Sin auditoría de dependencias | Abierto | — |
| A7 | 🟡 | QA visual puede fallar y quedarse en verde | Abierto | — |
| V1 | 🟢 | `shellcheck` solo a nivel `error` | Abierto | — |
| V2 | 🟢 | `panic = "abort"` y `unwrap` en datos de usuario | Abierto | — |
| V3 | 🟢 | `getpwuid`: falta validar `pw_dir` | Abierto | — |
| V4 | 🟢 | `process_is_popup` por subcadena de `cmdline` | Abierto | — |
| V5 | 🟢 | `nmcli` descarta resultado en `forget`/`disconnect` | Abierto | — |
| V6 | 🟢 | `repair_pending` oculta fallo de `pacman` | Abierto | — |
| V7 | 🟢 | `.gitignore` sin patrones criptográficos | Abierto | — |
| V8 | 🟢 | `churros-update.service` sin `TimeoutStartSec` | Abierto | — |
| V9 | 🟢 | Comentario obsoleto y artefacto compartido en `iso.yml` | Abierto | — |

| # | Nivel | Título | Área |
|---|---|---|---|
| R1 | 🔴 | Secretos de API expuestos a código del PR en 4 workflows de QA visual | CI/CD |
| R2 | 🔴 | «Restablecer ajustes» borra configuración y reporta éxito aunque la copia falle | Rust / datos |
| R3 | 🔴 | `churros-settings` aborta con un `config.jsonc` de fastfetch con raíz no-objeto | Rust / crash |
| A1 | 🟡 | `do-not-suspend.conf` del Live se hereda: el portátil instalado no suspende al cerrar la tapa | Instalador |
| A2 | 🟡 | `systemd-gpt-auto-generator` desactivado se hereda al sistema instalado | Instalador |
| A3 | 🟡 | Mirror HTTP en claro en el `pacman.conf` de aarch64 | Cadena de suministro |
| A4 | 🟡 | Las apps bloquean el hilo de GTK varios segundos (o minutos) | Rust / UX |
| A5 | 🟡 | Popups: pidfiles sin `O_EXCL` ni `flock`, ventana de carrera real | Rust / concurrencia |
| A6 | 🟡 | Sin auditoría de dependencias (`cargo-audit`/`cargo-deny`); Dependabot solo cubre actions | Cadena de suministro |
| A7 | 🟡 | El pipeline de QA visual puede fallar entero y quedarse en verde | CI/CD |
| V1 | 🟢 | `shellcheck` corre a nivel `error`: 15 avisos nunca fallan el CI | Calidad |
| V2 | 🟢 | `panic = "abort"` en release y `expect`/`unwrap` en rutas de datos de usuario | Rust |
| V3 | 🟢 | `getpwuid`: se valida el puntero de la struct, no el de `pw_dir` | Rust / UB |
| V4 | 🟢 | `process_is_popup` identifica por subcadena de `cmdline` y puede matar un proceso ajeno | Rust |
| V5 | 🟢 | `forget`/`disconnect`/`enable` de wifi descartan el resultado de `nmcli` | Rust / errores |
| V6 | 🟢 | `repair_pending` convierte un fallo de `pacman` en «no hay nada que reparar» | Rust / errores |
| V7 | 🟢 | Faltan `.env`, `*.pem`, `*.key`, `id_*` en `.gitignore` | Higiene |
| V8 | 🟢 | `churros-update.service` desatendido sin `TimeoutStartSec` | systemd |
| V9 | 🟢 | Comentario obsoleto en `iso.yml` y nombre de artefacto compartido PR/noche | CI/CD |

**Lo que está bien y conviene no romper:** la regla polkit `50-churros-store.rules` está correctamente endurecida (rutas absolutas, argv exacto, sin comodines de nombre, comprobación de `user == root`); `churros-update-utils` verifica firma minisign antes de leer el manifiesto y valida tipos y rutas del tarball; no hay secretos reales versionados ni `pull_request_target` ni `permissions: write-all` en ningún workflow; la secuencia de Calamares respeta todos los *keypins* de `AGENTS.md`; el `[churros]` se elimina del destino y `sudoers.d/churros` se borra al instalar.

---

# 🔴 ROJO

## R1 — Secretos de API expuestos a código del PR en cuatro workflows de QA visual

**Severidad:** Crítica (fuga de credenciales)
**Ubicación:** `.github/workflows/visual-qa-classify.yml:39-40`, `visual-qa-capture.yml:37-38` y `:115`, `visual-qa-iso.yml:45-46`, `visual-qa-report.yml:35-36`

**Evidencia**

```yaml
# visual-qa-classify.yml
on:
  pull_request:                    # :8-9  — se dispara con CUALQUIER PR

    continue-on-error: true        # :25   — y el resultado es verde pase lo que pase

      - name: Classify changed paths
        env:
          # :39-40 — las dos claves de API, leídas como secretos del repo
          <DOS_CLAVES_API>: ${{ secrets.<NOMBRE> }}
        run: |
          python3 scripts/qa/visual/classify.py \                # :48
```

Las dos variables son `TYPESAFE_API_KEY` y `ANTHROPIC_API_KEY`.

`scripts/qa/visual/classify.py:554-555` lee ambas claves de `os.environ`. El script se ejecuta desde el **checkout de la PR** (`actions/checkout` sin `ref`, en un evento `pull_request`, resuelve el merge commit de la PR).

**Consecuencia**

Cualquiera con permiso de escritura en el repositorio (colaborador, cuenta comprometida, bot) puede abrir una rama, añadir dos líneas a `scripts/qa/visual/classify.py` que lean `os.environ` y exfiltren las claves, y abrir una PR. El job se ejecuta con ambos secretos en el entorno, la fuga ocurre, y **nadie lo nota**: el workflow tiene `continue-on-error: true` y no es check requerido.

Además, `scripts/qa/` **no está en `CODEOWNERS`** (`.github/CODEOWNERS` cubre `/tests/`, `/scripts/cli/check.sh`, `/scripts/cli/test.sh`, `/scripts/test-*` y `/.github/`), así que el cambio ni siquiera solicita revisor de CI.

**Matices que acotan (no eliminan) el alcance**

- GitHub **no** entrega secretos a `pull_request` desde forks, así que un desconocido no puede explotarlo. El vector exige push a una rama del propio repositorio.
- El `GITHUB_TOKEN` está limitado a `contents: read`, así que el daño se limita a las dos claves de terceros, no al repositorio.

Es rojo igualmente: son dos credenciales de API de pago, el patrón es exactamente el que GitHub documenta como inseguro, y el repo ya conoce la solución correcta (`ci.yml:38-41` descarga actionlint y **verifica su sha256** antes de ejecutarlo).

**Corrección propuesta**

1. Mover la clasificación a un workflow `workflow_run` (que corre en el contexto de `main`, sin código de la PR) o ejecutar `classify.py` desde una copia de `main`, no desde el checkout de la PR.
2. Añadir `scripts/qa/` a `CODEOWNERS`.
3. Añadir a `tests/static/` una comprobación de que ningún workflow con `on: pull_request` referencia `secrets.*` (hoy no existe; ver A7/V1).
4. Rotar `TYPESAFE_API_KEY` y `ANTHROPIC_API_KEY` una vez corregido, porque el patrón lleva tiempo expuesto.

---

## R2 — «Restablecer ajustes» borra configuración del usuario y reporta éxito aunque la copia falle

**Severidad:** Crítica (pérdida de datos irreversible presentada como éxito)
**Ubicación:** `rust/preferences/src/services/backup_service.rs:334-336` y `:290`; UI en `rust/preferences/src/pages/backup.rs:289-293`

**Evidencia**

```rust
// backup_service.rs — restore_dotfiles()
for entry in entries.flatten() {
    let src = entry.path();
    if !src.is_dir() { continue; }
    let dst = home().join(".config").join(entry.file_name());
    if entry.file_name() == "noctalia" {
        restore_noctalia_config(&src, &dst);
        continue;
    }
    if dst.exists() {
        let _ = fs::remove_dir_all(&dst);        // :334  borra, error descartado
    }
    let _ = copy_dir_all(&src, &dst);            // :336  copia, error descartado
}
```

```rust
// backup_service.rs — reset_to_defaults()
Self::restore_settings();
Self::restore_dotfiles();      // no devuelve Result: no puede fallar hacia arriba
...
Ok(true)                       // :290  siempre Ok, pase lo que pase
```

**Alcance exacto (verificado, sin exagerar):** no borra todo `~/.config`. Itera los subdirectorios de `/usr/share/churros/defaults/`, que hoy son siete: `fastfetch`, `foot`, `fuzzel`, `mako`, `niri`, `noctalia`, `waybar`. **Sí destruye por completo la configuración que el usuario tenga en esos siete directorios**, y `~/.config/noctalia` pasa por una ruta distinta que preserva `live.toml` pero tampoco propaga errores.

**Consecuencia**

La secuencia real es: se borra el directorio del usuario → `copy_dir_all` falla (permisos, disco lleno, `DEFAULTS_DIR` incompleto, fichero inmutable) → el error se descarta dos veces → `reset_to_defaults` devuelve `Ok(true)` → la UI muestra *«Configuraciones restablecidas a defaults»*. El usuario ha perdido su configuración de niri/foot/waybar y la app le dice que todo fue bien.

El diálogo de confirmación existe y avisa de que se borrarán los ajustes (`backup.rs:259-262`), lo cual mitiga la sorpresa pero **no** convierte el fallo silencioso en aceptable: el usuario consiente un borrado *que se va a restaurar*, no un borrado a medias.

**Corrección propuesta**

1. Hacer que `restore_dotfiles` y `reset_to_defaults` devuelvan `Result<(), String>` propagando cada error de `remove_dir_all` y `copy_dir_all`.
2. Copiar a un directorio temporal y renombrar al final (o mover el original a `.bak` y restaurarlo si la copia falla), en vez de borrar primero.
3. Añadir la prueba que lo cubre y su mutación en `tests/mutations/mutations.d/`, como exige `AGENTS.md`.

---

## R3 — `churros-settings` aborta con un `config.jsonc` de fastfetch con raíz no-objeto

**Severidad:** Crítica (crash reproducible de la app)
**Ubicación:** `rust/preferences/src/services/fastfetch_config.rs:84` (origen), `:274`, `:317`, `:340`, `:392`, `:489` (los `unwrap`)

**Evidencia**

```rust
// :79-88  read_config()
fn read_config() -> Value {
    let path = config_path();
    match fs::read_to_string(&path) {
        Ok(raw) => {
            let clean = strip_jsonc_comments(&raw);
            serde_json::from_str(&clean).unwrap_or_else(|_| json!({}))   // :84
        }
        Err(_) => json!({}),
    }
}
```

```rust
// :268-274  set_logo_source()
let mut cfg = read_config();
let logo = cfg
    .as_object_mut()
    .unwrap()                                    // :270 — panic si la raíz no es objeto
    .entry("logo")
    .or_insert_with(|| json!({}));
let obj = logo.as_object_mut().unwrap();          // :274 — panic si "logo" no es objeto
```

**Por qué es alcanzable**

`unwrap_or_else` solo cubre el **error de parseo**. Un `config.jsonc` sintácticamente válido cuya raíz no sea un objeto (`[]`, `"x"`, `5`, `null`) pasa el parseo y hace que `as_object_mut()` devuelva `None`. Y un `"logo": "texto"` (cadena en lugar de objeto) dispara el segundo `unwrap`.

Los setters no son código muerto: se invocan desde callbacks de la UI —
`pages/fastfetch.rs:137` llama `set_logo_source` desde un `connect_selected_notify`, y `:198` llama `set_logo_padding_top` desde el callback de un `SpinRow`. Basta abrir *Ajustes → Fastfetch* y tocar el tipo de logo o el padding.

**Agravante:** `rust/Cargo.toml:9` fija `panic = "abort"`. Un panic no desenrolla: **mata el proceso entero**, sin diálogo y sin mensaje. El usuario ve desaparecer Ajustes.

**Detalle que confirma que es un descuido y no un diseño:** `write_config()` (`:89-97`) **sí** se protege — se niega a sobrescribir un fichero que no parsea. La asimetría entre lectura y escritura es el defecto.

**Corrección propuesta**

1. Normalizar en un único punto: que `read_config()` devuelva siempre un objeto.

```rust
fn read_config() -> Value {
    let parsed = /* … */;
    if parsed.is_object() { parsed } else { json!({}) }
}
```

2. Reemplazar los `as_object_mut().unwrap()` por `or_insert_with(|| json!({}))` seguido de un patrón que tolere un tipo inesperado (por ejemplo devolver `false` o degradar a `json!({})`).
3. Añadir prueba con raíz `[]` y con `"logo": "texto"`, más su mutación.

---

# 🟡 AMARILLO

## A1 — `do-not-suspend.conf` del Live se hereda: el portátil instalado no suspende al cerrar la tapa

**Ubicación:** `archiso/airootfs/etc/systemd/logind.conf.d/do-not-suspend.conf:4` frente a `installer/calamares/modules/shellprocess-cleanup.conf:53` y `:66`

**Evidencia**

```ini
# do-not-suspend.conf
[Login]
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandleLidSwitch=ignore      # :4
```

La limpieza post-instalación retira el drop-in de journald (`:66`), el de coredump (`:53`) y las unidades del Live, pero **no** este. `grep -rn "do-not-suspend"` en todo el árbol devuelve solo el propio fichero y `docs/live-services.md:274-276`, que lo documenta explícitamente como medida **del Live**: *«Impide que el sistema se suspenda automáticamente en el Live»*. `HandleLidSwitch` no aparece en ningún otro fichero, así que no hay nada que lo sobrescriba en el sistema instalado.

**Consecuencia**

`unpackfs` copia el airootfs completo al destino. El sistema instalado hereda `HandleLidSwitch=ignore` y **nunca suspende al cerrar la tapa**: batería consumida en la mochila, apagado sucio por agotamiento, y el usuario convencido de que la suspensión está rota.

**Por qué ninguna prueba lo ve:** `LiveUnitsTest` (`tests/static/test_calamares_config.py:1622`) solo comprueba unidades que `services-systemd.conf` marca `mask`; un drop-in de `logind` no es una unidad y queda fuera del modelo.

**Corrección propuesta**

Añadir a `shellprocess-cleanup.conf` una entrada `rm -f /etc/systemd/logind.conf.d/do-not-suspend.conf` junto a la de journald, y extender la prueba a un recorrido de `etc/systemd/**/*.conf.d` que verifique que todo drop-in exclusivo del Live está en la lista de limpieza.

---

## A2 — `systemd-gpt-auto-generator` desactivado se hereda al sistema instalado

**Ubicación:** `archiso/airootfs/etc/systemd/system-generators/systemd-gpt-auto-generator` (symlink → `/dev/null`)

**Evidencia**

```
$ ls -l archiso/airootfs/etc/systemd/system-generators/
lrwxrwxrwx 1 dylan dylan 9 nov 16 22:50 systemd-gpt-auto-generator -> /dev/null
```

Es el patrón estándar de archiso para que el Live **no** monte automáticamente las particiones del disco detectadas por GPT. El symlink es un fichero regular del airootfs, así que `unpackfs` lo copia al destino. `grep -rn "system-generators"` en `installer/`, `root/scripts/` y `usr/share/churros/scripts/` **no devuelve nada**: no hay limpieza ni sobrescritura.

**Consecuencia**

En el sistema instalado, el generador de systemd está enmascarado:

- Desaparece el montaje automático de la partición EFI, `/home`, `/srv`, `/var` y las particiones de intercambio declaradas por tipo GPT.
- Un equipo instalado con `/home` o swap en partición GPT separada puede no montarlos al arrancar.

Impacto limitado porque el instalador de ChurrOS (Calamares) genera un `fstab` explícito, que systemd respeta por delante del generador. Pero el generador también cubre casos que el `fstab` no: swap GPT, `root=` en la línea de comandos del kernel, y sistemas montados después. Es amarillo y no rojo justamente por el `fstab`.

**Corrección propuesta**

Eliminar el symlink en `shellprocess-cleanup.conf` (como se hace con `pacman-init.service`) y añadirlo al mismo recorrido de drop-ins/ficheros exclusivos del Live que pide A1.

---

## A3 — Mirror HTTP en claro en el `pacman.conf` de aarch64

**Ubicación:** `archiso/pacman.aarch64.conf:97`, `:103`, `:109`

**Evidencia**

```ini
[core]
Server = https://ftp.halifax.rwth-aachen.de/archlinux-arm/$arch/$repo
Server = http://mirror.archlinuxarm.org/$arch/$repo        # :97  ← HTTP en claro
Server = https://ca.us.mirror.archlinuxarm.org/...
```

`SigLevel = Required DatabaseOptional`, así que **la firma de paquetes protege la integridad** (un paquete manipulado se rechaza). Lo que queda expuesto es la **metadata** y la disponibilidad: la base de datos de paquetes viaja sin cifrar y es manipulable en tránsito, lo que permite degradar a versiones antiguas firmadas (rollback attack) o dirigir al cliente a un paquete distinto que sí esté firmado.

El mismo fichero ya tiene tres mirrors `https://` para el mismo repo, y el `pacman.i686.conf` usa **solo** `https://`. La inconsistencia es el defecto.

**Corrección propuesta**

Eliminar la línea `http://` de los tres bloques (`core`, `extra`, `alarm`) o reordenarla al final como último recurso. Añadir a `tests/static/` una comprobación de que ningún `pacman.*.conf` versionado contiene `Server = http://` para un repo remoto.

---

## A4 — Las apps bloquean el hilo de GTK varios segundos (o minutos)

**Ubicación:** `rust/preferences/src/services/users.rs:245-250`, `pages/greeter.rs:265`, `:159`, `:176`, `:308`, `:332`, `rust/popups/src/network.rs:146`, `:177`, `:195`, `:211`, `:219`, `:273`, `:339`, `:362`

**Evidencia**

```rust
// users.rs:245 — write_root_config(), llamado desde un connect_clicked
Command::new("churros-pkexec")
    .arg(WRITE_ROOT_CONFIG)
    .args(args)
    .status()          // espera bloqueante, sin timeout
```

```rust
// popups/src/network.rs:177 — callback de UI
refresh.connect_clicked(move |_| wifi2.reload());
// :146 — reload() llama wifi::get(), que encadena 4 comandos con run(cmd, 5000)
```

**Consecuencia**

En el caso de `churros-pkexec`, el hilo de GTK se para mientras el usuario teclea la contraseña de administrador en el diálogo de polkit y el helper escribe en `/etc`. Son segundos o minutos con la ventana sin repintar; el compositor puede marcarla como «no responde».

En el popup de red son hasta ~4 × 5 s = 20 s con la radio apagada o el daemon lento: `reload()`, `select_network` (`:195`, `:211`), `forget_network` (`:219`) y los botones de conexión (`:273`, `:339`) llaman a `wifi::*` de forma bloqueante desde callbacks, y `:362` lo hace al construir la ventana.

El propio crate demuestra que el patrón correcto existe y se usa: `pages/update.rs:152`, `pages/logs.rs:130`, `pages/connectivity.rs:92` y `pages/datetime.rs:227` lanzan `std::thread::spawn` y devuelven el resultado por canal. La inconsistencia, no la falta de herramienta, es el defecto.

**Corrección propuesta**

Envolver las rutas de `greeter.rs`/`users.rs` y las de `network.rs` en el mismo patrón hilo + canal que ya usan las otras páginas, deshabilitando el botón mientras corre la operación.

---

## A5 — Popups: pidfiles sin `O_EXCL` ni `flock`, con ventana de carrera real

**Ubicación:** `rust/popups/src/main.rs:187-193` y `:196-205`; `rust/services/src/lib.rs:59-71`

**Evidencia**

```rust
// main.rs:187-193
if running_name().as_deref() == Some(name.as_str()) { kill_popup(); return; }
kill_popup();
let code = launch(&name);      // dentro: open_runtime_file("popup.pid", false)
```

```rust
// services/src/lib.rs — open_runtime_file
.write(true).create(true).truncate(!append).custom_flags(O_NOFOLLOW)
```

`O_NOFOLLOW` impide seguir un symlink (bien), pero **no hay `O_EXCL` ni `flock`**: es un *check-then-act* puro.

**Consecuencia**

Dos clics seguidos en Waybar mientras la primera instancia aún no ha escrito el pidfile: ambos `running_name()` devuelven `None`, ambos `kill_popup()` no hacen nada, se lanzan dos apps GTK y la segunda sobrescribe el pid. Peor: el bloque de limpieza (`main.rs:196-205`) borra `popup.pid`/`popup.name` sin comprobar propiedad, así que al salir la instancia A borra el pidfile de B y el siguiente clic lanza una tercera. Popups huérfanos y toggles que no apagan.

**Corrección propuesta**

Abrir el pidfile con `O_CREAT | O_EXCL` y, en el proceso que gana, mantener un `flock(LOCK_EX)` durante toda la vida del popup. La limpieza solo borra el pidfile si el `flock` se obtuvo y el contenido sigue siendo el propio pid.

---

## A6 — Sin auditoría de dependencias; Dependabot solo cubre las actions

**Ubicación:** `.github/dependabot.yml:1-2`; `rust/Cargo.lock` versionado

**Evidencia**

```yaml
# Solo las acciones de GitHub (uses:). Cargo, pacman y las imágenes de
# contenedor no se actualizan por aquí.
```

`grep -rn "cargo-audit\|cargo-deny\|deny.toml\|osv-scanner\|trivy\|rustsec"` sobre todo el árbol **no devuelve ninguna ocurrencia**. `tests/static/test_supply_chain.py` cubre reproducibilidad (`SOURCE_DATE_EPOCH`) y pinning de PKGBUILD, no CVEs.

**Consecuencia**

`Cargo.lock` fija las versiones, pero nadie las mueve ni las audita. Una dependencia vulnerable en un crate del escritorio llega a la ISO y se queda ahí hasta que alguien la suba a mano. En una distribución que envía binarios compilados a usuarios finales, es deuda con fecha de caducidad.

**Corrección propuesta**

`cargo-deny` con un `deny.toml` (o `cargo-audit`) en `rust.yml`, y añadir `cargo` como ecosistema en `dependabot.yml`. Ambas son decisiones de política del proyecto: conviene discutirlas en el issue antes de implementarlas.

---

## A7 — El pipeline de QA visual puede fallar entero y quedarse en verde

**Ubicación:** `.github/workflows/visual-qa-classify.yml:25`, `visual-qa-iso.yml:32`, `visual-qa-capture.yml:24` y `:61`, `visual-qa-report.yml:24` y `:55`

**Evidencia**

```yaml
    continue-on-error: true
```

Las cuatro etapas lo llevan.

**Consecuencia**

Un `classify.py` roto, una clave caducada o un fallo de QEMU producen **exactamente el mismo resultado observable** que «esta PR no es visual»: cero capturas, cero comentario, todos los checks en verde. No hay ninguna comprobación de que el pipeline haya llegado al final. `AntiWeakeningTest` (`tests/static/test_repo_wiring.py:970-978`) solo prohíbe `continue-on-error` en jobs que ejecutan **pruebas**, y estos no lo son.

La intención de no bloquear el merge es correcta; el problema es que «no bloquear» se implementó como «no informar».

**Corrección propuesta**

Mantener `continue-on-error` (no bloquear el merge) pero publicar un resultado explícito: un paso final que falle el job *solo si nadie llegó a decidir* (`visual` vacío), y que comente en la PR cuando el pipeline se degradó. Así «no visual» y «se rompió» dejan de ser indistinguibles.

---

# 🟢 VERDE

## V1 — `shellcheck` corre a nivel `error`: 15 avisos nunca fallan el CI

`tests/static/test_shell_scripts.py:16` invoca `shellcheck -S error`. Ejecutando el mismo shellcheck 0.10.0 a nivel `warning` sobre los 52 scripts aparecen **15 avisos**, ninguno de los cuales se ve hoy:

| Fichero:línea | Aviso | Comentario |
|---|---|---|
| `scripts/cli/run.sh:284`, `:316`, `:321` | SC2054 | Comas separando elementos de array; es `-device virtio-vga-gl,xres=…`, un valor QEMU legítimo — falso positivo real |
| `scripts/build-kernel-vyper.sh:115` | SC2115 | `rm -rf "$WORK_DIR"/*` sin `${:?}`; si `WORK_DIR` quedara vacía expandiría a `/*` |
| `scripts/lib/local-repo.sh:143` | SC2164 | `cd "$dir"` sin `|| return` |
| `scripts/lib/cluster.sh:96`, `:139` | SC2087 | Heredoc sin comillas: la expansión ocurre en el cliente, no en el servidor |
| `scripts/container-entrypoint.sh:34` | SC2046 | La sustitución `$(pacman -Qq …)` sin comillas; el `disable=SC2046` de la línea 32 no la alcanza |
| `archiso/profiledef.sh:6`, `:8` y `scripts/build-kernel-vyper.sh:133`, `:151`, `:154` | SC2155 | Declarar y asignar por separado (5 en total) |
| `scripts/cli/check.sh:1776` | SC2034 | `CHURROS_BINFMT_DIR` se asigna y solo se usa para `unset` |
| `scripts/cli/build.sh:455` | SC2034 | `BAZAAR_PKG=""` se asigna y nunca se lee (verificado: solo `:455` y `:456`) |

**Propuesta:** subir el umbral a `warning` en `test_shell_scripts.py`, añadir a `known_issues.toml` el falso positivo de `run.sh` con su nota, y limpiar el resto. Empezando por `build-kernel-vyper.sh:115`, que es el único con potencial destructivo.

---

## V2 — `panic = "abort"` en release y `expect`/`unwrap` en rutas de datos de usuario

`rust/Cargo.toml:9` fija `panic = "abort"`. Hay **211** `unwrap`/`expect`/`panic!` en código no-test del workspace. La mayoría están justificados (literales constantes, invariantes ya comprobadas); una revisión dirigida confirmó que `settings.rs:124`, `mako_config.rs:142-182` y `niri_config.rs:167` están protegidos por el código que los precede. **El único panic alcanzable con datos de usuario es R3.** La sinergia sí importa como principio: con `panic = "abort"`, cualquier `expect` que un día quede mal guardado no degrada, mata la app sin mensaje. Merece un `#![deny(clippy::unwrap_used)]` acotado a los módulos de I/O, o al menos un repaso con esa lente.

---

## V3 — `getpwuid`: se valida el puntero de la struct, no el de `pw_dir`

`rust/services/src/lib.rs:87-90`

```rust
let pwd = unsafe { libc::getpwuid(uid) };
if !pwd.is_null() {
    let dir = unsafe { CStr::from_ptr((*pwd).pw_dir) };
```

El NULL de `getpwuid` está correctamente comprobado. Pero `(*pwd).pw_dir` es un `*mut c_char` que puede ser NULL (una entrada de `passwd` con home vacío lo produce), y `CStr::from_ptr(null)` es comportamiento indefinido, no un panic recuperable. Falta `if (*pwd).pw_dir.is_null() { … }`.

---

## V4 — `process_is_popup` identifica por subcadena de `cmdline`

`rust/popups/src/main.rs:44-52` y `:105-118`

```rust
Ok(cmdline) => cmdline.contains("churros-popup"),
...
signal_pidfd(pidfd.as_ref(), pid, libc::SIGKILL);   // tras 500 ms de gracia
```

No compara el ejecutable real (`/proc/<pid>/exe` o `comm`) sino una subcadena de la línea de comandos. Cualquier proceso cuya `cmdline` mencione `churros-popup` pasa el filtro y recibe SIGTERM y luego SIGKILL si su pid quedó en un pidfile obsoleto. Probabilidad baja (requiere reutilización de PID), daño destructivo, comprobación correcta barata: comparar `readlink("/proc/<pid>/exe")` con la ruta esperada.

---

## V5 — `wifi::forget`/`disconnect`/`enable`/`disable` descartan el resultado de `nmcli`

`rust/services/src/wifi.rs:260`, `:268`, `:272`, `:276`

```rust
pub fn forget(ssid: &str) {
    let _ = run(&["nmcli", "connection", "delete", ssid], 5000);
}
```

Si `nmcli` falla o expira, la UI (`popups/src/network.rs:219`) recarga y la red reaparece como «guardada» sin ningún mensaje: el usuario no distingue «no se pudo borrar el perfil» de «no pasó nada».

---

## V6 — `repair_pending` convierte un fallo de `pacman` en «no hay nada que reparar»

`rust/preferences/src/services/update.rs:458-459`

```rust
let query = churros_services::run(&["pacman", "-Qi"], 30_000).map(|r| r.1).unwrap_or_default();
let sync  = churros_services::run(&["pacman", "-Sl"], 30_000).map(|r| r.1).unwrap_or_default();
```

`run` devuelve `None` tanto en timeout como en error de ejecución; `unwrap_or_default()` lo colapsa a cadena vacía, `repair_candidates` no encuentra nada y la lista sale vacía. Una base de datos de pacman bloqueada se presenta como sistema sano.

---

## V7 — Faltan patrones criptográficos en `.gitignore`

`.gitignore` no cubre `.env`, `*.pem`, `*.key`, `id_*`, `*secret*`, `*.p12`. Hoy no hay ningún secreto versionado (verificado: `scripts/keys/pgp/` contiene solo la clave **pública** `155DC67D…C2834999.asc`, y la clave minisign de `churros-release.pubkey` es pública por diseño), así que es higiene pura: cierra la clase de error antes de que ocurra.

---

## V8 — `churros-update.service` desatendido sin `TimeoutStartSec`

`archiso/airootfs/etc/systemd/system/churros-update.service:7-8`

```ini
Type=oneshot
ExecStart=/usr/local/bin/churros-update-auto
```

`Type=oneshot` sin `TimeoutStartSec` hereda `infinity`. El script ejecuta `pacman -Syu --noconfirm` y `flatpak update`. Un pacman bloqueado por lock o una red colgada dejan la unidad en `activating` indefinidamente, y mientras tanto el timer no vuelve a disparar. Añadir `TimeoutStartSec=2h` acota el daño sin interrumpir una actualización real. (No hay `Restart=` en ninguna unidad del árbol, así que no existe riesgo de bucle de arranque.)

---

## V9 — Comentario obsoleto en `iso.yml` y nombre de artefacto compartido entre PR y nocturno

`.github/workflows/iso.yml:164-165` frente a `:22` y `:170`

```yaml
      # Este workflow ya no corre en pull_request, así que no hace falta filtrar
      # el evento: schedule y workflow_dispatch suben la ISO y su SHA256SUMS.
```

El `on:` de ese mismo fichero (`:22-31`) **sí** incluye `pull_request` con filtro de rutas. El comentario afirma lo contrario de lo que hace el fichero.

Además el artefacto se llama `churros-${{ matrix.edition }}-x86_64-iso` (`:170`), sin SHA ni id de ejecución: la ISO de una PR y la nocturna caen en el mismo espacio de nombres, y quien la descargue puede creer que es la de `main`. Añadir `${{ github.sha }}` o `${{ github.event_name }}` al nombre resuelve ambas cosas.

---

## 2. Lo verificado que **no** es un defecto

Se comprobaron y se descartaron explícitamente, para que nadie las «arregle» por error:

| Hipótesis | Resultado |
|---|---|
| Secretos o claves privadas versionadas | **Ninguno.** `scripts/keys/pgp/` es solo clave pública; `churros-release.pubkey` es la clave pública de minisign |
| `pull_request_target` / `permissions: write-all` | **Ausentes** en los 10 workflows |
| `workflow_run` con checkout del código de la PR | **No existe.** `coderabbit-fix-ci.yml` no hace checkout y solo publica un comentario |
| Regla polkit con comodín de nombre o basename | **No.** Ancla rutas absolutas y argv exacto, y exige `user == root` |
| `[churros]` en el `pacman.conf` del sistema instalado | **Se elimina** en `shellprocess-cleanup.conf:45` (probado con el comando real: exit 0) |
| `sudoers.d/churros` (NOPASSWD) sobrevive a la instalación | **Se borra** en `shellprocess-cleanup.conf:9` |
| Autologin del Live en el sistema instalado | **Impedido** por `users.conf:19` (`forbidden_names: [root, churros]`, `doAutologin: false`) y `verify-install` |
| `sshd_config.d/10-archiso.conf` (`PermitRootLogin yes`) sobrevive | **Se borra** en `shellprocess-cleanup.conf:27`. Un informe previo lo dio por vivo: era incorrecto |
| Timer de actualización duplicado en escritorio | **No.** El timer de sistema solo se habilita en la edición server (`configure-server:97`), que además elimina el de usuario (`:112-114`) |
| Secuencia de Calamares | **Correcta.** `boot-nocow` antes de `unpackfs`, `pacman-init` antes de `fix-boot`, `grub-theme` tras `bootloader`, `post-install` antes de `umount` |
| `file_permissions` incoherente con el árbol | **Coherente** (42 entradas contrastadas contra el disco; las 5 de binarios Rust los inyecta `build-rust.sh`) |
| Inyección de comandos en `Command::new` | **Sin hallazgos.** Los tres usos de shell son correctos: `welcome/src/actions.rs:76` evita `sh -c` a propósito, `lock_screen.rs:166` cita con `sh_quote`, `cursor.rs:77` ejecuta un script constante |
| `settings.rs:124` (`as_object_mut().unwrap()`) | **Protegido**: la rama anterior acaba de insertar `Value::Object` |

---

## 3. Cobertura: por qué estos issues conviven con el CI en verde

La suite de ChurrOS es inusualmente buena — modela el sistema entero desde el repo, con 401 mutaciones que verifican que las pruebas no se han debilitado. Los huecos son concretos:

1. **No modela `on: pull_request` + `secrets.*`.** Es R1 y A7. `test_visual_classify.py:361-362` solo comprueba que las claves *aparezcan* referenciadas, nunca que sea seguro.
2. **No modela drop-ins ni symlinks del Live distintos de unidades systemd.** Es A1 y A2. `LiveUnitsTest` solo mira `services-systemd.conf → mask`.
3. **`shellcheck` a nivel `error`** deja fuera los 15 avisos de V1.
4. **No audita CVEs** (A6) ni valida que los repos remotos sean HTTPS (A3).
5. **`known_issues.toml` solo puede registrar deuda que una prueba ya detecta.** Su contrato exige que el `id` coincida con algo que la prueba imprime. Por eso A1, A2 y R1 no pueden estar ahí aunque se sepan: el libro de deuda refleja lo que el CI ve, no lo que se sabe roto.

---

## 4. Orden de corrección sugerido

1. **R1** (rotar claves + mover la clasificación fuera del contexto de PR) — es el único con exposición de credenciales en curso.
2. **R2** (devolver `Result` y no borrar antes de copiar) — pérdida de datos del usuario.
3. **R3** (normalizar `read_config`) — crash de una app que se distribuye.
4. **A1** y **A2** juntos: una sola entrada de limpieza + el test que recorre `*.conf.d` y `system-generators/`.
5. **A4** y **A5**: UX y concurrencia de popups.
6. **A3**, **A6**, **A7**: cadena de suministro y visibilidad del CI.
7. **Verdes** en cualquier momento; **V1** es el de mejor relación esfuerzo/beneficio porque a partir de ahí el resto se detecta solo.

Cada corrección debería llegar con su prueba y su mutación en `tests/mutations/mutations.d/`, como exige `AGENTS.md`, y la de R1 con la rotación de claves en el mismo cambio.

---

## 5. Limitaciones de esta auditoría

Se declaran para que el informe se lea con el peso correcto:

- **No se compiló el workspace Rust.** `gtk4` no está instalado en la máquina de auditoría y `cargo build` lo exige. Todo lo relativo a Rust es análisis estático por lectura, no ejecución. R3 está confirmado por lectura del código y por la alcanzabilidad de los callbacks, pero **no se reprodujo el crash ejecutando la app**.
- **No se construyó la ISO ni se arrancó la sesión Live.** Los hallazgos del instalador (A1, A2) se basan en el contenido del airootfs y en la ausencia de limpieza, no en una instalación real.
- **No se pudo verificar `airootfs.sha512`.** `shellprocess-boot-nocow.conf:13` valida el sha512 del squashfs antes de `unpackfs`; `tests/iso/check_iso.py:277-281` comprueba el mismo fichero sobre ISOs construidas, y ambas referencias son coherentes entre sí, así que se asume correcto. Confirmarlo requiere una ISO real.
- **`zsh` no está instalado**, así que las 2 pruebas de sintaxis `zsh -n` se saltaron también en la baseline.
- Los workflows de QA visual con secretos (R1) no se ejecutaron: su análisis es de configuración.
- **Las líneas citadas son las del commit `5f12aad`.** Se obtuvieron con `grep -n` sobre ese árbol; cualquier cambio posterior en `main` las desplaza. En A4, la lista de líneas de `network.rs` sale de los puntos de llamada localizados con `grep -n`, no de ejecutar la app.

---

*Auditoría realizada sobre `main@5f12aad`. Baseline `./churros check`: 305 pruebas OK, exit 0. Ningún fichero del repositorio fue modificado.*
