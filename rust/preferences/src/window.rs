// ==========================================
// PreferencesWindow — ventana principal
// (equivalente a window.py)
// ==========================================

use gtk::prelude::*;

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use crate::pages;
use crate::services::settings;
use crate::services::theme::ThemeService;
use crate::widgets::sidebar::Sidebar;

type PageBuilder = Box<dyn FnOnce(gtk::Stack) -> crate::widgets::page::Page>;

fn ensure_page_built(
    id: &str,
    builders: &Rc<RefCell<HashMap<String, PageBuilder>>>,
    navigator: &gtk::Stack,
) {
    let builder_opt = builders.borrow_mut().remove(id);
    if let Some(builder) = builder_opt {
        crate::logging::log(&format!("[lazy] construyendo página: {id}"));
        let page = builder(navigator.clone());
        if let Some(child) = navigator.child_by_name(id) {
            if let Some(container) = child.downcast_ref::<gtk::Box>() {
                container.append(page.widget());
            }
        }
    }
}

pub struct PreferencesWindow {
    pub window: gtk::ApplicationWindow,
    sidebar: Rc<RefCell<Sidebar>>,
    navigator: gtk::Stack,
    sidebar_revealer: gtk::Revealer,
    toggle_button: gtk::Button,
    history: Rc<RefCell<Vec<String>>>,
    narrow_threshold: i32,
    is_narrow: Rc<RefCell<bool>>,
    builders: Rc<RefCell<HashMap<String, PageBuilder>>>,
    // Mantener la referencia viva: si se dropea, GLib destruye el objeto y
    // el handler de color-scheme deja de disparar.
    #[allow(dead_code)]
    gtk_settings: Option<gio::Settings>,
}

impl PreferencesWindow {
    pub fn new(app: &gtk::Application) -> Self {
        let window = gtk::ApplicationWindow::builder()
            .application(app)
            .title("Configuración")
            .default_width(900)
            .default_height(680)
            .build();

        let _is_xfce = churros_services::version::edition().contains("xfce");
        if _is_xfce {
            window.set_decorated(false);
        }

        window.add_css_class("preferences");
        apply_theme_class(&window);

        // Evitar que el compositor maximice la ventana al iniciar
        // (el CSS .maximized quita el blur/glassmorphism)
        window.set_resizable(true);

        let w = window.clone();
        let gtk_settings = gio::SettingsSchemaSource::default().and_then(|schema_source| {
            let schema = schema_source.lookup("org.gnome.desktop.interface", false)?;
            let settings =
                gio::Settings::new_full(&schema, None::<&gio::SettingsBackend>, None::<&str>);
            settings.connect_changed(Some("color-scheme"), move |_, _| {
                let w = w.clone();
                glib::idle_add_local_once(move || refresh_theme(&w));
            });
            Some(settings)
        });

        // Hook en vivo: ThemeService::set notifica aquí directamente, sin
        // depender de gsettings/dconf (equivalente a _refresh_root_theme del
        // Python). El listener de color-scheme de arriba queda como refuerzo
        // para cambios externos.
        let theme_window = window.clone();
        ThemeService::on_change(move |_dark| refresh_theme(&theme_window));

        // HeaderBar con controles de ventana (cerrar, maximizar, minimizar)
        let header_bar = adw::HeaderBar::new();
        header_bar.set_show_end_title_buttons(true);
        header_bar.set_show_start_title_buttons(true);
        header_bar.add_css_class("flat");

        let toggle_button = gtk::Button::from_icon_name("open-menu-symbolic");
        toggle_button.add_css_class("flat");
        toggle_button.set_tooltip_text(Some("Menú lateral"));
        toggle_button.set_visible(false);
        header_bar.pack_start(&toggle_button);

        // Layout principal
        let root = gtk::Box::new(gtk::Orientation::Horizontal, 0);

        let main_box = gtk::Box::new(gtk::Orientation::Vertical, 0);
        main_box.append(&header_bar);
        main_box.append(&root);
        window.set_child(Some(&main_box));

        // Sidebar + revealer
        let sidebar = Rc::new(RefCell::new(Sidebar::new()));
        let sidebar_revealer = gtk::Revealer::new();
        sidebar_revealer.set_transition_type(gtk::RevealerTransitionType::SlideRight);
        sidebar_revealer.set_reveal_child(true);
        sidebar_revealer.set_child(Some(&sidebar.borrow().root));
        root.append(&sidebar_revealer);

        // Cablear el buscador de la sidebar (el Search no puede conectar su
        // propio callback porque necesitaría una referencia a su Sidebar).
        let search_sidebar = Rc::clone(&sidebar);
        sidebar.borrow().search.connect_search(move |query| {
            let Ok(sidebar) = search_sidebar.try_borrow() else {
                return;
            };
            sidebar.on_search(query);
        });

        // Navegador principal
        let nav_box = gtk::Box::new(gtk::Orientation::Vertical, 0);

        let navigator = gtk::Stack::new();
        navigator.set_hexpand(true);
        navigator.set_vexpand(true);
        navigator.set_transition_type(gtk::StackTransitionType::SlideLeftRight);
        navigator.set_transition_duration(250);

        nav_box.append(&navigator);
        root.append(&nav_box);

        let history: Rc<RefCell<Vec<String>>> = Rc::new(RefCell::new(Vec::new()));
        let is_narrow: Rc<RefCell<bool>> = Rc::new(RefCell::new(false));
        let builders: Rc<RefCell<HashMap<String, PageBuilder>>> =
            Rc::new(RefCell::new(HashMap::new()));

        let mut win = Self {
            window,
            sidebar,
            navigator,
            sidebar_revealer,
            toggle_button,
            history,
            narrow_threshold: 760,
            is_narrow,
            builders,
            gtk_settings,
        };

        win.register_pages();
        win.wire_sidebar();
        win.wire_shortcuts();
        win.wire_responsive();

        // Página inicial: última visitada o system
        let mut last_page = settings::get_string("preferences.last_page", "system");
        if win.navigator.child_by_name(&last_page).is_none() {
            last_page = "system".to_string();
        }
        ensure_page_built(&last_page, &win.builders, &win.navigator);
        win.navigator.set_visible_child_name(&last_page);
        win.sidebar.borrow().select(&last_page);
        win
    }

