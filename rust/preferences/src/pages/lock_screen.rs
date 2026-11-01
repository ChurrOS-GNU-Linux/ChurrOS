// ==========================================
// LockScreenPage — swaylock + swayidle (bloqueo automatico y estilo)
// (equivalente a pages/lock_screen.py)
// ==========================================

use gtk::prelude::*;

use serde_json::{Value, json};

use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

use crate::services::lock_screen::LockScreenService;
use crate::services::wallpaper::WallpaperService;
use crate::widgets::color_picker::ColorPickerRow;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

const FONTS: [&str; 5] = ["JetBrains Mono", "Inter", "Cantarell", "Hack", "Monospace"];

struct LockState {
    enabled: SwitchRow,
    timeout: SliderRow,
    indicator: ComboRow,
    use_current_row: Row,
    custom_path_entry: gtk::Entry,
    apply_path_row: Row,
    font: ComboRow,
    font_size: SliderRow,
    ring: ColorPickerRow,
    inside: ColorPickerRow,
    key_hl: ColorPickerRow,
    bs: ColorPickerRow,
    sep: ColorPickerRow,
}

type LockStateRef = Rc<RefCell<LockState>>;

struct Scheduler {
    pending: bool,
}

/// Debounce 400ms (equivalente a _schedule_apply + GLib.timeout_add).
fn schedule(state: &LockStateRef, scheduler: &Rc<RefCell<Scheduler>>) {
    if scheduler.borrow().pending {
        return;
    }
    scheduler.borrow_mut().pending = true;

    let st = Rc::clone(state);
    let s = Rc::clone(scheduler);
    glib::timeout_add_local(Duration::from_millis(400), move || {
        s.borrow_mut().pending = false;

        let state = st.borrow();

        let updates = json!({
            "timeout_seconds": state.timeout.get_value() as i64,
            "indicator": state.indicator.value().unwrap_or_else(|| "auto".to_string()),
            "font": state.font.value().unwrap_or_default(),
            "font_size": state.font_size.get_value() as i64,
            "ring_color": state.ring.get_value().trim_start_matches('#').to_string(),
            "inside_color": state.inside.get_value().trim_start_matches('#').to_string(),
            "key_hl_color": state.key_hl.get_value().trim_start_matches('#').to_string(),
            "bs_color": state.bs.get_value().trim_start_matches('#').to_string(),
            "separator_color": state.sep.get_value().trim_start_matches('#').to_string(),
        });

        drop(state);
        LockScreenService::set_all(&updates);
        LockScreenService::apply();

        glib::ControlFlow::Break
    });
}

fn cb_str(state: &LockStateRef, scheduler: &Rc<RefCell<Scheduler>>) -> Box<dyn Fn(&str)> {
    let st = Rc::clone(state);
    let s = Rc::clone(scheduler);
    Box::new(move |_| schedule(&st, &s))
}

fn cb_f64(state: &LockStateRef, scheduler: &Rc<RefCell<Scheduler>>) -> Box<dyn Fn(f64)> {
    let st = Rc::clone(state);
    let s = Rc::clone(scheduler);
    Box::new(move |_| schedule(&st, &s))
}

