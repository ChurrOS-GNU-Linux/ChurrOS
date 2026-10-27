// ==========================================
// BackupPage — exportar/importar/restablecer configuracion
// (equivalente a pages/backup.py)
// ==========================================

use gtk::prelude::*;

use std::cell::RefCell;
use std::path::PathBuf;

use crate::services::backup_service::BackupService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;

// Equivalente a self._status_label (los callbacks son Fn(&gtk::Button),
// asi que el label se comparte via thread_local).
thread_local! {
    static STATUS_LABEL: RefCell<Option<gtk::Label>> = RefCell::new(None);
}

struct WLabel(gtk::Label);
impl crate::widgets::AsWidget for WLabel {
    fn widget(&self) -> &gtk::Widget {
        self.0.upcast_ref()
    }
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Copia de seguridad",
        Some("Exporta, importa o restablece la configuracion de ChurrOS"),
        Some("system".to_string()),
    );

    // ---------- Exportar ----------
    let mut export_group = Group::new("Exportar");

    export_group.add(&Row::new(
        "Exportar configuracion",
        Some("Empaqueta ajustes y dotfiles en un archivo .tar"),
        Some("backup.svg"),
        None,
        None,
        Some(Box::new(on_export)),
    ));

    page.add(export_group.widget());

    // ---------- Importar ----------
    let mut import_group = Group::new("Importar");

    import_group.add(&Row::new(
        "Importar configuracion",
        Some("Restaurar desde un backup de ChurrOS (.tar)"),
        Some("backup.svg"),
        None,
        None,
        Some(Box::new(on_import)),
    ));

    page.add(import_group.widget());

    // ---------- Restablecer ----------
    let mut reset_group = Group::new("Restablecer");

    reset_group.add(&Row::new(
        "Restablecer a valores de fabrica",
        Some("Borra tus cambios y restaura los defaults de ChurrOS"),
        Some("backup.svg"),
        None,
        None,
        Some(Box::new(on_reset)),
    ));

    page.add(reset_group.widget());

    // ---------- Estado ----------
    let mut status_group = Group::new("Estado");

    let status_label = gtk::Label::new(Some("Listo."));
    status_label.set_xalign(0.0);
    status_label.set_wrap(true);
    status_label.add_css_class("row-subtitle");
    status_label.set_margin_start(14);
    status_label.set_margin_end(14);
    status_label.set_margin_top(10);
    status_label.set_margin_bottom(10);

    STATUS_LABEL.with(|s| *s.borrow_mut() = Some(status_label.clone()));

    status_group.add(&WLabel(status_label));
    page.add(status_group.widget());

    page
}

/// Filtro de archivos tar (equivalente al Gtk.FileFilter del Python).
fn tar_filter() -> gtk::FileFilter {
    let filter = gtk::FileFilter::new();
    filter.set_name(Some("Archivo tar"));
    filter.add_pattern("*.tar");
    filter.add_pattern("*.tar.gz");
    filter.add_pattern("*.tar.zst");
    filter
}

/// Equivalente a _set_status.
fn set_status(msg: &str) {
    STATUS_LABEL.with(|s| {
        if let Some(label) = s.borrow().as_ref() {
            label.set_label(msg);
        }
    });
}

/// Dialogo de guardar backup (equivalente a _on_export).
fn on_export(btn: &gtk::Button) {
    let Some(window) = btn.root().and_downcast::<gtk::Window>() else {
        set_status("Error: no se pudo abrir el dialog (pagina sin root).");
        return;
    };

    let dialog = gtk::FileDialog::new();
    dialog.set_title("Guardar backup");

    let filter = tar_filter();
    let filters = gio::ListStore::new::<gtk::FileFilter>();
    filters.append(&filter);
    dialog.set_filters(Some(&filters));
    dialog.set_default_filter(Some(&filter));

    dialog.set_initial_name(Some("churros-backup.tar"));
    let home = churros_services::home_dir();
    dialog.set_initial_folder(Some(&gio::File::for_path(&home)));

    dialog.save(Some(&window), None::<&gio::Cancellable>, move |result| {
        let Ok(file) = result else {
            return;
        };
        let Some(path) = file.path().map(|p| p.to_string_lossy().to_string()) else {
            return;
        };

        set_status("Exportando...");

        match BackupService::export_to(&path) {
            Ok(_) => set_status(&format!("Backup guardado en {path}")),
            Err(e) => set_status(&format!("Error al exportar: {e}")),
        }
    });
}