    fn register_pages(&mut self) {
        // Páginas principales (13, mismo orden que widgets/sidebar.py)
        self.register_main_page("system", "system.svg", "Sistema", |n| pages::system::build(n));
        self.register_main_page("update", "system.svg", "Actualizaciones", |n| {
            pages::update::build(n)
        });
        self.register_main_page("datetime", "system.svg", "Fecha y hora", |n| {
            pages::datetime::build(n)
        });
        self.register_main_page("appearance", "appearance.svg", "Apariencia", |n| {
            pages::appearance::build(n)
        });
        self.register_main_page("display", "display.svg", "Pantalla", |n| {
            pages::display::build(n)
        });
        self.register_main_page("input", "input.svg", "Entrada", |n| pages::input::build(n));
        self.register_main_page("audio", "audio.svg", "Audio", |n| pages::audio::build(n));
        self.register_main_page("connectivity", "connectivity.svg", "Conectividad", |n| {
            pages::connectivity::build(n)
        });
        self.register_main_page("power", "power.svg", "Energía", |n| pages::power::build(n));
        self.register_main_page("users", "users.svg", "Usuarios", |n| pages::users::build(n));
        self.register_main_page("privacy", "privacy.svg", "Privacidad", |n| {
            pages::privacy::build(n)
        });
        self.register_main_page("applications", "applications.svg", "Aplicaciones", |n| {
            pages::applications::build(n)
        });
        self.register_main_page("keyboard", "input.svg", "Teclado", |n| {
            pages::keyboard::build(n)
        });
        self.register_main_page("about", "about.svg", "Acerca de", |n| pages::about::build(n));

        // Subpáginas con stack propio (id, parent, builder)
        self.register_subpage("accent", "appearance", |n| pages::accent::build(n));
        self.register_subpage("icons", "appearance", |n| pages::icons::build(n));
        self.register_subpage("cursor", "appearance", |n| pages::cursor::build(n));
        self.register_subpage("fonts", "appearance", |n| pages::fonts::build(n));
        let is_niri = churros_services::version::edition().contains("niri");
        // Con Noctalia en la sesión, Waybar y Mako no se ofrecen: aplicar
        // Waybar arranca una segunda barra y Mako choca con sus avisos.
        // Si la sesión sí los ejecuta, las páginas siguen registradas.
        let show_waybar = churros_services::noctalia::uses_waybar();
        let show_mako = churros_services::noctalia::uses_mako();

        if is_niri {
            if show_waybar {
                self.register_subpage("waybar", "appearance", |n| pages::waybar::build(n));
            }
            self.register_subpage("niri", "appearance", |n| pages::niri::build(n));
            self.register_subpage("foot", "appearance", |n| pages::foot::build(n));
            self.register_subpage("fuzzel", "appearance", |n| pages::fuzzel::build(n));
            if show_mako {
                self.register_subpage("mako", "appearance", |n| pages::mako::build(n));
            }
        }
        self.register_subpage("wallpaper", "appearance", |n| pages::wallpaper::build(n));
        if is_niri {
            self.register_subpage("night-light", "appearance", |n| pages::night_light::build(n));
            self.register_subpage("lock-screen", "appearance", |n| pages::lock_screen::build(n));
            self.register_subpage("window-rules", "appearance", |n| pages::window_rules::build(n));
        }
        self.register_subpage("power-profile", "power", |n| pages::power_profile::build(n));
        self.register_subpage("battery", "power", |n| pages::battery::build(n));
        self.register_subpage("sleep", "power", |n| pages::sleep::build(n));
        self.register_subpage("display-timeout", "display", |n| pages::display_timeout::build(n));
        self.register_subpage("backup", "system", |n| pages::backup::build(n));
        if is_niri {
            self.register_subpage("logs", "system", |n| pages::logs::build(n));
        }

        // Subpáginas registradas en el catálogo de búsqueda
        // (se añaden al stack según se porten)
        {
            let s = self.sidebar.borrow();
            s.register_subpage(
                "accent", "appearance", "Colores", "Color de acento del sistema", Some("palette.svg"));
            s.register_subpage(
                "icons", "appearance", "Iconos", "Tema de iconos", Some("icons.svg"));
            s.register_subpage(
                "cursor", "appearance", "Cursor", "Tema y tamano del cursor", Some("cursor.svg"));
            s.register_subpage(
                "fonts", "appearance", "Fuentes", "Familia y tamano de fuente", Some("font.svg"));
            if is_niri {
                if show_waybar {
                    s.register_subpage(
                        "waybar", "appearance", "Waybar", "Barra: posicion, colores, modulos", Some("waybar.svg"));
                }
                s.register_subpage(
                    "niri", "appearance", "Niri", "Compositor: disposicion, bordes, blur", Some("niri.svg"));
                s.register_subpage(
                    "foot", "appearance", "Foot", "Terminal: fuente, cursor, padding, bell", Some("terminal.svg"));
                s.register_subpage(
                    "fuzzel", "appearance", "Fuzzel", "Launcher: fuente, layout, iconos", Some("applications.svg"));
                if show_mako {
                    s.register_subpage(
                        "mako", "appearance", "Mako", "Notificaciones: fuente, colores, posicion, DND", Some("mako.svg"));
                }
            }
            s.register_subpage(
                "wallpaper", "appearance", "Fondo", "Cambiar el fondo de pantalla", Some("wallpaper.svg"));
            if is_niri {
                s.register_subpage(
                    "night-light", "appearance", "Luz nocturna", "Temperatura de color y filtro de luz azul", Some("night_light.svg"));
                let lock_blurb = if churros_services::noctalia::shell_active() {
                    "El bloqueo lo gestiona Noctalia"
                } else {
                    "swaylock + swayidle: estilo y bloqueo automatico"
                };
                s.register_subpage(
                    "lock-screen", "appearance", "Pantalla de bloqueo", lock_blurb, Some("lock_screen.svg"));
            }
            s.register_subpage(
                "power-profile", "power", "Perfiles de energia", "Performance, balanced o power-saver", None);
            s.register_subpage(
                "battery", "power", "Bateria", "Estado, nivel y opciones de bateria", None);
            s.register_subpage(
                "display-timeout", "display", "Apagado de pantalla", "Tiempo antes de apagar la pantalla", None);
            s.register_subpage(
                "sleep", "power", "Suspension", "Tiempo antes de suspender el sistema", None);
            s.register_subpage(
                "backup", "system", "Copia de seguridad", "Exportar, importar o restablecer la configuracion", Some("backup.svg"));
            if is_niri {
                s.register_subpage(
                    "logs", "system", "Logs de Niri", "Registros del compositor y validacion", Some("logs.svg"));
                s.register_subpage(
                    "window-rules", "appearance", "Reglas de ventana", "Opacidad, flotantes, esquinas, blur", Some("window_rules.svg"));
            }
        }
    }

