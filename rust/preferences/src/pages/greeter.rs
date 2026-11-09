// ==========================================
// GreeterPage — Apariencia > Pantalla de inicio (greetd + ReGreet)
//
// El fondo se escribe sin contraseña desde la sesión (GreeterService::sync);
// oscurecido, logo, reloj y color van por el helper con contraseña. Los
// cambios se ven la próxima vez que aparece la pantalla de inicio.
// ==========================================

use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::time::Duration;

use gtk::prelude::*;

use crate::services::accent::AccentService;
use crate::services::greeter::{GreeterService, ORANGE};
use crate::services::users::UsersService;
use crate::widgets::color_picker::ColorPickerRow;
use crate::widgets::combo_row::ComboRow;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::slider_row::SliderRow;
use crate::widgets::switch_row::SwitchRow;

const SIZES: [(&str, &str); 3] = [("Pequeño", "small"), ("Mediano", "medium"), ("Grande", "large")];
const COLOR_CHURROS: &str = "Naranja ChurrOS";
const COLOR_DESKTOP: &str = "Acento del escritorio";
const COLOR_CUSTOM: &str = "Personalizado";

type Feedback = Rc<RefCell<Option<gtk::Label>>>;

fn say(feedback: &Feedback, ok: bool, done: &str) {
    if let Some(label) = feedback.borrow().as_ref() {
        label.set_label(if ok {
            done
        } else {
            "No se pudo aplicar (¿contraseña cancelada?)"
        });
    }
}

fn sync_background(feedback: &Feedback) {
    let text = match GreeterService::sync(true) {
        Ok(_) => "Fondo de la pantalla de inicio actualizado".to_string(),
        Err(e) => format!("No se pudo actualizar el fondo: {e}"),
    };
    if let Some(label) = feedback.borrow().as_ref() {
        label.set_label(&text);
    }
}

