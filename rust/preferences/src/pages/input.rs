// ==========================================
// InputPage — teclado, ratón y panel táctil
// (equivalente a pages/input.py)
// ==========================================


use std::process::Command;

use crate::services::niri_config::NiriConfig;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

const LAYOUTS: [&str; 6] = ["es", "us", "latam", "fr", "de", "it"];

fn run_gsettings(args: &[&str]) -> String {
    let mut cmd: Vec<&str> = vec!["gsettings"];
    cmd.extend_from_slice(args);
    let output = churros_services::run(&cmd, 1000)
        .map(|(_, stdout, _)| stdout.trim().to_string())
        .unwrap_or_default();
    output.trim_matches(|c| c == '\'' || c == '"').to_string()
}

fn set_gsettings(schema: &str, key: &str, value: &str) {
    let _ = churros_services::run(&["gsettings", "set", schema, key, value], 1000);
}

pub fn build(navigator: gtk::Stack) -> Page {
    let edition = churros_services::version::edition();
    let is_xfce = edition.contains("xfce");
    let is_kde = edition.contains("kde");

    let subtitle = if is_kde {
        "Gestionado por KDE Plasma"
    } else if is_xfce {
        "Gestionado por XFCE"
    } else {
        "Teclado, raton y panel tactil"
    };

    let page = Page::new(
        Some(navigator),
        "Entrada",
        Some(subtitle),
        None,
    );

    if is_kde {
        let mut group = Group::new("Herramientas de KDE");
        let btn = crate::widgets::row::Row::new(
            "Abrir Ajustes de Ratón y Panel Táctil",
            Some("Lanza preferencias de puntero y touchpad de KDE Plasma"),
            Some("input-mouse-symbolic"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("systemsettings")
                    .arg("kcm_mouse")
                    .spawn();
            })),
        );
        group.add(&btn);
        page.add(group.widget());
        return page;
    }

    if is_xfce {
        let mut group = Group::new("Herramientas externas");
        let btn = crate::widgets::row::Row::new(
            "Abrir Ajustes de Ratón y Panel Táctil",
            Some("Lanza xfce4-mouse-settings"),
            Some("input-mouse-symbolic"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("xfce4-mouse-settings").spawn();
            })),
        );
        group.add(&btn);
        page.add(group.widget());
        return page;
    }

    // ============ Teclado ============
    let mut keyboard = Group::new("Teclado");

    let current = run_gsettings(&[
        "get",
        "org.gnome.desktop.input-sources",
        "sources",
    ]);

    let mut current_layout = "es";
    if current.contains("es") {
        current_layout = "es";
    } else if current.contains("us") {
        current_layout = "us";
    } else if current.contains("latam") {
        current_layout = "latam";
    }

    let layout_combo = ComboRow::new(
        "Disposicion del teclado",
        &LAYOUTS,
        Some(current_layout),
        None,
        None,
        Some(Box::new(|layout| {
            set_gsettings(
                "org.gnome.desktop.input-sources",
                "sources",
                &format!("[('xkb', '{layout}')]"),
            );
            NiriConfig::set_keyboard_layout(&layout);
        })),
    );

    keyboard.add(&layout_combo);
    page.add(keyboard.widget());

    // ============ Ratón ============
    let mut mouse = Group::new("Raton");

    let tap_value = run_gsettings(&[
        "get",
        "org.gnome.desktop.peripherals.touchpad",
        "tap-to-click",
    ]);
    let tap_active = tap_value.to_lowercase().contains("true");

    mouse.add(&SwitchRow::new(
        "Tocar para clic",
        None,
        Some("Raton: clic con un toque"),
        tap_active,
        Some(Box::new(|active| {
            set_gsettings(
                "org.gnome.desktop.peripherals.touchpad",
                "tap-to-click",
                if active { "true" } else { "false" },
            );
        })),
    ));

    page.add(mouse.widget());

    // ============ Velocidad del ratón ============
    let mut speed_group = Group::new("Velocidad");

    let speed_raw = run_gsettings(&[
        "get",
        "org.gnome.desktop.peripherals.mouse",
        "speed",
    ]);
    let speed: f64 = speed_raw.parse().unwrap_or(0.0);

    let speed_slider = SliderRow::new(
        "Velocidad del raton",
        None,
        None,
        -100.0,
        100.0,
        10.0,
        speed * 100.0,
        Some(Box::new(|value| {
            let v = value / 100.0;
            let _ = Command::new("gsettings")
                .args([
                    "set",
                    "org.gnome.desktop.peripherals.mouse",
                    "speed",
                    &v.to_string(),
                ])
                .output();
        })),
    );

    speed_group.add(&speed_slider);
    page.add(speed_group.widget());

    page
}
