// ==========================================
// ConnectivityPage — Wi-Fi y Bluetooth
// (equivalente a pages/connectivity.py)
// ==========================================


use std::cell::RefCell;
use std::rc::Rc;

use gtk::prelude::*;

use crate::services::connectivity::ConnectivityService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

// Datos Send (sin Rc ni widgets) para cargar en thread
#[derive(Default)]
struct WifiData {
    available: bool,
    enabled: bool,
    current: Option<String>,
    networks: Vec<(String, i64, String, bool, bool)>, // ssid, signal, security, connected, saved
}

#[derive(Default)]
struct BtData {
    available: bool,
    enabled: bool,
    devices: Vec<(String, String)>, // name, mac
}

struct ConnectivityData {
    wifi: WifiData,
    bluetooth: BtData,
}

fn load_data() -> ConnectivityData {
    ConnectivityData {
        wifi: WifiData {
            available: ConnectivityService::wifi_available(),
            enabled: ConnectivityService::wifi_enabled(),
            current: ConnectivityService::current_network(),
            networks: ConnectivityService::wifi_networks_full()
                .into_iter()
                .map(|n| (n.ssid, n.signal, n.security, n.connected, n.saved))
                .collect(),
        },
        bluetooth: BtData {
            available: ConnectivityService::bluetooth_available(),
            enabled: ConnectivityService::bluetooth_enabled(),
            devices: ConnectivityService::bluetooth_devices()
                .into_iter()
                .map(|d| (d.name, d.mac))
                .collect(),
        },
    }
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Conectividad",
        Some("Wi-Fi y Bluetooth"),
        None,
    );

    let wifi_group = Rc::new(RefCell::new(Group::new("Wi-Fi")));
    let bluetooth_group = Rc::new(RefCell::new(Group::new("Bluetooth")));

    wifi_group
        .borrow_mut()
        .add(&Row::new("Cargando...", None, None, None, None, None));
    bluetooth_group
        .borrow_mut()
        .add(&Row::new("Cargando...", None, None, None, None, None));

    page.add(wifi_group.borrow().widget());
    page.add(bluetooth_group.borrow().widget());

    // reload: función reutilizable que lanza la carga en thread y repuebla.
    // Se guarda en un Rc para poder pasarla a los callbacks de los switches
    // y a la fila "Recargar redes".
    let reload: Rc<RefCell<Option<Rc<dyn Fn()>>>> = Rc::new(RefCell::new(None));

    let start_load = {
        let wg = Rc::clone(&wifi_group);
        let bg = Rc::clone(&bluetooth_group);
        let reload = Rc::clone(&reload);
        move || {
            let (tx, rx) = std::sync::mpsc::channel::<ConnectivityData>();
            std::thread::spawn(move || {
                let _ = tx.send(load_data());
            });
            let wg = Rc::clone(&wg);
            let bg = Rc::clone(&bg);
            let reload = Rc::clone(&reload);
            glib::timeout_add_local(std::time::Duration::from_millis(100), move || {
                match rx.try_recv() {
                    Ok(data) => {
                        populate(&wg, &bg, data, &reload);
                        glib::ControlFlow::Break
                    }
                    Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
                    Err(std::sync::mpsc::TryRecvError::Disconnected) => glib::ControlFlow::Break,
                }
            });
        }
    };

    *reload.borrow_mut() = Some(Rc::new(start_load.clone()));
    start_load();

    page
}

/// Lanza un reload (recarga de datos) si ya está inicializado.
fn trigger_reload(reload: &Rc<RefCell<Option<Rc<dyn Fn()>>>>) {
    if let Some(f) = reload.borrow().as_ref() {
        f();
    }
}

