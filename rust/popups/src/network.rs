// ==========================================
// network.rs — popup de red (port de network/window.py + widgets)
// ==========================================

use std::cell::RefCell;
use std::rc::Rc;

use churros_services::ethernet;
use churros_services::wifi::{self, Network, WifiInfo};
use gtk::prelude::*;

use crate::popup::PopupWindow;

pub fn build(app: &gtk::Application) -> PopupWindow {
    let w = PopupWindow::new(app, "Network", "󰤨", "network.css");

    let vbox = gtk::Box::new(gtk::Orientation::Vertical, 18);
    vbox.add_css_class("network-widget");

    let wifi = Rc::new(WifiWidget::new());
    wifi.wire();
    vbox.append(&wifi.stack.clone());

    let separator = gtk::Separator::new(gtk::Orientation::Horizontal);
    separator.add_css_class("network-separator");
    vbox.append(&separator);

    let ethernet = EthernetWidget::new();
    ethernet.wire();
    vbox.append(&ethernet.vbox.clone());

    w.add(&vbox);
    w
}

fn clear_children(box_: &gtk::Box) {
    while let Some(child) = box_.first_child() {
        box_.remove(&child);
    }
}

// ---------------------------------------------------------------
// Wi-Fi (port de network/widgets/wifi.py)
// ---------------------------------------------------------------

struct WifiWidget {
    stack: gtk::Stack,
    list: gtk::Box,
    sw: gtk::Switch,
    last: RefCell<WifiInfo>,
    page: RefCell<Option<gtk::Box>>,
}

impl WifiWidget {
    fn new() -> Self {
        let stack = gtk::Stack::new();
        stack.set_hexpand(true);
        stack.set_vexpand(true);
        stack.set_transition_type(gtk::StackTransitionType::SlideLeftRight);
        stack.set_transition_duration(250);

        let network_page = gtk::Box::new(gtk::Orientation::Vertical, 10);

        let title = gtk::Label::new(Some("Wi-Fi"));
        title.set_xalign(0.0);
        title.add_css_class("section-title");
        network_page.append(&title);

        let (toggle, sw) = toggle_widget();
        network_page.append(&toggle);

        let list = gtk::Box::new(gtk::Orientation::Vertical, 10);

        let scroller = gtk::ScrolledWindow::new();
        scroller.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
        scroller.set_min_content_height(180);
        scroller.set_max_content_height(220);
        scroller.set_propagate_natural_height(false);
        scroller.set_child(Some(&list));
        scroller.set_vexpand(true);

        network_page.append(&scroller);

        stack.add_named(&network_page, Some("list"));
        stack.set_visible_child_name("list");

        Self {
            stack,
            list,
            sw,
            last: RefCell::new(WifiInfo::default()),
            page: RefCell::new(None),
        }
    }

    fn wire(self: &Rc<Self>) {
        let wifi = self.clone();

        let wifi2 = wifi.clone();
        self.sw.connect_state_set(move |_, state| {
            let w = wifi2.clone();
            crate::popup::run_bg(
                move || {
                    if state {
                        wifi::enable();
                    } else {
                        wifi::disable();
                    }
                },
                move |_| {
                    w.reload();
                },
            );
            glib::Propagation::Proceed
        });

        self.reload();

        let wifi3 = wifi.clone();
        glib::timeout_add_seconds_local(3, move || {
            wifi3.auto_refresh();
            glib::ControlFlow::Continue
        });
    }

    fn auto_refresh(self: &Rc<Self>) {
        if self.stack.visible_child_name().as_deref() != Some("list") {
            return;
        }
        let w = self.clone();
        crate::popup::run_bg(wifi::get, move |state| {
            if state != *w.last.borrow() {
                w.reload();
            }
        });
    }

    fn show_message(&self, text: &str) {
        let label = gtk::Label::new(Some(text));
        label.set_xalign(0.0);
        label.add_css_class("network-info");
        self.list.append(&label);
    }

