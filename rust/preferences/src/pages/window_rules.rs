// ==========================================
// WindowRulesPage — window-rules de Niri
// (equivalente a pages/window_rules.py)
// ==========================================

use gtk::prelude::*;

use std::cell::RefCell;
use std::rc::Rc;

use crate::services::niri_config::NiriConfig;
use crate::services::window_rules_service::WindowRulesService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

// AsWidget para widgets GTK crudos añadidos a un Group
// (el Group::add acepta &impl AsWidget)
struct WBox(gtk::Box);
impl crate::widgets::AsWidget for WBox {
    fn widget(&self) -> &gtk::Widget {
        self.0.upcast_ref()
    }
}
struct WEntry(gtk::Entry);
impl crate::widgets::AsWidget for WEntry {
    fn widget(&self) -> &gtk::Widget {
        self.0.upcast_ref()
    }
}
struct WSpin(gtk::SpinButton);
impl crate::widgets::AsWidget for WSpin {
    fn widget(&self) -> &gtk::Widget {
        self.0.upcast_ref()
    }
}
struct WLabel(gtk::Label);
impl crate::widgets::AsWidget for WLabel {
    fn widget(&self) -> &gtk::Widget {
        self.0.upcast_ref()
    }
}

struct RulesState {
    app_id_entry: gtk::Entry,
    title_entry: gtk::Entry,
    opacity_spin: gtk::SpinButton,
    corner_spin: gtk::SpinButton,
    floating_switch: SwitchRow,
    clip_switch: SwitchRow,
    blur_switch: SwitchRow,
    edit_index: Option<usize>,
    update_row: Option<Row>,
    rules_list: gtk::Box,
}

type RulesStateRef = Rc<RefCell<RulesState>>;

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator.clone()),
        "Reglas de ventana",
        Some("Window-rules de Niri: opacidad, flotantes, esquinas, blur"),
        Some("appearance".to_string()),
    );

    // ---------- Lista de reglas ----------
    let mut rules_group = Group::new("Reglas definidas");

    let rules_list = gtk::Box::new(gtk::Orientation::Vertical, 8);
    rules_group.add(&WBox(rules_list.clone()));

    page.add(rules_group.widget());

    // ---------- Anadir regla ----------
    let mut add_group = Group::new("Anadir regla");

    let app_id_entry = gtk::Entry::new();
    app_id_entry.set_placeholder_text(Some("app-id, p.ej. firefox"));
    app_id_entry.set_margin_start(14);
    app_id_entry.set_margin_end(14);
    app_id_entry.set_margin_top(10);
    app_id_entry.set_margin_bottom(10);
    add_group.add(&WEntry(app_id_entry.clone()));

    let title_entry = gtk::Entry::new();
    title_entry.set_placeholder_text(Some("regex del titulo (opcional)"));
    title_entry.set_margin_start(14);
    title_entry.set_margin_end(14);
    title_entry.set_margin_bottom(10);
    add_group.add(&WEntry(title_entry.clone()));

    // Opacidad
    let opacity_box = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    opacity_box.set_margin_start(14);
    opacity_box.set_margin_end(14);
    opacity_box.set_margin_bottom(10);

    let opacity_label = gtk::Label::new(Some("Opacidad:"));
    opacity_label.set_xalign(0.0);
    opacity_label.set_hexpand(true);

    let opacity_spin = gtk::SpinButton::with_range(0.0, 1.0, 0.05);
    opacity_spin.set_value(1.0);

    opacity_box.append(&opacity_label);
    opacity_box.append(&opacity_spin);
    add_group.add(&WBox(opacity_box));

    // Radio de esquinas
    let corner_box = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    corner_box.set_margin_start(14);
    corner_box.set_margin_end(14);
    corner_box.set_margin_bottom(10);

    let corner_label = gtk::Label::new(Some("Radio de esquinas:"));
    corner_label.set_xalign(0.0);
    corner_label.set_hexpand(true);

    let corner_spin = gtk::SpinButton::with_range(0.0, 64.0, 1.0);
    corner_spin.set_value(0.0);

    corner_box.append(&corner_label);
    corner_box.append(&corner_spin);
    add_group.add(&WBox(corner_box));

    let floating_switch = SwitchRow::new(
        "Abrir como flotante",
        None,
        Some("Las ventanas que matcheen se abren como popups"),
        false,
        Some(Box::new(|_| {})),
    );
    add_group.add(&floating_switch);

    let clip_switch = SwitchRow::new(
        "Recortar al geometry-corner-radius",
        None,
        Some("clip-to-geometry"),
        false,
        Some(Box::new(|_| {})),
    );
    add_group.add(&clip_switch);

    let blur_switch = SwitchRow::new(
        "Fondo con blur (background-effect)",
        None,
        Some("Desenfoque del fondo detras de la ventana"),
        false,
        Some(Box::new(|_| {})),
    );
    add_group.add(&blur_switch);

    // Fila "Anadir regla"
    let state: RulesStateRef = Rc::new(RefCell::new(RulesState {
        app_id_entry: app_id_entry.clone(),
        title_entry: title_entry.clone(),
        opacity_spin: opacity_spin.clone(),
        corner_spin: corner_spin.clone(),
        floating_switch,
        clip_switch,
        blur_switch,
        edit_index: None,
        update_row: None,
        rules_list: rules_list.clone(),
    }));

    {
        let st = Rc::clone(&state);
        add_group.add(&Row::new(
            "Anadir regla",
            Some("Crea una nueva window-rule con estos valores"),
            Some("window_rules.svg"),
            None,
            None,
            Some(Box::new(move |_| on_add_rule(&st))),
        ));
    }

    // Fila "Guardar cambios" (oculta al inicio)
    let update_row = Row::new(
        "Guardar cambios sobre la regla seleccionada",
        Some("Actualizar la regla que estas editando"),
        Some("window_rules.svg"),
        None,
        None,
        None,
    );
    update_row.widget().set_visible(false);
    {
        let st = Rc::clone(&state);
        update_row
            .widget()
            .connect_clicked(move |_| on_update_rule(&st));
    }
    state.borrow_mut().update_row = Some(update_row);
    {
        let st = state.borrow();
        add_group.add(st.update_row.as_ref().unwrap());
    }

    page.add(add_group.widget());

    // ---------- Acciones ----------
    let mut actions_group = Group::new("Acciones");

    actions_group.add(&Row::new(
        "Recargar Niri",
        Some("Aplica los cambios forzando una transicion"),
        Some("logs.svg"),
        None,
        None,
        Some(Box::new(|_| NiriConfig::reload())),
    ));

    page.add(actions_group.widget());

    // Cargar reglas
    refresh_rules(&state);

    page
}

