// ==========================================
// window.rs — ventana del control center (port de window.py)
// ==========================================

use std::rc::Rc;
use std::thread;

use gtk::prelude::*;

use churros_services::spawn;
use churros_services::audio;
use churros_services::battery;
use churros_services::bluetooth;
use churros_services::brightness;
use churros_services::ethernet;
use churros_services::wifi;

use super::super::assets;
use super::audio::AudioCard;
use super::battery::BatteryCard;
use super::bluetooth::BluetoothCard;
use super::brightness::BrightnessCard;
use super::network::NetworkCard;
use super::power::PowerButton;

pub struct ControlCenterWindow {
    window: gtk::ApplicationWindow,
    network: NetworkCard,
    bluetooth: BluetoothCard,
    brightness: BrightnessCard,
    battery: BatteryCard,
    audio: AudioCard,
    #[allow(dead_code)]
    theme_settings: Option<gio::Settings>,
}

fn apply_theme(window: &gtk::ApplicationWindow) {
    let is_dark = churros_services::theme::is_dark();
    if is_dark {
        window.remove_css_class("light");
    } else {
        window.add_css_class("light");
    }
    #[allow(deprecated)]
    if let Some(settings) = gtk::Settings::default() {
        settings.set_gtk_application_prefer_dark_theme(is_dark);
    }
    window.queue_draw();
}

fn setup_theme(window: &gtk::ApplicationWindow) -> Option<gio::Settings> {
    apply_theme(window);

    let w = window.clone();
    let settings = gio::SettingsSchemaSource::default().and_then(|schema_source| {
        let schema = schema_source.lookup("org.gnome.desktop.interface", false)?;
        let settings =
            gio::Settings::new_full(&schema, None::<&gio::SettingsBackend>, None::<&str>);
        settings.connect_changed(Some("color-scheme"), move |_, _| {
            let w = w.clone();
            glib::idle_add_local_once(move || apply_theme(&w));
        });
        Some(settings)
    });

    let w_active = window.clone();
    window.connect_is_active_notify(move |win| {
        if win.is_active() {
            apply_theme(&w_active);
        }
    });

    settings
}

#[derive(Default, Clone)]
pub struct SystemInfo {
    // Network
    pub ethernet_connected: bool,
    pub ethernet_name: String,
    pub ethernet_speed: Option<u32>,
    pub wifi_connected: bool,
    pub wifi_name: String,
    pub wifi_strength: u8,
    pub wifi_speed: String,
    pub network_rate_down: String,
    pub network_rate_up: String,
    // Bluetooth
    pub bluetooth_enabled: bool,
    pub bluetooth_connected: bool,
    pub bluetooth_device: String,
    // Brightness
    pub brightness_percent: u8,
    // Battery
    pub battery_percent: u8,
    pub battery_charging: bool,
    // Audio
    pub volume: u8,
    pub muted: bool,
}

