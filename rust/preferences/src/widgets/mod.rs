pub mod churr;
pub mod color_picker;
pub mod combo_row;
pub mod group;
pub mod navigation_row;
pub mod page;
pub mod row;
pub mod search;
pub mod select_row;
pub mod sidebar;
pub mod sidebar_item;
pub mod slider_row;
pub mod switch_row;

use gtk::prelude::*;

/// Trait para widgets envueltos (Row, Group, ...): expone el widget GTK
/// interno para poder añadirlos a contenedores.
pub trait AsWidget {
    fn widget(&self) -> &gtk::Widget;
}

impl AsWidget for row::Row {
    fn widget(&self) -> &gtk::Widget {
        self.button.upcast_ref()
    }
}

impl AsWidget for group::Group {
    fn widget(&self) -> &gtk::Widget {
        self.root.upcast_ref()
    }
}

impl AsWidget for sidebar_item::SidebarItem {
    fn widget(&self) -> &gtk::Widget {
        self.button.upcast_ref()
    }
}

impl AsWidget for page::Page {
    fn widget(&self) -> &gtk::Widget {
        self.scrolled.upcast_ref()
    }
}

// Widgets GTK crudos (upcast_ref::<gtk::Widget>) también son aceptables
impl AsWidget for gtk::Widget {
    fn widget(&self) -> &gtk::Widget {
        self
    }
}

impl AsWidget for select_row::SelectRow {
    fn widget(&self) -> &gtk::Widget {
        self.row.widget().upcast_ref()
    }
}

impl AsWidget for switch_row::SwitchRow {
    fn widget(&self) -> &gtk::Widget {
        self.row.widget().upcast_ref()
    }
}

impl AsWidget for slider_row::SliderRow {
    fn widget(&self) -> &gtk::Widget {
        self.row.widget().upcast_ref()
    }
}
