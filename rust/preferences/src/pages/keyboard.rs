// ==========================================
// KeyboardPage — atajos de teclado de Niri
// (equivalente a pages/keyboard.py)
// ==========================================

use gtk::prelude::*;

use std::rc::{Rc, Weak};

use crate::services::keyboard::{is_valid_key, Bind, KeyboardService};
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;

const ACTION_TYPES: [(&str, &str); 3] = [
    ("spawn", "Ejecutar programa"),
    ("spawn-sh", "Ejecutar shell"),
    ("builtin", "Accion de Niri"),
];

const BUILTIN_ACTIONS: [&str; 19] = [
    "close-window",
    "quit",
    "maximize-column",
    "fullscreen-window",
    "switch-preset-column-width",
    "toggle-window-floating",
    "focus-column-left",
    "focus-column-right",
    "focus-window-up",
    "focus-window-down",
    "move-column-left",
    "move-column-right",
    "move-window-up",
    "move-window-down",
    "show-hotkey-overlay",
    "toggle-overview",
    "screenshot",
    "screenshot-screen",
    "screenshot-window",
];

fn categorize(cmd: &str, bind_type: &str) -> &'static str {
    let c = cmd.to_lowercase();
    let _c = c.as_str();

    if bind_type == "spawn" || bind_type == "spawn-sh" {
        return "Aplicaciones";
    }

    let wm = [
        "close-window",
        "quit",
        "maximize-column",
        "fullscreen-window",
        "switch-preset-column-width",
        "toggle-window-floating",
        "switch-focus-between-floating-and-tiling",
    ];
    if wm.contains(&cmd) {
        return "Ventanas";
    }

    let move_keys = [
        "focus-column-left",
        "focus-column-right",
        "focus-window-up",
        "focus-window-down",
        "move-column-left",
        "move-column-right",
        "move-window-up",
        "move-window-down",
    ];
    if move_keys.contains(&cmd) {
        return "Movimiento";
    }

    if cmd.contains("focus-workspace") || cmd.contains("move-window-to-workspace") {
        return "Workspaces";
    }

    if cmd.contains("screenshot") {
        return "Capturas";
    }

    if cmd.contains("hotkey-overlay") || cmd.contains("toggle-overview") {
        return "Overlays";
    }

    if cmd.contains("battery") || cmd.contains("playerctl") {
        return "Multimedia";
    }

    if ["wpctl", "pamixer", "audio", "mute", "volume"]
        .iter()
        .any(|w| cmd.contains(w))
    {
        return "Audio";
    }

    if cmd.to_lowercase().contains("brightness") {
        return "Multimedia";
    }

    "Niri"
}

fn bind_summary(bind: &Bind) -> String {
    if bind.kind == "spawn" && !bind.command.is_empty() {
        if bind.args.is_empty() {
            bind.command.clone()
        } else {
            format!("{} {}", bind.command, bind.args)
        }
    } else if bind.kind == "spawn-sh" && !bind.command.is_empty() {
        format!("shell: {}", bind.command)
    } else if bind.kind == "builtin" && !bind.command.is_empty() {
        if bind.args.is_empty() {
            bind.command.clone()
        } else {
            format!("{} {}", bind.command, bind.args)
        }
    } else if bind.command.is_empty() {
        "(vacio)".to_string()
    } else {
        bind.command.clone()
    }
}

fn type_label(kind: &str) -> String {
    ACTION_TYPES
        .iter()
        .find(|(t, _)| t == &kind)
        .map(|(_, l)| (*l).to_string())
        .unwrap_or_else(|| kind.to_string())
}

