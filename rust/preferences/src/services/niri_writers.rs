// ==========================================
// Todo lo que churros-settings escribe en ~/.config/niri/config.kdl,
// aplicado a una copia del config del skel: un caso por cada llamada que
// hacen las páginas (pages/), con los extremos de sus controles.
//
// Aquí se comprueba que cada caso escribe (o rechaza) lo que debe y que no
// se lleva por delante nodos de primer nivel que no le tocan (add_keybind
// cortaba los spawn-at-startup que van detrás de binds, y el tamaño del
// cursor el environment de delante: niri lo da por bueno), y que guardar
// sin tocar nada deja config.kdl byte a byte igual
// (set_keybind perdía allow-when-locked y los argumentos de spawn a partir
// del segundo). Con CHURROS_NIRI_WRITERS_OUT=<dir> deja además cada
// resultado en <dir> y la lista en <dir>/cases.json;
// tests/container/test_niri_config.py pasa `niri validate` por cada uno.
// niri rechaza el config entero por un escape inválido, un entero donde
// espera un decimal o un atajo repetido, cosas que este test no ve.
// ==========================================

use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

use super::cursor::set_niri_cursor_size;
use super::keyboard::{is_valid_key, KeyboardService};
use super::niri_config::NiriConfig;
use super::test_support::{rule_form, skel_niri_config, TempHome};
use super::window_rules_service::WindowRulesService;
use crate::pages::input::LAYOUTS;
use crate::pages::keyboard::BUILTIN_ACTIONS;

/// La página de niri: de aquí salen los nombres de animación que escribe.
const NIRI_PAGE: &str = include_str!("../pages/niri.rs");

/// Tecla libre en el skel para los atajos nuevos.
const FREE_KEY: &str = "Mod+Ctrl+Alt+Z";

/// Funciones de los servicios que escriben config.kdl (los de services/
/// que lo nombran y escriben ficheros) que llaman las páginas pero que no
/// lo escriben. Las get_*, list_* y reload ya cuentan como lectoras.
/// tests/container/test_niri_config.py exige que cada llamada de pages/ a
/// esos servicios tenga un caso aquí o esté en esta lista.
const NOT_NIRI_WRITERS: [&str; 4] = [
    "CursorService::available",
    "CursorService::current",
    // Tema del cursor: settings.ini de GTK, gsettings y xfconf, no niri.
    "CursorService::set",
    "CursorService::size",
];

/// Qué tiene que pasar con config.kdl.
#[derive(Clone, Copy, PartialEq)]
enum Expect {
    /// El escritor lo cambia.
    Change,
    /// Guardar sin tocar nada: config.kdl queda byte a byte igual.
    Unchanged,
    /// El escritor se niega (false o Err) y no toca nada.
    Refuse,
}

struct Case {
    /// Funciones de services/ que llama, como las llaman las páginas.
    writers: &'static [&'static str],
    /// La llamada concreta: id del hallazgo en tests/container.
    name: String,
    /// Deja config.kdl en el estado de partida (p. ej. sin animaciones).
    setup: Box<dyn Fn()>,
    /// La llamada; devuelve lo que devuelve el escritor (true si nada).
    write: Box<dyn Fn() -> bool>,
    expect: Expect,
}

fn case(writers: &'static [&'static str], name: impl Into<String>, write: impl Fn() -> bool + 'static) -> Case {
    Case { writers, name: name.into(), setup: Box::new(|| {}), write: Box::new(write), expect: Expect::Change }
}

impl Case {
    fn after(mut self, setup: impl Fn() + 'static) -> Self {
        self.setup = Box::new(setup);
        self
    }

    fn expect(mut self, expect: Expect) -> Self {
        self.expect = expect;
        self
    }
}

/// Cambia config.kdl del HOME actual a mano (estados de partida).
fn edit_config(change: impl Fn(&str) -> String) {
    let path = PathBuf::from(churros_services::home_dir()).join(".config").join("niri").join("config.kdl");
    let text = fs::read_to_string(&path).expect("leer config.kdl");
    fs::write(&path, change(&text)).expect("escribir config.kdl");
}

