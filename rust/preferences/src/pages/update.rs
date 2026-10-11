// ==========================================
// UpdatePage — actualizaciones de pacman + flatpak
// ==========================================

use gtk::prelude::*;

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
        Some("Si el sistema no arranca, inicia desde la ISO live y ejecuta: \
              sudo churros-snapshot restore -d /dev/sdX <stamp>"),
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
