use gtk::prelude::*;

use churros_tour::catalog::{CATEGORIES, PRESETS, PROFILE_NAMES, Selection};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

pub struct CustomizationPage {
    pub root: gtk::Box,
    selection: Rc<RefCell<Selection>>,
}

impl CustomizationPage {
    pub fn packages(&self) -> Vec<String> {
        self.selection.borrow().packages()
    }
}

pub fn build() -> CustomizationPage {
    let selection = Rc::new(RefCell::new(Selection::default()));
    let applying_profile = Rc::new(Cell::new(false));
    let profile = gtk::DropDown::from_strings(PROFILE_NAMES);
    profile.set_selected(0);
    profile.set_tooltip_text(Some(
        "Elige un perfil o Personalizado para seleccionar cada aplicación.",
    ));
    profile.update_property(&[gtk::accessible::Property::Label("Perfil de uso")]);
    let mut buttons = Vec::new();
    let mut expanders = Vec::new();
    let container = gtk::Box::new(gtk::Orientation::Vertical, 10);
    container.set_valign(gtk::Align::Center);
    container.set_halign(gtk::Align::Center);

    let title = gtk::Label::new(Some("¿Para qué usarás tu sistema?"));
    title.add_css_class("page-title");
    title.set_halign(gtk::Align::Center);

    let subtitle = gtk::Label::new(Some(
        "Despliega cada grupo y selecciona las herramientas que deseas instalar.",
    ));
    subtitle.add_css_class("page-subtitle");
    subtitle.set_halign(gtk::Align::Center);

    // Make the list scrollable in case there are many items
    let scrolled_window = gtk::ScrolledWindow::new();
    scrolled_window.set_policy(gtk::PolicyType::Never, gtk::PolicyType::Automatic);
    scrolled_window.set_min_content_height(400); // Give it some height
    scrolled_window.set_vexpand(true);

    let categories_box = gtk::Box::new(gtk::Orientation::Vertical, 10);
    categories_box.set_margin_start(32);
    categories_box.set_margin_end(32);

    for &(name, desc, pkgs) in CATEGORIES {
        let expander = gtk::Expander::new(None);
        expander.set_expanded(true);
        expander.add_css_class("category-expander");

        let header_box = gtk::Box::new(gtk::Orientation::Vertical, 2);
        header_box.set_margin_top(4);
        header_box.set_margin_bottom(4);
        let title_lbl = gtk::Label::new(Some(name));
        title_lbl.set_halign(gtk::Align::Start);
        title_lbl.add_css_class("expander-title");
        let desc_lbl = gtk::Label::new(Some(desc));
        desc_lbl.set_halign(gtk::Align::Start);
        desc_lbl.add_css_class("expander-subtitle");
        header_box.append(&title_lbl);
        header_box.append(&desc_lbl);
        expander.set_label_widget(Some(&header_box));

        let sub_list = gtk::ListBox::new();
        sub_list.set_selection_mode(gtk::SelectionMode::None);
        sub_list.add_css_class("sub-list");

        for &(pkg_id, pkg_name) in pkgs {
            let row = gtk::ListBoxRow::new();
            row.set_activatable(false);
            row.set_selectable(false);
            row.add_css_class("pkg-row");

            let row_box = gtk::Box::new(gtk::Orientation::Horizontal, 12);
            row_box.set_margin_top(6);
            row_box.set_margin_bottom(6);
            row_box.set_margin_start(12);
            row_box.set_margin_end(12);

            let check_btn = gtk::CheckButton::new();
            check_btn.set_valign(gtk::Align::Center);

            check_btn.update_property(&[gtk::accessible::Property::Label(pkg_name)]);
            let selected = selection.clone();
            let applying = applying_profile.clone();
            let profile_weak = profile.downgrade();
            check_btn.connect_toggled(move |btn| {
                selected.borrow_mut().set(pkg_id, btn.is_active());
                if !applying.get()
                    && let Some(profile) = profile_weak.upgrade()
                {
                    // Editing a preset becomes custom without clearing the selection.
                    profile.set_selected(0);
                }
            });
            buttons.push((pkg_id, check_btn.clone()));

            let text_box = gtk::Box::new(gtk::Orientation::Vertical, 2);
            text_box.set_hexpand(true);
            let name_lbl = gtk::Label::new(Some(pkg_name));
            name_lbl.set_halign(gtk::Align::Start);
            name_lbl.add_css_class("pkg-title");
            let id_lbl = gtk::Label::new(Some(pkg_id));
            id_lbl.set_halign(gtk::Align::Start);
            id_lbl.add_css_class("pkg-id");

            text_box.append(&name_lbl);
            text_box.append(&id_lbl);

            row_box.append(&check_btn);
            row_box.append(&text_box);
            row.set_child(Some(&row_box));
            sub_list.append(&row);
        }

        expander.set_child(Some(&sub_list));
        categories_box.append(&expander);
        expanders.push(expander);
    }

    profile.connect_selected_notify(move |profile| {
        let index = profile.selected() as usize;
        if let Some(preset) = PRESETS.get(index).filter(|_| index != 0) {
            applying_profile.set(true);
            for (id, button) in &buttons {
                button.set_active(preset.contains(id));
            }
            applying_profile.set(false);
        }
        for expander in &expanders {
            expander.set_expanded(true);
        }
    });

    scrolled_window.set_child(Some(&categories_box));

    container.append(&title);
    container.append(&subtitle);
    container.append(&profile);
    container.append(&scrolled_window);

    CustomizationPage {
        root: container,
        selection,
    }
}
