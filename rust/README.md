# Workspace Rust

Workspace de Cargo con las aplicaciones propias de ChurrOS, escritas en Rust con `gtk4-rs` (`churros-settings` usa además `libadwaita-rs`, solo para la barra de título).

## Crates

| Crate | Binario | `deploy` | Qué es |
| :--- | :--- | :--- | :--- |
| [`churros-welcome`](churros-welcome/) | `/usr/bin/churros-welcome` | `true` | Pantalla de bienvenida del Live con accesos rápidos. |
| [`churros-tour`](churros-tour/) | `/usr/bin/churros-tour` | `true` | Recorrido del primer inicio: atajos e instalación de apps con `yay`. |
| [`preferences`](preferences/) | `/usr/bin/churros-settings` | `true` | Panel de configuración (14 páginas principales y subpáginas según la edición). |
| [`control-center`](control-center/) | `/usr/bin/churros-control-center` | `true` | Ventana de ajustes rápidos (red, bluetooth, brillo, batería, audio) que abre los popups. |
| [`popups`](popups/) | `/usr/bin/churros-popup` | `true` | Popups de audio, red, bluetooth, brillo, batería y energía, con toggle por PID. |
| [`services`](services/) | librería `churros_services` | `false` | Capa común sobre `wpctl`, `nmcli`, `bluetoothctl`, `brightnessctl`, etc. |

`Cargo.toml` define el workspace y el perfil release (sin LTO, `codegen-units = 16`, `panic = "abort"`, `strip`).

## Compilar y probar

```bash
./churros rust            # cargo build, test y clippy como el CI (en contenedor; --host en este equipo)
./churros rust -p churros-services
```

`./churros build` llama a [`scripts/build-rust.sh`](../scripts/build-rust.sh), que compila en release y copia a `archiso/airootfs/usr/bin/` el binario de cada crate con `deploy = true` en su `Cargo.toml`, y sus `assets/` a `archiso/airootfs/usr/share/churros/<binario>/assets/`. Los binarios no se versionan; los assets copiados tampoco, salvo los de `churros-tour`, que sí están en el repositorio.

## Abrir las apps en el host

```bash
./churros apps doctor
./churros apps welcome
./churros apps settings
./churros apps control-center
./churros apps tour
./churros apps popup audio
```

Este modo usa un HOME temporal, stubs en `PATH` y `CHURROS_DEV=1`, que bloquea y registra en stderr (`[churros-dev] blocked:`) los comandos que cambiarían el sistema. `--live-host` desactiva ese aislamiento. Detalle en [docs/cli.md](../docs/cli.md).

## Documentación

- [Apps](../docs/apps.md): índice de las apps, cómo se abren y dónde dejan logs.
- [Preferences](../docs/preferences.md): `churros-settings`.
- [Popups](../docs/popups.md): `churros-popup`.
- [Services](../docs/services.md): crate `churros_services`.
- [ChurrOS Tour](../docs/churros-tour.md): `churros-tour`.
- [Project Structure](../docs/project-structure.md): dónde encaja `rust/` en el repositorio.
