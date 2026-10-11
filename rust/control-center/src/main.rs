mod logging;
mod widgets;

use gtk::prelude::*;

const APP_ID: &str = "org.churros.controlcenter";

fn main() -> glib::ExitCode {
    logging::init("control-center");

    let app = gtk::Application::builder()
        .application_id(APP_ID)
        .build();
    logging::log("gtk app creada");

    app.connect_activate(|app| {
        logging::log("activate");
        load_css();
        logging::log("css cargado");
        let window = widgets::ControlCenterWindow::new(app);
        window.window().present();
        logging::log("ventana presentada");
    });

    // run() pasaría std::env::args() a GApplication (el nombre del popup
    // se interpretaría como fichero a abrir). Sin argumentos extra.
    let code = app.run_with_args(&[] as &[&str]);
    logging::log(&format!("salida code={code:?}"));
    code
}

fn load_css() {
    logging::log("cargando css");
    let Some(display) = gtk::gdk::Display::default() else {
        eprintln!("churros-control-center: no hay display Wayland/X11 disponible");
        std::process::exit(1);
    };
    logging::log("display ok");

    // CSS compartido (misma prioridad que Preferences)
    let shared = "/usr/share/churros/styles/churros.css";
    let dev_shared = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../archiso/airootfs/usr/share/churros/styles/churros.css"
    );
    let shared_path = if std::path::Path::new(shared).is_file() {
        Some(std::path::Path::new(shared))
    } else if std::path::Path::new(dev_shared).is_file() {
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
    let css = assets::css_path();
    logging::log(&format!("css local: {} existe={}", css.display(), css.is_file()));
    let provider = gtk::CssProvider::new();
    if css.is_file() {
        provider.load_from_path(css);
    } else {
        provider.load_from_string(include_str!("../assets/style.css"));
    }
    gtk::style_context_add_provider_for_display(
        &display,
        &provider,
        gtk::STYLE_PROVIDER_PRIORITY_APPLICATION + 1, // Cambiado de USER+1 a APPLICATION+1
    );

    // Accent CSS (misma prioridad que Preferences)
    let home = churros_services::home_dir();
    let accent_path = std::path::PathBuf::from(home).join(".config/churros/accent.css");
    if let Ok(css) = std::fs::read_to_string(&accent_path) {
        let provider = gtk::CssProvider::new();
        provider.load_from_string(&css);
        gtk::style_context_add_provider_for_display(
            &display,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_USER, // Más alta, igual que Preferences
        );
    }
}

mod assets {
    use std::path::PathBuf;

    const RUNTIME_ROOTS: &[&str] = &[
        "/usr/share/churros/churros-control-center/assets",
        "/usr/share/churros/churros-control-center",
    ];
    const DEV_ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/assets");

    pub fn css_path() -> PathBuf {
        for root in RUNTIME_ROOTS {
            for name in ["style.css", "assets/style.css"] {
                let p = PathBuf::from(root).join(name);
                if p.is_file() {
                    return p;
                }
            }
        }
        PathBuf::from(DEV_ROOT).join("style.css")
    }

    pub fn icon_path(name: &str) -> PathBuf {
        for root in RUNTIME_ROOTS {
            for sub in [format!("icons/{name}"), format!("assets/icons/{name}")] {
                let p = PathBuf::from(root).join(&sub);
                if p.is_file() {
                    return p;
                }
            }
        }
        PathBuf::from(DEV_ROOT).join(format!("icons/{name}"))
    }

    pub fn logo_path() -> PathBuf {
        for root in RUNTIME_ROOTS {
            for name in ["logo.svg", "assets/logo.svg"] {
                let p = PathBuf::from(root).join(name);
                if p.is_file() {
                    return p;
                }
            }
        }
        PathBuf::from(DEV_ROOT).join("logo.svg")
    }
}