/// get() con default tipado (equivalente a LockScreenService.get(key, default)).
fn get(key: &str, default: Value) -> Value {
    LockScreenService::get(key, default)
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Pantalla de bloqueo",
        Some("swaylock + swayidle: bloqueo automatico y estilo"),
        Some("appearance".to_string()),
    );

    if !LockScreenService::is_available() {
        let mut warn = Group::new("No disponible");
        warn.add(&Row::new(
            "swaylock no esta instalado",
            Some("Para personalizar el bloqueo instala el paquete swaylock"),
            Some("lock_screen.svg"),
            None,
            None,
            None,
        ));
        page.add(warn.widget());
        return page;
    }

    let state: LockStateRef = Rc::new(RefCell::new(LockState {
        enabled: SwitchRow::new("", None, None, false, None),
        timeout: SliderRow::new("", None, None, 30.0, 3600.0, 30.0, 600.0, None),
        indicator: ComboRow::new("", &["auto"], None, None, None, None),
        use_current_row: Row::new("", None, Some("wallpaper.svg"), None, None, None),
        custom_path_entry: gtk::Entry::new(),
        apply_path_row: Row::new("", None, Some("lock_screen.svg"), None, None, None),
        font: ComboRow::new("", &FONTS, None, None, None, None),
        font_size: SliderRow::new("", None, None, 12.0, 64.0, 1.0, 24.0, None),
        ring: ColorPickerRow::new("", "#7aa2f7ff", None, None),
        inside: ColorPickerRow::new("", "#00000088", None, None),
        key_hl: ColorPickerRow::new("", "#bb9af7ff", None, None),
        bs: ColorPickerRow::new("", "#f7768eff", None, None),
        sep: ColorPickerRow::new("", "#00000000", None, None),
    }));

    let scheduler: Rc<RefCell<Scheduler>> = Rc::new(RefCell::new(Scheduler { pending: false }));

    // ---------- Estado ----------
    let mut state_group = Group::new("Estado");

    {
        let mut st = state.borrow_mut();
        st.enabled = SwitchRow::new(
            "Bloqueo automatico",
            None,
            Some("Bloquea la pantalla tras un periodo de inactividad"),
            LockScreenService::is_enabled(),
            Some(Box::new(on_enable_toggle())),
        );
    }
    {
        let st = state.borrow();
        state_group.add(&st.enabled);
    }

    {
        let mut st = state.borrow_mut();
        st.timeout = SliderRow::new(
            "Tiempo de inactividad",
            None,
            Some("Segundos hasta que se bloquee"),
            30.0,
            3600.0,
            30.0,
            get("timeout_seconds", json!(600)).as_f64().unwrap_or(600.0),
            Some(cb_f64(&state, &scheduler)),
        );
    }
    {
        let st = state.borrow();
        state_group.add(&st.timeout);
    }

    let _st = Rc::clone(&state);
    state_group.add(&Row::new(
        "Bloquear ahora",
        Some("Lanza swaylock al instante"),
        Some("lock_screen.svg"),
        None,
        None,
        Some(Box::new(move |_| LockScreenService::lock_now())),
    ));

    state_group.add(&Row::new(
        "Previsualizar estilo",
        Some("Lanza swaylock con la configuracion actual"),
        Some("lock_screen.svg"),
        None,
        None,
        Some(Box::new(move |button| {
            button.set_sensitive(false);
            let button = button.clone();
            let parent = button.root().and_downcast::<gtk::Window>();
            glib::spawn_future_local(async move {
                let result = gio::spawn_blocking(LockScreenService::preview).await;
                button.set_sensitive(true);
                let error = match result {
                    Ok(Ok(())) => return,
                    Ok(Err(error)) => error,
                    Err(error) => format!("No se pudo ejecutar la vista previa: {error:?}"),
                };
                eprintln!("[lock-screen] {error}");
                gtk::AlertDialog::builder()
                    .message("No se pudo bloquear la pantalla")
                    .detail(&error)
                    .modal(true)
                    .build()
                    .show(parent.as_ref());
            });
        })),
    ));

    page.add(state_group.widget());

    // ---------- Indicador ----------
    let mut ind_group = Group::new("Indicador de progreso");

    {
        let mut st = state.borrow_mut();
        let indicators = crate::services::lock_screen::INDICATORS;
        st.indicator = ComboRow::new(
            "Tipo de indicador",
            &indicators,
            Some(if get("indicator", json!("auto")) == json!("none") {
                "none"
            } else {
                "auto"
            }),
            Some("Como se muestra el estado al escribir"),
            None,
            Some(cb_str(&state, &scheduler)),
        );
    }
    {
        let st = state.borrow();
        ind_group.add(&st.indicator);
    }

    page.add(ind_group.widget());

    // ---------- Fondo ----------
    let mut bg_group = Group::new("Fondo");

    {
        let mut st = state.borrow_mut();

        let current_wallpaper = get("wallpaper_path", json!(""))
            .as_str()
            .unwrap_or("")
            .to_string();

        let subtitle = if current_wallpaper.is_empty() {
            "Pasa el wallpaper activo a swaylock (-i)".to_string()
        } else {
            format!("Actual: {current_wallpaper}")
        };

        st.use_current_row = Row::new(
            "Usar fondo actual",
            Some(&subtitle),
            Some("wallpaper.svg"),
            None,
            None,
            None,
        );

        st.custom_path_entry = gtk::Entry::new();
        st.custom_path_entry
            .set_placeholder_text(Some("Ruta a una imagen personalizada"));
        st.custom_path_entry.set_margin_start(14);
        st.custom_path_entry.set_margin_end(14);
        st.custom_path_entry.set_margin_top(8);
        st.custom_path_entry.set_margin_bottom(8);

        st.apply_path_row = Row::new(
            "Aplicar ruta personalizada",
            Some("swaylock usara esta imagen al bloquear"),
            Some("lock_screen.svg"),
            None,
            None,
            None,
        );
    }

    // Conectar callbacks tras construir las filas
    {
        let st = state.borrow();
        let st2 = Rc::clone(&state);
        st.use_current_row
            .widget()
            .connect_clicked(move |_| on_use_current_wallpaper(&st2));
        let st2 = Rc::clone(&state);
        st.apply_path_row
            .widget()
            .connect_clicked(move |_| on_apply_custom_path(&st2));
    }
    {
        let st = state.borrow();
        bg_group.add(&st.use_current_row);
        bg_group.add(st.custom_path_entry.upcast_ref::<gtk::Widget>());
        bg_group.add(&st.apply_path_row);
    }

    page.add(bg_group.widget());

    // ---------- Tipografia ----------
    let mut font_group = Group::new("Tipografia");

    {
        let mut st = state.borrow_mut();
        st.font = ComboRow::new(
            "Familia",
            &FONTS,
            Some(
                get("font", json!("JetBrains Mono"))
                    .as_str()
                    .unwrap_or("JetBrains Mono"),
            ),
            None,
            None,
            Some(cb_str(&state, &scheduler)),
        );
        st.font_size = SliderRow::new(
            "Tamano",
            None,
            None,
            12.0,
            64.0,
            1.0,
            get("font_size", json!(24)).as_f64().unwrap_or(24.0),
            Some(cb_f64(&state, &scheduler)),
        );
    }
    {
        let st = state.borrow();
        font_group.add(&st.font);
        font_group.add(&st.font_size);
    }

    page.add(font_group.widget());

    // ---------- Colores ----------
    let mut colors_group = Group::new("Colores");

    {
        let mut st = state.borrow_mut();
        st.ring = ColorPickerRow::new(
            "Anillo",
            &format!(
                "#{}",
                get("ring_color", json!("7aa2f7ff"))
                    .as_str()
                    .unwrap_or("7aa2f7ff")
            ),
            Some(cb_str(&state, &scheduler)),
            Some("Color del indicador"),
        );
        st.inside = ColorPickerRow::new(
            "Interior",
            &format!(
                "#{}",
                get("inside_color", json!("00000088"))
                    .as_str()
                    .unwrap_or("00000088")
            ),
            Some(cb_str(&state, &scheduler)),
            Some("Color dentro del indicador"),
        );
        st.key_hl = ColorPickerRow::new(
            "Tecla resaltada",
            &format!(
                "#{}",
                get("key_hl_color", json!("bb9af7ff"))
                    .as_str()
                    .unwrap_or("bb9af7ff")
            ),
            Some(cb_str(&state, &scheduler)),
            Some("Color al pulsar una tecla correcta"),
        );
        st.bs = ColorPickerRow::new(
            "Backspace",
            &format!(
                "#{}",
                get("bs_color", json!("f7768eff"))
                    .as_str()
                    .unwrap_or("f7768eff")
            ),
            Some(cb_str(&state, &scheduler)),
            Some("Color al pulsar backspace"),
        );
        st.sep = ColorPickerRow::new(
            "Separador",
            &format!(
                "#{}",
                get("separator_color", json!("00000000"))
                    .as_str()
                    .unwrap_or("00000000")
            ),
            Some(cb_str(&state, &scheduler)),
            Some("Borde del indicador"),
        );
    }
    {
        let st = state.borrow();
        colors_group.add(&st.ring);
        colors_group.add(&st.inside);
        colors_group.add(&st.key_hl);
        colors_group.add(&st.bs);
        colors_group.add(&st.sep);
    }

    page.add(colors_group.widget());

    page
}