impl ControlCenterWindow {
    pub fn new(app: &gtk::Application) -> Rc<Self> {
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Control Center")
            .build();

        window.set_default_size(430, 650);
        window.set_resizable(false);
        window.set_decorated(false);

        window.add_css_class("control-center");
        window.add_css_class("churros-glass");

        let theme_settings = setup_theme(&window);

        let network = NetworkCard::new(&window);
        let bluetooth = BluetoothCard::new(&window);
        let brightness = BrightnessCard::new(&window);
        let battery = BatteryCard::new(&window);
        let audio = AudioCard::new();

        // Estado inicial inmediato (< 2ms) para que no haya parpadeo ni "Loading..."
        let initial_bat = battery::get();
        let initial_bright = brightness::get();
        let (initial_vol, initial_muted) = audio::get_volume_status();
        let initial_info = SystemInfo {
            brightness_percent: initial_bright.brightness,
            battery_percent: initial_bat.percentage,
            battery_charging: matches!(
                initial_bat.state.as_str(),
                "charging" | "fully-charged" | "pending-charge"
            ),
            volume: initial_vol,
            muted: initial_muted,
            ..Default::default()
        };
        brightness.apply_info(&initial_info);
        battery.apply_info(&initial_info);
        audio.apply_info(&initial_info);

        let root = gtk::Box::new(gtk::Orientation::Vertical, 20);
        root.set_margin_top(20);
        root.set_margin_bottom(20);
        root.set_margin_start(20);
        root.set_margin_end(20);
        root.add_css_class("control-center-root");

        root.append(&Self::build_header(&window));

        let grid = gtk::Grid::new();
        grid.set_column_homogeneous(true);
        grid.set_row_spacing(16);
        grid.set_column_spacing(16);
        grid.add_css_class("control-center-grid");

        grid.attach(network.button(), 0, 0, 1, 1);
        grid.attach(bluetooth.button(), 1, 0, 1, 1);
        grid.attach(brightness.button(), 0, 1, 1, 1);
        grid.attach(battery.button(), 1, 1, 1, 1);

        root.append(&grid);
        root.append(audio.box_());

        let scroller = gtk::ScrolledWindow::new();
        scroller.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
        scroller.set_child(Some(&root));
        scroller.set_hexpand(true);
        scroller.set_vexpand(true);
        scroller.add_css_class("control-center-scroller");

        window.set_child(Some(&scroller));

        let win = Rc::new(Self {
            window,
            network,
            bluetooth,
            brightness,
            battery,
            audio,
            theme_settings,
        });

        win.refresh_async();
        win.wire();
        win
    }

    fn build_header(window: &gtk::ApplicationWindow) -> gtk::Box {
        let header = gtk::Box::new(gtk::Orientation::Horizontal, 12);

        let logo = gtk::Image::from_file(assets::logo_path());
        logo.set_pixel_size(40);

        let titles = gtk::Box::new(gtk::Orientation::Vertical, 0);
        titles.set_hexpand(true);

        let title = gtk::Label::new(Some("ChurrOS"));
        title.add_css_class("title");
        title.set_xalign(0.0);

        let subtitle = gtk::Label::new(Some("Control Center"));
        subtitle.add_css_class("subtitle");
        subtitle.set_xalign(0.0);

        titles.append(&title);
        titles.append(&subtitle);

        let settings_btn = gtk::Button::from_icon_name("preferences-system");
        settings_btn.set_tooltip_text(Some("Configuración"));
        settings_btn.add_css_class("settings-button");

        let win = window.clone();
        settings_btn.connect_clicked(move |_| {
            spawn(&["churros-settings"]);
            win.close();
        });

        let close_btn = gtk::Button::from_icon_name("window-close-symbolic");
        close_btn.set_tooltip_text(Some("Cerrar"));
        close_btn.add_css_class("close-button");
        let win_close = window.clone();
        close_btn.connect_clicked(move |_| {
            win_close.close();
        });

        header.append(&logo);
        header.append(&titles);
        header.append(&settings_btn);
        header.append(PowerButton::new(window).button());
        header.append(&close_btn);

        header
    }

    pub fn window(&self) -> &gtk::ApplicationWindow {
        &self.window
    }

    fn wire(self: &Rc<Self>) {
        let controller = gtk::EventControllerKey::new();
        let win = self.window.clone();
        controller.connect_key_pressed(move |_, key, _, _| {
            if key == gtk::gdk::Key::Escape {
                win.close();
                glib::Propagation::Stop
            } else {
                glib::Propagation::Proceed
            }
        });
        self.window.add_controller(controller);

        glib::timeout_add_seconds_local(1, glib::clone!(#[strong(rename_to = this)] self, move || {
            this.refresh_async();
            glib::ControlFlow::Continue
        }));
    }

    fn refresh_async(self: &Rc<Self>) {
        let this = self.clone();
        let (tx, rx) = std::sync::mpsc::channel();
        thread::spawn(move || {
            let info = collect_system_info();
            tx.send(info).ok();
        });
        glib::timeout_add_local(std::time::Duration::from_millis(25), glib::clone!(#[strong] this, move || {
            match rx.try_recv() {
                Ok(info) => {
                    this.apply_system_info(&info);
                    glib::ControlFlow::Break
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
                // El hilo murió sin enviar: no reprogramar para siempre.
                Err(std::sync::mpsc::TryRecvError::Disconnected) => glib::ControlFlow::Break,
            }
        }));
    }

    fn apply_system_info(&self, info: &SystemInfo) {
        self.network.apply_info(info);
        self.bluetooth.apply_info(info);
        self.brightness.apply_info(info);
        self.battery.apply_info(info);
        self.audio.apply_info(info);
    }
}