/// Vacía la lista y la rellena con las reglas (equivalente a _refresh_rules).
fn refresh_rules(state: &RulesStateRef) {
    let st = state.borrow();

    while let Some(child) = st.rules_list.first_child() {
        st.rules_list.remove(&child);
    }

    let rules = WindowRulesService::list_rules();
    if rules.is_empty() {
        let label = gtk::Label::new(Some("Sin reglas o error al leer config.kdl"));
        label.set_xalign(0.0);
        label.set_wrap(true);
        st.rules_list.append(&label);
        return;
    }

    if rules.is_empty() {
        let label = gtk::Label::new(Some("No hay reglas definidas."));
        label.set_xalign(0.0);
        label.add_css_class("row-subtitle");
        label.set_margin_start(14);
        label.set_margin_top(10);
        label.set_margin_bottom(10);
        st.rules_list.append(&label);
        return;
    }

    for rule in &rules {
        st.rules_list.append(&build_rule_card(state, rule));
    }
}

/// Tarjeta de regla con Editar/Borrar (equivalente a _build_rule_card).
fn build_rule_card(state: &RulesStateRef, rule: &serde_json::Value) -> gtk::Box {
    let card = gtk::Box::new(gtk::Orientation::Vertical, 6);
    card.add_css_class("row");
    card.set_margin_top(10);
    card.set_margin_bottom(10);
    card.set_margin_start(14);
    card.set_margin_end(14);

    let app_id = rule["app_id"].as_str().unwrap_or("");
    let title = rule["title"].as_str().unwrap_or("");
    let card_title = if !app_id.is_empty() || !title.is_empty() {
        if !app_id.is_empty() { app_id } else { title }
    } else {
        "(sin filtro)"
    };

    let title_label = gtk::Label::new(Some(&format!("Regla: {card_title}")));
    title_label.set_xalign(0.0);
    title_label.set_hexpand(true);
    title_label.add_css_class("row-title");
    card.append(&title_label);

    // Resumen
    let mut summary_parts: Vec<String> = Vec::new();

    if !title.is_empty() && !app_id.is_empty() {
        summary_parts.push(format!("title=\"{title}\""));
    }
    if let Some(opacity) = rule["opacity"].as_f64() {
        summary_parts.push(format!("opacity {opacity}"));
    }
    if let Some(open_floating) = rule["open_floating"].as_bool() {
        summary_parts.push(format!("open-floating {open_floating}"));
    }
    if let Some(corner_radius) = rule["corner_radius"].as_f64() {
        summary_parts.push(format!("radius {corner_radius}"));
    }
    if let Some(clip) = rule["clip_to_geometry"].as_bool() {
        summary_parts.push(format!("clip {clip}"));
    }
    if let Some(blur) = rule["blur"].as_bool() {
        summary_parts.push(format!("blur {blur}"));
    }

    let summary_text = if summary_parts.is_empty() {
        "(sin cambios)".to_string()
    } else {
        summary_parts.join(", ")
    };

    let summary = gtk::Label::new(Some(&format!("    {summary_text}")));
    summary.set_xalign(0.0);
    summary.set_hexpand(true);
    summary.add_css_class("row-subtitle");
    summary.set_wrap(true);
    card.append(&summary);

    // Acciones
    let actions = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    actions.set_halign(gtk::Align::End);

    let index = rule["index"].as_u64().unwrap_or(0) as usize;

    let edit_btn = gtk::Button::with_label("Editar");
    edit_btn.add_css_class("suggested-action");
    let st = Rc::clone(state);
    edit_btn.connect_clicked(move |_| on_edit_rule(&st, index));

    let del_btn = gtk::Button::with_label("Borrar");
    del_btn.add_css_class("destructive-action");
    let st = Rc::clone(state);
    del_btn.connect_clicked(move |btn| on_delete_rule(btn, &st, index));

    actions.append(&edit_btn);
    actions.append(&del_btn);
    card.append(&actions);

    card
}

