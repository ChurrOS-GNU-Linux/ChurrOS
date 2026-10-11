// ==========================================
// AppearancePage — página principal de apariencia
// (equivalente a pages/appearance.py)
// ==========================================

use std::cell::RefCell;
use std::rc::Rc;

use gtk::prelude::*;

use crate::services::niri_config::NiriConfig;
use crate::services::pywal::PywalService;
use crate::services::settings;
use crate::services::theme::ThemeService;
use crate::services::wallpaper::WallpaperService;
use crate::widgets::group::Group;
use crate::widgets::navigation_row;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator.clone()),
        "Apariencia",
        Some("Personaliza el aspecto de ChurrOS"),
        None,
    );

    // feedback_label compartido: los callbacks actualizan el subtítulo en vivo
    let feedback: Rc<RefCell<Option<Row>>> = Rc::new(RefCell::new(None));

    // ============ Tema ============
    let mut theme_group = Group::new("Tema");

    // Modo oscuro
    let dark_active = ThemeService::is_dark();
    let feedback_rc = Rc::clone(&feedback);
    let dark_row = SwitchRow::new(
        "Modo oscuro",
        Some("appearance.svg"),
        Some("Usar el tema oscuro"),
        dark_active,
        Some(Box::new(move |active| {
            ThemeService::set(active);
            set_feedback(
                &feedback_rc,
                if active {
                    "Modo oscuro activado"
                } else {
                    "Modo claro activado"
                },
            );
        })),
    );
    let dark_switch = dark_row.switch.clone();
    theme_group.add(&dark_row);
    // La página se construye una vez: el interruptor no se entera del
    // restablecer si nadie lo mueve. set_active reentra en el callback,
    // y apply() ignora esa reentrada mientras APPLYING está puesto.
    ThemeService::on_change(move |dark| {
        if dark_switch.is_active() != dark {
            dark_switch.set_active(dark);
        }
    });

    // Colores dinámicos (pywal)
    let dynamic_active = settings::get_bool("theme.dynamic_colors", false);
    let feedback_rc = Rc::clone(&feedback);
    theme_group.add(&SwitchRow::new(
        "Colores dinámicos",
        Some("appearance.svg"),
        Some("Generar paleta desde el wallpaper (pywal)"),
        dynamic_active,
        Some(Box::new(move |active| {
            let ok = PywalService::toggle(active);
            set_feedback(
                &feedback_rc,
                if active {
                    if ok {
                        "Colores dinámicos activados"
                    } else {
                        "No se pudo activar (¿pywal instalado y wallpaper válido?)"
                    }
                } else {
                    "Colores dinámicos desactivados"
                },
            );
        })),
    ));

    page.add(theme_group.widget());

    // ============ Fondo de pantalla ============
    let mut wallpaper_group = Group::new("Fondo de pantalla");

    let wallpaper_row = Row::new(
        "Wallpaper actual",
        Some(&wallpaper_subtitle()),
        Some("wallpaper.svg"),
        None,
        None,
        None,
    );
    if let Some(label) = wallpaper_row.subtitle_label().cloned() {
        let navigator_for_wallpaper = navigator.clone();
        navigator_for_wallpaper.connect_visible_child_name_notify(move |stack| {
            if stack.visible_child_name().as_deref() == Some("appearance") {
                label.set_label(&wallpaper_subtitle());
            }
        });
    }
    wallpaper_group.add(&wallpaper_row);

    wallpaper_group.add(&navigation_row::new(
        navigator.clone(),
        "Cambiar fondo",
        "wallpaper.svg",
        "wallpaper",
        Some("Elegir entre los fondos disponibles"),
    ));

    page.add(wallpaper_group.widget());

    let edition = churros_services::version::edition();
    let is_niri = edition.contains("niri");
    let is_kde = edition.contains("kde");
    let is_xfce = edition.contains("xfce");

    // ============ Rendimiento (solo Niri) ============
    if is_niri {
        let mut performance_group = Group::new("Rendimiento");

        let performance_on = NiriConfig::get_performance_mode();
        let feedback_rc = Rc::clone(&feedback);
        performance_group.add(&SwitchRow::new(
            "Modo rendimiento",
            Some("appearance.svg"),
            Some("Desactiva blur y animaciones (mejor rendimiento en hardware modesto)"),
            performance_on,
            Some(Box::new(move |active| {
                NiriConfig::set_performance_mode(active);
                NiriConfig::reload();
                set_feedback(
                    &feedback_rc,
                    if active {
                        "Modo rendimiento activado (blur + animaciones OFF)"
                    } else {
                        "Modo rendimiento desactivado (blur + animaciones ON)"
                    },
                );
            })),
        ));

        page.add(performance_group.widget());

        // ============ Escritorio (solo Niri) ============
        let mut desktop_group = Group::new("Escritorio");

        let animations_on = NiriConfig::get_animations();
        let feedback_rc = Rc::clone(&feedback);
        desktop_group.add(&SwitchRow::new(
            "Animaciones de niri",
            Some("appearance.svg"),
            Some("Desactiva todas las transiciones (mas agil en hardware modesto)"),
            animations_on,
            Some(Box::new(move |active| {
                NiriConfig::set_animations(active);
                NiriConfig::reload();
                set_feedback(
                    &feedback_rc,
                    if active {
                        "Animaciones activadas"
                    } else {
                        "Animaciones desactivadas"
                    },
                );
            })),
        ));

        let prefer_no_csd = NiriConfig::get_prefer_no_csd();
        let feedback_rc = Rc::clone(&feedback);
        desktop_group.add(&SwitchRow::new(
            "Sin decoraciones de cliente (CSD)",
            Some("appearance.svg"),
            Some("Las apps omiten sus propios marcos de ventana"),
            prefer_no_csd,
            Some(Box::new(move |active| {
                NiriConfig::set_prefer_no_csd(active);
                NiriConfig::reload();
                set_feedback(
                    &feedback_rc,
                    if active { "CSD deshabilitado" } else { "CSD permitido" },
                );
            })),
        ));

        page.add(desktop_group.widget());

        // ============ Componentes de UI (solo Niri) ============
        let mut components_group = Group::new("Componentes de UI");

        let mut components = vec![
            (
                "Foot",
                "Terminal: fuente, cursor, padding, bell",
                "terminal.svg",
                "foot",
            ),
            (
                "Fuzzel",
                "Launcher: fuente, layout, iconos",
                "applications.svg",
                "fuzzel",
            ),
        ];
        // Waybar y Mako solo si esta sesión los usa. Con Noctalia, aplicar
        // Waybar lanza una segunda barra y Mako pisa sus notificaciones.
        if churros_services::noctalia::uses_waybar() {
            components.insert(
                0,
                (
                    "Waybar",
                    "Barra superior: posicion, colores y modulos",
                    "waybar.svg",
                    "waybar",
                ),
            );
        }
        if churros_services::noctalia::uses_mako() {
            components.push((
                "Mako",
                "Notificaciones: fuente, colores, posicion, DND",
                "mako.svg",
                "mako",
            ));
        }
        for (title, subtitle, icon, page_name) in components {
            components_group.add(&navigation_row::new(
                navigator.clone(),
                title,
                icon,
                page_name,
                Some(subtitle),
            ));
        }

        page.add(components_group.widget());

        // ============ Compositor (solo Niri) ============
        let mut compositor_group = Group::new("Compositor");

        compositor_group.add(&navigation_row::new(
            navigator.clone(),
            "Niri",
            "niri.svg",
            "niri",
            Some("Layout, bordes, focus-ring, blur, prefer-no-csd"),
        ));

        page.add(compositor_group.widget());

        // ============ Pantalla (solo Niri) ============
        let mut screen_group = Group::new("Pantalla");

        screen_group.add(&navigation_row::new(
            navigator.clone(),
            "Luz nocturna",
            "night_light.svg",
            "night-light",
            Some("Temperatura de color y filtro de luz azul (wlsunset)"),
        ));

        let lock_blurb = if churros_services::noctalia::shell_active() {
            "El bloqueo lo gestiona Noctalia"
        } else {
            "swaylock + swayidle: estilo y bloqueo automatico"
        };
        screen_group.add(&navigation_row::new(
            navigator.clone(),
            "Pantalla de bloqueo",
            "lock_screen.svg",
            "lock-screen",
            Some(lock_blurb),
        ));

        page.add(screen_group.widget());
    } else if is_kde {
        // ============ Pantalla y Bloqueo (KDE Plasma) ============
        let mut kde_screen_group = Group::new("Pantalla y Bloqueo");

        let lock_row = Row::new(
            "Pantalla de bloqueo",
            Some("Configurar tiempo de espera y fondo de bloqueo en KDE"),
            Some("lock_screen.svg"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("systemsettings")
                    .arg("kcm_screenlocker")
                    .spawn();
            })),
        );
        kde_screen_group.add(&lock_row);

        let night_row = Row::new(
            "Color nocturno",
            Some("Configurar filtro de luz azul en Preferencias de KDE"),
            Some("night_light.svg"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("systemsettings")
                    .arg("kcm_nightlight")
                    .spawn();
            })),
        );
        kde_screen_group.add(&night_row);

        page.add(kde_screen_group.widget());
    }

    // ============ Personalización básica ============
    let mut personalization_group = Group::new("Personalización básica");

    for (title, subtitle, icon, page_name) in [
        (
            "Colores",
            "Color de acento (manual o desde paleta)",
            "palette.svg",
            "accent",
        ),
        ("Iconos", "Tema de iconos del sistema", "icons.svg", "icons"),
        ("Cursor", "Tema y tamano del cursor", "cursor.svg", "cursor"),
        (
            "Fuentes",
            "Familia y tamano de fuente del sistema",
            "font.svg",
            "fonts",
        ),
    ] {
        personalization_group.add(&navigation_row::new(
            navigator.clone(),
            title,
            icon,
            page_name,
            Some(subtitle),
        ));
    }

    page.add(personalization_group.widget());

    // ============ Reglas de ventana (solo Niri) ============
    if is_niri {
        let mut window_rules_group = Group::new("Reglas de ventana");

        window_rules_group.add(&navigation_row::new(
            navigator.clone(),
            "Reglas de ventana",
            "window_rules.svg",
            "window-rules",
            Some("Opacidad, floatantes, esquinas, blur por app"),
        ));

        page.add(window_rules_group.widget());
    } else if is_kde {
        let mut kde_group = Group::new("Ajustes del Entorno");
        let sys_row = Row::new(
            "Preferencias del Sistema de KDE",
            Some("Abrir el panel de control completo de Plasma 6"),
            Some("appearance.svg"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("systemsettings").spawn();
            })),
        );
        kde_group.add(&sys_row);
        page.add(kde_group.widget());
    } else if is_xfce {
        let mut xfce_group = Group::new("Ajustes del Entorno");
        let sys_row = Row::new(
            "Gestor de Configuración de XFCE",
            Some("Abrir la configuración completa de XFCE"),
            Some("appearance.svg"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("xfce4-settings-manager").spawn();
            })),
        );
        xfce_group.add(&sys_row);
        page.add(xfce_group.widget());
    }

    // ============ Estado ============
    let mut status_group = Group::new("Estado");

    let feedback_row = Row::new(
        "Cambios en vivo",
        Some("Los cambios se aplican al instante"),
        Some("appearance.svg"),
        None,
        None,
        None,
    );
    *feedback.borrow_mut() = Some(feedback_row);

    status_group.add(feedback.borrow().as_ref().unwrap());
    page.add(status_group.widget());

    page
}

fn wallpaper_subtitle() -> String {
    let current = WallpaperService::current();
    if !current.is_empty() && std::path::Path::new(&current).is_file() {
        format!("Actual: {current}")
    } else {
        "Sin wallpaper configurado".to_string()
    }
}

fn set_feedback(feedback: &Rc<RefCell<Option<Row>>>, text: &str) {
    if let Some(row) = feedback.borrow().as_ref() {
        row.set_subtitle(text);
    }
}
