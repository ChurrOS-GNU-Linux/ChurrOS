// ==========================================
// UpdatePage — actualizaciones de pacman + flatpak
// ==========================================

use adw::prelude::*;

use std::cell::RefCell;
use std::rc::Rc;
use std::sync::mpsc::TryRecvError;

use crate::services::update::{CheckFailed, Snapshot, UpdateService};
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

const INTERVAL_LABELS: [&str; 3] = ["Cada día", "Cada semana", "Cada mes"];

fn interval_label(id: &str) -> &'static str {
    match id {
        "weekly" => "Cada semana",
        "monthly" => "Cada mes",
        _ => "Cada día",
    }
}

fn interval_id(label: &str) -> Option<&'static str> {
    match label {
        "Cada semana" => Some("weekly"),
        "Cada mes" => Some("monthly"),
        "Cada día" => Some("daily"),
        _ => None,
    }
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Actualizaciones",
        Some("Mantén ChurrOS al día"),
        None,
    );

    let status: Rc<RefCell<Option<Row>>> = Rc::new(RefCell::new(None));
    let churros_status: Rc<RefCell<Option<Row>>> = Rc::new(RefCell::new(None));
    let log_view: Rc<RefCell<Option<gtk::TextView>>> = Rc::new(RefCell::new(None));

    // ---------- Automáticas ----------
    let mut auto_group = Group::new("Actualizaciones automáticas");

    let enabled = UpdateService::enabled();
    auto_group.add(&SwitchRow::new(
        "Activar actualizaciones automáticas",
        Some("system.svg"),
        Some("Actualiza pacman y flatpak según la frecuencia elegida"),
        enabled,
        Some(Box::new(|active| {
            UpdateService::set_enabled(active);
            UpdateService::apply_timer();
        })),
    ));

    let interval = UpdateService::interval();
    let interval_combo = ComboRow::new(
        "Frecuencia",
        &INTERVAL_LABELS,
        Some(interval_label(&interval)),
        Some("Cada cuánto actualizar automáticamente"),
        Some("system.svg"),
        Some(Box::new(|label| {
            if let Some(id) = interval_id(label) {
                UpdateService::set_interval(id);
                UpdateService::apply_timer();
            }
        })),
    );
    auto_group.add(&interval_combo);
    page.add(auto_group.widget());

    // ---------- Acciones ----------
    let mut action_group = Group::new("Acciones");

    let status_rc = Rc::clone(&status);
    let churros_rc = Rc::clone(&churros_status);
    action_group.add(&Row::new(
        "Buscar actualizaciones",
        Some("Comprueba pacman, flatpak y utilidades de ChurrOS"),
        Some("system.svg"),
        None,
        None,
        Some(Box::new(move |_| check_updates(&status_rc, &churros_rc))),
    ));

    let log_rc = Rc::clone(&log_view);
    action_group.add(&Row::new(
        "Actualizar ahora",
        Some("Ejecuta pacman -Syu, flatpak update y utilidades de ChurrOS"),
        Some("system.svg"),
        None,
        None,
        Some(Box::new(move |_| run_update(&log_rc))),
    ));

    let status_row = Row::new(
        "Estado",
        Some("Sin comprobar"),
        Some("system.svg"),
        None,
        None,
        None,
    );
    *status.borrow_mut() = Some(status_row);
    action_group.add(status.borrow().as_ref().unwrap());

    let installed = UpdateService::installed_churros_version();
    let churros_row = Row::new(
        "Utilidades de ChurrOS",
        Some(&format!("v{installed} instalada")),
        Some("system.svg"),
        None,
        None,
        None,
    );
    *churros_status.borrow_mut() = Some(churros_row);
    action_group.add(churros_status.borrow().as_ref().unwrap());
    page.add(action_group.widget());

    // ---------- Rollback (snapshots btrfs) ----------
    let mut rb_group = Group::new("Rollback (snapshots btrfs)");

    let snap_box: Rc<gtk::Box> = Rc::new(gtk::Box::new(gtk::Orientation::Vertical, 0));
    let create_btn = {
        let b = Rc::clone(&snap_box);
        Row::new(
            "Crear snapshot ahora",
            Some("Crea una copia btrfs del sistema antes de cambios importantes"),
            Some("system.svg"),
            None,
            None,
            Some(Box::new(move |_| {
                let b = Rc::clone(&b);
                let (tx, rx) = std::sync::mpsc::channel::<()>();
                std::thread::spawn(move || {
                    let _ = UpdateService::create_snapshot();
                    let _ = tx.send(());
                });
                glib::timeout_add_local(std::time::Duration::from_millis(150), move || {
                    match rx.try_recv() {
                        Ok(()) => {
                            refresh_snapshots(Rc::clone(&b));
                            glib::ControlFlow::Break
                        }
                        Err(TryRecvError::Empty) => glib::ControlFlow::Continue,
                        Err(TryRecvError::Disconnected) => glib::ControlFlow::Break,
                    }
                });
            })),
        )
    };
    rb_group.add(&create_btn);

    let restore_info = Row::new(
        "Cómo restaurar",
        Some("Si el sistema no arranca, inicia desde la ISO live y ejecuta:\n\
              sudo churros-snapshot restore -d /dev/sdXN <stamp>\n\
              /dev/sdXN es la partición btrfs del sistema, no el disco entero: \
              la que lsblk -f muestra como btrfs (p. ej. /dev/sda2 o \
              /dev/nvme0n1p2). Si cifraste el disco, ábrela antes con \
              cryptsetup open y usa /dev/mapper/<nombre>.\n\
              <stamp> es el nombre del snapshot en la lista de abajo (p. ej. \
              20260824-163000). Desde la ISO, churros-snapshot list no \
              funciona: monta la partición con mount -o subvolid=5 y cada \
              carpeta de @snapshots es un stamp."),
        Some("system.svg"),
        None,
        None,
        None,
    );
    rb_group.add(&restore_info);

    rb_group.add(snap_box.as_ref().upcast_ref::<gtk::Widget>());
    page.add(rb_group.widget());

    let snap_box_rc = Rc::clone(&snap_box);
    glib::idle_add_local_once(move || refresh_snapshots(snap_box_rc));

    // ---------- Limpieza y almacenamiento ----------
    page.add(build_cleanup_group().widget());

    // ---------- Log ----------
    let mut log_group = Group::new("Registro de actualización");

    let scrolled = gtk::ScrolledWindow::new();
    scrolled.set_min_content_height(260);
    scrolled.set_max_content_height(420);
    scrolled.set_propagate_natural_height(true);

    let text_view = gtk::TextView::new();
    text_view.set_editable(false);
    text_view.set_monospace(true);
    text_view.set_wrap_mode(gtk::WrapMode::Char);
    scrolled.set_child(Some(&text_view));

    *log_view.borrow_mut() = Some(text_view);
    log_group.add(scrolled.upcast_ref::<gtk::Widget>());
    page.add(log_group.widget());

    // Habilitar el timer la primera vez (diferido para no bloquear el arranque).
    glib::idle_add_local_once(|| {
        UpdateService::ensure_timer();
    });

    page
}