/// Equivalente a _on_add_rule.
fn on_add_rule(state: &RulesStateRef) {
    let st = state.borrow();
    let app_id = st.app_id_entry.text().trim().to_string();
    let title = st.title_entry.text().trim().to_string();

    let opacity = st.opacity_spin.value();
    let opacity = if opacity >= 1.0 { None } else { Some(opacity) };

    let corner_radius = st.corner_spin.value();
    let corner_radius = if corner_radius == 0.0 { None } else { Some(corner_radius) };

    let open_floating = st.floating_switch.get_active().then_some(true);
    let clip_to_geometry = st.clip_switch.get_active().then_some(true);
    let blur = st.blur_switch.get_active().then_some(true);
    drop(st);

    match WindowRulesService::add_rule(
        &app_id,
        &title,
        opacity,
        open_floating,
        corner_radius,
        clip_to_geometry,
        blur,
    ) {
        _ => {}
    }

    reset_form(state);
    NiriConfig::reload();
    refresh_rules(state);
}

/// Lo que muestra el formulario: un valor por control.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct FormValues {
    pub app_id: String,
    pub title: String,
    pub opacity: f64,
    pub corner_radius: f64,
    pub open_floating: bool,
    pub clip_to_geometry: bool,
    pub blur: bool,
}

/// El formulario al pulsar Editar en `rule`: todos los controles, también
/// los que la regla no tiene (opacidad 1, radio 0, interruptor apagado,
/// como un formulario vacío). on_edit_rule solo ponía la opacidad y el radio
/// si la regla los tenía, y guardar una regla sin opacidad tras editar otra
/// con `opacity 0.8` (o tras escribirla en Añadir) le escribía esa opacidad.
pub(crate) fn form_values(rule: &Value) -> FormValues {
    FormValues {
        app_id: rule["app_id"].as_str().unwrap_or("").to_string(),
        title: rule["title"].as_str().unwrap_or("").to_string(),
        opacity: rule["opacity"].as_f64().unwrap_or(1.0),
        corner_radius: rule["corner_radius"].as_f64().unwrap_or(0.0),
        open_floating: rule["open_floating"].as_bool().unwrap_or(false),
        clip_to_geometry: rule["clip_to_geometry"].as_bool().unwrap_or(false),
        blur: rule["blur"].as_bool().unwrap_or(false),
    }
}

/// Lo que manda on_update_rule a update_rule con el formulario `form`.
/// Opacidad 1 o más, radio 0 e interruptor apagado van como null
/// (Python: get_active() or None -> None si False).
pub(crate) fn rule_payload(form: &FormValues) -> Value {
    let opacity = if form.opacity >= 1.0 { Value::Null } else { serde_json::json!(form.opacity) };
    let corner_radius = if form.corner_radius == 0.0 { Value::Null } else { serde_json::json!(form.corner_radius) };
    serde_json::json!({
        "app_id": form.app_id.trim(),
        "title": form.title.trim(),
        "opacity": opacity,
        "corner_radius": corner_radius,
        "open_floating": form.open_floating.then_some(true),
        "clip_to_geometry": form.clip_to_geometry.then_some(true),
        "blur": form.blur.then_some(true),
    })
}

/// Equivalente a _on_update_rule.
fn on_update_rule(state: &RulesStateRef) {
    let st = state.borrow();
    let Some(index) = st.edit_index else {
        return;
    };

    let updates = rule_payload(&FormValues {
        app_id: st.app_id_entry.text().to_string(),
        title: st.title_entry.text().to_string(),
        opacity: st.opacity_spin.value(),
        corner_radius: st.corner_spin.value(),
        open_floating: st.floating_switch.get_active(),
        clip_to_geometry: st.clip_switch.get_active(),
        blur: st.blur_switch.get_active(),
    });
    drop(st);

    match WindowRulesService::update_rule(index, &updates) {
        Ok(()) => {
            {
                let mut st = state.borrow_mut();
                st.edit_index = None;
                if let Some(row) = st.update_row.as_ref() {
                    row.widget().set_visible(false);
                }
            }
            reset_form(state);
            NiriConfig::reload();
            refresh_rules(state);
        }
        Err(e) => show_error(state, &e),
    }
}

