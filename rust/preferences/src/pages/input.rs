// ==========================================
// InputPage — teclado, ratón y panel táctil
// (equivalente a pages/input.py)
// ==========================================


use crate::services::niri_config::NiriConfig;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

/// Opciones de niri en input > touchpad que maneja esta página.
pub(crate) const TAP: &str = "tap";
pub(crate) const NATURAL_SCROLL: &str = "natural-scroll";

pub(crate) const LAYOUTS: [&str; 6] = ["es", "us", "latam", "fr", "de", "it"];

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

    let subtitle = if is_xfce {
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

    // ============ Panel táctil ============
    // niri lo lee de config.kdl (input > touchpad), no de gsettings.
    let mut touchpad = Group::new("Panel táctil");

    touchpad.add(&SwitchRow::new(
        "Tocar para hacer clic",
        None,
        Some("Un toque es un clic; dos dedos, clic derecho"),
        NiriConfig::get_touchpad_flag(TAP),
        Some(Box::new(|active| NiriConfig::set_touchpad_flag(TAP, active))),
    ));
    touchpad.add(&SwitchRow::new(
        "Desplazamiento natural",
        None,
        Some("El contenido sigue a los dedos, como en el móvil"),
        NiriConfig::get_touchpad_flag(NATURAL_SCROLL),
        Some(Box::new(|active| NiriConfig::set_touchpad_flag(NATURAL_SCROLL, active))),
    ));

    page.add(touchpad.widget());

    // ============ Velocidad ============
    let mut speed_group = Group::new("Velocidad");

    let speed_slider = SliderRow::new(
        "Velocidad del puntero",
        None,
        Some("Panel táctil y ratón"),
        -100.0,
        100.0,
        10.0,
        NiriConfig::get_pointer_speed() * 100.0,
        Some(Box::new(|value| NiriConfig::set_pointer_speed(value / 100.0))),
    );

    speed_group.add(&speed_slider);
    page.add(speed_group.widget());

    page
}

#[cfg(test)]
mod tests {
    /// Esta página tal cual: en niri el panel táctil y la velocidad se
    /// guardan en config.kdl. gsettings (org.gnome.desktop.peripherals) no
    /// lo lee niri y el interruptor no hacía nada.
    const SOURCE: &str = include_str!("input.rs");

    #[test]
    fn touchpad_and_speed_are_written_to_niri() {
        let code: String = SOURCE.split("#[cfg(test)]").next().unwrap().to_string();
        assert!(
            !code.contains("org.gnome.desktop.peripherals"),
            "[niri-touchpad-gsettings] Entrada vuelve a guardar el panel táctil o la velocidad en gsettings"
        );
        for call in ["set_touchpad_flag(TAP", "set_touchpad_flag(NATURAL_SCROLL", "set_pointer_speed("] {
            assert!(code.contains(call), "[niri-touchpad-gsettings] falta NiriConfig::{call}");
        }
    }
}