/// Ejecuta `work` en un hilo y entrega el resultado a `done` en el hilo de GTK.
fn run_in_background<T, W, D>(work: W, done: D)
where
    T: Send + 'static,
    W: FnOnce() -> T + Send + 'static,
    D: FnOnce(T) + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(work());
    });
    let mut done = Some(done);
    glib::timeout_add_local(std::time::Duration::from_millis(150), move || {
        match rx.try_recv() {
            Ok(value) => {
                if let Some(done) = done.take() {
                    done(value);
                }
                glib::ControlFlow::Break
            }
            Err(TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(TryRecvError::Disconnected) => glib::ControlFlow::Break,
        }
    });
}

/// Fila informativa (sin botón) con título, subtítulo actualizable y acción.
fn cleanup_row(title: &str, subtitle: &str, action: &gtk::Button) -> (gtk::Box, gtk::Label) {
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 14);
    row.set_margin_top(12);
    row.set_margin_bottom(12);
    row.set_margin_start(14);
    row.set_margin_end(14);

    let icon = gtk::Image::from_file(crate::assets::icon_path("system.svg"));
    icon.set_pixel_size(22);
    row.append(&icon);

    let labels = gtk::Box::new(gtk::Orientation::Vertical, 2);
    labels.set_hexpand(true);
    labels.set_valign(gtk::Align::Center);
    let title_label = gtk::Label::builder().label(title).xalign(0.0).build();
    title_label.add_css_class("row-title");
    labels.append(&title_label);
    let subtitle_label = gtk::Label::builder()
        .label(subtitle)
        .xalign(0.0)
        .wrap(true)
        .wrap_mode(gtk::pango::WrapMode::WordChar)
        .build();
    subtitle_label.add_css_class("row-subtitle");
    labels.append(&subtitle_label);
    row.append(&labels);

    action.set_valign(gtk::Align::Center);
    row.append(action);

    (row, subtitle_label)
}

