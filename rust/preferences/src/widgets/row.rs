// ==========================================
// Row — fila de configuración (botón con icono, título, subtítulo, valor)
// (equivalente a widgets/row.py)
// ==========================================

use gtk::prelude::*;

pub struct Row {
    pub button: gtk::Button,
    title_label: gtk::Label,
    subtitle_label: Option<gtk::Label>,
}

impl Row {
    pub fn new(
        title: &str,
        subtitle: Option<&str>,
        icon: Option<&str>,
        value: Option<&str>,
        suffix: Option<&gtk::Widget>,
        callback: Option<Box<dyn Fn(&gtk::Button)>>,
    ) -> Self {
        let button = gtk::Button::new();
        button.add_css_class("row");
        button.set_has_frame(false);

        let content = gtk::Box::new(gtk::Orientation::Horizontal, 14);
        content.set_margin_top(12);
        content.set_margin_bottom(12);
        content.set_margin_start(14);
        content.set_margin_end(14);

        // Icono
        if let Some(icon_name) = icon {
            let image = gtk::Image::from_file(crate::assets::icon_path(icon_name));
            image.set_pixel_size(22);
            content.append(&image);
        }

        // Labels
        let labels = gtk::Box::new(gtk::Orientation::Vertical, 2);
        labels.set_hexpand(true);

        let title_label = gtk::Label::builder()
            .label(title)
            .xalign(0.0)
            .wrap(true)
            .wrap_mode(gtk::pango::WrapMode::WordChar)
            .build();
        title_label.add_css_class("row-title");
        labels.append(&title_label);

        let mut subtitle_label = None;
        if let Some(sub) = subtitle {
            let label = gtk::Label::builder()
                .label(sub)
                .xalign(0.0)
                .wrap(true)
                .wrap_mode(gtk::pango::WrapMode::WordChar)
                .build();
            label.add_css_class("row-subtitle");
            labels.append(&label);
            subtitle_label = Some(label);
        }

        content.append(&labels);

        // Valor o widget derecho
        if let Some(val) = value {
            let value_label = gtk::Label::new(Some(val));
            value_label.add_css_class("row-value");
            content.append(&value_label);
        } else if let Some(suffix_widget) = suffix {
            content.append(suffix_widget);
        }

        button.set_child(Some(&content));

        if let Some(cb) = callback {
            button.connect_clicked(cb);
        }

        Self {
            button,
            title_label,
            subtitle_label,
        }
    }

    pub fn widget(&self) -> &gtk::Button {
        &self.button
    }

    pub fn set_title(&self, text: &str) {
        self.title_label.set_label(text);
    }

    pub fn set_subtitle(&self, text: &str) {
        if let Some(label) = &self.subtitle_label {
            label.set_label(text);
        }
    }

    /// Etiqueta del subtítulo, para actualizarla desde el propio callback de
    /// la fila sin que la fila se retenga a sí misma.
    pub fn subtitle_label(&self) -> Option<&gtk::Label> {
        self.subtitle_label.as_ref()
    }
}
