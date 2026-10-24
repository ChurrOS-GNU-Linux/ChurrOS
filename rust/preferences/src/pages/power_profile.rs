// ==========================================
// PowerProfilePage — modo de energía (perfiles powerprofilesctl)
// (equivalente a pages/power_profile.py)
// ==========================================


use crate::services::power::PowerService;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;

const PROFILES: [(&str, &str, &str); 3] = [
    (
        "performance",
        "Rendimiento",
        "Maximo rendimiento, mas consumo. Ideal para juegos, edicion de video o cargas intensivas.",
    ),
    (
        "balanced",
        "Balanceado",
        "Optima relacion entre rendimiento y consumo. Recomendado para uso diario.",
    ),
    (
        "power-saver",
        "Ahorro de energia",
        "Minimo consumo, reloj reducido. Prolonga la bateria en portatiles.",
    ),
];

fn profile_label(id: &str) -> &str {
    for (pid, label, _) in PROFILES.iter() {
        if pid == &id {
            return label;
        }
    }
    id
}

fn profile_desc(id: &str) -> String {
    for (pid, _, desc) in PROFILES.iter() {
        if pid == &id {
            return desc.to_string();
        }
    }
    format!("Perfil: {id}")
}

/// Governor, planificador y GameMode (no dependen de powerprofilesctl).
fn performance_group() -> Group {
    let mut group = Group::new("Rendimiento y Gaming");
    group.add(&Row::new(
        "Governor de CPU",
        None,
        Some("power.svg"),
        Some(&PowerService::cpu_governor()),
        None,
        None,
    ));
    group.add(&Row::new(
        "Planificador del Kernel",
        None,
        Some("system.svg"),
        Some(&PowerService::kernel_scheduler()),
        None,
        None,
    ));
    group.add(&Row::new(
        "Feral GameMode",
        Some("Optimización automática para juegos (prioridad de CPU/GPU)"),
        Some("applications.svg"),
        Some(&PowerService::gamemode_status()),
        None,
        None,
    ));
    group
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Modo de energia",
        Some("Equilibra rendimiento y consumo"),
        Some("power".to_string()),
    );

    // ============ Estado actual ============
    let available = PowerService::power_profiles_available();

    if available.is_empty() {
        let mut info_group = Group::new("No soportado");
        info_group.add(&Row::new(
            "Perfiles de energia no disponibles",
            Some("powerprofilesctl no encontro perfiles en el hardware actual"),
            Some("power.svg"),
            None,
            None,
            None,
        ));
        page.add(info_group.widget());
        page.add(performance_group().widget());
        return page;
    }

    let current = PowerService::power_profile();
    let desc = profile_desc(&current);

    let mut info_group = Group::new("Perfil actual");
    info_group.add(&Row::new(
        profile_label(&current),
        Some(&desc),
        Some("power.svg"),
        None,
        None,
        None,
    ));
    page.add(info_group.widget());

    // ============ Cambiar perfil ============
    let mut profile_group = Group::new("Cambiar perfil");

    // labels de los perfiles disponibles, en el orden de `available`
    let labels: Vec<String> = available
        .iter()
        .map(|p| profile_label(p).to_string())
        .collect();
    let labels_refs: Vec<&str> = labels.iter().map(|s| s.as_str()).collect();

    let selected = profile_label(&current).to_string();

    let available_clone = available.clone();
    let combo = ComboRow::new(
        "Perfil activo",
        &labels_refs,
        Some(&selected),
        Some("El cambio se aplica de inmediato"),
        None,
        Some(Box::new(move |label| {
            // label -> id inverso
            for p in available_clone.iter() {
                if profile_label(p) == label {
                    PowerService::set_power_profile(p);
                    break;
                }
            }
        })),
    );

    profile_group.add(&combo);
    page.add(profile_group.widget());

    // ============ Rendimiento y Gaming ============
    page.add(performance_group().widget());

    // ============ Advertencias ============
    let msg = match current.as_str() {
        "performance" => Some(
            "Modo rendimiento activo. Ventilador puede subir de revoluciones y la bateria se agota mas rapido.",
        ),
        "power-saver" => Some(
            "Modo ahorro activo. Aplicaciones pesadas pueden responder mas lentas; ideal para alargar la bateria.",
        ),
        _ => None,
    };

    if let Some(msg) = msg {
        let mut warn_group = Group::new("Detalles del perfil");
        warn_group.add(&Row::new(
            "Como afecta al sistema",
            Some(msg),
            None,
            None,
            None,
            None,
        ));
        page.add(warn_group.widget());
    }

    page
}
