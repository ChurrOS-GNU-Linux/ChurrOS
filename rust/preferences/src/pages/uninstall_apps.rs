// ==========================================
// UninstallAppsPage — listar y desinstalar apps (Pacman / Flatpak)
// ==========================================

use adw::prelude::*;

use std::cell::{Cell, RefCell};
use std::rc::{Rc, Weak};
use std::sync::mpsc;
use std::time::Duration;

use crate::services::desktop_apps::{self, AppInfo};
use crate::widgets::group::Group;
use crate::widgets::page::Page;

struct AppRow(gtk::Box);
impl crate::widgets::AsWidget for AppRow {
    fn widget(&self) -> &gtk::Widget {
        self.0.upcast_ref()
    }
}

/// Una app ya construida: los widgets se crean una vez por carga y el
/// filtro solo cambia su visibilidad.
struct Entry {
    app: AppInfo,
    /// Nombre, comentario, ID y paquete en minúsculas (se calcula una vez).
    search_key: String,
    row: gtk::Box,
    /// Separador que `Group::add` pone delante de la fila (ninguno en la primera).
    separator: Option<gtk::Widget>,
    button: gtk::Button,
}

impl Entry {
    fn removable(&self) -> bool {
        removable(&self.app)
    }
}

fn removable(app: &AppInfo) -> bool {
    !app.is_protected && (app.is_flatpak || !app.package_name.is_empty())
}

struct State {
    entries: RefCell<Vec<Entry>>,
    group: RefCell<Group>,
    search: gtk::SearchEntry,
    status: gtk::Label,
    busy: Cell<bool>,
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Desinstalar aplicaciones",
        Some("Buscar y eliminar programas instalados"),
        Some("applications".to_string()),
    );

    let search = gtk::SearchEntry::new();
    search.set_placeholder_text(Some("Buscar aplicaciones…"));
    search.set_hexpand(true);
    page.add(&search);

    let status = gtk::Label::new(Some("Cargando aplicaciones…"));
    status.set_xalign(0.0);
    status.set_wrap(true);
    status.add_css_class("row-subtitle");
    page.add(&status);

    let group = Group::new("Aplicaciones instaladas");
    page.add(group.widget());

    let state = Rc::new(State {
        entries: RefCell::new(Vec::new()),
        group: RefCell::new(group),
        search: search.clone(),
        status,
        busy: Cell::new(false),
    });

    {
        let state = Rc::downgrade(&state);
        search.connect_search_changed(move |_| {
            if let Some(state) = state.upgrade() {
                apply_filter(&state);
            }
        });
    }

    load(&state, None);

    page
}

/// Ejecuta `work` en un hilo y entrega el resultado a `done` en el hilo de GTK.
fn run_in_background<T, W, D>(work: W, done: D)
where
    T: Send + 'static,
    W: FnOnce() -> T + Send + 'static,
    D: FnOnce(T) + 'static,
{
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(work());
    });
    let mut done = Some(done);
    glib::timeout_add_local(Duration::from_millis(50), move || match rx.try_recv() {
        Ok(value) => {
            if let Some(done) = done.take() {
                done(value);
            }
            glib::ControlFlow::Break
        }
        Err(mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
        Err(mpsc::TryRecvError::Disconnected) => glib::ControlFlow::Break,
    });
}

/// Recarga la lista en segundo plano; `message` se muestra al terminar.
fn load(state: &Rc<State>, message: Option<String>) {
    if message.is_none() {
        state.status.set_label("Cargando aplicaciones…");
        state.status.set_visible(true);
    }
    let state = state.clone();
    run_in_background(desktop_apps::list_installed_apps, move |apps| {
        rebuild(&state, apps);
        if let Some(msg) = message {
            state.status.set_label(&msg);
            state.status.set_visible(true);
        }
    });
}

fn search_key(app: &AppInfo) -> String {
    format!("{}\n{}\n{}\n{}", app.name, app.comment, app.id, app.package_name).to_lowercase()
}

/// Reconstruye los widgets tras (re)cargar la lista de apps.
fn rebuild(state: &Rc<State>, apps: Vec<AppInfo>) {
    let mut group = state.group.borrow_mut();
    group.clear();

    let entries = apps
        .into_iter()
        .map(|app| {
            let (row, button) = build_row(state, &app);
            group.add(&AppRow(row.clone()));
            Entry {
                search_key: search_key(&app),
                separator: row.prev_sibling(),
                row,
                button,
                app,
            }
        })
        .collect();
    drop(group);

    *state.entries.borrow_mut() = entries;
    apply_filter(state);
}

/// Muestra solo las filas que coinciden con la búsqueda, sin recrear nada.
fn apply_filter(state: &State) {
    let query = state.search.text().trim().to_lowercase();
    let entries = state.entries.borrow();

    let mut shown = 0;
    for entry in entries.iter() {
        let visible = query.is_empty() || entry.search_key.contains(&query);
        entry.row.set_visible(visible);
        // El separador solo se ve si hay otra fila visible por encima.
        if let Some(sep) = &entry.separator {
            sep.set_visible(visible && shown > 0);
        }
        if visible {
            shown += 1;
        }
    }

    state.group.borrow().widget().set_visible(shown > 0);

    if state.busy.get() {
        return;
    }
    if shown == 0 {
        state.status.set_label(if entries.is_empty() {
            "No se encontraron aplicaciones instaladas."
        } else {
            "Ninguna aplicación coincide con la búsqueda."
        });
        state.status.set_visible(true);
    } else {
        state.status.set_visible(false);
    }
}