use serde_json::Value;

/// Equivalente a _reset_form.
fn reset_form(state: &RulesStateRef) {
    let st = state.borrow();
    st.app_id_entry.set_text("");
    st.title_entry.set_text("");
    st.opacity_spin.set_value(1.0);
    st.corner_spin.set_value(0.0);
    st.floating_switch.set_active(false);
    st.clip_switch.set_active(false);
    st.blur_switch.set_active(false);
}

/// Equivalente a _on_delete_rule (con confirmacion).
fn on_delete_rule(btn: &gtk::Button, state: &RulesStateRef, index: usize) {
    let dialog = gtk::AlertDialog::builder()
        .message("¿Seguro que quieres borrar esta regla?")
        .modal(true)
        .buttons(["Cancelar", "Borrar"])
        .build();

    let window = btn.root().and_downcast::<gtk::Window>();
    let st = Rc::clone(state);

    dialog.choose(window.as_ref(), None::<&gio::Cancellable>, move |result| {
        let Ok(response) = result else {
            return;
        };
        if response != 1 {
            return;
        }

        match WindowRulesService::delete_rule(index) {
            Ok(()) => {
                NiriConfig::reload();
                refresh_rules(&st);
            }
            Err(e) => show_error(&st, &e),
        }
    });
}

/// Equivalente a _on_edit_rule: rellena el formulario con la regla.
fn on_edit_rule(state: &RulesStateRef, index: usize) {
    let rules = WindowRulesService::list_rules();
    if rules.is_empty() {
        return;
    }

    let Some(match_rule) = rules.iter().find(|r| r["index"].as_u64() == Some(index as u64)) else {
        return;
    };

    // Todos los controles, sin condiciones: lo que no se pone se queda con
    // lo de la regla editada antes.
    let form = form_values(match_rule);
    let st = state.borrow();
    st.app_id_entry.set_text(&form.app_id);
    st.title_entry.set_text(&form.title);
    st.opacity_spin.set_value(form.opacity);
    st.corner_spin.set_value(form.corner_radius);
    st.floating_switch.set_active(form.open_floating);
    st.clip_switch.set_active(form.clip_to_geometry);
    st.blur_switch.set_active(form.blur);
    drop(st);

    state.borrow_mut().edit_index = Some(index);
    if let Some(row) = state.borrow().update_row.as_ref() {
        row.widget().set_visible(true);
    }
}

/// Dialogo de error (equivalente al Gtk.AlertDialog del Python).
fn show_error(state: &RulesStateRef, message: &str) {
    let dialog = gtk::AlertDialog::builder()
        .message(message)
        .build();

    // Necesitamos un parent: usamos la raiz de cualquier widget del estado
    let root = state
        .borrow()
        .rules_list
        .root()
        .and_downcast::<gtk::Window>();
    dialog.show(root.as_ref());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::services::test_support::{skel_niri_config, TempHome};

    #[test]
    fn editing_a_rule_after_another_saves_it_unchanged() {
        // Editar foot (opacity 0.8) y después pavucontrol (sin opacidad ni
        // radio) y guardar le escribía `opacity 0.8` a pavucontrol: el
        // formulario se quedaba con lo de la regla anterior (o con lo
        // escrito en Añadir regla). Al pulsar Editar, cada control toma el
        // valor de la regla o el de un formulario vacío.
        let skel = skel_niri_config();
        let home = TempHome::new("rules-edit-edit", &skel);
        let rules = WindowRulesService::list_rules();
        let position = |id: &str| rules.iter().position(|r| r["app_id"] == id).expect("regla del skel");
        let (foot, pavucontrol) = (position("foot"), position("pavucontrol"));

        let form = form_values(&rules[foot]);
        assert_eq!((form.opacity, form.blur), (0.8, true), "form_values no lee la regla de foot");
        let form = form_values(&rules[pavucontrol]);
        assert_eq!(
            form,
            FormValues {
                app_id: "pavucontrol".to_string(),
                title: String::new(),
                opacity: 1.0,
                corner_radius: 0.0,
                open_floating: true,
                clip_to_geometry: false,
                blur: false,
            },
            "el formulario de pavucontrol no es el de un formulario vacío con lo que tiene la regla"
        );
        WindowRulesService::update_rule(pavucontrol, &rule_payload(&form)).unwrap();
        assert_eq!(home.read(), skel, "guardar pavucontrol sin cambios tras editar foot cambia config.kdl");
    }
}