fn build_cleanup_group() -> Group {
    let mut group = Group::new("Limpieza y Almacenamiento");

    // Caché de pacman
    let cache_btn = gtk::Button::with_label("Limpiar caché");
    cache_btn.add_css_class("destructive-action");
    cache_btn.set_sensitive(false);
    let (cache_row, cache_label) =
        cleanup_row("Caché de paquetes Pacman", "Calculando…", &cache_btn);
    group.add(cache_row.upcast_ref::<gtk::Widget>());
    refresh_cache(&cache_label, &cache_btn, None);

    {
        let cache_label = cache_label.clone();
        cache_btn.connect_clicked(move |btn| confirm_clean_cache(btn, &cache_label));
    }

    // Residuos de Flatpak
    let flatpak_btn = gtk::Button::with_label("Limpiar residuos");
    let (flatpak_row, flatpak_label) = cleanup_row(
        "Residuos Flatpak",
        "Runtimes y extensiones que ya no usa ninguna aplicación",
        &flatpak_btn,
    );
    if !churros_services::which("flatpak") {
        flatpak_btn.set_sensitive(false);
        flatpak_label.set_label("Flatpak no está instalado");
    }
    flatpak_btn.connect_clicked(move |btn| {
        btn.set_sensitive(false);
        flatpak_label.set_label("Limpiando residuos de Flatpak…");
        let btn = btn.clone();
        let label = flatpak_label.clone();
        run_in_background(UpdateService::clean_unused_flatpaks, move |result| {
            btn.set_sensitive(true);
            label.set_label(&match result {
                Ok(()) => "Residuos de Flatpak eliminados".to_string(),
                Err(e) => format!("No se pudo limpiar: {e}"),
            });
        });
    });
    group.add(flatpak_row.upcast_ref::<gtk::Widget>());

    group
}

/// Recalcula el espacio recuperable. `prefix` (resultado de una limpieza)
/// se muestra delante del nuevo cálculo.
fn refresh_cache(label: &gtk::Label, button: &gtk::Button, prefix: Option<String>) {
    button.set_sensitive(false);
    if prefix.is_none() {
        label.set_label("Calculando…");
    }
    let label = label.clone();
    let button = button.clone();
    run_in_background(UpdateService::check_cache_cleanup, move |summary| {
        let has_candidates = summary.as_deref().is_some_and(|s| !s.starts_with("Caché al día"));
        let text = summary.unwrap_or_else(|| "No se pudo comprobar (¿falta paccache?)".to_string());
        label.set_label(&match prefix {
            Some(p) => format!("{p}. {text}"),
            None => text,
        });
        button.set_sensitive(has_candidates);
    });
}

fn confirm_clean_cache(button: &gtk::Button, label: &gtk::Label) {
    let dialog = adw::AlertDialog::new(
        Some("¿Limpiar la caché de paquetes?"),
        Some(
            "Solo se borrarán las versiones obsoletas de los paquetes descargados; \
             se conserva la más reciente de cada uno. Las aplicaciones instaladas \
             no se ven afectadas, pero no podrás volver a una versión anterior \
             desde la caché. Se pedirá la contraseña de administrador.",
        ),
    );
    dialog.add_responses(&[("cancel", "Cancelar"), ("clean", "Limpiar caché")]);
    dialog.set_response_appearance("clean", adw::ResponseAppearance::Destructive);
    dialog.set_default_response(Some("cancel"));
    dialog.set_close_response("cancel");

    let button_c = button.clone();
    let label = label.clone();
    dialog.connect_response(None, move |_, response| {
        if response != "clean" {
            return;
        }
        button_c.set_sensitive(false);
        label.set_label("Limpiando caché…");
        let button = button_c.clone();
        let label = label.clone();
        run_in_background(UpdateService::clean_cache, move |result| {
            let prefix = match result {
                Ok(msg) => msg,
                Err(e) => format!("No se pudo limpiar: {e}"),
            };
            refresh_cache(&label, &button, Some(prefix));
        });
    });

    dialog.present(Some(button));
}

