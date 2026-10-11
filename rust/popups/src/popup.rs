// ==========================================
// popup.rs — ventana base de los popups (port de common/popup.py + header.py)
// ==========================================

use std::path::{Path, PathBuf};

use gtk::gdk::Key;
use gtk::prelude::*;

// En runtime (ISO) los assets viven en /usr/share/churros/churros-popup/assets/
// (desplegados por build-rust.sh a /usr/share/churros/<crate>/assets/).
// En desarrollo se usan los assets locales del crate.
const RUNTIME_ROOT: &str = "/usr/share/churros/churros-popup/assets";
const DEV_ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/assets");

fn assets_root() -> PathBuf {
    let runtime = PathBuf::from(RUNTIME_ROOT);
    if runtime.is_dir() {
        runtime
    } else {
        PathBuf::from(DEV_ROOT)
    }
}

/// Carga el CSS compartido de ChurrOS (si existe), el común de popups y el
/// propio del popup (equivalente a popup.py + load_*_css de cada ventana).
pub fn load_css(own: &str) {
    let Some(display) = gtk::gdk::Display::default() else {
        eprintln!("churros-popup: no hay display Wayland/X11 disponible");
        std::process::exit(1);
    };

    // CSS compartido (misma prioridad que Preferences)
    let shared = "/usr/share/churros/styles/churros.css";
    let dev_shared = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../archiso/airootfs/usr/share/churros/styles/churros.css"
    );
    let shared_path = if Path::new(shared).is_file() {
        Some(Path::new(shared))
    } else if Path::new(dev_shared).is_file() {
        Some(Path::new(dev_shared))
    } else {
        None
    };
    if let Some(path) = shared_path {
        let provider = gtk::CssProvider::new();
        let _ = provider.load_from_path(path);
        gtk::style_context_add_provider_for_display(
            &display,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
    }

    // CSS local (misma prioridad que Preferences)
    for css in ["common.css", own] {
        let path = assets_root().join(css);
        if path.is_file() {
            let provider = gtk::CssProvider::new();
            let _ = provider.load_from_path(&path);
            gtk::style_context_add_provider_for_display(
                &display,
                &provider,
                gtk::STYLE_PROVIDER_PRIORITY_APPLICATION + 1, // Cambiado de USER+1 a APPLICATION+1
            );
        }
    }

    // Accent CSS (misma prioridad que Preferences)
    let home = churros_services::home_dir();
    let accent_path = PathBuf::from(home).join(".config/churros/accent.css");
    if let Ok(css) = std::fs::read_to_string(&accent_path) {
        let provider = gtk::CssProvider::new();
        provider.load_from_string(&css);
        gtk::style_context_add_provider_for_display(
            &display,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_USER,
        );
    }
}

/// Cabecera del popup: icono + título (port de common/widgets/header.py).
pub struct Header {
    pub widget: gtk::Box,
}

impl Header {
    pub fn new(icon: &str, title: &str) -> Self {
        let hbox = gtk::Box::new(gtk::Orientation::Horizontal, 0);
        hbox.add_css_class("popup-header");
        hbox.set_margin_bottom(12);

        let icon_label = gtk::Label::new(Some(icon));
        icon_label.add_css_class("popup-header-icon");

        let title_label = gtk::Label::new(Some(title));
        title_label.add_css_class("popup-header-title");
        title_label.set_hexpand(true);
        title_label.set_halign(gtk::Align::Start);

        hbox.append(&icon_label);
        hbox.append(&title_label);

        Self { widget: hbox }
    }
}

/// Ejecuta `work` en un hilo aparte y entrega el resultado al hilo GTK vía
/// timeout (repliega cada 25 ms hasta que llegue). Evita bloquear la UI con
/// comandos síncronos como wpctl/nmcli/gsettings.
pub fn run_bg<T, F, C>(work: F, cb: C)
where
    T: Send + 'static,
    F: FnOnce() -> T + Send + 'static,
    C: FnOnce(T) + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel::<T>();
    std::thread::spawn(move || {
        let _ = tx.send(work());
    });
    let mut cb = Some(cb);
    glib::timeout_add_local(std::time::Duration::from_millis(25), move || {
        match rx.try_recv() {
            Ok(v) => {
                if let Some(cb) = cb.take() {
                    cb(v);
                }
                glib::ControlFlow::Break
            }
            Err(std::sync::mpsc::TryRecvError::Empty) => glib::ControlFlow::Continue,
            Err(std::sync::mpsc::TryRecvError::Disconnected) => glib::ControlFlow::Break,
        }
    });
}

fn apply_theme(window: &gtk::ApplicationWindow) {
    let w = window.clone();
    run_bg(churros_services::theme::is_dark, move |is_dark| {
        apply_theme_now(&w, is_dark);
    });
}

fn apply_theme_now(window: &gtk::ApplicationWindow, is_dark: bool) {
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

/// Ventana base del popup (port de common/popup.py).
pub struct PopupWindow {
    pub window: gtk::ApplicationWindow,
    pub content: gtk::Box,
    #[allow(dead_code)]
    theme_settings: Option<gio::Settings>,
}

impl PopupWindow {
    pub fn new(app: &gtk::Application, title: &str, icon: &str, css: &str) -> Self {
        load_css(css);

        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title(title)
            .default_width(320)
            .default_height(400)
            .resizable(false)
            .decorated(false)
            .css_classes(["popup", "churros-glass"])
            .build();

        let theme_settings = setup_theme(&window);

        let main_box = gtk::Box::new(gtk::Orientation::Vertical, 0);
        main_box.add_css_class("popup-content");
        window.set_child(Some(&main_box));

        let header = Header::new(icon, title);
        main_box.append(&header.widget);

        let content = gtk::Box::new(gtk::Orientation::Vertical, 0);
        content.set_vexpand(true);
        main_box.append(&content);

        let controller = gtk::EventControllerKey::new();
        controller.connect_key_pressed(glib::clone!(
            #[weak] window,
            #[upgrade_or] glib::Propagation::Proceed,
            move |_, key, _, _| {
                if key == Key::Escape {
                    window.destroy();
                    return glib::Propagation::Stop;
                }
                glib::Propagation::Proceed
            }
        ));
        window.add_controller(controller);

        Self {
            window,
            content,
            theme_settings,
        }
    }

    pub fn add(&self, widget: &impl IsA<gtk::Widget>) {
        self.content.append(widget);
    }

    pub fn present(&self) {
        self.window.present();
    }
}
