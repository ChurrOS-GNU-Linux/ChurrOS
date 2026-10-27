// ==========================================
// MakoPage — notificaciones (fuente, colores, bordes, posicion, DND)
// (equivalente a pages/mako.py)
// ==========================================


use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

use crate::services::mako_config::MakoConfig;
use crate::widgets::color_picker::ColorPickerRow;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

const FONT_FAMILIES: [&str; 5] = [
    "JetBrains Mono",
    "Inter",
    "Cantarell",
    "Hack",
    "Monospace",
];

struct MakoState {
    font_family: ComboRow,
    font_size: ComboRow,
    background: ColorPickerRow,
    text: ColorPickerRow,
    border_color: ColorPickerRow,
    border_size: SliderRow,
    border_radius: SliderRow,
    anchor: ComboRow,
    width: SliderRow,
    margin: SliderRow,
    pad_v: SliderRow,
    pad_h: SliderRow,
    timeout: SliderRow,
    markup: SwitchRow,
    actions: SwitchRow,
    icons: SwitchRow,
    history: SwitchRow,
    max_icon: SliderRow,
    dnd_status: Row,
}

type MakoStateRef = Rc<RefCell<MakoState>>;

struct Scheduler {
    pending: bool,
}

/// makoctl mode — salida cruda (equivalente al subprocess del Python).
fn makoctl_mode() -> String {
    // Con timeout vía churros_services::run: nunca quedarse bloqueado en UI.
    churros_services::run(&["makoctl", "mode"], 1000)
        .map(|(_, stdout, _)| stdout)
        .unwrap_or_default()
}

/// ¿Está activo el modo do-not-disturb?
fn is_dnd_active() -> bool {
    makoctl_mode().contains("do-not-disturb")
}

/// Texto de estado de makoctl (equivalente a _dnd_status_text).
fn dnd_status_text() -> String {
    let output = makoctl_mode().trim().to_string();
    if !output.is_empty() {
        format!("Modos activos: {output}")
    } else {
        "Sin modos activos".to_string()
    }
}

/// Debounce 400ms (equivalente a _schedule_apply + GLib.timeout_add).
fn schedule(holder: &Rc<RefCell<Option<MakoStateRef>>>, scheduler: &Rc<RefCell<Scheduler>>) {
    if scheduler.borrow().pending {
        return;
    }
    scheduler.borrow_mut().pending = true;

    let h = Rc::clone(holder);
    let s = Rc::clone(scheduler);
    glib::timeout_add_local(Duration::from_millis(400), move || {
        s.borrow_mut().pending = false;

        if let Some(state) = h.borrow().as_ref() {
            let st = state.borrow();

            let font = format!(
                "{}:size={}",
                st.font_family.value().unwrap_or_default(),
                st.font_size.value().unwrap_or_default()
            );

            MakoConfig::set_font(&font);
            MakoConfig::set_appearance(
                Some(&st.background.get_value()),
                Some(&st.text.get_value()),
                Some(&st.border_color.get_value()),
                Some(st.border_size.get_value() as i64),
                Some(st.border_radius.get_value() as i64),
            );
            MakoConfig::set_layout(
                Some(&format!(
                    "{},{}",
                    st.pad_h.get_value() as i64,
                    st.pad_v.get_value() as i64
                )),
                Some(st.margin.get_value() as i64),
                Some((st.timeout.get_value() * 1000.0) as i64),
                Some(st.width.get_value() as i64),
            );
            MakoConfig::set_anchor(st.anchor.value().unwrap_or_default().as_str());
            MakoConfig::set_behaviors(
                Some(st.markup.get_active()),
                Some(st.actions.get_active()),
                Some(st.icons.get_active()),
                Some(st.history.get_active()),
                Some(st.max_icon.get_value() as i64),
            );
            MakoConfig::reload();
        }

        glib::ControlFlow::Break
    });
}