fn pick_image(parent: &impl IsA<gtk::Widget>, on_file: impl Fn(String) + 'static) {
    let dialog = gtk::FileDialog::builder().title("Imagen para la pantalla de inicio").build();
    let filters = gio::ListStore::new::<gtk::FileFilter>();
    let images = gtk::FileFilter::new();
    images.set_name(Some("Imágenes"));
    images.add_pixbuf_formats();
    filters.append(&images);
    dialog.set_filters(Some(&filters));
    let window = parent.root().and_then(|r| r.downcast::<gtk::Window>().ok());
    dialog.open(window.as_ref(), None::<&gio::Cancellable>, move |result| {
        if let Some(path) = result.ok().and_then(|f| f.path()) {
            on_file(path.to_string_lossy().to_string());
        }
    });
}

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Pantalla de inicio",
        Some("Fondo, reloj, saludo y colores de la pantalla de login"),
        Some("appearance".to_string()),
    );
    let cfg = GreeterService::config();
    let feedback: Feedback = Rc::new(RefCell::new(None));

    // ===== Fondo =====
    let mut background = Group::new("Fondo");

    let image_row = Row::new(
        "Imagen propia",
        Some(&{
            let custom = GreeterService::custom_image();
            if custom.is_empty() { "Ninguna elegida".to_string() } else { custom }
        }),
        Some("wallpaper.svg"),
        None,
        None,
        None,
    );
    image_row.widget().set_sensitive(!GreeterService::follows_wallpaper());
    {
        let feedback = Rc::clone(&feedback);
        let subtitle = image_row.subtitle_label().cloned();
        let button = image_row.widget().clone();
        image_row.widget().connect_clicked(move |_| {
            let feedback = Rc::clone(&feedback);
            let subtitle = subtitle.clone();
            pick_image(&button, move |path| {
                GreeterService::set_custom_image(&path);
                if let Some(label) = &subtitle {
                    label.set_label(&path);
                }
                sync_background(&feedback);
            });
        });
    }

    {
        let feedback = Rc::clone(&feedback);
        let image_widget = image_row.widget().clone();
        background.add(&SwitchRow::new(
            "Usar el fondo del escritorio",
            Some("wallpaper.svg"),
            Some("Se actualiza solo cada vez que cambias el fondo"),
            GreeterService::follows_wallpaper(),
            Some(Box::new(move |on| {
                GreeterService::set_follows_wallpaper(on);
                image_widget.set_sensitive(!on);
                sync_background(&feedback);
            })),
        ));
    }
    background.add(&image_row);
    {
        let feedback = Rc::clone(&feedback);
        background.add(&SwitchRow::new(
            "Difuminar el fondo",
            None,
            Some("Desenfoque suave detrás del reloj y los campos"),
            GreeterService::blur(),
            Some(Box::new(move |on| {
                GreeterService::set_blur(on);
                sync_background(&feedback);
            })),
        ));
    }
    {
        // Debounce: una sola petición (y una contraseña) al soltar.
        let feedback = Rc::clone(&feedback);
        let generation = Rc::new(Cell::new(0u32));
        background.add(&SliderRow::new(
            "Oscurecer",
            None,
            Some("Más oscuro = texto más legible sobre fondos claros"),
            0.0,
            80.0,
            1.0,
            f64::from(cfg.dim),
            Some(Box::new(move |value| {
                let ticket = generation.get().wrapping_add(1);
                generation.set(ticket);
                let generation = Rc::clone(&generation);
                let feedback = Rc::clone(&feedback);
                glib::timeout_add_local_once(Duration::from_millis(700), move || {
                    if generation.get() == ticket {
                        let ok = GreeterService::set_dim(value.round() as u8);
                        say(&feedback, ok, "Oscurecido aplicado");
                    }
                });
            })),
        ));
    }
    page.add(background.widget());

    // ===== Reloj =====
    let mut clock_group = Group::new("Reloj");
    let clock_state = Rc::new(RefCell::new(cfg.clone()));
    let apply_clock = {
        let feedback = Rc::clone(&feedback);
        let state = Rc::clone(&clock_state);
        Rc::new(move || {
            let s = state.borrow();
            let ok = GreeterService::set_clock(s.clock24, s.seconds, s.date, &s.clock_size);
            say(&feedback, ok, "Reloj actualizado");
        })
    };
    {
        let (state, apply) = (Rc::clone(&clock_state), Rc::clone(&apply_clock));
        clock_group.add(&ComboRow::new(
            "Formato",
            &["24 horas", "12 horas"],
            Some(if cfg.clock24 { "24 horas" } else { "12 horas" }),
            None,
            Some("system.svg"),
            Some(Box::new(move |value| {
                state.borrow_mut().clock24 = value == "24 horas";
                apply();
            })),
        ));
    }
    {
        let (state, apply) = (Rc::clone(&clock_state), Rc::clone(&apply_clock));
        clock_group.add(&SwitchRow::new(
            "Mostrar segundos",
            None,
            None,
            cfg.seconds,
            Some(Box::new(move |on| {
                state.borrow_mut().seconds = on;
                apply();
            })),
        ));
    }
    {
        let (state, apply) = (Rc::clone(&clock_state), Rc::clone(&apply_clock));
        clock_group.add(&SwitchRow::new(
            "Mostrar la fecha",
            None,
            Some("Encima de la hora, en el idioma del sistema"),
            cfg.date,
            Some(Box::new(move |on| {
                state.borrow_mut().date = on;
                apply();
            })),
        ));
    }
    {
        let (state, apply) = (Rc::clone(&clock_state), Rc::clone(&apply_clock));
        let current = SIZES.iter().find(|(_, id)| *id == cfg.clock_size).map(|(l, _)| *l);
        clock_group.add(&ComboRow::new(
            "Tamaño de la hora",
            &SIZES.map(|(label, _)| label),
            current,
            None,
            None,
            Some(Box::new(move |value| {
                if let Some((_, id)) = SIZES.iter().find(|(label, _)| *label == value) {
                    state.borrow_mut().clock_size = (*id).to_string();
                    apply();
                }
            })),
        ));
    }
    page.add(clock_group.widget());

    // ===== Saludo y logo =====
    let mut greeting_group = Group::new("Saludo y logo");
    let entry = gtk::Entry::new();
    entry.set_text(&UsersService::regreet_greeting());
    entry.set_max_length(80);
    entry.set_hexpand(true);
    entry.set_valign(gtk::Align::Center);
    let save = gtk::Button::with_label("Guardar");
    save.set_valign(gtk::Align::Center);
    let line = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    line.append(&entry);
    line.append(&save);
    greeting_group.add(&Row::new(
        "Mensaje de bienvenida",
        Some("Hasta 80 caracteres, debajo del logo"),
        Some("palette.svg"),
        None,
        Some(line.upcast_ref::<gtk::Widget>()),
        None,
    ));
    {
        let feedback = Rc::clone(&feedback);
        let entry_c = entry.clone();
        let apply = move || {
            let text = entry_c.text().trim().to_string();
            if text.is_empty() {
                return;
            }
            let ok = UsersService::set_regreet_greeting(&text);
            say(&feedback, ok, "Saludo guardado");
        };
        let apply = Rc::new(apply);
        let a = Rc::clone(&apply);
        save.connect_clicked(move |_| a());
        entry.connect_activate(move |_| apply());
    }
    {
        let feedback = Rc::clone(&feedback);
        greeting_group.add(&SwitchRow::new(
            "Mostrar el logo",
            None,
            Some("Círculo con el logo de ChurrOS encima del saludo"),
            cfg.avatar,
            Some(Box::new(move |on| {
                let ok = GreeterService::set_avatar(on);
                say(&feedback, ok, "Logo actualizado");
            })),
        ));
    }
    page.add(greeting_group.widget());

    // ===== Color =====
    let mut color_group = Group::new("Color");
    let desktop_accent = AccentService::hex_for(&AccentService::current()).to_uppercase();
    let mode = if cfg.accent.eq_ignore_ascii_case(ORANGE) {
        COLOR_CHURROS
    } else if cfg.accent.eq_ignore_ascii_case(&desktop_accent) {
        COLOR_DESKTOP
    } else {
        COLOR_CUSTOM
    };
    let custom_box = gtk::Box::new(gtk::Orientation::Vertical, 0);
    {
        let feedback = Rc::clone(&feedback);
        let picker = ColorPickerRow::new(
            "Color personalizado",
            &cfg.accent,
            Some(Box::new(move |hex: &str| {
                let hex = format!("#{}", hex.trim_start_matches('#').chars().take(6).collect::<String>());
                let ok = GreeterService::set_accent(&hex.to_uppercase());
                say(&feedback, ok, "Color aplicado");
            })),
            Some("Botón de entrar y foco de los campos"),
        );
        custom_box.append(picker.widget());
    }
    custom_box.set_visible(mode == COLOR_CUSTOM);
    {
        let feedback = Rc::clone(&feedback);
        let custom_box = custom_box.clone();
        color_group.add(&ComboRow::new(
            "Color de acento",
            &[COLOR_CHURROS, COLOR_DESKTOP, COLOR_CUSTOM],
            Some(mode),
            Some("Botón de entrar, foco de los campos y menús"),
            Some("palette.svg"),
            Some(Box::new(move |value| {
                custom_box.set_visible(value == COLOR_CUSTOM);
                let hex = match value {
                    COLOR_CHURROS => ORANGE.to_string(),
                    COLOR_DESKTOP => AccentService::hex_for(&AccentService::current()).to_uppercase(),
                    _ => return,
                };
                let ok = GreeterService::set_accent(&hex);
                say(&feedback, ok, "Color aplicado");
            })),
        ));
    }
    color_group.add(custom_box.upcast_ref::<gtk::Widget>());
    page.add(color_group.widget());

    // ===== Estado =====
    let note = gtk::Label::new(Some(
        "Los cambios se ven la próxima vez que aparezca la pantalla de inicio. \
         Las opciones del reloj, el logo, el color y el oscurecido piden la \
         contraseña de administrador; el fondo no.",
    ));
    note.set_wrap(true);
    note.set_xalign(0.0);
    note.add_css_class("row-subtitle");
    page.add(&note);
    let status = gtk::Label::new(None);
    status.set_wrap(true);
    status.set_xalign(0.0);
    page.add(&status);
    *feedback.borrow_mut() = Some(status);

    page
}