/// `text` sin el bloque de primer nivel `head { … }`.
fn without_block(text: &str, head: &str) -> String {
    let lines: Vec<&str> = text.lines().collect();
    let start = lines.iter().position(|l| *l == format!("{head} {{")).expect("bloque en el skel");
    let end = start + lines[start..].iter().position(|l| *l == "}").expect("cierre del bloque");
    [&lines[..start], &lines[end + 1..]].concat().join("\n")
}

/// Nodos de primer nivel que algún escritor quita o mueve a propósito.
const MANAGED_TOP_LEVEL: [&str; 4] = ["animations", "blur", "prefer-no-csd", "window-rule"];

/// Cabeceras de los nodos de primer nivel de `text`.
fn top_level_nodes(text: &str) -> Vec<&str> {
    let mut depth = 0usize;
    let mut nodes = Vec::new();
    for line in text.lines().map(str::trim) {
        if line.is_empty() || line.starts_with("//") {
            continue;
        }
        if line.starts_with('}') {
            depth = depth.saturating_sub(1);
        } else {
            if depth == 0 {
                nodes.push(line);
            }
            if line.ends_with('{') {
                depth += 1;
            }
        }
    }
    nodes
}

/// Nombres de animación que pasa pages/niri.rs a set_animation_duration.
fn page_animations() -> Vec<&'static str> {
    let marker = "set_animation_duration(\"";
    let mut names: Vec<&'static str> = NIRI_PAGE
        .match_indices(marker)
        .filter_map(|(at, _)| NIRI_PAGE[at + marker.len()..].split('"').next())
        .collect();
    names.sort();
    names.dedup();
    names
}