/// Recuento de una comprobación, o el aviso de que no se pudo hacer: un error
/// no es "0 actualizaciones" (#137).
fn count_label(count: Result<usize, CheckFailed>) -> String {
    match count {
        Ok(n) => format!("{n} actualizaciones"),
        Err(CheckFailed) => "no se pudo comprobar".to_string(),
    }
}

fn packages_summary(
    pacman: Result<usize, CheckFailed>,
    flatpak: Result<usize, CheckFailed>,
) -> String {
    format!(
        "{} (pacman) · {} (flatpak)",
        count_label(pacman),
        count_label(flatpak)
    )
}

fn churros_summary(check: Result<Option<String>, CheckFailed>, installed: &str) -> String {
    match check {
        Ok(Some(avail)) => format!("v{installed} instalada · v{avail} disponible"),
        Ok(None) => format!("al día (v{installed})"),
        Err(CheckFailed) => {
            format!(
                "v{installed} instalada · no se pudo comprobar (sin conexión o error del servidor)"
            )
        }
    }
}

type CheckResults = (
    Result<usize, CheckFailed>,
    Result<usize, CheckFailed>,
    Result<Option<String>, CheckFailed>,
);

fn check_updates(status: &Rc<RefCell<Option<Row>>>, churros_status: &Rc<RefCell<Option<Row>>>) {
    if let Some(row) = status.borrow().as_ref() {
        row.set_subtitle("Comprobando...");
    }
    if let Some(row) = churros_status.borrow().as_ref() {
        row.set_subtitle("Comprobando...");
    }

    let (tx, rx) = std::sync::mpsc::channel::<CheckResults>();
    std::thread::spawn(move || {
        let p = UpdateService::check_pacman().map(|v| v.len());
        let f = UpdateService::check_flatpak().map(|v| v.len());
        let c = UpdateService::check_churros().map(|u| u.map(|u| u.version));
        let _ = tx.send((p, f, c));
    });

    let status_rc = Rc::clone(status);
    let churros_rc = Rc::clone(churros_status);
    glib::timeout_add_local(std::time::Duration::from_millis(150), move || {
        match rx.try_recv() {
            Ok((p, f, c)) => {
                if let Some(row) = status_rc.borrow().as_ref() {
                    row.set_subtitle(&packages_summary(p, f));
                }
                let installed = UpdateService::installed_churros_version();
                if let Some(row) = churros_rc.borrow().as_ref() {
                    row.set_subtitle(&churros_summary(c, &installed));
                }
                glib::ControlFlow::Break
            }
            Err(TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(TryRecvError::Disconnected) => glib::ControlFlow::Break,
        }
    });
}

fn run_update(log_view: &Rc<RefCell<Option<gtk::TextView>>>) {
    set_log(log_view, "");
    append_log(log_view, "Iniciando actualización...\n");

    let (tx, rx) = std::sync::mpsc::channel::<String>();
    std::thread::spawn(move || {
        let ok_pac = {
            let tx_p = tx.clone();
            UpdateService::update_pacman(&move |line| {
                let _ = tx_p.send(line.to_string());
            })
        };
        let _ = tx.send("\n--- Flatpak ---\n".to_string());
        let ok_flat = {
            let tx_f = tx.clone();
            UpdateService::update_flatpak(&move |line| {
                let _ = tx_f.send(line.to_string());
            })
        };
        let _ = tx.send("\n--- Utilidades de ChurrOS ---\n".to_string());
        let ok_churros = {
            let tx_c = tx.clone();
            UpdateService::update_churros(&move |line| {
                let _ = tx_c.send(line.to_string());
            })
        };
        let summary = if ok_pac && ok_flat && ok_churros {
            "\n[COMPLETADO] Sistema actualizado correctamente.\n"
        } else {
            "\n[ERROR] La actualización no se completó. Si aparece \
             \"Request dismissed\" o \"Not authorized\", se canceló o no se \
             aceptó la contraseña de administrador que pide pkexec.\n"
        };
        let _ = tx.send(summary.to_string());
    });

    let lv = Rc::clone(log_view);
    glib::timeout_add_local(std::time::Duration::from_millis(120), move || {
        loop {
            match rx.try_recv() {
                Ok(line) => append_log(&lv, &line),
                Err(TryRecvError::Empty) => return glib::ControlFlow::Continue,
                Err(TryRecvError::Disconnected) => return glib::ControlFlow::Break,
            }
        }
    });
}

fn set_log(log_view: &Rc<RefCell<Option<gtk::TextView>>>, text: &str) {
    if let Some(view) = log_view.borrow().as_ref() {
        view.buffer().set_text(text);
    }
}

fn append_log(log_view: &Rc<RefCell<Option<gtk::TextView>>>, text: &str) {
    if let Some(view) = log_view.borrow().as_ref() {
        let buffer = view.buffer();
        let mut end = buffer.end_iter();
        buffer.insert(&mut end, text);
        let mut end = buffer.end_iter();
        let _ = view.scroll_to_iter(&mut end, 0.0, false, 0.0, 1.0);
    }
}

// ------------------------------------------------------------ rollback UI

fn refresh_snapshots(snap_box: Rc<gtk::Box>) {
    let (tx, rx) = std::sync::mpsc::channel::<Vec<Snapshot>>();
    std::thread::spawn(move || {
        let list = UpdateService::list_snapshots();
        let _ = tx.send(list);
    });

    glib::timeout_add_local(std::time::Duration::from_millis(150), move || {
        match rx.try_recv() {
            Ok(list) => {
                while let Some(child) = snap_box.first_child() {
                    snap_box.remove(&child);
                }
                if list.is_empty() {
                    let empty = gtk::Label::new(Some("Sin snapshots todavía."));
                    empty.add_css_class("row-subtitle");
                    empty.set_xalign(0.0);
                    empty.set_margin_top(10);
                    empty.set_margin_bottom(10);
                    empty.set_margin_start(14);
                    empty.set_margin_end(14);
                    snap_box.append(&empty);
                } else {
                    for snap in &list {
                        let row = build_snapshot_row(snap, Rc::clone(&snap_box));
                        snap_box.append(row.widget());
                    }
                }
                glib::ControlFlow::Break
            }
            Err(TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(TryRecvError::Disconnected) => glib::ControlFlow::Break,
        }
    });
}

fn build_snapshot_row(snap: &Snapshot, snap_box: Rc<gtk::Box>) -> Row {
    let delete = gtk::Button::with_label("Eliminar");
    delete.add_css_class("flat");
    delete.add_css_class("destructive-action");
    delete.set_halign(gtk::Align::End);

    let stamp = snap.stamp.clone();
    let b = Rc::clone(&snap_box);
    delete.connect_clicked(move |_| {
        let b = Rc::clone(&b);
        let s = stamp.clone();
        let (tx, rx) = std::sync::mpsc::channel::<()>();
        std::thread::spawn(move || {
            let _ = UpdateService::delete_snapshot(&s);
            let _ = tx.send(());
        });
        glib::timeout_add_local(std::time::Duration::from_millis(150), move || {
            match rx.try_recv() {
                Ok(()) => {
                    refresh_snapshots(Rc::clone(&b));
                    glib::ControlFlow::Break
                }
                Err(TryRecvError::Empty) => glib::ControlFlow::Continue,
                Err(TryRecvError::Disconnected) => glib::ControlFlow::Break,
            }
        });
    });

    let subtitle = if snap.date.is_empty() {
        snap.reason.clone()
    } else {
        format!("{} · {}", snap.reason, snap.date)
    };

    Row::new(
        &snap.stamp,
        Some(&subtitle),
        Some("system.svg"),
        None,
        Some(&delete.upcast_ref::<gtk::Widget>()),
        None,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_failed_check_is_not_zero_updates() {
        assert_eq!(
            packages_summary(Ok(3), Ok(0)),
            "3 actualizaciones (pacman) · 0 actualizaciones (flatpak)"
        );
        assert_eq!(
            packages_summary(Err(CheckFailed), Ok(2)),
            "no se pudo comprobar (pacman) · 2 actualizaciones (flatpak)"
        );
    }

    #[test]
    fn a_failed_churros_check_is_not_up_to_date() {
        assert_eq!(churros_summary(Ok(None), "1.2"), "al día (v1.2)");
        assert_eq!(
            churros_summary(Ok(Some("1.3".to_string())), "1.2"),
            "v1.2 instalada · v1.3 disponible"
        );
        assert!(!churros_summary(Err(CheckFailed), "1.2").contains("al día"));
    }
}
