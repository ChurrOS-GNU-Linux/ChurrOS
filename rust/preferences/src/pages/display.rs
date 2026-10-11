// ==========================================
// DisplayPage — configuración de monitores
// (equivalente a pages/display.py)
// ==========================================


use crate::services::display::DisplayService;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

pub fn build(navigator: gtk::Stack) -> Page {
    let edition = churros_services::version::edition();
    let is_xfce = edition.contains("xfce");
    let is_kde = edition.contains("kde");

    let subtitle = if is_kde {
        "Gestionado por KDE Plasma"
    } else if is_xfce {
        "Gestionado por XFCE"
    } else {
        "Configura tus monitores"
    };

    let page = Page::new(
        Some(navigator),
        "Pantalla",
        Some(subtitle),
        None,
    );

    if is_kde {
        let mut group = Group::new("Herramientas de KDE");
        let btn = crate::widgets::row::Row::new(
            "Abrir Ajustes de Pantalla",
            Some("Lanza preferencias de pantalla de KDE Plasma"),
            Some("video-display-symbolic"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("systemsettings")
                    .arg("kcm_kscreen")
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
            "Abrir Ajustes de Pantalla",
            Some("Lanza xfce4-display-settings"),
            Some("video-display-symbolic"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("xfce4-display-settings").spawn();
            })),
        );
        group.add(&btn);
        page.add(group.widget());
        return page;
    }

    let service = DisplayService::new();
    let monitor = service.current_monitor();

    let Some(monitor) = monitor else {
        let mut group = Group::new("Monitor");
        group.add(&Row::new("No se encontró ningún monitor", None, None, None, None, None));
        page.add(group.widget());
        return page;
    };

    // ============ Información ============
    let mut info = Group::new("Monitor");
    info.add(&Row::new(
        &monitor.description,
        Some(&monitor.name),
        None,
        None,
        None,
        None,
    ));
    page.add(info.widget());

    // ============ Configuración ============
    let mut config = Group::new("Configuración");

    let backend = DisplayService::new();
    // Resolución
    let resolutions: Vec<String> = monitor.modes.iter().map(|m| m.label()).collect();
    let mut current = None;
    for mode in &monitor.modes {
        if mode.current {
            current = Some(mode.label());
            break;
        }
    }

    if backend.supports_resolution() && !monitor.modes.is_empty() {
        let res_refs: Vec<&str> = resolutions.iter().map(|s| s.as_str()).collect();
        let monitor_clone = monitor.clone();
        let service_clone = service.clone();
        let combo = ComboRow::new(
            "Resolución",
            &res_refs,
            current.as_deref(),
            None,
            None,
            Some(Box::new(move |value| {
                for mode in &monitor_clone.modes {
                    if mode.label() == value {
                        service_clone.set_resolution(&monitor_clone, mode);
                        break;
                    }
                }
            })),
        );
        config.add(&combo);
    }

    // Escala
    let scales = ["100 %", "125 %", "150 %", "175 %", "200 %"];
    let current_scale = format!("{} %", monitor.scale_percent());
    let monitor_clone = monitor.clone();
    let service_clone = service.clone();
    let combo = ComboRow::new(
        "Escala",
        &scales,
        Some(&current_scale),
        None,
        None,
        Some(Box::new(move |value| {
            let scale = value.replace('%', "").parse::<f64>().unwrap_or(100.0) / 100.0;
            service_clone.set_scale(&monitor_clone, scale);
        })),
    );
    config.add(&combo);

    // Rotación
    let rotations = ["Normal", "90°", "180°", "270°"];
    let current_rotation = monitor.rotation();
    let monitor_clone = monitor.clone();
    let service_clone = service.clone();
    let combo = ComboRow::new(
        "Rotación",
        &rotations,
        Some(&current_rotation),
        None,
        None,
        Some(Box::new(move |value| {
            let mapping = match value {
                "Normal" => "normal",
                "90°" => "90",
                "180°" => "180",
                "270°" => "270",
                _ => "normal",
            };
            service_clone.set_rotation(&monitor_clone, mapping);
        })),
    );
    config.add(&combo);

    // VRR
    if backend.supports_vrr() {
        let monitor_clone = monitor.clone();
        let service_clone = service.clone();
        let sw = SwitchRow::new(
            "Frecuencia variable (VRR)",
            None,
            None,
            monitor.vrr,
            Some(Box::new(move |active| {
                service_clone.set_vrr(&monitor_clone, active);
            })),
        );
        config.add(&sw);
    }

    page.add(config.widget());

    // ============ Brillo ============
    if DisplayService::has_brightness() {
        let mut brightness = Group::new("Brillo");
        let slider = SliderRow::new(
            "Nivel",
            None,
            None,
            0.0,
            100.0,
            1.0,
            DisplayService::brightness(),
            Some(Box::new(|value| {
                let s = DisplayService::new();
                s.set_brightness(value);
            })),
        );
        brightness.add(&slider);
        page.add(brightness.widget());
    }

    page
}