    fn register_subpage(
        &mut self,
        id: &str,
        _parent_id: &str,
        builder: impl FnOnce(gtk::Stack) -> crate::widgets::page::Page + 'static,
    ) {
        let container = gtk::Box::new(gtk::Orientation::Vertical, 0);
        container.set_hexpand(true);
        container.set_vexpand(true);
        self.navigator.add_named(&container, Some(id));
        self.builders.borrow_mut().insert(id.to_string(), Box::new(builder));
    }

    fn register_main_page(
        &mut self,
        id: &str,
        icon: &str,
        title: &str,
        builder: impl FnOnce(gtk::Stack) -> crate::widgets::page::Page + 'static,
    ) {
        let container = gtk::Box::new(gtk::Orientation::Vertical, 0);
        container.set_hexpand(true);
        container.set_vexpand(true);
        self.navigator.add_named(&container, Some(id));
        self.sidebar.borrow_mut().register_page(id, icon, title);
        self.builders.borrow_mut().insert(id.to_string(), Box::new(builder));
    }

    fn wire_sidebar(&mut self) {
        // Sidebar -> navegar
        let navigator = self.navigator.clone();
        let history = Rc::clone(&self.history);
        let sidebar_revealer = self.sidebar_revealer.clone();
        let is_narrow = Rc::clone(&self.is_narrow);
        let sidebar_select = Rc::clone(&self.sidebar);
        let builders_for_sidebar = Rc::clone(&self.builders);
        self.sidebar.borrow().connect_page_selected(move |page| {
            ensure_page_built(page, &builders_for_sidebar, &navigator);
            settings::set("preferences.last_page", serde_json::json!(page));
            sidebar_select.borrow().select(page);

            // Guardar la página actual en la historia antes de navegar
            if let Some(current) = navigator.visible_child_name() {
                if current != page {
                    history.borrow_mut().push(current.to_string());
                }
            }
            navigator.set_visible_child_name(page);

            if *is_narrow.borrow() {
                sidebar_revealer.set_reveal_child(false);
            }
        });

        // Navegación (back / stack) -> sincronizar sidebar y lazy build
        let sidebar2 = Rc::clone(&self.sidebar);
        let builders_for_nav = Rc::clone(&self.builders);
        self.navigator
            .connect_visible_child_name_notify(move |stack| {
                if let Some(name) = stack.visible_child_name() {
                    ensure_page_built(&name, &builders_for_nav, stack);
                    sidebar2.borrow().select(&name.to_string());
                }
            });
    }