    fn reload(self: &Rc<Self>) {
        *self.last.borrow_mut() = wifi::get();
        wifi::scan();
        clear_children(&self.list);

        let state = self.last.borrow().clone();
        if !state.available {
            self.show_message("No Wi-Fi adapter detected.");
            return;
        }
        if !state.enabled {
            self.show_message("Wi-Fi is disabled.");
            return;
        }
        if state.networks.is_empty() {
            let spinner = gtk::Spinner::new();
            spinner.start();
            self.list.append(&spinner);
            self.show_message("Searching for networks...");
            return;
        }
        self.show_networks(&state.networks);
    }

    fn show_networks(self: &Rc<Self>, networks: &[Network]) {
        let wifi = self.clone();

        let actions_box = gtk::Box::new(gtk::Orientation::Horizontal, 8);

        let refresh = gtk::Button::with_label("Refresh");
        refresh.add_css_class("network-button");
        let wifi2 = wifi.clone();
        refresh.connect_clicked(move |_| wifi2.reload());
        actions_box.append(&refresh);

        let hidden_btn = gtk::Button::with_label("Connect to hidden network");
        hidden_btn.add_css_class("network-button");
        let wifi3 = wifi.clone();
        hidden_btn.connect_clicked(move |_| wifi3.show_hidden());
        actions_box.append(&hidden_btn);

        self.list.append(&actions_box);

        for network in networks {
            self.list.append(&network_item(network, &wifi));
        }
    }

    fn select_network(self: &Rc<Self>, network: &Network) {
        if network.connected {
            wifi::disconnect();
            self.reload();
            return;
        }

        if network.ssid == "Hidden Network" {
            self.show_hidden();
            return;
        }

        let secured = network.security != "" && network.security != "--";
        if secured && !network.saved {
            self.show_password(network);
            return;
        }

        let (success, message) = wifi::connect(&network.ssid, None);
        self.reload();
        if !success {
            self.show_message(&message);
        }
    }

    fn forget_network(self: &Rc<Self>, network: &Network) {
        wifi::forget(&network.ssid);
        self.reload();
    }

    fn show_page(self: &Rc<Self>, page: gtk::Box, name: &str) {
        if let Some(old) = self.page.borrow_mut().take() {
            self.stack.remove(&old);
        }
        self.stack.add_named(&page, Some(name));
        self.stack.set_visible_child_name(name);
        *self.page.borrow_mut() = Some(page);
    }

    fn back(&self) {
        self.stack.set_visible_child_name("list");
    }

    fn show_password(self: &Rc<Self>, network: &Network) {
        let wifi = self.clone();

        let page = gtk::Box::new(gtk::Orientation::Vertical, 12);
        page.add_css_class("password-page");

        let back = gtk::Button::with_label("Back");
        back.add_css_class("network-button");
        let wifi2 = wifi.clone();
        back.connect_clicked(move |_| wifi2.back());
        page.append(&back);

        let title = gtk::Label::new(Some(&format!("Connect to {}", network.ssid)));
        title.add_css_class("section-title");
        title.set_xalign(0.0);
        page.append(&title);

        let entry = gtk::Entry::new();
        entry.set_placeholder_text(Some("Password"));
        entry.set_visibility(false);
        page.append(&entry);

        let error = gtk::Label::new(None);
        error.add_css_class("network-error");
        error.set_xalign(0.0);
        page.append(&error);

        let connect = gtk::Button::with_label("Connect");
        connect.add_css_class("suggested-action");
        page.append(&connect);

        let ssid = network.ssid.clone();
        let entry2 = entry.clone();
        let error2 = error.clone();
        let wifi3 = wifi.clone();
        let do_connect = move || {
            let password = entry2.text();
            let (success, message) = wifi::connect(&ssid, Some(password.as_str()));
            if success {
                wifi3.back();
            } else {
                error2.set_label(&message);
            }
        };

        let do_connect2 = do_connect.clone();
        entry.connect_activate(move |_| do_connect2());
        connect.connect_clicked(move |_| do_connect());

        self.show_page(page, "password");
    }