fn niri_config_cases() -> Vec<Case> {
    const LAYOUT: &[&str] = &["NiriConfig::set_keyboard_layout"];
    const GAPS: &[&str] = &["NiriConfig::set_gaps"];
    const BORDER: &[&str] = &["NiriConfig::set_border"];
    const FOCUS_RING: &[&str] = &["NiriConfig::set_focus_ring"];
    const BLUR: &[&str] = &["NiriConfig::set_blur"];
    const BLUR_ENABLED: &[&str] = &["NiriConfig::set_blur_enabled"];
    const DURATION: &[&str] = &["NiriConfig::set_animation_duration"];
    const ANIMATIONS: &[&str] = &["NiriConfig::set_animations"];
    const CSD: &[&str] = &["NiriConfig::set_prefer_no_csd"];
    const PERFORMANCE: &[&str] = &["NiriConfig::set_performance_mode"];

    let mut cases = Vec::new();

    // pages/input.rs
    for layout in LAYOUTS {
        let other = if layout == "us" { "es" } else { "us" };
        cases.push(
            case(LAYOUT, format!("NiriConfig::set_keyboard_layout({layout:?})"), move || {
                NiriConfig::set_keyboard_layout(layout);
                true
            })
            .after(move || NiriConfig::set_keyboard_layout(other)),
        );
    }
    cases.push(
        case(LAYOUT, "NiriConfig::set_keyboard_layout(\"es\") sin bloque input", || {
            NiriConfig::set_keyboard_layout("es");
            true
        })
        .after(|| edit_config(|text| without_block(text, "input"))),
    );

    // pages/niri.rs: los extremos de cada control.
    for gaps in [0, 32] {
        cases.push(case(GAPS, format!("NiriConfig::set_gaps({gaps})"), move || {
            NiriConfig::set_gaps(gaps);
            true
        }));
    }
    for (on, width, active, inactive) in [
        (true, 1, "#000000", "#ffffff"),
        (true, 8, "#11223344", "#aabbccdd"),
        (false, 2, "#DE8636", "#766561"),
    ] {
        cases.push(case(BORDER, format!("NiriConfig::set_border({on}, {width}, {active:?}, {inactive:?})"), move || {
            NiriConfig::set_border(on, width, active, inactive);
            true
        }));
    }
    cases.push(
        case(BORDER, "NiriConfig::set_border(true, 2, …) sin bloque border", || {
            NiriConfig::set_border(true, 2, "#DE8636", "#766561");
            true
        })
        .after(|| NiriConfig::set_border(false, 2, "#DE8636", "#766561")),
    );
    for on in [true, false] {
        cases.push(case(FOCUS_RING, format!("NiriConfig::set_focus_ring({on})"), move || {
            NiriConfig::set_focus_ring(on);
            true
        }));
        cases.push(
            case(FOCUS_RING, format!("NiriConfig::set_focus_ring({on}) sin bloque focus-ring"), move || {
                NiriConfig::set_focus_ring(on);
                true
            })
            .after(|| NiriConfig::set_focus_ring(false)),
        );
    }
    for (passes, offset, noise, saturation) in [(0, 0.0, 0.0, 0.0), (6, 16.0, 1.0, 2.0), (2, 2.0, 0.05, 1.2)] {
        cases.push(case(BLUR, format!("NiriConfig::set_blur({passes}, {offset:?}, {noise:?}, {saturation:?})"), move || {
            NiriConfig::set_blur(passes, offset, noise, saturation);
            true
        }));
    }
    cases.push(
        case(BLUR, "NiriConfig::set_blur(2, 2.0, 0.05, 1.2) sin bloque blur", || {
            NiriConfig::set_blur(2, 2.0, 0.05, 1.2);
            true
        })
        .after(|| NiriConfig::set_blur_enabled(false)),
    );
    for name in page_animations() {
        for duration in [0, 1000] {
            cases.push(case(DURATION, format!("NiriConfig::set_animation_duration({name:?}, {duration})"), move || {
                NiriConfig::set_animation_duration(name, duration);
                true
            }));
        }
        cases.push(
            case(DURATION, format!("NiriConfig::set_animation_duration({name:?}, 300) con animaciones apagadas"), move || {
                NiriConfig::set_animation_duration(name, 300);
                true
            })
            .after(|| NiriConfig::set_animations(false)),
        );
    }
    cases.push(case(ANIMATIONS, "NiriConfig::set_animations(false)", || {
        NiriConfig::set_animations(false);
        true
    }));
    cases.push(
        case(ANIMATIONS, "NiriConfig::set_animations(true) tras apagarlas", || {
            NiriConfig::set_animations(true);
            true
        })
        .after(|| NiriConfig::set_animations(false)),
    );
    cases.push(
        case(ANIMATIONS, "NiriConfig::set_animations(true) con duraciones", || {
            NiriConfig::set_animations(true);
            true
        })
        .after(|| {
            NiriConfig::set_animations(false);
            NiriConfig::set_animation_duration("window-open", 300);
        }),
    );

    // pages/appearance.rs (y la de niri)
    cases.push(case(CSD, "NiriConfig::set_prefer_no_csd(false)", || {
        NiriConfig::set_prefer_no_csd(false);
        true
    }));
    cases.push(
        case(CSD, "NiriConfig::set_prefer_no_csd(true) tras quitarlo", || {
            NiriConfig::set_prefer_no_csd(true);
            true
        })
        .after(|| NiriConfig::set_prefer_no_csd(false)),
    );
    cases.push(case(PERFORMANCE, "NiriConfig::set_performance_mode(true)", || {
        NiriConfig::set_performance_mode(true);
        true
    }));
    cases.push(
        case(PERFORMANCE, "NiriConfig::set_performance_mode(false) tras activarlo", || {
            NiriConfig::set_performance_mode(false);
            true
        })
        .after(|| NiriConfig::set_performance_mode(true)),
    );
    cases.push(case(BLUR_ENABLED, "NiriConfig::set_blur_enabled(false)", || {
        NiriConfig::set_blur_enabled(false);
        true
    }));
    cases.push(
        case(BLUR_ENABLED, "NiriConfig::set_blur_enabled(true) tras quitarlo", || {
            NiriConfig::set_blur_enabled(true);
            true
        })
        .after(|| NiriConfig::set_blur_enabled(false)),
    );
    cases
}