    fn wire_shortcuts(&mut self) {
        let key_ctrl = gtk::EventControllerKey::new();
        key_ctrl.set_propagation_phase(gtk::PropagationPhase::Bubble);

        let sidebar_search = self.sidebar.borrow().search.widget().clone();
        let is_narrow = Rc::clone(&self.is_narrow);
        let sidebar_revealer = self.sidebar_revealer.clone();
        key_ctrl.connect_key_pressed(move |_controller, keyval, _keycode, state| {
            let ctrl = state.contains(gtk::gdk::ModifierType::CONTROL_MASK);
            let shift = state.contains(gtk::gdk::ModifierType::SHIFT_MASK);

            if ctrl && (keyval == gtk::gdk::Key::f || keyval == gtk::gdk::Key::F) {
                sidebar_search.grab_focus();
                return glib::Propagation::Proceed;
            }

            if ctrl && (keyval == gtk::gdk::Key::b || keyval == gtk::gdk::Key::B) {
                if *is_narrow.borrow() {
                    let revealed = sidebar_revealer.reveals_child();
                    sidebar_revealer.set_reveal_child(!revealed);
                }
                return glib::Propagation::Proceed;
            }

            if ctrl && shift && (keyval == gtk::gdk::Key::n || keyval == gtk::gdk::Key::N) {
                let revealed = sidebar_revealer.reveals_child();
                sidebar_revealer.set_reveal_child(!revealed);
                return glib::Propagation::Proceed;
            }

            glib::Propagation::Proceed
        });

        self.window.add_controller(key_ctrl);
    }