    fn show_hidden(self: &Rc<Self>) {
        let wifi = self.clone();

        let page = gtk::Box::new(gtk::Orientation::Vertical, 12);
        page.add_css_class("hidden-dialog");

        let back = gtk::Button::with_label("Back");
        back.add_css_class("network-button");
        let wifi2 = wifi.clone();
        back.connect_clicked(move |_| wifi2.back());
        page.append(&back);

        let title = gtk::Label::new(Some("Connect to hidden network"));
        title.add_css_class("section-title");
        title.set_xalign(0.0);
        page.append(&title);

        let ssid_entry = gtk::Entry::new();
        ssid_entry.set_placeholder_text(Some("SSID"));
        page.append(&ssid_entry);

        let password_entry = gtk::Entry::new();
        password_entry.set_visibility(false);
        password_entry.set_placeholder_text(Some("Password"));
        page.append(&password_entry);

        let error = gtk::Label::new(None);
        error.set_xalign(0.0);
        error.add_css_class("network-error");
        page.append(&error);

        let connect = gtk::Button::with_label("Connect");
        connect.add_css_class("suggested-action");
        page.append(&connect);

        let ssid2 = ssid_entry.clone();
        let password2 = password_entry.clone();
        let error2 = error.clone();
        let wifi3 = wifi.clone();
        connect.connect_clicked(move |_| {
            let ssid = ssid2.text().trim().to_string();
            if ssid.is_empty() {
                error2.set_label("SSID required.");
                return;
            }
            let password = password2.text();
            let pwd = if password.is_empty() {
                None
            } else {
                Some(password.as_str())
            };
            let (success, message) = wifi::connect_hidden(&ssid, pwd);
            if success {
                wifi3.back();
            } else {
                error2.set_label(&message);
            }
        });

        self.show_page(page, "hidden");
    }
}

/// Toggle de Wi-Fi (port de network/widgets/wifi.py — _build_toggle).
fn toggle_widget() -> (gtk::Box, gtk::Switch) {
    let box_ = gtk::Box::new(gtk::Orientation::Horizontal, 12);
    box_.add_css_class("network-toggle");

    let label = gtk::Label::new(Some("Wi-Fi"));
    label.add_css_class("network-label");
    label.set_hexpand(true);
    label.set_xalign(0.0);

    let sw = gtk::Switch::new();
    let info = wifi::get();
    if info.available {
        sw.set_active(info.enabled);
    } else {
        sw.set_sensitive(false);
    }

    box_.append(&label);
    box_.append(&sw);

    (box_, sw)
}

