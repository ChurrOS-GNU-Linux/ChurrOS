// ==========================================
// UninstallAppsPage — listar y desinstalar apps (Pacman / Flatpak)
// ==========================================

use adw::prelude::*;

use std::cell::{Cell, RefCell};
use std::rc::Rc;
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

struct State {
    apps: RefCell<Vec<AppInfo>>,
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
        apps: RefCell::new(Vec::new()),
        group: RefCell::new(group),
        search: search.clone(),
        status,
        busy: Cell::new(false),
    });

    {
        let state = state.clone();
        search.connect_search_changed(move |_| render(&state));
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
        *state.apps.borrow_mut() = apps;
        render(&state);
        if let Some(msg) = message {
            state.status.set_label(&msg);
            state.status.set_visible(true);
        }
    });
}

fn matches(app: &AppInfo, query: &str) -> bool {
    query.is_empty()
        || app.name.to_lowercase().contains(query)
        || app.comment.to_lowercase().contains(query)
        || app.id.to_lowercase().contains(query)
        || app.package_name.to_lowercase().contains(query)
}

fn render(state: &Rc<State>) {
    let query = state.search.text().trim().to_lowercase();
    let apps = state.apps.borrow();
    let mut group = state.group.borrow_mut();
    group.clear();

    let mut shown = 0;
    for app in apps.iter().filter(|a| matches(a, &query)) {
        group.add(&AppRow(build_row(state, app)));
        shown += 1;
    }

    if !state.busy.get() {
        if shown == 0 {
            state.status.set_label(if apps.is_empty() {
                "No se encontraron aplicaciones instaladas."
            } else {
                "Ninguna aplicación coincide con la búsqueda."
            });
            state.status.set_visible(true);
        } else {
            state.status.set_visible(false);
        }
    }
    group.widget().set_visible(shown > 0);
}

fn app_icon(icon_name: &str) -> gtk::Image {
    const FALLBACK: &str = "application-x-executable";
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

fn build_row(state: &Rc<State>, app: &AppInfo) -> gtk::Box {
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
    let removable = app.is_flatpak || !app.package_name.is_empty();
    button.set_sensitive(removable && !state.busy.get());
    if !removable {
        button.set_tooltip_text(Some("Este lanzador no pertenece a ningún paquete"));
    }

    {
        let state = state.clone();
        let app = app.clone();
        button.connect_clicked(move |btn| confirm_uninstall(&state, btn, &app));
    }
    row.append(&button);

    row
}

fn confirm_uninstall(state: &Rc<State>, button: &gtk::Button, app: &AppInfo) {
    if state.busy.get() {
        return;
    }

    let body = if app.is_flatpak {
        format!("Se eliminará la aplicación Flatpak «{}».", app.id)
    } else {
        format!(
            "Se eliminará el paquete «{}» con pacman. Se pedirá la contraseña de administrador.",
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
    state.busy.set(true);
    state.status.set_label(&format!("Desinstalando {}…", app.name));
    state.status.set_visible(true);
    render(state); // deshabilita los botones mientras dura

    let name = app.name.clone();
    let state = state.clone();
    run_in_background(
        move || desktop_apps::uninstall_app(&app),
        move |result| {
            state.busy.set(false);
            let msg = match result {
                Ok(()) => format!("{name} se desinstaló correctamente."),
                Err(e) => format!("No se pudo desinstalar {name}: {e}"),
            };
            load(&state, Some(msg));
        },
    );
}
