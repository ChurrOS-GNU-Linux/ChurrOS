use gtk::prelude::*;

pub fn build() -> gtk::Box {
    let container = gtk::Box::new(gtk::Orientation::Vertical, 10);
    container.set_valign(gtk::Align::Center);
    container.set_halign(gtk::Align::Center);

    let ed = churros_services::version::edition();

    let (title, description, shortcuts) = if ed == "kde" {
        (
            "Atajos de Teclado (KDE Plasma)",
            "Conoce los atajos más importantes para moverte rápido por ChurrOS KDE:",
            vec![
                ("Super", "Abrir menú de aplicaciones (Kickoff)"),
                ("Super + T", "Abrir Terminal (Konsole)"),
                ("Super + E", "Abrir Archivos (Dolphin)"),
                ("Super + Q / Alt + F4", "Cerrar ventana actual"),
                ("Super + Flechas", "Ajustar / Posicionar ventana"),
                ("Alt + Tab", "Cambiar de ventana"),
                ("Super + L", "Bloquear pantalla"),
            ],
        )
    } else if ed == "xfce" || ed == "server" {
        (
            "Atajos de Teclado (Xfce)",
            "Conoce los atajos más importantes para moverte rápido por ChurrOS:",
            vec![
                ("Super", "Abrir menú de aplicaciones"),
                ("Super + T", "Abrir Terminal"),
                ("Super + Q", "Cerrar ventana actual"),
                ("Alt + Tab", "Cambiar de ventana"),
                ("Super + L", "Bloquear pantalla"),
            ],
        )
    } else {
        (
            "Atajos de Teclado (Niri)",
            "ChurrOS con Niri se maneja principalmente por teclado. Aquí tienes los atajos más importantes:",
            vec![
                ("Super + T", "Abrir Terminal (Foot)"),
                ("Super + Q", "Cerrar ventana actual"),
                ("Super + D", "Abrir lanzador de aplicaciones (Fuzzel)"),
                ("Super + Flechas", "Mover el foco entre ventanas"),
                ("Super + Shift + Flechas", "Mover ventana"),
                ("Super + F", "Pantalla completa"),
            ],
        )
    };

    let title_label = gtk::Label::new(Some(title));
    title_label.add_css_class("page-title");
    title_label.set_halign(gtk::Align::Center);

    let subtitle = gtk::Label::new(Some(description));
    subtitle.add_css_class("page-subtitle");
    subtitle.set_halign(gtk::Align::Center);
    subtitle.set_wrap(true);
    subtitle.set_justify(gtk::Justification::Center);

    let listbox = gtk::ListBox::new();
    listbox.add_css_class("boxed-list");
    listbox.set_margin_start(32);
    listbox.set_margin_end(32);
    listbox.set_selection_mode(gtk::SelectionMode::None);

    for (keys, action) in shortcuts {
        let row = gtk::ListBoxRow::new();
        row.set_activatable(false);
        row.set_selectable(false);
        row.add_css_class("shortcut-row");

        let row_box = gtk::Box::new(gtk::Orientation::Horizontal, 16);
        row_box.set_margin_top(8);
        row_box.set_margin_bottom(8);
        row_box.set_margin_start(16);
        row_box.set_margin_end(16);

        let action_lbl = gtk::Label::new(Some(action));
        action_lbl.set_halign(gtk::Align::Start);
        action_lbl.set_hexpand(true);
        action_lbl.add_css_class("shortcut-action");

        let keys_lbl = gtk::Label::new(Some(keys));
        keys_lbl.set_halign(gtk::Align::End);
        keys_lbl.add_css_class("shortcut-keys");

        row_box.append(&action_lbl);
        row_box.append(&keys_lbl);
        row.set_child(Some(&row_box));
        listbox.append(&row);
    }

    container.append(&title_label);
    container.append(&subtitle);
    container.append(&listbox);

    container
}