fn populate(
    wifi_group: &Rc<RefCell<Group>>,
    bluetooth_group: &Rc<RefCell<Group>>,
    data: ConnectivityData,
    reload: &Rc<RefCell<Option<Rc<dyn Fn()>>>>,
) {
    // ============ Wi-Fi ============
    wifi_group.borrow_mut().clear();

    if !data.wifi.available {
        wifi_group.borrow_mut().add(&Row::new(
            "No se encontró un adaptador Wi-Fi",
            None,
            None,
            None,
            None,
            None,
        ));
    } else {
        let wifi_reload = Rc::clone(reload);
        wifi_group.borrow_mut().add(&SwitchRow::new(
            "Activar Wi-Fi",
            None,
            None,
            data.wifi.enabled,
            Some(Box::new(move |active| {
                ConnectivityService::set_wifi(active);
                trigger_reload(&wifi_reload);
            })),
        ));

        if let Some(current) = &data.wifi.current {
            let current_owned = current.clone();
            wifi_group.borrow_mut().add(&Row::new(
                "Red actual",
                Some(&current_owned),
                None,
                None,
                None,
                None,
            ));
        }

        if data.wifi.networks.is_empty() {
            wifi_group.borrow_mut().add(&Row::new(
                "No se encontraron redes",
                None,
                None,
                None,
                None,
                None,
            ));
        } else {
            for (ssid, signal, security, connected, saved) in &data.wifi.networks {
                let mut parts = vec![format!("Señal: {signal}%")];
                if !security.is_empty() {
                    parts.push(security.clone());
                }
                if *connected {
                    parts.push("conectado".to_string());
                } else if *saved {
                    parts.push("guardada".to_string());
                }
                let subtitle = parts.join(" · ");

                let ssid_owned = ssid.clone();
                let security_owned = security.clone();
                let saved = *saved;
                let connected = *connected;
                let row_reload = Rc::clone(reload);
                wifi_group.borrow_mut().add(&Row::new(
                    ssid,
                    Some(&subtitle),
                    None,
                    None,
                    None,
                    Some(Box::new(move |btn| {
                        if connected {
                            return;
                        }
                        let needs_password =
                            !security_owned.is_empty() && security_owned != "--" && !saved;
                        if needs_password {
                            show_password_dialog(btn, ssid_owned.clone(), Rc::clone(&row_reload));
                        } else {
                            connect_wifi(ssid_owned.clone(), None, Rc::clone(&row_reload), None);
                        }
                    })),
                ));
            }
        }

        let rescan_reload = Rc::clone(reload);
        wifi_group.borrow_mut().add(&Row::new(
            "Recargar redes",
            Some("Forzar un nuevo escaneo"),
            None,
            None,
            None,
            Some(Box::new(move |_btn| {
                ConnectivityService::rescan_wifi();
                trigger_reload(&rescan_reload);
            })),
        ));
    }

    // ============ Bluetooth ============
    bluetooth_group.borrow_mut().clear();

    if !data.bluetooth.available {
        bluetooth_group.borrow_mut().add(&Row::new(
            "No se encontró un adaptador Bluetooth",
            None,
            None,
            None,
            None,
            None,
        ));
    } else {
        let bluetooth_reload = Rc::clone(reload);
        bluetooth_group.borrow_mut().add(&SwitchRow::new(
            "Activar Bluetooth",
            None,
            None,
            data.bluetooth.enabled,
            Some(Box::new(move |active| {
                ConnectivityService::set_bluetooth(active);
                trigger_reload(&bluetooth_reload);
            })),
        ));

        if data.bluetooth.devices.is_empty() {
            bluetooth_group.borrow_mut().add(&Row::new(
                "No hay dispositivos",
                None,
                None,
                None,
                None,
                None,
            ));
        } else {
            for (name, mac) in &data.bluetooth.devices {
                bluetooth_group.borrow_mut().add(&Row::new(
                    name,
                    Some(mac),
                    None,
                    None,
                    None,
                    None,
                ));
            }
        }
    }
}

fn parent_window(widget: &impl IsA<gtk::Widget>) -> Option<gtk::Window> {
    widget.root().and_downcast::<gtk::Window>()
}

fn wifi_error_es(err: &str) -> String {
    match err {
        "Password required." => "Se requiere contraseña.".to_string(),
        "Incorrect password." => "Contraseña incorrecta.".to_string(),
        "Unable to connect." => "No se pudo conectar.".to_string(),
        "Unknown error." | "execution error" => "Error desconocido.".to_string(),
        other if other.is_empty() => "No se pudo conectar.".to_string(),
        other => other.to_string(),
    }
}