fn cb_str(
    holder: &Rc<RefCell<Option<MakoStateRef>>>,
    scheduler: &Rc<RefCell<Scheduler>>,
) -> Box<dyn Fn(&str)> {
    let h = Rc::clone(holder);
    let s = Rc::clone(scheduler);
    Box::new(move |_| schedule(&h, &s))
}

fn cb_f64(
    holder: &Rc<RefCell<Option<MakoStateRef>>>,
    scheduler: &Rc<RefCell<Scheduler>>,
) -> Box<dyn Fn(f64)> {
    let h = Rc::clone(holder);
    let s = Rc::clone(scheduler);
    Box::new(move |_| schedule(&h, &s))
}

fn cb_bool(
    holder: &Rc<RefCell<Option<MakoStateRef>>>,
    scheduler: &Rc<RefCell<Scheduler>>,
) -> Box<dyn Fn(bool)> {
    let h = Rc::clone(holder);
    let s = Rc::clone(scheduler);
    Box::new(move |_| schedule(&h, &s))
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Mako",
        Some("Configura las notificaciones (fuente, colores, bordes, posicion)"),
        Some("appearance".to_string()),
    );

    let values = serde_json::json!({
        "font": MakoConfig::get_font(),
        "background_color": MakoConfig::get_background_color(),
        "text_color": MakoConfig::get_text_color(),
        "border_color": MakoConfig::get_border_color(),
        "border_size": MakoConfig::get_border_size(),
        "border_radius": MakoConfig::get_border_radius(),
        "padding": MakoConfig::get_padding(),
        "margin": MakoConfig::get_margin(),
        "default_timeout": MakoConfig::get_default_timeout(),
        "width": MakoConfig::get_width(),
        "anchor": MakoConfig::get_anchor(),
        "markup": MakoConfig::get_markup(),
        "actions": MakoConfig::get_actions(),
        "icons": MakoConfig::get_icons(),
        "history": MakoConfig::get_history(),
        "max_icon_size": MakoConfig::get_max_icon_size(),
    });

    // Fuente actual: "Familia:size=Tamano" (partition(":size=") del Python)
    let current_font = values["font"].as_str().unwrap_or("");
    let (current_family, current_size) = match current_font.find(":size=") {
        Some(i) => (
            current_font[..i].to_string(),
            current_font[i + 6..]
                .split(':')
                .next()
                .unwrap_or("11")
                .to_string(),
        ),
        None => (
            String::new(),
            if current_font.is_empty() {
                "11".to_string()
            } else {
                current_font.split(':').next().unwrap_or("").to_string()
            },
        ),
    };

    let sizes: Vec<String> = (8..22).map(|s| s.to_string()).collect();
    let size_refs: Vec<&str> = sizes.iter().map(|s| s.as_str()).collect();

    // Padding "12,16" -> (h, v)
    let padding = values["padding"].as_str().unwrap_or("12,16");
    let (pad_h_val, pad_v_val): (i64, i64) = match padding
        .split(',')
        .map(|p| p.trim())
        .collect::<Vec<&str>>()
        .as_slice()
    {
        [h] => match h.parse() {
            Ok(v) => (v, v),
            Err(_) => (12, 16),
        },
        [h, v, ..] => match (h.parse(), v.parse()) {
            (Ok(h), Ok(v)) => (h, v),
            _ => (12, 16),
        },
        _ => (12, 16),
    };

    let holder: Rc<RefCell<Option<MakoStateRef>>> = Rc::new(RefCell::new(None));
    let scheduler: Rc<RefCell<Scheduler>> = Rc::new(RefCell::new(Scheduler { pending: false }));

    // Tipografia
    let font_family = ComboRow::new(
        "Familia",
        &FONT_FAMILIES,
        Some(&current_family),
        None,
        None,
        Some(cb_str(&holder, &scheduler)),
    );
    let font_size = ComboRow::new(
        "Tamano",
        &size_refs,
        Some(&current_size),
        None,
        None,
        Some(cb_str(&holder, &scheduler)),
    );

    let mut font_group = Group::new("Tipografia");
    font_group.add(&font_family);
    font_group.add(&font_size);
    page.add(font_group.widget());

    // Colores
    let background = ColorPickerRow::new(
        "Fondo",
        values["background_color"].as_str().unwrap_or("#1e1e2e"),
        Some(cb_str(&holder, &scheduler)),
        None,
    );
    let text = ColorPickerRow::new(
        "Texto",
        values["text_color"].as_str().unwrap_or("#cdd6f4"),
        Some(cb_str(&holder, &scheduler)),
        None,
    );
    let border_color = ColorPickerRow::new(
        "Borde",
        values["border_color"].as_str().unwrap_or("#38bdf8"),
        Some(cb_str(&holder, &scheduler)),
        None,
    );

    let mut colors_group = Group::new("Colores");
    colors_group.add(&background);
    colors_group.add(&text);
    colors_group.add(&border_color);
    page.add(colors_group.widget());

    // Bordes
    let border_size = SliderRow::new(
        "Grosor del borde",
        None,
        Some("Ancho en pixeles (0 = sin borde)"),
        0.0,
        8.0,
        1.0,
        values["border_size"].as_f64().unwrap_or(2.0),
        Some(cb_f64(&holder, &scheduler)),
    );
    let border_radius = SliderRow::new(
        "Radio de las esquinas",
        None,
        Some("Redondez en pixeles"),
        0.0,
        24.0,
        1.0,
        values["border_radius"].as_f64().unwrap_or(8.0),
        Some(cb_f64(&holder, &scheduler)),
    );

    let mut borders_group = Group::new("Bordes");
    borders_group.add(&border_size);
    borders_group.add(&border_radius);
    page.add(borders_group.widget());

    // Disposicion
    let anchors = [
        "top-right",
        "top-center",
        "top-left",
        "bottom-right",
        "bottom-center",
        "bottom-left",
        "center",
    ];
    let anchor = ComboRow::new(
        "Posicion",
        &anchors,
        Some(values["anchor"].as_str().unwrap_or("top-right")),
        None,
        None,
        Some(cb_str(&holder, &scheduler)),
    );
    let width = SliderRow::new(
        "Ancho",
        None,
        Some("Ancho de las notificaciones (px)"),
        200.0,
        600.0,
        10.0,
        values["width"].as_f64().unwrap_or(380.0),
        Some(cb_f64(&holder, &scheduler)),
    );
    let margin = SliderRow::new(
        "Margen exterior",
        None,
        Some("Separacion desde el borde de la pantalla (px)"),
        0.0,
        64.0,
        1.0,
        values["margin"].as_f64().unwrap_or(8.0),
        Some(cb_f64(&holder, &scheduler)),
    );

    let mut layout_group = Group::new("Disposicion");
    layout_group.add(&anchor);
    layout_group.add(&width);
    layout_group.add(&margin);
    page.add(layout_group.widget());

    // Padding interno
    let pad_v = SliderRow::new(
        "Padding vertical",
        None,
        None,
        0.0,
        32.0,
        1.0,
        pad_v_val as f64,
        Some(cb_f64(&holder, &scheduler)),
    );
    let pad_h = SliderRow::new(
        "Padding horizontal",
        None,
        None,
        0.0,
        48.0,
        1.0,
        pad_h_val as f64,
        Some(cb_f64(&holder, &scheduler)),
    );

    let mut padding_group = Group::new("Padding interno");
    padding_group.add(&pad_v);
    padding_group.add(&pad_h);
    page.add(padding_group.widget());

    // Comportamiento
    let timeout = SliderRow::new(
        "Tiempo visible (segundos)",
        None,
        Some("Duracion por defecto antes de ocultar"),
        1.0,
        30.0,
        1.0,
        values["default_timeout"].as_f64().unwrap_or(5000.0) / 1000.0,
        Some(cb_f64(&holder, &scheduler)),
    );
    let markup = SwitchRow::new(
        "Permitir markup",
        None,
        Some("Interpreta etiquetas HTML en el texto"),
        values["markup"].as_bool().unwrap_or(true),
        Some(cb_bool(&holder, &scheduler)),
    );
    let actions = SwitchRow::new(
        "Acciones",
        None,
        Some("Permite botones accionables en las notificaciones"),
        values["actions"].as_bool().unwrap_or(true),
        Some(cb_bool(&holder, &scheduler)),
    );
    let icons = SwitchRow::new(
        "Iconos",
        None,
        Some("Muestra el icono de la aplicacion"),
        values["icons"].as_bool().unwrap_or(true),
        Some(cb_bool(&holder, &scheduler)),
    );
    let history = SwitchRow::new(
        "Historial",
        None,
        Some("Guarda notificaciones pasadas"),
        values["history"].as_bool().unwrap_or(true),
        Some(cb_bool(&holder, &scheduler)),
    );
    let max_icon = SliderRow::new(
        "Tamano maximo de icono",
        None,
        Some("En pixeles"),
        16.0,
        128.0,
        4.0,
        values["max_icon_size"].as_f64().unwrap_or(48.0),
        Some(cb_f64(&holder, &scheduler)),
    );

    let mut behavior_group = Group::new("Comportamiento");
    behavior_group.add(&timeout);
    behavior_group.add(&markup);
    behavior_group.add(&actions);
    behavior_group.add(&icons);
    behavior_group.add(&history);
    behavior_group.add(&max_icon);
    page.add(behavior_group.widget());

    // Acciones
    let mut actions_group = Group::new("Acciones");

    actions_group.add(&Row::new(
        "Recargar Mako",
        Some("Aplica los cambios a las notificaciones"),
        Some("mako.svg"),
        None,
        None,
        Some(Box::new(|_| MakoConfig::reload())),
    ));

    page.add(actions_group.widget());

    // Estado actual (Do Not Disturb)
    let mut state_group = Group::new("Estado actual");

    let dnd_active = is_dnd_active();
    let dnd_switch = SwitchRow::new(
        "No molestar",
        None,
        Some("Silencia todas las notificaciones entrantes"),
        dnd_active,
        Some(cb_dnd(&holder)),
    );

    state_group.add(&dnd_switch);

    let dnd_status = Row::new(
        "Estado de makoctl",
        Some(&dnd_status_text()),
        Some("mako.svg"),
        None,
        None,
        None,
    );

    state_group.add(&dnd_status);
    page.add(state_group.widget());

    *holder.borrow_mut() = Some(Rc::new(RefCell::new(MakoState {
        font_family,
        font_size,
        background,
        text,
        border_color,
        border_size,
        border_radius,
        anchor,
        width,
        margin,
        pad_v,
        pad_h,
        timeout,
        markup,
        actions,
        icons,
        history,
        max_icon,
        dnd_status,
    })));

    page
}

/// Callback del switch de DND (equivalente a _on_dnd_toggle).
fn cb_dnd(holder: &Rc<RefCell<Option<MakoStateRef>>>) -> Box<dyn Fn(bool)> {
    let h = Rc::clone(holder);
    Box::new(move |active: bool| {
        let current = makoctl_mode();
        let is_active = current.contains("do-not-disturb");

        if active && !is_active {
            let _ = std::process::Command::new("makoctl")
                .args(["mode", "-a", "do-not-disturb"])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
        } else if !active && is_active {
            let _ = std::process::Command::new("makoctl")
                .args(["mode", "-r", "do-not-disturb"])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
        }

        // GLib.timeout_add(300, ...) del Python: refresca el subtitulo
        let h2 = Rc::clone(&h);
        glib::timeout_add_local(Duration::from_millis(300), move || {
            if let Some(state) = h2.borrow().as_ref() {
                let st = state.borrow();
                st.dnd_status.set_subtitle(&dnd_status_text());
            }
            glib::ControlFlow::Break
        });
    })
}