    fn wire_responsive(&mut self) {
        let window = self.window.clone();
        let sidebar_revealer = self.sidebar_revealer.clone();
        let toggle_button = self.toggle_button.clone();
        let is_narrow = Rc::clone(&self.is_narrow);
        let threshold = self.narrow_threshold;

        // connect_realize (una sola vez) en vez de connect_map: el map podía
        // dispararse varias veces y acumular timers de 250ms concurrentes.
        let map_window = window.clone();
        map_window.connect_realize(move |_| {
            apply_narrow(&window, &is_narrow, &sidebar_revealer, &toggle_button, threshold);

            let w = window.clone();
            let is_narrow = is_narrow.clone();
            let sidebar_revealer = sidebar_revealer.clone();
            let toggle_button = toggle_button.clone();
            glib::timeout_add_local(std::time::Duration::from_millis(250), move || {
                apply_narrow(&w, &is_narrow, &sidebar_revealer, &toggle_button, threshold);
                glib::ControlFlow::Continue
            });
        });

        // Toggle del sidebar (botón hamburguesa)
        let sidebar_revealer2 = self.sidebar_revealer.clone();
        self.toggle_button.connect_clicked(move |_| {
            let revealed = sidebar_revealer2.reveals_child();
            sidebar_revealer2.set_reveal_child(!revealed);
        });
    }
}

impl PreferencesWindow {
    pub fn present(&self) {
        self.window.present();
    }
}

/// Aplica el estado "narrow" de la ventana (oculta/muestra sidebar).
fn apply_narrow(
    window: &gtk::ApplicationWindow,
    is_narrow: &Rc<RefCell<bool>>,
    sidebar_revealer: &gtk::Revealer,
    toggle_button: &gtk::Button,
    threshold: i32,
) {
    let new_narrow = window.width() < threshold;
    if *is_narrow.borrow() != new_narrow {
        *is_narrow.borrow_mut() = new_narrow;
        sidebar_revealer.set_reveal_child(!new_narrow);
        toggle_button.set_visible(new_narrow);
    }
}

fn apply_theme_class(window: &gtk::ApplicationWindow) {
    let want_light = !ThemeService::is_dark();
    let has_light = window.has_css_class("light");

    if want_light && !has_light {
        window.add_css_class("light");
    } else if !want_light && has_light {
        window.remove_css_class("light");
    }
}

fn refresh_theme(window: &gtk::ApplicationWindow) {
    apply_theme_class(window);
     // Flip del tema de los widgets GTK en vivo (Adwaita dark/light). Esto es
    // lo que hace que botones/switch/entrys cambien al instante, además de
    // los tokens CSS de window.light.
    if let Some(settings) = gtk::Settings::default() {
        settings.set_gtk_application_prefer_dark_theme(ThemeService::is_dark());
    }
    window.queue_draw();
}
