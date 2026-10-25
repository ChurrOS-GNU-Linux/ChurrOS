use gtk::prelude::*;

pub fn build() -> gtk::Box {
    let container = gtk::Box::new(gtk::Orientation::Vertical, 8);
    container.set_halign(gtk::Align::Center);

    let is_live = std::path::Path::new("/run/archiso").exists();
    let is_dev = std::env::var("CHURROS_DEV").is_ok();

    if !is_live && !is_dev {
        let home = churros_services::home_dir();
        let no_welcome = std::path::PathBuf::from(home).join(".config/churros/no-welcome");
        let check = gtk::CheckButton::with_label("Mostrar esta ventana al iniciar sesión");
        check.set_active(!no_welcome.exists());
        check.add_css_class("welcome-autostart-check");
        check.connect_toggled(move |btn| {
            let active = btn.is_active();
            let home = churros_services::home_dir();
            let conf_dir = std::path::PathBuf::from(home).join(".config/churros");
            let _ = std::fs::create_dir_all(&conf_dir);
            let no_welcome = conf_dir.join("no-welcome");
            if active {
                let _ = std::fs::remove_file(no_welcome);
            } else {
                let _ = std::fs::write(no_welcome, "1\n");
            }
        });
        container.append(&check);
    }

    let footer = gtk::Label::new(Some(&format!(
        "Linux • {} • ChurrOS {}",
        churros_services::version::desktop_name(),
        churros_services::version::distro()
    )));

    footer.add_css_class("footer");
    footer.set_halign(gtk::Align::Center);

    container.append(&footer);

    container
}

