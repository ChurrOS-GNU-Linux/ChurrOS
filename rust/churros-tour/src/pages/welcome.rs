use gtk::prelude::*;

pub fn build() -> gtk::Box {
    let container = gtk::Box::new(gtk::Orientation::Vertical, 10);
    container.set_valign(gtk::Align::Center);
    container.set_halign(gtk::Align::Center);
    
    // =====================================
    // Logo
    // =====================================

    let logo = gtk::Picture::for_filename(crate::assets::image_path("churr.png"));
    logo.set_size_request(250, 250);
    logo.set_halign(gtk::Align::Center);
    logo.add_css_class("logo");

    // =====================================
    // Título
    // =====================================

    let title = gtk::Label::new(None);
    title.set_markup(
        "<span foreground='white'>¡Bienvenido a Churr</span><span foreground='#ff8c00'>OS</span><span foreground='white'>!</span>",
    );
    title.add_css_class("title");
    title.set_halign(gtk::Align::Center);

    // =====================================
    // Subtítulo
    // =====================================

    let subtitle = gtk::Label::new(Some(
        "Gracias por instalar ChurrOS.\nEn este breve tour te mostraremos lo básico para empezar\ny configuraremos tu sistema según tus necesidades.",
    ));
    subtitle.set_halign(gtk::Align::Center);
    subtitle.set_justify(gtk::Justification::Center);
    subtitle.set_wrap(true); // wrap en pantallas pequeñas
    subtitle.add_css_class("subtitle");

    container.append(&logo);
    container.append(&title);
    container.append(&subtitle);
    
    container
}
