mod action_card;
mod actions;
mod assets;
mod cards;
mod footer;
mod header;
mod system_card;
mod system_info;

use gtk::prelude::*;

const APP_ID: &str = "org.churros.welcome";

fn load_css() {
    // Cada archivo en su propio provider: load_from_path REEMPLAZA el
    // contenido previo del provider, así que compartir provider perdería
    // el churros.css (el style.css de welcome es autocontenido, pero el
    // CSS compartido aporta tokens/paleta a la ISO).
    let Some(display) = gtk::gdk::Display::default() else {
        eprintln!("churros-welcome: no hay display Wayland/X11 disponible");
        std::process::exit(1);
    };

    // CSS compartido (misma prioridad que Preferences)
    let shared = "/usr/share/churros/styles/churros.css";
    let dev_shared = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../archiso/airootfs/usr/share/churros/styles/churros.css"
    );
    let shared_path = if std::path::Path::new(shared).exists() {
        Some(std::path::Path::new(shared))
    } else if std::path::Path::new(dev_shared).exists() {
        Some(std::path::Path::new(dev_shared))
    } else {
        None
    };
    if let Some(path) = shared_path {
        let provider = gtk::CssProvider::new();
        provider.load_from_path(path);
        gtk::style_context_add_provider_for_display(
            &display,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
    }

    // CSS local (misma prioridad que Preferences)
    let local = assets::css_path();
    let provider = gtk::CssProvider::new();
    if local.is_file() {
        provider.load_from_path(&local);
    } else {
        provider.load_from_string(include_str!("../assets/style.css"));
    }
    gtk::style_context_add_provider_for_display(
        &display,
        &provider,
        gtk::STYLE_PROVIDER_PRIORITY_APPLICATION + 1, // Cambiado de USER+1 a APPLICATION+1
    );

    // Colores dinámicos (accent.css de pywal o preferencias) - misma prioridad que Preferences
    let home = churros_services::home_dir();
    let accent_path = std::path::PathBuf::from(home).join(".config/churros/accent.css");
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

thread_local! {
    static THEME_SETTINGS: std::cell::RefCell<Option<gio::Settings>> = const { std::cell::RefCell::new(None) };
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

fn setup_theme(window: &gtk::ApplicationWindow) {
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
    THEME_SETTINGS.with(|cell| *cell.borrow_mut() = settings);

    let w_active = window.clone();
    window.connect_is_active_notify(move |win| {
        if win.is_active() {
            apply_theme(&w_active);
        }
    });
}

fn activate(app: &gtk::Application) {
    load_css();

    let window = gtk::ApplicationWindow::builder()
        .application(app)
        .title("ChurrOS Welcome")
        .default_width(900)
        .default_height(680)
        .build();

    window.add_css_class("welcome");
    window.add_css_class("churros-glass");
    window.set_size_request(480, 400);
    setup_theme(&window);

    let header_bar = gtk::HeaderBar::new();
    header_bar.add_css_class("flat");
    window.set_titlebar(Some(&header_bar));

    let content = gtk::Box::new(gtk::Orientation::Vertical, 24);
    content.set_margin_top(20);
    content.set_margin_bottom(30);
    content.set_margin_start(24);
    content.set_margin_end(24);
    content.set_halign(gtk::Align::Center);
    content.add_css_class("welcome-content");
    content.add_css_class("welcome-root");

    content.append(&header::build());
    content.append(&cards::build());
    content.append(&footer::build());

    let scroller = gtk::ScrolledWindow::new();
    scroller.set_policy(gtk::PolicyType::Automatic, gtk::PolicyType::Automatic);
    scroller.set_vexpand(true);
    scroller.set_child(Some(&content));
    scroller.add_css_class("content-scroller");
    scroller.add_css_class("welcome-scroller");

    window.set_child(Some(&scroller));

    window.present();
}

fn main() -> glib::ExitCode {
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    // Si se pasa --live-only, la app solo debe iniciar en el entorno Live.
    // En un sistema ya instalado no debe autoiniciar al entrar a la sesión.
    let live_only = std::env::args().any(|arg| arg == "--live-only");
    let is_live = std::path::Path::new("/run/archiso").exists();
    let is_dev = std::env::var("CHURROS_DEV").is_ok();
    if live_only && !is_live && !is_dev {
        return glib::ExitCode::SUCCESS;
    }

    let app = gtk::Application::builder()
        .application_id(APP_ID)
        .build();

    app.connect_activate(activate);

    app.run()
}