/// Fila de red: icono de señal, nombre, candado y estado
/// (port de network/widgets/network_item.py).
fn network_item(network: &Network, wifi: &Rc<WifiWidget>) -> gtk::Box {
    let item = gtk::Box::new(gtk::Orientation::Horizontal, 10);
    item.add_css_class("network-item");
    item.set_hexpand(true);

    let main_btn = gtk::Button::new();
    main_btn.set_hexpand(true);
    main_btn.add_css_class("network-main");

    let net = network.clone();
    let wifi_rc = wifi.clone();
    main_btn.connect_clicked(move |_| wifi_rc.select_network(&net));

    let root = gtk::Box::new(gtk::Orientation::Vertical, 8);

    let row = gtk::Box::new(gtk::Orientation::Horizontal, 10);

    let signal = network.signal;
    let icon = if signal >= 80 {
        "󰤨"
    } else if signal >= 60 {
        "󰤥"
    } else if signal >= 40 {
        "󰤢"
    } else if signal >= 20 {
        "󰤟"
    } else {
        "󰤯"
    };
    let icon_label = gtk::Label::new(Some(icon));
    icon_label.add_css_class("network-icon");

    let name = gtk::Label::new(Some(&network.ssid));
    name.set_hexpand(true);
    name.set_xalign(0.0);
    name.add_css_class("network-name");

    row.append(&icon_label);
    row.append(&name);

    if network.security != "" && network.security != "--" {
        let lock = gtk::Label::new(Some("󰌾"));
        lock.add_css_class("network-lock");
        row.append(&lock);
    }

    root.append(&row);

    let status = gtk::Label::new(None);
    status.set_xalign(0.0);
    status.add_css_class("network-status");

    if network.connected {
        status.set_label("Connected");
        status.add_css_class("connected");
    } else {
        status.set_label(&format!("Signal {signal}%"));
    }

    root.append(&status);
    main_btn.set_child(Some(&root));
    item.append(&main_btn);

    if network.saved && !network.connected {
        let net = network.clone();
        let wifi_rc = wifi.clone();
        let forget = gtk::Button::with_label("✕");
        forget.set_tooltip_text(Some("Forget"));
        forget.add_css_class("network-forget");
        forget.connect_clicked(move |_| wifi_rc.forget_network(&net));
        item.append(&forget);
    }

    item
}

// ---------------------------------------------------------------
// Ethernet (port de network/widgets/ethernet.py)
// ---------------------------------------------------------------

struct EthernetWidget {
    vbox: gtk::Box,
    last: RefCell<ethernet::EthernetInfo>,
}

impl EthernetWidget {
    fn new() -> Rc<Self> {
        let vbox = gtk::Box::new(gtk::Orientation::Vertical, 10);
        vbox.add_css_class("ethernet-widget");
        Rc::new(Self {
            vbox,
            last: RefCell::new(ethernet::get()),
        })
    }

    fn wire(self: &Rc<Self>) {
        self.reload();

        let this = self.clone();
        glib::timeout_add_seconds_local(3, move || {
            let current = ethernet::get();
            if current != *this.last.borrow() {
                *this.last.borrow_mut() = current;
                this.reload();
            }
            glib::ControlFlow::Continue
        });
    }

    fn reload(self: &Rc<Self>) {
        clear_children(&self.vbox);
        let data = self.last.borrow().clone();

        let title = gtk::Label::new(Some("󰈀 Ethernet"));
        title.set_xalign(0.0);
        title.add_css_class("section-title");
        self.vbox.append(&title);

        if !data.available {
            let label = gtk::Label::new(Some("No ethernet adapter detected."));
            label.set_xalign(0.0);
            label.add_css_class("network-info");
            self.vbox.append(&label);
            return;
        }

        let status = gtk::Label::new(None);
        status.set_xalign(0.0);
        if data.connected {
            status.set_label("Connected");
            status.add_css_class("connected");
        } else {
            status.set_label("Cable disconnected");
            status.add_css_class("network-info");
        }
        self.vbox.append(&status);

        if data.connected {
            if let Some(speed) = data.speed {
                let speed_label = gtk::Label::new(Some(&format!("󰓅 {speed} Mbps")));
                speed_label.set_xalign(0.0);
                speed_label.add_css_class("network-info");
                self.vbox.append(&speed_label);
            }

            if let Some(ip) = &data.ip {
                let ip_label = gtk::Label::new(Some(&format!("󰩠 {ip}")));
                ip_label.set_xalign(0.0);
                ip_label.add_css_class("network-info");
                self.vbox.append(&ip_label);
            }
        }

        let connected = data.connected;
        let this = self.clone();
        let btn = gtk::Button::with_label(if connected { "Disconnect" } else { "Connect" });
        btn.add_css_class("network-button");
        btn.connect_clicked(move |_| {
            if connected {
                ethernet::disconnect();
            } else {
                ethernet::connect();
            }
            *this.last.borrow_mut() = ethernet::get();
            this.reload();
        });

        self.vbox.append(&btn);
    }
}