pub fn build(navigator: gtk::Stack) -> Page {
    let edition = churros_services::version::edition();
    let is_xfce = edition.contains("xfce");
    let is_kde = edition.contains("kde");

    let subtitle = if is_kde {
        "Gestionado por KDE Plasma"
    } else if is_xfce {
        "Gestionado por XFCE"
    } else {
        "Modifica los atajos de teclado de Niri"
    };

    let page = Page::new(
        Some(navigator),
        "Atajos de teclado",
        Some(subtitle),
        None,
    );

    if is_kde {
        let mut group = Group::new("Herramientas de KDE");
        let btn = crate::widgets::row::Row::new(
            "Abrir Atajos de Teclado",
            Some("Lanza ajustes de atajos y teclado de KDE Plasma"),
            Some("input-keyboard-symbolic"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("systemsettings")
                    .arg("kcm_keys")
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
            "Abrir Ajustes de Teclado",
            Some("Lanza xfce4-keyboard-settings"),
            Some("input-keyboard-symbolic"),
            None,
            None,
            Some(Box::new(|_| {
                let _ = std::process::Command::new("xfce4-keyboard-settings").spawn();
            })),
        );
        group.add(&btn);
        page.add(group.widget());
        return page;
    }

    // Las callbacks de los diálogos necesitan reconstruir la página al
    // guardar; se les pasa un Weak del Page (que se devuelve por valor).
    let rc = Rc::new(page);
    let weak = Rc::downgrade(&rc);
    build_content(&rc, &weak);

    match Rc::try_unwrap(rc) {
        Ok(page) => page,
        Err(_) => unreachable!("el Page tiene referencias vivas al construir"),
    }
}

fn clear_page(page: &Page) {
    while let Some(child) = page.content.first_child() {
        page.content.remove(&child);
    }
}

fn rebuild(weak: &Weak<Page>) {
    if let Some(page) = weak.upgrade() {
        clear_page(&page);
        build_content(&page, weak);
    }
}

fn show_alert(message: &str) {
    let dialog = gtk::AlertDialog::builder().message(message).build();
    dialog.show(None::<&gtk::Window>);
}

/// Ventana padre desde un widget (transient_for del diálogo).
fn parent_window(widget: &impl IsA<gtk::Widget>) -> Option<gtk::Window> {
    widget.root().and_downcast::<gtk::Window>()
}

fn dialog_window(parent: Option<&gtk::Window>, title: &str) -> gtk::Window {
    let dialog = gtk::Window::builder()
        .title(title)
        .default_width(440)
        .resizable(false)
        .modal(true)
        .decorated(true)
        .build();
    if let Some(p) = parent {
        dialog.set_transient_for(Some(p));
        // Heredar la application del padre: sin esto el app-id de la
        // ventana en Wayland queda vacío y las window-rules de niri
        // (blur, radios) no se le aplican.
        if let Some(app) = p.application() {
            dialog.set_application(Some(&app));
        }
    }
    dialog
}

/// Fila label + entry (diálogos de atajos).
fn field_row(label: &str, entry: &gtk::Entry) -> gtk::Box {
    let box_ = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    let label_widget = gtk::Label::new(Some(label));
    label_widget.set_xalign(0.0);
    label_widget.set_width_chars(16);
    box_.append(&label_widget);
    entry.set_hexpand(true);
    box_.append(entry);
    box_
}

fn edit_bind_dialog(parent: Option<gtk::Window>, bind: Bind, weak: Weak<Page>) {
    let dialog = dialog_window(parent.as_ref(), "Editar atajo");

    let vbox = gtk::Box::new(gtk::Orientation::Vertical, 10);
    vbox.set_margin_top(16);
    vbox.set_margin_bottom(16);
    vbox.set_margin_start(16);
    vbox.set_margin_end(16);

    let header = gtk::Label::new(None);
    header.set_markup("<b>Cambiar atajo</b>");
    header.set_xalign(0.0);
    vbox.append(&header);

    let current = gtk::Label::new(None);
    current.set_markup(&format!(
        "Atajo actual: <b>{}</b>\nAccion: {}",
        bind.key, bind.command
    ));
    current.set_xalign(0.0);
    current.set_wrap(true);
    vbox.append(&current);

    vbox.append(&gtk::Separator::new(gtk::Orientation::Horizontal));

    let key_entry = gtk::Entry::new();
    key_entry.set_placeholder_text(Some("Ej: Mod+Shift+X"));
    key_entry.set_text(&bind.key);
    vbox.append(&field_row("Nuevo atajo:", &key_entry));

    let cmd_entry = gtk::Entry::new();
    cmd_entry.set_text(&bind.command);
    vbox.append(&field_row("Nuevo comando:", &cmd_entry));

    let args_entry = gtk::Entry::new();
    args_entry.set_text(&bind.args);
    vbox.append(&field_row("Argumentos:", &args_entry));

    let buttons = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    buttons.set_halign(gtk::Align::End);

    let cancel_btn = gtk::Button::with_label("Cancelar");
    let dialog_weak = dialog.downgrade();
    cancel_btn.connect_clicked(move |_| {
        if let Some(d) = dialog_weak.upgrade() {
            d.close();
        }
    });
    buttons.append(&cancel_btn);

    let save_btn = gtk::Button::with_label("Guardar");
    save_btn.add_css_class("suggested-action");

    {
        let key_entry = key_entry.clone();
        let cmd_entry = cmd_entry.clone();
        let args_entry = args_entry.clone();
        let dialog_weak = dialog.downgrade();
        let weak = weak.clone();
        save_btn.connect_clicked(move |_| {
            let new_key = key_entry.text().trim().to_string();
            let mut new_cmd = cmd_entry.text().trim().to_string();
            let mut new_args = args_entry.text().trim().to_string();

            if new_key.is_empty() {
                if let Some(d) = dialog_weak.upgrade() {
                    d.close();
                }
                show_alert("Define la nueva combinacion de teclas");
                return;
            }
            if !is_valid_key(&new_key) {
                show_alert(
                    "Combinacion invalida: usa Mod+X, Print, Ctrl+Print, Alt+Print o XF86...",
                );
                return;
            }

            let mut bind_type_new = bind.kind.clone();
            if let Some(rest) = new_cmd.strip_prefix("spawn ") {
                bind_type_new = "spawn".to_string();
                new_cmd = rest.trim().to_string();
                if new_args.is_empty() {
                    if let Some((first, rest_args)) = new_cmd.split_once(' ') {
                        let cmd = first.to_string();
                        new_args = rest_args.to_string();
                        new_cmd = cmd;
                    }
                }
            }

            let ok = if new_key != bind.key {
                KeyboardService::remove_keybind(&bind.key)
                    && KeyboardService::add_keybind(&new_key, &bind_type_new, &new_cmd, &new_args)
            } else {
                KeyboardService::set_keybind(&bind.key, &bind_type_new, &new_cmd, &new_args)
            };

            if let Some(d) = dialog_weak.upgrade() {
                d.close();
            }
            if !ok {
                show_alert("No se pudo guardar el atajo");
            } else {
                rebuild(&weak);
            }
        });
    }
    buttons.append(&save_btn);

    vbox.append(&buttons);
    dialog.set_child(Some(&vbox));
    dialog.present();
}

fn add_bind_dialog(parent: Option<gtk::Window>, weak: Weak<Page>) {
    let dialog = dialog_window(parent.as_ref(), "Nuevo atajo");

    let vbox = gtk::Box::new(gtk::Orientation::Vertical, 10);
    vbox.set_margin_top(16);
    vbox.set_margin_bottom(16);
    vbox.set_margin_start(16);
    vbox.set_margin_end(16);

    let header = gtk::Label::new(None);
    header.set_markup("<b>Nuevo atajo de teclado</b>");
    header.set_xalign(0.0);
    vbox.append(&header);

    vbox.append(&gtk::Separator::new(gtk::Orientation::Horizontal));

    let key_entry = gtk::Entry::new();
    key_entry.set_placeholder_text(Some("Ej: Mod+Shift+X"));
    vbox.append(&field_row("Combinacion:", &key_entry));

    let cmd_entry = gtk::Entry::new();
    cmd_entry.set_placeholder_text(Some("Ej: churros-settings o close-window"));
    vbox.append(&field_row("Comando o accion:", &cmd_entry));

    let args_entry = gtk::Entry::new();
    args_entry.set_placeholder_text(Some("Opcional"));
    vbox.append(&field_row("Argumentos:", &args_entry));

    let buttons = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    buttons.set_halign(gtk::Align::End);

    let cancel_btn = gtk::Button::with_label("Cancelar");
    let dialog_weak = dialog.downgrade();
    cancel_btn.connect_clicked(move |_| {
        if let Some(d) = dialog_weak.upgrade() {
            d.close();
        }
    });
    buttons.append(&cancel_btn);

    let add_btn = gtk::Button::with_label("Agregar");
    add_btn.add_css_class("suggested-action");

    {
        let key_entry = key_entry.clone();
        let cmd_entry = cmd_entry.clone();
        let args_entry = args_entry.clone();
        let dialog_weak = dialog.downgrade();
        let weak = weak.clone();
        add_btn.connect_clicked(move |_| {
            let new_key = key_entry.text().trim().to_string();
            let new_cmd = cmd_entry.text().trim().to_string();
            let new_args = args_entry.text().trim().to_string();

            if new_key.is_empty() || new_cmd.is_empty() {
                if let Some(d) = dialog_weak.upgrade() {
                    d.close();
                }
                show_alert("Define la combinacion y el comando");
                return;
            }
            if !is_valid_key(&new_key) {
                show_alert(
                    "Combinacion invalida: usa Mod+X, Print, Ctrl+Print, Alt+Print o XF86...",
                );
                return;
            }

            let action_type = if BUILTIN_ACTIONS.contains(&new_cmd.as_str()) {
                "builtin"
            } else {
                "spawn"
            };

            let ok = KeyboardService::add_keybind(&new_key, action_type, &new_cmd, &new_args);

            if let Some(d) = dialog_weak.upgrade() {
                d.close();
            }
            if !ok {
                show_alert("No se pudo agregar el atajo");
            } else {
                rebuild(&weak);
            }
        });
    }
    buttons.append(&add_btn);

    vbox.append(&buttons);
    dialog.set_child(Some(&vbox));
    dialog.present();
}

fn build_content(page: &Page, weak: &Weak<Page>) {
    let binds = KeyboardService::get_keybinds();

    let mut hint = Group::new("Info");
    hint.add(&Row::new(
        "Haz clic en un atajo para editarlo",
        Some("Los cambios se guardan en config.kdl al instante"),
        Some("system.svg"),
        None,
        None,
        None,
    ));
    page.add(hint.widget());

    let mut add_group = Group::new("Agregar");
    let add_weak = weak.clone();
    add_group.add(&Row::new(
        "Agregar nuevo atajo",
        Some("Define una nueva combinacion de teclas"),
        Some("system.svg"),
        None,
        None,
        Some(Box::new(move |btn| {
            add_bind_dialog(parent_window(btn), add_weak.clone());
        })),
    ));
    page.add(add_group.widget());

    let mut categories: Vec<(&str, Vec<Bind>)> = [
        "Aplicaciones",
        "Ventanas",
        "Workspaces",
        "Movimiento",
        "Capturas",
        "Overlays",
        "Multimedia",
        "Audio",
        "Niri",
    ]
    .iter()
    .map(|c| (*c, Vec::new()))
    .collect();

    for bind in &binds {
        let cat = categorize(&bind.command, &bind.kind);
        if let Some((_, list)) = categories.iter_mut().find(|(name, _)| name == &cat) {
            list.push(bind.clone());
        }
    }

    for (cat_name, cat_binds) in categories {
        if cat_binds.is_empty() {
            continue;
        }

        let mut group = Group::new(cat_name);
        for bind in &cat_binds {
            let summary = bind_summary(bind);
            let subtitle = type_label(&bind.kind);
            let bind = bind.clone();
            let weak = weak.clone();

            group.add(&Row::new(
                &summary,
                Some(&subtitle),
                Some("system.svg"),
                None,
                None,
                Some(Box::new(move |btn| {
                    edit_bind_dialog(parent_window(btn), bind.clone(), weak.clone());
                })),
            ));
        }
        page.add(group.widget());
    }
}
