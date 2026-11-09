// ==========================================
// NightLightPage — luz nocturna / wlsunset (equivalente a pages/night_light.py)
// ==========================================

use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

use gtk::prelude::*;

use crate::services::night_light::NightLightService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

// Estado compartido: (slider_dia, slider_noche, slider_gamma)
type Sliders = Rc<RefCell<(Option<SliderRow>, Option<SliderRow>, Option<SliderRow>)>>;
// Estado compartido: (entry_lat, entry_lng)
type Entries = Rc<RefCell<(Option<gtk::Entry>, Option<gtk::Entry>)>>;

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Luz nocturna",
        Some("Temperatura de color y filtro de luz azul"),
        Some("appearance".to_string()),
    );

    // Debounce (equivalente a self._pending)
    let pending: Rc<RefCell<bool>> = Rc::new(RefCell::new(false));

    if !NightLightService::is_available() {
        let mut warn = Group::new("No disponible");
        warn.add(&Row::new(
            "wlsunset no esta instalado",
            Some("Para activar la luz nocturna necesitas el paquete wlsunset"),
            Some("night_light.svg"),
            None,
            None,
            None,
        ));
        page.add(warn.widget());
        return page;
    }

    // ===== Estado =====
    let mut state_group = Group::new("Estado");

    let status_row: Rc<RefCell<Option<Row>>> = Rc::new(RefCell::new(None));

    let status_cb = Rc::clone(&status_row);
    state_group.add(&SwitchRow::new(
        "Activar luz nocturna",
        None,
        Some("Ajusta la temperatura del color segun la hora del dia"),
        NightLightService::is_enabled(),
        Some(Box::new(move |value| {
            NightLightService::set_enabled(value);
            refresh_status(&status_cb);
        })),
    ));

    let status = Row::new(
        "Estado",
        Some(&status_text()),
        Some("night_light.svg"),
        None,
        None,
        None,
    );
    *status_row.borrow_mut() = Some(status);
    state_group.add(status_row.borrow().as_ref().unwrap());

    page.add(state_group.widget());

    // ===== Temperatura de color =====
    let mut temp_group = Group::new("Temperatura de color");

    let sliders: Sliders = Rc::new(RefCell::new((None, None, None)));

    let pending_cb = Rc::clone(&pending);
    let sliders_cb = Rc::clone(&sliders);
    let day_slider = SliderRow::new(
        "Temperatura de dia",
        None,
        Some("Color en Kelvin durante el dia (6500K = neutro)"),
        3500.0,
        10000.0,
        100.0,
        NightLightService::get_temp_day(),
        Some(Box::new(move |_| {
            schedule_apply(&pending_cb, &sliders_cb);
        })),
    );

    let pending_cb = Rc::clone(&pending);
    let sliders_cb = Rc::clone(&sliders);
    let night_slider = SliderRow::new(
        "Temperatura de noche",
        None,
        Some("Color en Kelvin durante la noche (mas bajo = mas calido)"),
        2500.0,
        6500.0,
        100.0,
        NightLightService::get_temp_night(),
        Some(Box::new(move |_| {
            schedule_apply(&pending_cb, &sliders_cb);
        })),
    );

    temp_group.add(&day_slider.row);
    temp_group.add(&night_slider.row);

    page.add(temp_group.widget());

    // ===== Gamma =====
    let mut gamma_group = Group::new("Gamma");

    let pending_cb = Rc::clone(&pending);
    let sliders_cb = Rc::clone(&sliders);
    let gamma_slider = SliderRow::new(
        "Intensidad",
        None,
        Some("1.0 = maximo, 0.5 = moderado"),
        0.1,
        1.0,
        0.05,
        NightLightService::get_gamma(),
        Some(Box::new(move |_| {
            schedule_apply(&pending_cb, &sliders_cb);
        })),
    );

    gamma_group.add(&gamma_slider.row);

    if NightLightService::has_gamma() {
        page.add(gamma_group.widget());
    }

    *sliders.borrow_mut() = (Some(day_slider), Some(night_slider), Some(gamma_slider));

    // ===== Ubicacion manual =====
    let mut loc_group = Group::new("Ubicacion manual");

    loc_group.add(&Row::new(
        "Latitud / Longitud",
        Some("Vacías: geolocalización automática"),
        None,
        None,
        None,
        None,
    ));

    let (lat, lng) = NightLightService::get_location();

    let lat_entry = gtk::Entry::new();
    lat_entry.set_placeholder_text(Some("Latitud (-90 a 90)"));
    lat_entry.set_margin_start(14);
    lat_entry.set_margin_end(14);
    lat_entry.set_margin_top(8);
    lat_entry.set_margin_bottom(8);
    if let Some(lat) = lat {
        lat_entry.set_text(&lat.to_string());
    }

    let lng_entry = gtk::Entry::new();
    lng_entry.set_placeholder_text(Some("Longitud (-180 a 180)"));
    lng_entry.set_margin_start(14);
    lng_entry.set_margin_end(14);
    lng_entry.set_margin_bottom(8);
    if let Some(lng) = lng {
        lng_entry.set_text(&lng.to_string());
    }

    // Gtk::Entry no implementa AsWidget; se añaden directo a la tarjeta del grupo
    loc_group.card.append(&lat_entry);
    loc_group.card.append(&lng_entry);

    let entries: Entries = Rc::new(RefCell::new((Some(lat_entry), Some(lng_entry))));

    let entries_cb = Rc::clone(&entries);
    let status_cb = Rc::clone(&status_row);
    loc_group.add(&Row::new(
        "Aplicar ubicacion",
        Some("Usa la latitud/longitud manual (o vacia para geolocalizar)"),
        Some("night_light.svg"),
        None,
        None,
        Some(Box::new(move |_| {
            on_location_apply(&entries_cb, &status_cb);
        })),
    ));

    page.add(loc_group.widget());

    // Refresco periódico del estado cada 5s (GLib.timeout_add_seconds(5, ...))
    let status_timer = Rc::clone(&status_row);
    glib::timeout_add_seconds_local(5, move || {
        refresh_status(&status_timer);
        glib::ControlFlow::Continue
    });

    page
}