/// Equivalente a _on_enable_toggle: guarda enabled y aplica.
fn on_enable_toggle() -> Box<dyn Fn(bool)> {
    Box::new(|value: bool| {
        LockScreenService::set_all(&json!({ "enabled": value }));
        LockScreenService::apply();
    })
}

/// Equivalente a _on_use_current_wallpaper.
fn on_use_current_wallpaper(state: &LockStateRef) {
    let current = WallpaperService::current();

    if current.is_empty() || !std::path::Path::new(&current).is_file() {
        state
            .borrow()
            .use_current_row
            .set_subtitle("No hay wallpaper activo. Selecciona uno primero.");
        return;
    }

    LockScreenService::set_all(&json!({ "wallpaper_path": current }));
    LockScreenService::apply();
    state
        .borrow()
        .use_current_row
        .set_subtitle(&format!("Actual: {current}"));
}

/// Equivalente a _on_apply_custom_path.
fn on_apply_custom_path(state: &LockStateRef) {
    let path = state.borrow().custom_path_entry.text().trim().to_string();

    if path.is_empty() || !std::path::Path::new(&path).is_file() {
        state
            .borrow()
            .apply_path_row
            .set_subtitle("La ruta no apunta a un archivo valido");
        return;
    }

    LockScreenService::set_all(&json!({ "wallpaper_path": path }));
    LockScreenService::apply();
    state
        .borrow()
        .apply_path_row
        .set_subtitle(&format!("Aplicado: {path}"));
}
