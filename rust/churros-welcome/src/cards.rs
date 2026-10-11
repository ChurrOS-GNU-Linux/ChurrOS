use gtk::prelude::*;

use crate::action_card;
use crate::actions;
use crate::system_card;

const CARDS: [(&str, &str, &str, fn(&gtk::Button)); 3] = [
    (
        "install.svg",
        "Install ChurrOS",
        "Instala ChurrOS en tu disco duro.",
        actions::install_clicked,
    ),
    (
        "github.svg",
        "GitHub",
        "Repositorio oficial del proyecto.",
        actions::github_clicked,
    ),
    (
        "community.svg",
        "Comunidad",
        "Unete a la comunidad de ChurrOS.",
        actions::discord_clicked,
    ),
];

pub fn build() -> gtk::FlowBox {
    let flow = gtk::FlowBox::new();

    flow.set_selection_mode(gtk::SelectionMode::None);

    // Cuatro tarjetas: la de información y las tres acciones. Con el Clamp de
    // 840 px entran dos por fila (280 px + separaciones), así que el reparto
    // real es 2x2 en ventana grande y una columna cuando se estrecha.
    flow.set_max_children_per_line(4);
    flow.set_min_children_per_line(1);

    flow.set_row_spacing(20);
    flow.set_column_spacing(20);

    flow.set_halign(gtk::Align::Center);

    flow.append(&system_card::build());

    let is_live = std::path::Path::new("/run/archiso").exists() || std::env::var("CHURROS_DEV").is_ok();

    for (icon, title, description, callback) in CARDS {
        if icon == "install.svg" && !is_live {
            continue;
        }
        flow.append(&action_card::new(icon, title, description, callback));
    }

    flow
}