/// Conecta en un hilo y llama `on_done` en el hilo de GTK.
fn connect_wifi(
    ssid: String,
    password: Option<String>,
    reload: Rc<RefCell<Option<Rc<dyn Fn()>>>>,
    on_done: Option<Box<dyn Fn(bool, String)>>,
) {
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let result = ConnectivityService::wifi_connect(&ssid, password.as_deref());
        let _ = tx.send(result);
    });
    glib::timeout_add_local(std::time::Duration::from_millis(100), move || {
        match rx.try_recv() {
            Ok((ok, err)) => {
                if let Some(cb) = &on_done {
                    cb(ok, err);
                } else {
                    trigger_reload(&reload);
                }
                glib::ControlFlow::Break
            }
            Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(std::sync::mpsc::TryRecvError::Disconnected) => glib::ControlFlow::Break,
        }
    });
}

fn show_password_dialog(
    parent_widget: &impl IsA<gtk::Widget>,
    ssid: String,
    reload: Rc<RefCell<Option<Rc<dyn Fn()>>>>,
) {
    let dialog = gtk::Window::builder()
        .title("Contraseña de Wi-Fi")
        .default_width(420)
        .resizable(false)
        .modal(true)
        .decorated(true)
        .build();
    if let Some(parent) = parent_window(parent_widget) {
        dialog.set_transient_for(Some(&parent));
        if let Some(app) = parent.application() {
            dialog.set_application(Some(&app));
        }
    }

    let vbox = gtk::Box::new(gtk::Orientation::Vertical, 12);
    vbox.set_margin_top(16);
    vbox.set_margin_bottom(16);
    vbox.set_margin_start(16);
    vbox.set_margin_end(16);

    let header = gtk::Label::new(None);
    header.set_markup(&format!(
        "Conectar a <b>{}</b>",
        glib::markup_escape_text(&ssid)
    ));
    header.set_xalign(0.0);
    header.set_wrap(true);
    vbox.append(&header);

    let entry = gtk::PasswordEntry::new();
    entry.set_show_peek_icon(true);
    entry.set_placeholder_text(Some("Contraseña"));
    entry.set_hexpand(true);
    vbox.append(&entry);

    let error = gtk::Label::new(None);
    error.add_css_class("error");
    error.set_xalign(0.0);
    error.set_wrap(true);
    error.set_visible(false);
    vbox.append(&error);

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

    let connect_btn = gtk::Button::with_label("Conectar");
    connect_btn.add_css_class("suggested-action");
    buttons.append(&connect_btn);
    vbox.append(&buttons);

    dialog.set_child(Some(&vbox));
    dialog.set_default_widget(Some(&connect_btn));

    let try_connect = {
        let entry = entry.clone();
        let error = error.clone();
        let connect_btn = connect_btn.clone();
        let dialog = dialog.clone();
        let ssid = ssid.clone();
        let reload = Rc::clone(&reload);
        move || {
            let password = entry.text().to_string();
            if password.is_empty() {
                error.set_label("Introduce la contraseña.");
                error.set_visible(true);
                return;
            }

            error.set_visible(false);
            connect_btn.set_sensitive(false);
            entry.set_sensitive(false);

            let error = error.clone();
            let connect_btn = connect_btn.clone();
            let entry = entry.clone();
            let dialog = dialog.clone();
            let reload = Rc::clone(&reload);
            connect_wifi(
                ssid.clone(),
                Some(password),
                Rc::clone(&reload),
                Some(Box::new(move |ok, err| {
                    if ok {
                        dialog.close();
                        trigger_reload(&reload);
                    } else {
                        error.set_label(&wifi_error_es(&err));
                        error.set_visible(true);
                        connect_btn.set_sensitive(true);
                        entry.set_sensitive(true);
                        entry.grab_focus();
                    }
                })),
            );
        }
    };

    let try_connect_click = try_connect.clone();
    connect_btn.connect_clicked(move |_| try_connect_click());
    entry.connect_activate(move |_| try_connect());

    dialog.present();
    entry.grab_focus();
}