/// Equivalente a NightLightPage._status_text
fn status_text() -> String {
    let who = if NightLightService::uses_noctalia() { "Noctalia" } else { "wlsunset" };
    if NightLightService::is_running() {
        return format!("Activa ({who})");
    }
    if NightLightService::is_enabled() {
        return format!("Activada, pero {who} no está aplicando el filtro");
    }
    "Desactivada".to_string()
}

/// Equivalente a NightLightPage._refresh_status (try/except silencioso en el Python)
fn refresh_status(status: &Rc<RefCell<Option<Row>>>) {
    if let Some(row) = status.borrow().as_ref() {
        row.set_subtitle(&status_text());
    }
}

/// Equivalente a NightLightPage._on_location_apply:
/// parsea lat/lng (None si vacío o inválido) y los guarda.
fn on_location_apply(entries: &Entries, status: &Rc<RefCell<Option<Row>>>) {
    let entries_ref = entries.borrow();
    let (lat_entry, lng_entry) = &*entries_ref;
    let lat = lat_entry
        .as_ref()
        .and_then(|e| e.text().parse::<f64>().ok());
    let lng = lng_entry
        .as_ref()
        .and_then(|e| e.text().parse::<f64>().ok());

    NightLightService::set_location(lat, lng);

    refresh_status(status);
}

/// Equivalente a NightLightPage._schedule_apply: aplica temperaturas + gamma
/// 400ms después del último cambio. El try/except del Python no hace falta:
/// los setters de NightLightService no pueden fallar.
fn schedule_apply(pending: &Rc<RefCell<bool>>, sliders: &Sliders) {
    if *pending.borrow() {
        return;
    }
    *pending.borrow_mut() = true;

    let pending = Rc::clone(pending);
    let sliders = Rc::clone(sliders);

    glib::timeout_add_local(Duration::from_millis(400), move || {
        *pending.borrow_mut() = false;

        let sliders_ref = sliders.borrow();
        let (day, night, gamma) = &*sliders_ref;
        if let (Some(day), Some(night), Some(gamma)) = (day.as_ref(), night.as_ref(), gamma.as_ref())
        {
            NightLightService::set_temps(day.get_value(), night.get_value());
            NightLightService::set_gamma(gamma.get_value());
        }

        glib::ControlFlow::Break
    });
}