static PREV_NET: std::sync::Mutex<Option<(std::time::Instant, String, wifi::NetThroughput)>> =
    std::sync::Mutex::new(None);

fn collect_system_info() -> SystemInfo {
    let (vol, muted) = audio::get_volume_status();
    let bright = brightness::get();
    let bat = battery::get();

    let (net_tx, net_rx) = std::sync::mpsc::channel();
    let (bt_tx, bt_rx) = std::sync::mpsc::channel();

    thread::spawn(move || {
        let eth = ethernet::get();
        let active_wifi = wifi::get_active();

        let active_dev = if eth.connected {
            eth.device.clone()
        } else if active_wifi.connected {
            Some(active_wifi.device.clone())
        } else {
            None
        };

        let mut down_rate = String::new();
        let mut up_rate = String::new();

        if let Some(dev) = active_dev {
            if let Some(curr) = wifi::read_interface_bytes(&dev) {
                if let Ok(mut prev_guard) = PREV_NET.lock() {
                    if let Some((prev_time, prev_dev, prev_bytes)) = prev_guard.as_ref() {
                        if prev_dev == &dev {
                            let dt = prev_time.elapsed().as_secs_f64();
                            if dt >= 0.4 {
                                let rx_rate = ((curr.rx_bytes.saturating_sub(prev_bytes.rx_bytes)) as f64 / dt) as u64;
                                let tx_rate = ((curr.tx_bytes.saturating_sub(prev_bytes.tx_bytes)) as f64 / dt) as u64;
                                if rx_rate > 500 {
                                    down_rate = wifi::format_bytes_rate(rx_rate);
                                }
                                if tx_rate > 500 {
                                    up_rate = wifi::format_bytes_rate(tx_rate);
                                }
                                *prev_guard = Some((std::time::Instant::now(), dev, curr));
                            }
                        } else {
                            *prev_guard = Some((std::time::Instant::now(), dev, curr));
                        }
                    } else {
                        *prev_guard = Some((std::time::Instant::now(), dev, curr));
                    }
                }
            }
        }

        net_tx.send((eth, active_wifi, down_rate, up_rate)).ok();
    });

    thread::spawn(move || {
        let bt_avail = bluetooth::available();
        let bt_connected_dev = if bt_avail {
            bluetooth::connected_device()
        } else {
            None
        };
        bt_tx.send((bt_avail, bt_connected_dev)).ok();
    });

    let (eth, active_wifi, down_rate, up_rate) = net_rx.recv().unwrap_or_default();
    let (bt_avail, bt_connected_dev) = bt_rx.recv().unwrap_or((false, None));

    let mut info = SystemInfo::default();

    // Network
    info.ethernet_connected = eth.connected;
    info.ethernet_name = eth.connection;
    info.ethernet_speed = eth.speed;

    info.wifi_connected = active_wifi.connected;
    info.wifi_name = active_wifi.ssid;
    info.wifi_strength = active_wifi.signal;
    info.wifi_speed = active_wifi.speed;
    info.network_rate_down = down_rate;
    info.network_rate_up = up_rate;

    // Bluetooth
    info.bluetooth_enabled = bt_avail;
    if let Some(dev) = bt_connected_dev {
        info.bluetooth_connected = true;
        info.bluetooth_device = dev;
    }

    // Brightness
    info.brightness_percent = bright.brightness;

    // Battery
    info.battery_percent = bat.percentage;
    info.battery_charging = matches!(
        bat.state.as_str(),
        "charging" | "fully-charged" | "pending-charge"
    );

    // Audio
    info.volume = vol;
    info.muted = muted;

    info
}
