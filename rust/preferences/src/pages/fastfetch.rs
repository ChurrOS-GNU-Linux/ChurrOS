// ==========================================
// FastfetchPage — personalización de fastfetch
// Logo (ASCII/imagen), módulos, formato de salida.
// ==========================================

use std::cell::RefCell;
use std::rc::Rc;

use gtk::prelude::*;

use crate::services::fastfetch_config::FastfetchConfig;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

// ---- helpers --------------------------------------------------------------

const SEPARATOR_OPTIONS: &[&str] = &[" 󰁔 ", " → ", " : ", " ➜ ", " │ ", " - ", "  "];

const LOGO_COLORS: &[&str] = &[
    "red", "green", "yellow", "blue", "magenta", "cyan", "white", "black",
];

/// Build a file chooser and call `on_file` with the selected path.
fn pick_file(parent: &impl IsA<gtk::Widget>, on_file: impl Fn(String) + 'static) {
    let dialog = gtk::FileDialog::builder()
        .title("Importar logo para fastfetch")
        .build();

    // Only allow images and text (ASCII art) files
    let filters = gio::ListStore::new::<gtk::FileFilter>();
    let ascii_filter = gtk::FileFilter::new();
    ascii_filter.set_name(Some("Archivos ASCII / texto"));
    ascii_filter.add_mime_type("text/plain");
    ascii_filter.add_pattern("*.txt");
    ascii_filter.add_pattern("*.ascii");
    ascii_filter.add_pattern("*.ans");
    filters.append(&ascii_filter);

    let img_filter = gtk::FileFilter::new();
    img_filter.set_name(Some("Imágenes (PNG, JPG, SVG)"));
    img_filter.add_mime_type("image/png");
    img_filter.add_mime_type("image/jpeg");
    img_filter.add_mime_type("image/svg+xml");
    img_filter.add_pattern("*.png");
    img_filter.add_pattern("*.jpg");
    img_filter.add_pattern("*.jpeg");
    img_filter.add_pattern("*.svg");
    filters.append(&img_filter);

    let all_filter = gtk::FileFilter::new();
    all_filter.set_name(Some("Todos los archivos"));
    all_filter.add_pattern("*");
    filters.append(&all_filter);

    dialog.set_filters(Some(&filters));

    // get the window from the widget tree
    let window = parent
        .root()
        .and_then(|r| r.downcast::<gtk::Window>().ok());

    dialog.open(window.as_ref(), None::<&gio::Cancellable>, move |result| {
        if let Ok(file) = result {
            if let Some(path) = file.path() {
                on_file(path.to_string_lossy().to_string());
            }
        }
    });
}