/// pages/keyboard.rs: editar, borrar y renombrar cada atajo del skel, y
/// añadir cada acción de la lista de la página.
fn keyboard_cases() -> Vec<Case> {
    const SET: &[&str] = &["KeyboardService::set_keybind"];
    const ADD: &[&str] = &["KeyboardService::add_keybind"];
    const REMOVE: &[&str] = &["KeyboardService::remove_keybind"];
    const RENAME: &[&str] = &["KeyboardService::rename_keybind"];

    let binds = {
        let _home = TempHome::new("niri-writers-binds", &skel_niri_config());
        KeyboardService::get_keybinds()
    };
    assert!(binds.len() > 20, "get_keybinds no lee los atajos del skel");

    let mut cases = Vec::new();
    for bind in binds {
        let (key, kind, command, args) = (bind.key, bind.kind, bind.command, bind.args);
        // Guardar sin cambios.
        let (k, t, c, a) = (key.clone(), kind.clone(), command.clone(), args.clone());
        cases.push(
            case(SET, format!("KeyboardService::set_keybind({key:?}, {kind:?}, {command:?}, {args:?})"), move || {
                KeyboardService::set_keybind(&k, &t, &c, &a)
            })
            .expect(Expect::Unchanged),
        );
        // "spawn notify-send ChurrOS" en el campo de comando.
        let k = key.clone();
        cases.push(case(SET, format!("KeyboardService::set_keybind({key:?}, \"spawn\", \"notify-send\", \"ChurrOS\")"), move || {
            KeyboardService::set_keybind(&k, "spawn", "notify-send", "ChurrOS")
        }));
        let k = key.clone();
        cases.push(case(REMOVE, format!("KeyboardService::remove_keybind({key:?})"), move || {
            KeyboardService::remove_keybind(&k)
        }));
        // Renombrar: lo que hace la página si cambia la tecla; a una libre y
        // a la misma con la tecla en minúsculas (Mod+Return -> Mod+return:
        // para niri, la misma), si la página la acepta.
        let lower = match key.rsplit_once('+') {
            Some((mods, name)) => format!("{mods}+{}", name.to_lowercase()),
            None => key.to_lowercase(),
        };
        for new in [FREE_KEY.to_string(), lower].into_iter().filter(|new| *new != key && is_valid_key(new)) {
            let (k, t, c, a) = (key.clone(), kind.clone(), command.clone(), args.clone());
            cases.push(case(RENAME, format!("KeyboardService::rename_keybind({key:?}, {new:?})"), move || {
                KeyboardService::rename_keybind(&k, &new, &t, &c, &a)
            }));
        }
    }

    for action in BUILTIN_ACTIONS {
        cases.push(case(ADD, format!("KeyboardService::add_keybind({FREE_KEY:?}, \"builtin\", {action:?}, \"\")"), move || {
            KeyboardService::add_keybind(FREE_KEY, "builtin", action, "")
        }));
    }
    for (command, args) in [("notify-send", ""), ("notify-send", r#"dice "hola" \ adiós"#)] {
        cases.push(case(ADD, format!("KeyboardService::add_keybind({FREE_KEY:?}, \"spawn\", {command:?}, {args:?})"), move || {
            KeyboardService::add_keybind(FREE_KEY, "spawn", command, args)
        }));
    }
    // Una tecla que ya tiene atajo: niri rechazaría el config ("duplicate keybind").
    for key in ["Mod+W", "Mod+w"] {
        cases.push(
            case(ADD, format!("KeyboardService::add_keybind({key:?}, \"spawn\", \"foot\", \"\")"), move || {
                KeyboardService::add_keybind(key, "spawn", "foot", "")
            })
            .expect(Expect::Refuse),
        );
    }
    // La misma tecla con otro nombre: para niri Control es Ctrl y Prior es Page_Up.
    for (bound, key) in [("Mod+Ctrl+T", "Mod+Control+T"), ("Mod+Page_Up", "Mod+Prior")] {
        cases.push(
            case(ADD, format!("KeyboardService::add_keybind({key:?}, \"spawn\", \"foot\", \"\") con {bound} puesto"), move || {
                KeyboardService::add_keybind(key, "spawn", "foot", "")
            })
            .after(move || assert!(KeyboardService::add_keybind(bound, "spawn", "foot", ""), "{bound} ya está en el skel"))
            .expect(Expect::Refuse),
        );
    }
    cases.push(
        case(RENAME, "KeyboardService::rename_keybind(\"Mod+W\", \"Mod+Q\") (ya tiene atajo)", || {
            KeyboardService::rename_keybind("Mod+W", "Mod+Q", "spawn", "churros-welcome", "")
        })
        .expect(Expect::Refuse),
    );
    cases
}

/// pages/window_rules.rs: guardar, editar, vaciar y borrar cada regla del
/// skel, y añadir reglas con los extremos del formulario.
fn window_rules_cases() -> Vec<Case> {
    const ADD: &[&str] = &["WindowRulesService::add_rule"];
    const UPDATE: &[&str] = &["WindowRulesService::update_rule"];
    const DELETE: &[&str] = &["WindowRulesService::delete_rule"];

    let rules = {
        let _home = TempHome::new("niri-writers-rules", &skel_niri_config());
        WindowRulesService::list_rules()
    };
    assert!(rules.len() > 5, "list_rules no lee las reglas del skel");

    let mut cases = Vec::new();
    for (index, rule) in rules.iter().enumerate() {
        let id = rule["app_id"].as_str().unwrap_or("").to_string();
        let form = rule_form(rule);
        let mut edited = form.clone();
        for (field, value) in [
            ("opacity", json!(0.5)),
            ("corner_radius", json!(8.0)),
            ("open_floating", json!(true)),
            ("clip_to_geometry", json!(true)),
            ("blur", json!(true)),
        ] {
            edited[field] = value;
        }
        let mut regex = form.clone();
        regex["app_id"] = json!(r"^org\.example\.(Foo|Bar)$");
        regex["title"] = json!(r#""entre comillas" \d+"#);
        let cleared = json!({
            "app_id": "", "title": "", "opacity": null, "corner_radius": null,
            "open_floating": null, "clip_to_geometry": null, "blur": null,
        });
        for (label, updates, expect) in [
            ("sin cambios", form, Expect::Unchanged),
            ("todo activado", edited, Expect::Change),
            ("regex", regex, Expect::Change),
            ("vaciada", cleared, Expect::Change),
        ] {
            cases.push(
                case(UPDATE, format!("WindowRulesService::update_rule({index}: {id}, {label})"), move || {
                    WindowRulesService::update_rule(index, &updates).is_ok()
                })
                .expect(expect),
            );
        }
        cases.push(case(DELETE, format!("WindowRulesService::delete_rule({index}: {id})"), move || {
            WindowRulesService::delete_rule(index).is_ok()
        }));
    }

    type Rule = (&'static str, &'static str, Option<f64>, Option<bool>, Option<f64>, Option<bool>, Option<bool>);
    let added: [Rule; 4] = [
        ("foot", "", None, None, None, None, None),
        (r"^org\.gnome\..*$", r#"Título "con comillas" \d"#, Some(0.0), Some(true), Some(64.0), Some(true), Some(true)),
        ("", "", Some(0.05), None, Some(1.0), None, None),
        ("firefox", "", Some(0.35000000000000003), None, None, Some(true), None),
    ];
    for (app_id, title, opacity, floating, radius, clip, blur) in added {
        cases.push(case(
            ADD,
            format!("WindowRulesService::add_rule({app_id:?}, {title:?}, {opacity:?}, {floating:?}, {radius:?}, {clip:?}, {blur:?})"),
            move || {
                WindowRulesService::add_rule(app_id, title, opacity, floating, radius, clip, blur);
                true
            },
        ));
    }
    cases
}

/// pages/cursor.rs: CursorService::set_size con los extremos del deslizador
/// (8-64). Solo la parte de niri: set_size además llama a gsettings y
/// xfconf-query, que cambiarían la sesión de quien corre el test.
fn cursor_cases() -> Vec<Case> {
    const SIZE: &[&str] = &["CursorService::set_size"];
    let mut cases = Vec::new();
    for size in [8.0, 64.0] {
        cases.push(case(SIZE, format!("CursorService::set_size({size})"), move || {
            set_niri_cursor_size(size);
            true
        }));
    }
    cases.push(
        case(SIZE, "CursorService::set_size(32) sin bloque cursor", || {
            set_niri_cursor_size(32.0);
            true
        })
        .after(|| edit_config(|text| without_block(text, "cursor"))),
    );
    cases
}

/// Las líneas que cambian de `before` a `after` (lo que no comparten al
/// principio ni al final), para los mensajes.
fn changed_lines(before: &str, after: &str) -> String {
    let (old, new): (Vec<&str>, Vec<&str>) = (before.lines().collect(), after.lines().collect());
    let head = old.iter().zip(&new).take_while(|(a, b)| a == b).count();
    let tail = old[head..].iter().rev().zip(new[head..].iter().rev()).take_while(|(a, b)| a == b).count();
    let removed = old[head..old.len() - tail].iter().map(|l| format!("\n    - {l}"));
    let added = new[head..new.len() - tail].iter().map(|l| format!("\n    + {l}"));
    let lines: String = removed.chain(added).collect();
    if lines.is_empty() { "\n    (solo el salto de línea final)".to_string() } else { lines }
}

#[test]
fn every_ui_writer_output() {
    let out = std::env::var_os("CHURROS_NIRI_WRITERS_OUT").map(PathBuf::from);
    if let Some(dir) = &out {
        fs::create_dir_all(dir).expect("crear CHURROS_NIRI_WRITERS_OUT");
    }
    let skel = skel_niri_config();
    let cases: Vec<Case> =
        [niri_config_cases(), keyboard_cases(), window_rules_cases(), cursor_cases()].into_iter().flatten().collect();

    let mut manifest: Vec<Value> = Vec::new();
    let mut problems: Vec<String> = Vec::new();
    for (number, case) in cases.iter().enumerate() {
        let home = TempHome::new("niri-writers", &skel);
        (case.setup)();
        let before = home.read();
        let ok = (case.write)();
        let after = home.read();
        let problem = match case.expect {
            Expect::Change | Expect::Unchanged if !ok => Some("el escritor devolvió un error".to_string()),
            Expect::Change if after == before => Some("config.kdl no cambia: el caso no prueba nada".to_string()),
            Expect::Unchanged if after != before => Some(format!(
                "guardar sin cambios cambia config.kdl (pierde lo que el formulario no modela):{}",
                changed_lines(&before, &after)
            )),
            Expect::Refuse if ok => Some("tenía que negarse y dice que escribió".to_string()),
            Expect::Refuse if after != before => Some("se negó, pero cambió config.kdl".to_string()),
            _ => None,
        };
        if let Some(problem) = problem {
            problems.push(format!("{}: {problem}", case.name));
        }
        // niri validate da por bueno un config al que le falta un trozo.
        let kept = top_level_nodes(&after);
        let lost: Vec<&str> = top_level_nodes(&before)
            .into_iter()
            .filter(|node| !MANAGED_TOP_LEVEL.contains(&node.split_whitespace().next().unwrap_or("")))
            .filter(|node| !kept.contains(node))
            .collect();
        if !lost.is_empty() {
            problems.push(format!("{}: borra nodos de primer nivel que no le tocan: {lost:?}", case.name));
        }
        if let Some(dir) = &out {
            let file = format!("{number:03}.kdl");
            fs::write(dir.join(&file), &after).expect("escribir el resultado");
            manifest.push(json!({"name": case.name, "writers": case.writers, "file": file}));
        }
    }
    if let Some(dir) = &out {
        let text = serde_json::to_string_pretty(&json!({"cases": manifest, "not_writers": NOT_NIRI_WRITERS})).unwrap();
        fs::write(dir.join("cases.json"), text).expect("escribir cases.json");
    }
    assert!(problems.is_empty(), "{} caso(s) mal:\n{}", problems.len(), problems.join("\n"));
}
