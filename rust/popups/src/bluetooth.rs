// ==========================================
// bluetooth.rs — popup de bluetooth (port de bluetooth/window.py + widgets)
// ==========================================

use std::cell::Cell;
use std::rc::Rc;

use churros_services::bluetooth;
use gtk::prelude::*;

use crate::popup::PopupWindow;

pub fn build(app: &gtk::Application) -> PopupWindow {
    let w = PopupWindow::new(app, "Bluetooth", "󰂯", "bluetooth.css");
    w.add(&toggle_widget());
    w.add(&device_list_widget());
    w
}

/// Fila de activación de bluetooth (port de bluetooth/widgets/toggle.py).
fn toggle_widget() -> gtk::Box {
    let box_ = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    box_.add_css_class("bluetooth-toggle");

    let label = gtk::Label::new(Some("Bluetooth"));
    label.set_hexpand(true);
    label.set_xalign(0.0);

    let sw = gtk::Switch::new();

    if bluetooth::is_blocked() {
        sw.set_active(false);
        sw.set_sensitive(false);
        label.set_label("Bluetooth blocked (rfkill)");
        label.add_css_class("blocked");
    } else {
        sw.set_active(bluetooth::is_enabled());

        let suppress = Rc::new(Cell::new(false));

        let s1 = suppress.clone();
        sw.connect_state_set(move |_, state| {
            if s1.get() {
                return glib::Propagation::Proceed;
            }
            if state {
                bluetooth::enable();
                bluetooth::scan_start();
            } else {
                bluetooth::scan_stop();
                bluetooth::disable();
            }
            glib::Propagation::Proceed
        });

        let s2 = suppress.clone();
        let sw2 = sw.clone();
        glib::timeout_add_seconds_local(2, move || {
            if !bluetooth::is_blocked() {
                let current = bluetooth::is_enabled();
                if current != sw2.is_active() {
                    s2.set(true);
                    sw2.set_active(current);
                    s2.set(false);
                }
            }
            glib::ControlFlow::Continue
        });
    }

    box_.append(&label);
    box_.append(&sw);
    box_
}

/// Icono por tipo de dispositivo (port de bluetooth/widgets/list.py).
fn device_icon(name: &str) -> &'static str {
    let n = name.to_lowercase();
    if ["airpod", "headphone", "earbuds", "speaker"].iter().any(|k| n.contains(k)) {
        "🎧"
    } else if ["keyboard", "keychron"].iter().any(|k| n.contains(k)) {
        "⌨"
    } else if ["mouse", "mx master", "logi"].iter().any(|k| n.contains(k)) {
        "🖱"
    } else if ["controller", "dualsense", "xbox", "joy"].iter().any(|k| n.contains(k)) {
        "🎮"
    } else if ["watch", "band"].iter().any(|k| n.contains(k)) {
        "⌚"
    } else {
        "📱"
    }
}

/// Lista de dispositivos con refresco de 3s (port de bluetooth/widgets/list.py).
fn device_list_widget() -> gtk::Box {
    let vbox = gtk::Box::new(gtk::Orientation::Vertical, 6);
    vbox.add_css_class("device-list");

    let header = gtk::Label::new(Some("Devices"));
    header.add_css_class("section-title");
    header.set_xalign(0.0);
    vbox.append(&header);

    let empty = gtk::Label::new(Some("No devices"));
    empty.set_xalign(0.0);
    empty.add_css_class("empty-label");
    empty.set_visible(false);
    vbox.append(&empty);

    let devices_box = gtk::Box::new(gtk::Orientation::Vertical, 4);
    vbox.append(&devices_box);

    let refresh = glib::clone!(#[strong] devices_box, #[strong] empty, move || {
        let db = devices_box.clone();
        let em = empty.clone();
        crate::popup::run_bg(bluetooth::list_devices, move |devices| {
            clear_children(&db);
            if devices.is_empty() {
                em.set_visible(true);
                return;
            }
            em.set_visible(false);
            for device in &devices {
                db.append(&device_row(device));
            }
        });
    });

    refresh();

    glib::timeout_add_seconds_local(3, move || {
        refresh();
        glib::ControlFlow::Continue
    });

    vbox
}

fn clear_children(box_: &gtk::Box) {
    while let Some(child) = box_.first_child() {
        box_.remove(&child);
    }
}

/// Fila de un dispositivo: icono, nombre, estado y acciones
/// (port de bluetooth/widgets/list.py — DeviceRow).
fn device_row(device: &bluetooth::BtDevice) -> gtk::Box {
    let row = gtk::Box::new(gtk::Orientation::Horizontal, 10);
    row.add_css_class("device-item");

    let icon = gtk::Label::new(Some(device_icon(&device.name)));

    let name_box = gtk::Box::new(gtk::Orientation::Vertical, 2);
    name_box.set_hexpand(true);

    let name = gtk::Label::new(Some(&device.name));
    name.set_hexpand(true);
    name.set_xalign(0.0);
    name.add_css_class("device-name");
    name_box.append(&name);

    if device.connected {
        let status = gtk::Label::new(Some("Connected"));
        status.set_xalign(0.0);
        status.add_css_class("device-status");
        name_box.append(&status);
    }

    let address = device.address.clone();
    let connected = device.connected;
    let action = gtk::Button::with_label(if device.connected {
        "Disconnect"
    } else {
        "Connect"
    });
    action.set_tooltip_text(Some(if device.connected { "Disconnect" } else { "Connect" }));
    action.add_css_class("device-action");
    if device.connected {
        action.add_css_class("connected");
    }
    action.connect_clicked(move |_| {
        if connected {
            bluetooth::disconnect(&address);
        } else {
            bluetooth::connect(&address);
        }
    });

    let address = device.address.clone();
    let forget = gtk::Button::with_label("✕");
    forget.set_tooltip_text(Some("Remove"));
    forget.add_css_class("device-forget");
    forget.connect_clicked(move |_| {
        bluetooth::remove(&address);
    });

    row.append(&icon);
    row.append(&name_box);
    row.append(&action);
    row.append(&forget);

    row
}
