use gtk::prelude::*;

use crate::pages;

fn load_css() {
    let Some(display) = gtk::gdk::Display::default() else {
        eprintln!("churros-tour: no hay display Wayland/X11 disponible");
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
    let local = crate::assets::css_path();
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

    // Accent CSS (misma prioridad que Preferences)
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

pub fn activate(app: &gtk::Application) {
    load_css();

    let window = gtk::ApplicationWindow::builder()
        .application(app)
        .title("ChurrOS Tour")
        .default_width(900)
        .default_height(680)
        .resizable(false)
        .build();

    window.add_css_class("welcome");
    window.add_css_class("tour");
    window.add_css_class("churros-glass");
    setup_theme(&window);

    let stack = gtk::Stack::new();
    stack.set_transition_type(gtk::StackTransitionType::SlideLeftRight);
    stack.set_transition_duration(250);
    stack.set_vexpand(true);

    let welcome = pages::welcome::build();
    let shortcuts = pages::shortcuts::build();
    let customization = pages::customization::build();
    let install = pages::install::build();

    stack.add_named(&welcome, Some("welcome"));
    stack.add_named(&shortcuts, Some("shortcuts"));
    stack.add_named(&customization.root, Some("customization"));
    stack.add_named(&install.root, Some("install"));

    let action_bar = gtk::ActionBar::new();

    let back_btn = gtk::Button::with_label("Atrás");
    let next_btn = gtk::Button::with_label("Siguiente");
    next_btn.add_css_class("suggested-action");

    // Autostart checkbox at the end
    let autostart_check = gtk::CheckButton::builder()
        .label("Abrir al iniciar")
        .active(false)
        .visible(false) // Solo se muestra al final
        .build();

    action_bar.pack_start(&back_btn);
    action_bar.pack_end(&next_btn);
    action_bar.set_center_widget(Some(&autostart_check));

    back_btn.set_sensitive(false);

    let back_btn_clone = back_btn.clone();
    let next_btn_clone = next_btn.clone();
    let autostart_check_clone = autostart_check.clone();

    // Logic to update buttons when page changes
    stack.connect_visible_child_name_notify(move |s| {
        if let Some(child) = s.visible_child_name() {
            let name = child.as_str();

            back_btn_clone.set_sensitive(name != "welcome");

            if name == "install" {
                next_btn_clone.set_label("Finalizar");
                autostart_check_clone.set_visible(true);
            } else {
                next_btn_clone.set_label("Siguiente");
                autostart_check_clone.set_visible(false);
            }
        }
    });

    let stack_for_next = stack.clone();
    let window_clone = window.clone();
    let autostart_check_clone2 = autostart_check.clone();

    let install_for_next = install.clone();
    let back_for_next = back_btn.clone();
    next_btn.connect_clicked(move |next| {
        let current = stack_for_next
            .visible_child_name()
            .map(|s| s.to_string())
            .unwrap_or_default();
        match current.as_str() {
            "welcome" => stack_for_next.set_visible_child_name("shortcuts"),
            "shortcuts" => stack_for_next.set_visible_child_name("customization"),
            "customization" => {
                stack_for_next.set_visible_child_name("install");
                back_for_next.set_sensitive(false);
                next.set_sensitive(false);
                autostart_check_clone2.set_sensitive(false);
                let back = back_for_next.clone();
                let next = next.clone();
                let autostart = autostart_check_clone2.clone();
                install_for_next.start(customization.packages(), move |success| {
                    back.set_sensitive(true);
                    next.set_sensitive(true);
                    next.set_label(if success { "Finalizar" } else { "Cerrar" });
                    autostart.set_sensitive(success);
                    if !success {
                        autostart.set_active(true);
                    }
                });
            }
            "install" => match install_for_next.finish(autostart_check_clone2.is_active()) {
                Ok(()) => window_clone.close(),
                Err(e) => install_for_next
                    .show_error(&format!("No se pudo guardar el inicio del Tour: {e}")),
            },
            _ => {}
        }
    });

    let install_for_close = install.clone();
    window.connect_close_request(move |_| {
        if install_for_close.is_running() {
            install_for_close.show_error("La instalación sigue en curso. Termina o cancela la operación en la terminal antes de cerrar el Tour.");
            glib::Propagation::Stop
        } else {
            glib::Propagation::Proceed
        }
    });

    let stack_for_back = stack.clone();
    back_btn.connect_clicked(move |_| {
        let current = stack_for_back
            .visible_child_name()
            .map(|s| s.to_string())
            .unwrap_or_default();
        match current.as_str() {
            "shortcuts" => stack_for_back.set_visible_child_name("welcome"),
            "customization" => stack_for_back.set_visible_child_name("shortcuts"),
            "install" => stack_for_back.set_visible_child_name("customization"),
            _ => {}
        }
    });

    let content = gtk::Box::new(gtk::Orientation::Vertical, 0);
    content.add_css_class("tour-content");
    content.append(&stack);
    content.append(&action_bar);

    window.set_child(Some(&content));
    window.present();
}