/// Activa o desactiva los botones mientras hay una desinstalación en curso.
fn set_busy(state: &State, busy: bool) {
    state.busy.set(busy);
    for entry in state.entries.borrow().iter() {
        entry.button.set_sensitive(!busy && entry.removable());
    }
}

fn app_icon(icon_name: &str) -> gtk::Image {
    const FALLBACK: &str = "application-x-executable";
    // Algunos .desktop ponen "Icon=foo.png": el tema solo conoce "foo".
    let icon_name = if icon_name.starts_with('/') {
        icon_name
    } else {
        icon_name
            .strip_suffix(".png")
            .or_else(|| icon_name.strip_suffix(".svg"))
            .unwrap_or(icon_name)
    };
    let image = if icon_name.starts_with('/') {
        gtk::Image::from_file(icon_name)
    } else {
        let has_icon = !icon_name.is_empty()
            && gtk::gdk::Display::default()
                .map(|d| gtk::IconTheme::for_display(&d).has_icon(icon_name))
                .unwrap_or(false);
        gtk::Image::from_icon_name(if has_icon { icon_name } else { FALLBACK })
    };
    image.set_pixel_size(32);
    image
}

fn build_row(state: &Rc<State>, app: &AppInfo) -> (gtk::Box, gtk::Button) {
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 14);
    row.add_css_class("row");
    row.set_margin_top(10);
    row.set_margin_bottom(10);
    row.set_margin_start(14);
    row.set_margin_end(14);

    row.append(&app_icon(&app.icon_name));

    let labels = gtk::Box::new(gtk::Orientation::Vertical, 2);
    labels.set_hexpand(true);
    labels.set_valign(gtk::Align::Center);

    let title = gtk::Label::builder()
        .label(&app.name)
        .xalign(0.0)
        .ellipsize(gtk::pango::EllipsizeMode::End)
        .build();
    title.add_css_class("row-title");
    labels.append(&title);

    let origin = if app.is_flatpak {
        format!("Flatpak · {}", app.id)
    } else if app.package_name.is_empty() {
        "Sin paquete asociado".to_string()
    } else {
        format!("Pacman · {}", app.package_name)
    };
    let subtitle_text = if app.comment.is_empty() {
        origin
    } else {
        format!("{}\n{}", app.comment, origin)
    };
    let subtitle = gtk::Label::builder()
        .label(&subtitle_text)
        .xalign(0.0)
        .wrap(true)
        .wrap_mode(gtk::pango::WrapMode::WordChar)
        .build();
    subtitle.add_css_class("row-subtitle");
    labels.append(&subtitle);

    row.append(&labels);

    let button = gtk::Button::with_label("Desinstalar");
    button.add_css_class("destructive-action");
    button.set_valign(gtk::Align::Center);
    button.set_sensitive(removable(app) && !state.busy.get());
    if app.is_protected {
        button.set_tooltip_text(Some("Componente esencial del sistema"));
    } else if !removable(app) {
        button.set_tooltip_text(Some("Este lanzador no pertenece a ningún paquete"));
    }

    {
        let state: Weak<State> = Rc::downgrade(state);
        let app = app.clone();
        button.connect_clicked(move |btn| {
            if let Some(state) = state.upgrade() {
                confirm_uninstall(&state, btn, &app);
            }
        });
    }
    row.append(&button);

    (row, button)
}

fn confirm_uninstall(state: &Rc<State>, button: &gtk::Button, app: &AppInfo) {
    if state.busy.get() {
        return;
    }

    let body = if app.is_flatpak {
        format!("Se eliminará la aplicación Flatpak «{}».", app.id)
    } else {
        format!(
            "Se eliminará el paquete «{}» con pacman, junto con las dependencias que ya no use nada más. Se pedirá la contraseña de administrador.",
            app.package_name
        )
    };

    let dialog = adw::AlertDialog::new(Some(&format!("¿Desinstalar {}?", app.name)), Some(&body));
    dialog.add_responses(&[("cancel", "Cancelar"), ("uninstall", "Desinstalar")]);
    dialog.set_response_appearance("uninstall", adw::ResponseAppearance::Destructive);
    dialog.set_default_response(Some("cancel"));
    dialog.set_close_response("cancel");

    let state = state.clone();
    let app = app.clone();
    dialog.connect_response(None, move |_, response| {
        if response == "uninstall" {
            start_uninstall(&state, app.clone());
        }
    });

    dialog.present(Some(button));
}

fn start_uninstall(state: &Rc<State>, app: AppInfo) {
    set_busy(state, true);
    state.status.set_label(&format!("Desinstalando {}…", app.name));
    state.status.set_visible(true);

    let name = app.name.clone();
    let state = state.clone();
    run_in_background(
        move || desktop_apps::uninstall_app(&app),
        move |result| {
            set_busy(&state, false);
            let msg = match result {
                Ok(()) => format!("{name} se desinstaló correctamente."),
                Err(e) => format!("No se pudo desinstalar {name}: {e}"),
            };
            load(&state, Some(msg));
        },
    );
}
