use gtk::prelude::*;

pub fn build() -> gtk::Box {
    let container = gtk::Box::new(gtk::Orientation::Vertical, 18);
    container.set_halign(gtk::Align::Center);

    // =====================================
    // Logo
    // =====================================

    let logo = gtk::Picture::for_filename(crate::assets::icons_path("logo.svg"));
    logo.set_size_request(140, 140);
    logo.set_halign(gtk::Align::Center);
    logo.add_css_class("logo");

    // =====================================
    // Título
    // =====================================

    // Los colores salen de clases CSS y no de atributos foreground del markup,
    // para que "OS" respete el acento dinámico que escriben pywal o
    // churros-settings en ~/.config/churros/accent.css (antes iba #ff8c00
    // fijo en el código, que además no coincide con el naranja de marca).
    //
    // Son dos labels y no un markup con <span class="..."> porque Pango no
    // admite el atributo class: rechaza el markup entero y el título se
    // queda en blanco. Se comprobó ejecutando la app.
    let title_box = gtk::Box::new(gtk::Orientation::Horizontal, 0);
    title_box.set_halign(gtk::Align::Center);

    let title_plain = gtk::Label::new(Some("Churr"));
    title_plain.add_css_class("app-title");
    title_plain.add_css_class("title-plain");

    let title_accent = gtk::Label::new(Some("OS"));
    title_accent.add_css_class("app-title");
    title_accent.add_css_class("title-accent");

    title_box.append(&title_plain);
    title_box.append(&title_accent);

    // =====================================
    // Subtítulo
    // =====================================

    let subtitle = gtk::Label::new(Some(
        "Bienvenido a ChurrOS\nUna distribución Linux basada en Arch Linux.",
    ));
    subtitle.set_max_width_chars(48);
    subtitle.set_halign(gtk::Align::Center);
    subtitle.set_justify(gtk::Justification::Center);
    subtitle.set_wrap(true); // wrap en pantallas pequeñas
    subtitle.add_css_class("subtitle");

    // =====================================
    // Separador
    // =====================================

    let separator = gtk::Separator::new(gtk::Orientation::Horizontal);
    separator.set_margin_top(15);
    separator.set_margin_bottom(15);

    // =====================================
    // Construcción
    // =====================================

    container.append(&logo);
    container.append(&title_box);
    container.append(&subtitle);
    container.append(&separator);

    container
}
