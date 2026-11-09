// ==========================================
// SleepPage — suspensión automática y cierre de tapa
// (equivalente a pages/sleep.py)
// ==========================================


use gtk::prelude::*;

use crate::services::power::PowerService;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;

const OPTIONS: [(&str, i64); 6] = [
    ("5 minutos", 300),
    ("10 minutos", 600),
    ("15 minutos", 900),
    ("30 minutos", 1800),
    ("1 hora", 3600),
    ("Nunca", 0),
];

const LID_LABELS: [(&str, &str); 6] = [
    ("suspend", "Suspender"),
    ("hibernate", "Hibernar"),
    ("lock", "Bloquear la pantalla"),
    ("blank", "Apagar la pantalla"),
    ("nothing", "No hacer nada"),
    ("shutdown", "Apagar el equipo"),
];

/// Quién aplica estos ajustes en la sesión, o por qué no hacen nada.
pub fn idle_note() -> gtk::Label {
    use crate::services::power::IdleBackend;
    let text = match PowerService::idle_backend() {
        IdleBackend::Noctalia => "Se aplica al momento en Noctalia (inactividad del escritorio).",
        IdleBackend::Xfce => "Se aplica al momento en el gestor de energía de XFCE.",
        IdleBackend::None => {
            "No disponible en esta sesión: ni Noctalia ni el gestor de energía de XFCE están en marcha."
        }
    };
    let label = gtk::Label::new(Some(text));
    label.set_wrap(true);
    label.set_xalign(0.0);
    label.add_css_class("row-subtitle");
    label
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Suspension",
        Some("Suspension automatica y acciones de tapa"),
        Some("power".to_string()),
    );

    // ============ Estado de batería ============
    let has_battery = PowerService::battery_present();
    if has_battery {
        let pct = PowerService::battery_percentage();
        let state = PowerService::battery_state();

        let state_desc = if state.contains("charging") {
            "Cargando"
        } else if state.contains("discharging") {
            "Descargando"
        } else {
            ""
        };

        let value = if pct >= 0 {
            if state_desc.is_empty() {
                format!("{pct:.0}%")
            } else {
                format!("{pct:.0}%  ({state_desc})")
            }
        } else {
            "Desconocido".to_string()
        };

        let mut battery_group = Group::new("Estado de la bateria");
        battery_group.add(&Row::new(
            "Nivel de carga",
            Some("El estado actual influye en el comportamiento de suspension"),
            Some("power.svg"),
            Some(&value),
            None,
            None,
        ));
        page.add(battery_group.widget());
    }

    // ============ Suspensión automática ============
    let mut group = Group::new("Suspension automatica");

    let labels: Vec<&str> = OPTIONS.iter().map(|(l, _)| *l).collect();
    let current = PowerService::sleep_timeout();

    let mut selected = "Nunca";
    for (label, value) in OPTIONS.iter() {
        if current == *value {
            selected = label;
            break;
        }
    }

    let combo = ComboRow::new(
        "Suspender tras",
        &labels,
        Some(selected),
        Some("Inactividad antes de que el sistema entre en suspension"),
        None,
        Some(Box::new(|label| {
            if let Some((_, value)) = OPTIONS.iter().find(|(lbl, _)| *lbl == label) {
                PowerService::set_sleep_timeout(*value);
            }
        })),
    );

    group.add(&combo);
    page.add(group.widget());

    // ============ Cierre de tapa ============
    let mut lid = Group::new("Cierre de tapa");
    if PowerService::lid_action_configurable() {
        let current_action = PowerService::lid_close_action();
        let selected = LID_LABELS
            .iter()
            .find(|(id, _)| *id == current_action)
            .map(|(_, label)| *label)
            .unwrap_or("Suspender");
        let labels: Vec<&str> = LID_LABELS.iter().map(|(_, l)| *l).collect();
        lid.add(&ComboRow::new(
            "Al cerrar la tapa",
            &labels,
            Some(selected),
            None,
            None,
            Some(Box::new(|label| {
                if let Some((id, _)) = LID_LABELS.iter().find(|(_, l)| *l == label) {
                    PowerService::set_lid_close_action(id);
                }
            })),
        ));
    } else {
        // logind decide la tapa en Niri; cambiarlo exige root.
        lid.add(&Row::new(
            "Al cerrar la tapa",
            Some("Suspender: lo decide el sistema (systemd-logind)"),
            Some("power.svg"),
            None,
            None,
            None,
        ));
    }
    page.add(lid.widget());
    page.add(&idle_note());

    page
}