/// Dialogo de abrir backup (equivalente a _on_import).
fn on_import(btn: &gtk::Button) {
    let Some(window) = btn.root().and_downcast::<gtk::Window>() else {
        set_status("Error: no se pudo abrir el dialog (pagina sin root).");
        return;
    };

    let dialog = gtk::FileDialog::new();
    dialog.set_title("Seleccionar backup de ChurrOS");

    let filter = tar_filter();
    let filters = gio::ListStore::new::<gtk::FileFilter>();
    filters.append(&filter);
    dialog.set_filters(Some(&filters));
    dialog.set_default_filter(Some(&filter));

    let home = churros_services::home_dir();
    dialog.set_initial_folder(Some(&gio::File::for_path(&home)));

    let btn = btn.clone();
    dialog.open(Some(&window), None::<&gio::Cancellable>, move |result| {
        let Ok(file) = result else {
            return;
        };
        let Some(path) = file.path() else {
            return;
        };
        let path = path.to_string_lossy().to_string();
        if !PathBuf::from(&path).is_file() {
            return;
        }
        confirm_import(&btn, &path);
    });
}

/// Confirmacion de importacion (equivalente a _confirm_import).
fn confirm_import(btn: &gtk::Button, path: &str) {
    let confirm = gtk::AlertDialog::builder()
        .message(
            "Esto reemplazara tu configuracion actual con la del archivo seleccionado. ¿Continuar?",
        )
        .modal(true)
        .buttons(["Cancelar", "Importar"])
        .build();

    let window = btn.root().and_downcast::<gtk::Window>();
    let path = path.to_string();

    confirm.choose(window.as_ref(), None::<&gio::Cancellable>, move |result| {
        let Ok(response) = result else {
            return;
        };
        if response != 1 {
            return;
        }

        set_status("Importando...");

        match BackupService::import_from(&path) {
            Ok(_) => set_status(
                "Configuracion importada. Reinicia las apps para ver todos los cambios.",
            ),
            Err(e) => set_status(&format!("Error al importar: {e}")),
        }
    });
}

/// Confirmacion de restablecimiento (equivalente a _on_reset).
fn on_reset(btn: &gtk::Button) {
    let Some(parent) = btn.root().and_downcast::<gtk::Window>() else {
        return;
    };

    let dialog = gtk::Window::builder()
        .transient_for(&parent)
        .modal(true)
        .resizable(false)
        .title("Restablecer")
        .default_width(520)
        .build();
    dialog.add_css_class("reset-confirm");
    if parent.has_css_class("light") {
        dialog.add_css_class("light");
    }

    let root = gtk::Box::new(gtk::Orientation::Vertical, 16);
    root.add_css_class("reset-confirm-surface");
    if parent.has_css_class("light") {
        root.add_css_class("light");
    }
    root.set_width_request(460);
    root.set_margin_top(28);
    root.set_margin_bottom(22);
    root.set_margin_start(28);
    root.set_margin_end(28);

    let heading = gtk::Label::new(Some("Restablecer a valores de fábrica"));
    heading.add_css_class("reset-heading");
    heading.set_wrap(true);
    heading.set_xalign(0.0);
    heading.set_max_width_chars(36);

    let body = gtk::Label::new(Some(
        "Se borraran tus ajustes personales (tema, wallpaper, tipografia, dotfiles de niri/foot/fuzzel/mako/waybar) y se restauraran los defaults de ChurrOS. ¿Continuar?",
    ));
    body.add_css_class("reset-body");
    body.set_wrap(true);
    body.set_wrap_mode(gtk::pango::WrapMode::WordChar);
    body.set_xalign(0.0);
    body.set_max_width_chars(48);

    let actions = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    actions.set_halign(gtk::Align::End);
    actions.set_margin_top(12);

    let cancel = gtk::Button::with_label("Cancelar");
    let confirm = gtk::Button::with_label("Restablecer");
    confirm.add_css_class("destructive-action");
    actions.append(&cancel);
    actions.append(&confirm);

    root.append(&heading);
    root.append(&body);
    root.append(&actions);
    dialog.set_child(Some(&root));

    let dialog_cancel = dialog.clone();
    cancel.connect_clicked(move |_| {
        dialog_cancel.close();
    });

    let dialog_ok = dialog.clone();
    confirm.connect_clicked(move |_| {
        dialog_ok.close();
        set_status("Restableciendo...");
        match BackupService::reset_to_defaults() {
            Ok(_) => set_status(
                "Configuraciones restablecidas a defaults. Reinicia las apps para ver todos los cambios.",
            ),
            Err(e) => set_status(&format!("Error al restablecer: {e}")),
        }
    });

    dialog.present();
}