// ---- build ----------------------------------------------------------------

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator.clone()),
        "Fastfetch",
        Some("Personaliza el fetch de tu terminal (logo, módulos, formato)"),
        Some("appearance".to_string()),
    );

    let feedback: Rc<RefCell<Option<Row>>> = Rc::new(RefCell::new(None));

    // ============ Logo ============
    let mut logo_group = Group::new("Logo");

    // Current source display
    let current_source = FastfetchConfig::get_logo_source();
    let source_label = if current_source.is_empty() {
        "Sin logo configurado".to_string()
    } else {
        current_source.clone()
    };

    let source_row = Row::new(
        "Fuente del logo",
        Some(&source_label),
        Some("terminal.svg"),
        None,
        None,
        None,
    );
    let source_subtitle = source_row.subtitle_label().cloned();
    logo_group.add(&source_row);

    // Logo type selector
    let logo_type = FastfetchConfig::get_logo_type();
    let type_labels: Vec<&str> = crate::services::fastfetch_config::LOGO_TYPES
        .iter()
        .map(|(_, label)| *label)
        .collect();
    let current_type_label = crate::services::fastfetch_config::LOGO_TYPES
        .iter()
        .find(|(k, _)| *k == logo_type)
        .map(|(_, l)| *l)
        .unwrap_or("Archivo ASCII / imagen");

    let feedback_rc = Rc::clone(&feedback);
    let source_lbl = source_subtitle.clone();
    let logo_type_combo = ComboRow::new(
        "Tipo de logo",
        &type_labels,
        Some(current_type_label),
        Some("Cómo fastfetch muestra el logo"),
        None,
        Some(Box::new(move |selected: &str| {
            let type_key = crate::services::fastfetch_config::LOGO_TYPES
                .iter()
                .find(|(_, l)| *l == selected)
                .map(|(k, _)| *k)
                .unwrap_or("file");

            let current = FastfetchConfig::get_logo_source();
            FastfetchConfig::set_logo_source(&current, type_key);
            set_feedback(&feedback_rc, &format!("Logo tipo: {selected}"));
            if let Some(lbl) = &source_lbl {
                if type_key == "none" {
                    lbl.set_label("Logo desactivado");
                }
            }
        })),
    );
    logo_group.add(&logo_type_combo);

    // Import file button
    let feedback_rc = Rc::clone(&feedback);
    let source_lbl2 = source_subtitle.clone();
    let import_row = Row::new(
        "Importar archivo",
        Some("Seleccionar un archivo ASCII o imagen como logo"),
        Some("wallpaper.svg"),
        None,
        None,
        Some(Box::new(move |btn| {
            let fb = Rc::clone(&feedback_rc);
            let sl = source_lbl2.clone();
            pick_file(btn, move |path| {
                match FastfetchConfig::import_logo_file(&path) {
                    Ok(dest) => {
                        set_feedback(&fb, &format!("Logo importado: {dest}"));
                        if let Some(lbl) = &sl {
                            lbl.set_label(&dest);
                        }
                    }
                    Err(e) => {
                        set_feedback(&fb, &e);
                    }
                }
            });
        })),
    );
    logo_group.add(&import_row);

    // Logo top padding
    let padding_top = FastfetchConfig::get_logo_padding_top();
    let feedback_rc = Rc::clone(&feedback);
    logo_group.add(&SliderRow::new(
        "Padding superior del logo",
        None,
        Some("Espacio antes del logo (líneas)"),
        0.0,
        10.0,
        1.0,
        padding_top as f64,
        Some(Box::new(move |val| {
            FastfetchConfig::set_logo_padding_top(val as i64);
            set_feedback(&feedback_rc, &format!("Padding: {}", val as i64));
        })),
    ));

    page.add(logo_group.widget());

    // ============ Colores del logo ============
    let mut colors_group = Group::new("Colores del logo");
    let current_colors = FastfetchConfig::get_logo_colors();

    for i in 0..4 {
        let label = format!("Color {}", i + 1);
        let current = if current_colors[i].is_empty() {
            "(por defecto)"
        } else {
            &current_colors[i]
        };
        let cur_sel = if current_colors[i].is_empty() {
            None
        } else {
            Some(current_colors[i].as_str())
        };
        let feedback_rc = Rc::clone(&feedback);
        let idx = i;
        colors_group.add(&ComboRow::new(
            &label,
            LOGO_COLORS,
            cur_sel,
            Some(current),
            None,
            Some(Box::new(move |selected: &str| {
                let mut colors = FastfetchConfig::get_logo_colors();
                colors[idx] = selected.to_string();
                FastfetchConfig::set_logo_colors(&colors);
                set_feedback(
                    &feedback_rc,
                    &format!("Color {} → {selected}", idx + 1),
                );
            })),
        ));
    }

    page.add(colors_group.widget());

    // ============ Formato de salida ============
    let mut display_group = Group::new("Formato de salida");

    // Separator
    let current_sep = FastfetchConfig::get_separator();
    let feedback_rc = Rc::clone(&feedback);
    display_group.add(&ComboRow::new(
        "Separador",
        SEPARATOR_OPTIONS,
        Some(&current_sep),
        Some("Carácter entre la clave y el valor"),
        None,
        Some(Box::new(move |selected: &str| {
            FastfetchConfig::set_separator(selected);
            set_feedback(&feedback_rc, &format!("Separador: \"{selected}\""));
        })),
    ));

    // Key width
    let current_width = FastfetchConfig::get_key_width();
    let feedback_rc = Rc::clone(&feedback);
    display_group.add(&SliderRow::new(
        "Ancho de claves",
        None,
        Some("Espacio reservado para los nombres de las claves"),
        6.0,
        30.0,
        1.0,
        current_width as f64,
        Some(Box::new(move |val| {
            FastfetchConfig::set_key_width(val as i64);
            set_feedback(
                &feedback_rc,
                &format!("Ancho de claves: {}", val as i64),
            );
        })),
    ));

    page.add(display_group.widget());

    // ============ Módulos de información ============
    let mut modules_group = Group::new("Módulos de información");

    let enabled = FastfetchConfig::get_enabled_modules();

    for (mod_type, mod_label) in crate::services::fastfetch_config::ALL_MODULES {
        let is_enabled = enabled.iter().any(|m| m == mod_type);
        let feedback_rc = Rc::clone(&feedback);
        let mod_type_owned = mod_type.to_string();
        let mod_label_owned = mod_label.to_string();
        modules_group.add(&SwitchRow::new(
            mod_label,
            None,
            Some(mod_type),
            is_enabled,
            Some(Box::new(move |active| {
                let mut current = FastfetchConfig::get_enabled_modules();
                if active {
                    if !current.contains(&mod_type_owned) {
                        current.push(mod_type_owned.clone());
                    }
                } else {
                    current.retain(|m| m != &mod_type_owned);
                }
                let refs: Vec<&str> = current.iter().map(|s| s.as_str()).collect();
                FastfetchConfig::set_enabled_modules(&refs);
                set_feedback(
                    &feedback_rc,
                    &format!(
                        "{} {}",
                        mod_label_owned,
                        if active { "activado" } else { "desactivado" }
                    ),
                );
            })),
        ));
    }

    page.add(modules_group.widget());

    // ============ Acciones ============
    let mut actions_group = Group::new("Acciones");

    let feedback_rc = Rc::clone(&feedback);
    actions_group.add(&Row::new(
        "Vista previa",
        Some("Ejecutar fastfetch con la config actual"),
        Some("terminal.svg"),
        None,
        None,
        Some(Box::new(move |_| {
            // Launch fastfetch in a foot terminal so the user can see the result
            let result = std::process::Command::new("foot")
                .args(["--title", "Fastfetch Preview", "-e", "sh", "-c", "fastfetch; echo; echo 'Presiona Enter para cerrar...'; read _"])
                .spawn();
            match result {
                Ok(_) => set_feedback(&feedback_rc, "Vista previa abierta"),
                Err(e) => set_feedback(&feedback_rc, &format!("Error: {e}")),
            }
        })),
    ));

    let feedback_rc = Rc::clone(&feedback);
    let source_lbl3 = source_subtitle;
    actions_group.add(&Row::new(
        "Restablecer a predeterminado",
        Some("Restaurar la configuración de fábrica de ChurrOS"),
        Some("backup.svg"),
        None,
        None,
        Some(Box::new(move |_| {
            FastfetchConfig::reset_to_default();
            set_feedback(&feedback_rc, "Configuración restaurada a la de fábrica");
            if let Some(lbl) = &source_lbl3 {
                lbl.set_label("~/.config/fastfetch/churros-logo");
            }
        })),
    ));

    page.add(actions_group.widget());

    // ============ Estado ============
    let mut status_group = Group::new("Estado");
    let feedback_row = Row::new(
        "Cambios en vivo",
        Some("Los cambios se guardan al instante en config.jsonc"),
        Some("terminal.svg"),
        None,
        None,
        None,
    );
    *feedback.borrow_mut() = Some(feedback_row);
    status_group.add(feedback.borrow().as_ref().unwrap());
    page.add(status_group.widget());

    page
}

fn set_feedback(feedback: &Rc<RefCell<Option<Row>>>, text: &str) {
    if let Some(row) = feedback.borrow().as_ref() {
        row.set_subtitle(text);
    }
}
