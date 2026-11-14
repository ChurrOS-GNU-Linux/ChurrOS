// ==========================================
// Bluetooth en Conectividad: mis dispositivos, buscar y emparejar
// ==========================================
//
// El grupo «Bluetooth» de Conectividad:
//   - interruptor para encenderlo;
//   - «Mis dispositivos»: los emparejados; tocar conecta o desconecta y
//     «Olvidar» borra el emparejamiento;
//   - «Buscar dispositivos»: unos 30 s de búsqueda; los que aparecen con
//     nombre se emparejan con un toque.
// Emparejar abre una ventanita que enseña el código a comprobar, el código a
// escribir en el teclado o pide el PIN, según lo que pida el dispositivo
// (services/bluez.rs registra el agente que recibe esas preguntas).

use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::rc::Rc;
use std::time::{Duration, Instant};

use gtk::prelude::*;

use crate::services::bluez::{self, AgentRequest, Bluez, Device, Reply};
use crate::services::connectivity::ConnectivityService;
use crate::widgets::group::Group;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

pub type Reload = Rc<RefCell<Option<Rc<dyn Fn()>>>>;

/// Tiempo de búsqueda y cada cuánto se refresca la lista mientras busca.
const SCAN_FOR: Duration = Duration::from_secs(30);
const SCAN_REFRESH: Duration = Duration::from_millis(1500);

#[derive(Default)]
struct State {
    available: bool,
    enabled: bool,
    adapter: Option<String>,
    paired: Vec<Device>,
    found: Vec<Device>,
    scanning: bool,
    /// Generación de la búsqueda: un temporizador viejo se para solo.
    scan_generation: u32,
    /// Operación en curso por dispositivo (ruta D-Bus -> texto).
    busy: HashMap<String, &'static str>,
    error: Option<String>,
}

pub struct Panel {
    group: Rc<RefCell<Group>>,
    reload: Reload,
    bluez: Option<Bluez>,
    state: RefCell<State>,
    rows: RefCell<RowCache>,
}

/// Lo que muestra cada fila del grupo, con una clave estable.
#[derive(Clone, PartialEq)]
enum Item {
    NoAdapter,
    Switch(bool),
    Error(String),
    NonePaired,
    Paired { path: String, title: String, subtitle: String },
    Scan(bool),
    Waiting,
    Found { path: String, title: String, subtitle: String },
}

impl Item {
    fn key(&self) -> String {
        match self {
            Self::NoAdapter => "no-adapter".into(),
            // Encendido y apagado son filas distintas: el interruptor no se toca en caliente.
            Self::Switch(on) => format!("switch:{on}"),
            Self::Error(_) => "error".into(),
            Self::NonePaired => "none-paired".into(),
            Self::Paired { path, .. } => format!("paired:{path}"),
            Self::Scan(_) => "scan".into(),
            Self::Waiting => "waiting".into(),
            Self::Found { path, .. } => format!("found:{path}"),
        }
    }

    fn texts(&self) -> Option<(String, String)> {
        match self {
            Self::Error(message) => Some((message.clone(), "Toca para ocultar".into())),
            Self::Paired { title, subtitle, .. } | Self::Found { title, subtitle, .. } => {
                Some((title.clone(), subtitle.clone()))
            }
            Self::Scan(scanning) => Some(if *scanning {
                ("Buscando dispositivos…".into(), "Toca para parar".into())
            } else {
                ("Buscar dispositivos".into(), "Ponlo en modo emparejamiento y toca aquí".into())
            }),
            _ => None,
        }
    }
}

enum RowWidget {
    Row(Row),
    Switch(SwitchRow),
}

impl RowWidget {
    fn widget(&self) -> gtk::Widget {
        match self {
            Self::Row(row) => row.widget().clone().upcast(),
            Self::Switch(row) => row.widget().clone().upcast(),
        }
    }
}

/// Filas ya creadas, por clave. Una fila nueva bajo un ratón quieto no
/// recibe el primer clic (GTK no le ha mandado «entrar»): pulsar «Buscar»
/// y, sin mover el ratón, pulsar otra vez para parar no hacía nada. Por eso
/// las filas que siguen se reutilizan y solo cambian sus textos.
#[derive(Default)]
struct RowCache {
    order: Vec<String>,
    rows: HashMap<String, RowWidget>,
}

/// Las acciones de una fila redibujan el grupo, es decir, destruyen la fila
/// que se acaba de pulsar. Hacerlo dentro de su propio «clicked» dejaba el
/// gesto de GTK a medias y el siguiente clic se perdía (probado en la VM:
/// pulsar «Buscar» y luego otra vez para parar no hacía nada). Se aplaza a
/// cuando GTK termina con el clic.
fn later(action: impl FnOnce() + 'static) {
    glib::idle_add_local_once(action);
}

/// Deja solo las `keep` primeras filas de la tarjeta (con sus separadores).
fn truncate_group(group: &mut Group, keep: usize) {
    if keep == 0 {
        group.clear();
        return;
    }
    // Hijos: fila, separador, fila, separador... La fila n está en 2n.
    let mut index = 0;
    let mut child = group.card.first_child();
    while let Some(widget) = child {
        child = widget.next_sibling();
        if index >= 2 * keep - 1 {
            group.card.remove(&widget);
        }
        index += 1;
    }
}

fn trigger(reload: &Reload) {
    if let Some(f) = reload.borrow().as_ref() {
        f();
    }
}

impl Panel {
    pub fn new(group: Rc<RefCell<Group>>, reload: Reload) -> Rc<Self> {
        Rc::new(Self {
            group,
            reload,
            bluez: Bluez::system(),
            state: RefCell::new(State::default()),
            rows: RefCell::new(RowCache::default()),
        })
    }

    /// Datos del hilo de carga de Conectividad (adaptador y encendido).
    pub fn set_status(self: &Rc<Self>, available: bool, enabled: bool) {
        {
            let mut st = self.state.borrow_mut();
            st.available = available && self.bluez.is_some();
            st.enabled = enabled;
            if !enabled {
                st.scanning = false;
                st.scan_generation += 1;
                st.found.clear();
            }
        }
        self.render();
        if available && enabled {
            self.refresh();
        }
    }

    fn refresh(self: &Rc<Self>) {
        let Some(bluez) = self.bluez.clone() else { return };
        let panel = Rc::clone(self);
        glib::MainContext::default().spawn_local(async move {
            match bluez.objects().await {
                Ok((adapters, devices)) => {
                    let changed = {
                        let mut st = panel.state.borrow_mut();
                        let adapter = adapters.iter().find(|a| a.powered).or(adapters.first());
                        let adapter = adapter.map(|a| a.path.clone());
                        let (paired, found) = bluez::split_devices(&devices, adapter.as_deref().unwrap_or_default());
                        // Fuera de una búsqueda, BlueZ recuerda los vistos hace poco: no se
                        // ofrecen para emparejar hasta que el usuario busque.
                        let found = if st.scanning { bluez::merge_found(&st.found, found) } else { Vec::new() };
                        let changed = adapter != st.adapter
                            || bluez::visible_key(&paired) != bluez::visible_key(&st.paired)
                            || bluez::visible_key(&found) != bluez::visible_key(&st.found);
                        st.adapter = adapter;
                        st.paired = paired;
                        st.found = found;
                        changed
                    };
                    // Redibujar destruye las filas: un clic a medias (pulsar y
                    // soltar) se perdería. Solo si cambió algo visible.
                    if changed {
                        panel.render();
                    }
                }
                Err(err) => {
                    panel.state.borrow_mut().error =
                        Some(bluez::error_message(bluez::error_name(&err).as_deref()).to_string());
                    panel.render();
                }
            }
        });
    }

    fn items(&self) -> Vec<Item> {
        let st = self.state.borrow();
        if !st.available {
            return vec![Item::NoAdapter];
        }
        let mut items = vec![Item::Switch(st.enabled)];
        if !st.enabled {
            return items;
        }
        if let Some(error) = &st.error {
            items.push(Item::Error(error.clone()));
        }
        if st.paired.is_empty() {
            items.push(Item::NonePaired);
        }
        for device in &st.paired {
            let status = st
                .busy
                .get(&device.path)
                .copied()
                .unwrap_or(if device.connected { "Conectado" } else { "Desconectado" });
            items.push(Item::Paired {
                path: device.path.clone(),
                title: device.display_name(),
                subtitle: format!("{} · {status}", device.kind()),
            });
        }
        items.push(Item::Scan(st.scanning));
        if st.scanning && st.found.is_empty() {
            items.push(Item::Waiting);
        }
        for device in &st.found {
            items.push(Item::Found {
                path: device.path.clone(),
                title: device.display_name(),
                subtitle: format!("{} · Toca para emparejar", device.kind()),
            });
        }
        items
    }

    fn render(self: &Rc<Self>) {
        let items = self.items();
        let keys: Vec<String> = items.iter().map(Item::key).collect();
        let mut cache = self.rows.borrow_mut();
        cache.rows.retain(|key, _| keys.contains(key));
        for item in &items {
            let key = item.key();
            match cache.rows.get(&key) {
                Some(RowWidget::Row(row)) => {
                    // Misma fila: solo cambia el texto (no se destruye bajo el ratón).
                    if let Some((title, subtitle)) = item.texts() {
                        row.set_title(&title);
                        row.set_subtitle(&subtitle);
                    }
                }
                Some(RowWidget::Switch(_)) => {}
                None => {
                    let widget = self.build_row(item);
                    cache.rows.insert(key, widget);
                }
            }
        }
        if cache.order != keys {
            // Se queda el tramo inicial que no cambia y solo se quita y añade
            // lo de después: empezar o parar la búsqueda añade o quita filas
            // bajo «Buscar», que así no sale nunca de la ventana (quitar y
            // volver a poner un widget equivale a crearlo de nuevo).
            let keep = cache.order.iter().zip(&keys).take_while(|(old, new)| old == new).count();
            let mut group = self.group.borrow_mut();
            truncate_group(&mut group, keep);
            for key in &keys[keep..] {
                group.add(&cache.rows[key].widget());
            }
            cache.order = keys;
        }
    }

    fn build_row(self: &Rc<Self>, item: &Item) -> RowWidget {
        let texts = item.texts();
        let (title, subtitle) = texts.as_ref().map(|(t, s)| (t.as_str(), Some(s.as_str()))).unwrap_or(("", None));
        match item {
            Item::NoAdapter => RowWidget::Row(Row::new(
                "No se encontró un adaptador Bluetooth",
                Some("¿Está activado el modo avión?"),
                None,
                None,
                None,
                None,
            )),
            Item::Switch(enabled) => {
                let reload = Rc::clone(&self.reload);
                RowWidget::Switch(SwitchRow::new(
                    "Activar Bluetooth",
                    None,
                    None,
                    *enabled,
                    Some(Box::new(move |active| {
                        ConnectivityService::set_bluetooth(active);
                        trigger(&reload);
                    })),
                ))
            }
            Item::Error(_) => {
                let panel = Rc::clone(self);
                RowWidget::Row(Row::new(title, subtitle, None, None, None, Some(Box::new(move |_| {
                    let panel = Rc::clone(&panel);
                    later(move || {
                        panel.state.borrow_mut().error = None;
                        panel.render();
                    });
                }))))
            }
            Item::NonePaired => RowWidget::Row(Row::new(
                "Ningún dispositivo emparejado",
                Some("Busca para añadir auriculares, un ratón…"),
                None,
                None,
                None,
                None,
            )),
            Item::Paired { path, .. } => {
                let forget = gtk::Button::with_label("Olvidar");
                forget.add_css_class("flat");
                forget.set_valign(gtk::Align::Center);
                forget.set_tooltip_text(Some("Borrar el emparejamiento"));
                {
                    let (panel, path) = (Rc::clone(self), path.clone());
                    forget.connect_clicked(move |button| panel.forget(button, &path));
                }
                // La fila es un gtk::Button: el clic en un botón de dentro se lo
                // quedaba ella (conectaba en vez de olvidar). En fase de captura,
                // este gesto llega antes y reclama el clic; el teclado sigue
                // usando «clicked».
                let press = gtk::GestureClick::new();
                press.set_propagation_phase(gtk::PropagationPhase::Capture);
                {
                    let (panel, path, button) = (Rc::clone(self), path.clone(), forget.clone());
                    press.connect_pressed(move |gesture, _, _, _| {
                        gesture.set_state(gtk::EventSequenceState::Claimed);
                        panel.forget(&button, &path);
                    });
                }
                forget.add_controller(press);
                let (panel, path) = (Rc::clone(self), path.clone());
                RowWidget::Row(Row::new(title, subtitle, None, None, Some(forget.upcast_ref()), Some(Box::new(
                    move |_| {
                        let (panel, path) = (Rc::clone(&panel), path.clone());
                        later(move || panel.toggle_connection(&path));
                    },
                ))))
            }
            // Sin gtk::Spinner dentro y con subtítulos cortos: Ajustes reparte
            // el ancho según lo que miden los textos y uno largo ensancha la
            // barra lateral.
            Item::Scan(_) => {
                let panel = Rc::clone(self);
                RowWidget::Row(Row::new(title, subtitle, None, None, None, Some(Box::new(move |_| {
                    let panel = Rc::clone(&panel);
                    later(move || panel.toggle_scan());
                }))))
            }
            Item::Waiting => RowWidget::Row(Row::new("Todavía no aparece ninguno…", None, None, None, None, None)),
            Item::Found { path, .. } => {
                let (panel, path) = (Rc::clone(self), path.clone());
                RowWidget::Row(Row::new(title, subtitle, None, None, None, Some(Box::new(move |button| {
                    let parent = button.root().and_downcast::<gtk::Window>();
                    let (panel, path) = (Rc::clone(&panel), path.clone());
                    later(move || panel.pair(parent.as_ref(), &path));
                }))))
            }
        }
    }

    fn device(&self, path: &str) -> Option<Device> {
        let st = self.state.borrow();
        st.paired.iter().chain(st.found.iter()).find(|d| d.path == path).cloned()
    }

    fn toggle_scan(self: &Rc<Self>) {
        if self.state.borrow().scanning {
            self.stop_scan();
            return;
        }
        let (Some(bluez), Some(adapter)) = (self.bluez.clone(), self.state.borrow().adapter.clone()) else {
            return;
        };
        let generation = {
            let mut st = self.state.borrow_mut();
            st.scanning = true;
            st.error = None;
            st.scan_generation += 1;
            st.scan_generation
        };
        self.render();

        let panel = Rc::clone(self);
        glib::MainContext::default().spawn_local(async move {
            if let Err(err) = bluez.start_discovery(&adapter).await {
                // InProgress: otro programa ya está buscando; sirve igual.
                if !bluez::error_name(&err).is_some_and(|n| n.ends_with("InProgress")) {
                    let mut st = panel.state.borrow_mut();
                    st.scanning = false;
                    st.error = Some(bluez::error_message(bluez::error_name(&err).as_deref()).to_string());
                    drop(st);
                    panel.render();
                    return;
                }
            }
            panel.refresh();
        });

        let panel = Rc::clone(self);
        let started = Instant::now();
        glib::timeout_add_local(SCAN_REFRESH, move || {
            let current = {
                let st = panel.state.borrow();
                st.scanning && st.scan_generation == generation
            };
            if !current {
                return glib::ControlFlow::Break;
            }
            if started.elapsed() >= SCAN_FOR {
                panel.stop_scan();
                return glib::ControlFlow::Break;
            }
            panel.refresh();
            glib::ControlFlow::Continue
        });
    }

    fn stop_scan(self: &Rc<Self>) {
        let adapter = {
            let mut st = self.state.borrow_mut();
            if !st.scanning {
                return;
            }
            st.scanning = false;
            st.scan_generation += 1;
            st.adapter.clone()
        };
        if let (Some(bluez), Some(adapter)) = (self.bluez.clone(), adapter) {
            glib::MainContext::default().spawn_local(async move {
                let _ = bluez.stop_discovery(&adapter).await;
            });
        }
        // Los encontrados se quedan a la vista hasta el siguiente refresco.
        self.render();
    }

    fn toggle_connection(self: &Rc<Self>, path: &str) {
        let Some(bluez) = self.bluez.clone() else { return };
        let Some(device) = self.device(path) else { return };
        if self.state.borrow().busy.contains_key(&device.path) {
            return;
        }
        let connect = !device.connected;
        self.state
            .borrow_mut()
            .busy
            .insert(device.path.clone(), if connect { "Conectando…" } else { "Desconectando…" });
        self.render();
        let panel = Rc::clone(self);
        let path = device.path.clone();
        glib::MainContext::default().spawn_local(async move {
            let result = if connect { bluez.connect(&path).await } else { bluez.disconnect(&path).await };
            {
                let mut st = panel.state.borrow_mut();
                st.busy.remove(&path);
                if let Err(err) = result {
                    let name = bluez::error_name(&err);
                    // Ya estaba como se pedía (doble toque, o lo cambió otro programa).
                    if !bluez::already_done(name.as_deref()) {
                        st.error = Some(bluez::error_message(name.as_deref()).to_string());
                    }
                }
            }
            // «Conectando…» y el error no cuentan como cambio para refresh().
            panel.render();
            panel.refresh();
        });
    }

    fn forget(self: &Rc<Self>, button: &gtk::Button, path: &str) {
        let Some(device) = self.device(path) else { return };
        let dialog = gtk::AlertDialog::builder()
            .message(format!("¿Olvidar {}?", device.display_name()))
            .detail("Tendrás que volver a emparejarlo para usarlo.")
            .modal(true)
            .buttons(["Cancelar", "Olvidar"])
            .build();
        let window = button.root().and_downcast::<gtk::Window>();
        let panel = Rc::clone(self);
        let device = device.clone();
        dialog.choose(window.as_ref(), None::<&gio::Cancellable>, move |result| {
            if result != Ok(1) {
                return;
            }
            let (Some(bluez), Some(adapter)) = (panel.bluez.clone(), panel.state.borrow().adapter.clone()) else {
                return;
            };
            let panel = Rc::clone(&panel);
            let device = device.clone();
            glib::MainContext::default().spawn_local(async move {
                let adapter = if device.adapter.is_empty() { adapter } else { device.adapter.clone() };
                if let Err(err) = bluez.remove(&adapter, &device.path).await {
                    panel.state.borrow_mut().error =
                        Some(bluez::error_message(bluez::error_name(&err).as_deref()).to_string());
                    panel.render();
                }
                panel.refresh();
            });
        });
    }

    fn pair(self: &Rc<Self>, parent: Option<&gtk::Window>, path: &str) {
        let Some(bluez) = self.bluez.clone() else { return };
        let Some(device) = self.device(path) else { return };
        // Buscar a la vez ralentiza (o hace fallar) el emparejamiento.
        self.stop_scan();
        PairingWindow::open(parent, bluez, device, Rc::clone(self));
    }
}

// ------------------------------------------------------------------
// Ventana de emparejamiento
// ------------------------------------------------------------------

struct PairingWindow {
    window: gtk::Window,
    status: gtk::Label,
    code: gtk::Label,
    entry: gtk::Entry,
    spinner: gtk::Spinner,
    accept: gtk::Button,
    cancel: gtk::Button,
    pending: RefCell<Option<(AgentRequest, Reply)>>,
    /// Pair() sigue en curso (cerrar la ventana lo cancela).
    in_progress: Cell<bool>,
    device: Device,
    bluez: Bluez,
}

impl PairingWindow {
    fn open(parent: Option<&gtk::Window>, bluez: Bluez, device: Device, panel: Rc<Panel>) {
        let window = gtk::Window::builder()
            .title("Emparejar dispositivo")
            .modal(true)
            .resizable(false)
            .default_width(380)
            .build();
        window.add_css_class("bt-pairing");
        if let Some(parent) = parent {
            window.set_transient_for(Some(parent));
            if parent.has_css_class("light") {
                window.add_css_class("light");
            }
        }

        let content = gtk::Box::new(gtk::Orientation::Vertical, 12);
        content.set_margin_top(22);
        content.set_margin_bottom(20);
        content.set_margin_start(24);
        content.set_margin_end(24);

        let title = gtk::Label::new(Some(&device.display_name()));
        title.add_css_class("bt-pairing-title");
        title.set_wrap(true);
        let kind = gtk::Label::new(Some(device.kind()));
        kind.add_css_class("bt-pairing-kind");

        let spinner = gtk::Spinner::new();
        spinner.start();
        let status = gtk::Label::new(Some("Emparejando…"));
        status.set_wrap(true);
        status.set_justify(gtk::Justification::Center);
        status.set_max_width_chars(38);

        let code = gtk::Label::new(None);
        code.add_css_class("bt-pairing-code");
        code.set_selectable(true);
        code.set_visible(false);

        let entry = gtk::Entry::new();
        entry.set_visible(false);
        entry.set_halign(gtk::Align::Center);
        entry.set_width_chars(12);
        entry.set_max_length(16);

        let buttons = gtk::Box::new(gtk::Orientation::Horizontal, 10);
        buttons.set_halign(gtk::Align::Center);
        buttons.set_margin_top(6);
        let cancel = gtk::Button::with_label("Cancelar");
        let accept = gtk::Button::with_label("Coincide");
        accept.add_css_class("suggested-action");
        accept.set_visible(false);
        buttons.append(&cancel);
        buttons.append(&accept);

        for widget in [title.upcast_ref::<gtk::Widget>(), kind.upcast_ref(), spinner.upcast_ref(), status.upcast_ref(), code.upcast_ref(), entry.upcast_ref(), buttons.upcast_ref()] {
            content.append(widget);
        }
        window.set_child(Some(&content));

        let this = Rc::new(Self {
            window: window.clone(),
            status,
            code,
            entry: entry.clone(),
            spinner,
            accept: accept.clone(),
            cancel: cancel.clone(),
            pending: RefCell::new(None),
            in_progress: Cell::new(true),
            device,
            bluez,
        });

        {
            let this = Rc::clone(&this);
            bluez::set_agent_handler(Some(Rc::new(move |request, reply| this.on_agent(request, reply))));
        }
        {
            let this = Rc::clone(&this);
            accept.connect_clicked(move |_| this.on_accept());
        }
        {
            let this = Rc::clone(&this);
            entry.connect_activate(move |_| this.on_accept());
        }
        {
            let window = window.clone();
            cancel.connect_clicked(move |_| window.close());
        }
        {
            let this = Rc::clone(&this);
            window.connect_close_request(move |_| {
                this.on_close();
                glib::Propagation::Proceed
            });
        }

        window.present();

        glib::MainContext::default().spawn_local(async move {
            let result = match this.bluez.ensure_agent().await {
                Ok(()) => this.bluez.pair(&this.device.path).await,
                Err(err) => Err(err),
            };
            let already = result.as_ref().err().and_then(bluez::error_name).is_some_and(|n| n.ends_with("AlreadyExists"));
            if result.is_ok() || already {
                // De confianza (se reconecta solo) y conectado ya, si ofrece algo que conectar.
                let _ = this.bluez.set_trusted(&this.device.path, true).await;
                this.status.set_label("Conectando…");
                let _ = this.bluez.connect(&this.device.path).await;
            }
            this.in_progress.set(false);
            this.pending.borrow_mut().take();
            // Si la ventana ya se cerró, on_close soltó el agente (y puede que
            // otra ventana lo tenga ahora): no se toca.
            if this.window.is_visible() {
                bluez::set_agent_handler(None);
            }
            this.spinner.stop();
            this.spinner.set_visible(false);
            this.code.set_visible(false);
            this.entry.set_visible(false);
            this.accept.set_visible(false);
            match result {
                Ok(()) => {
                    this.status.set_label(&format!("¡Listo! {} ya está emparejado.", this.device.display_name()));
                    this.cancel.set_label("Cerrar");
                    let window = this.window.clone();
                    glib::timeout_add_local_once(Duration::from_millis(1600), move || window.close());
                }
                Err(err) => {
                    let name = bluez::error_name(&err);
                    this.status.set_label(bluez::error_message(name.as_deref()));
                    this.cancel.set_label("Cerrar");
                }
            }
            panel.refresh();
        });
    }

    fn show_code(&self, text: &str) {
        self.code.set_label(text);
        self.code.set_visible(true);
    }

    fn on_agent(&self, request: AgentRequest, reply: Reply) {
        // Peticiones de otro dispositivo mientras esta ventana está abierta: no.
        if request.device().is_some_and(|d| d != self.device.path) {
            reply.reject();
            return;
        }
        let name = self.device.display_name();
        match &request {
            AgentRequest::Confirmation { passkey, .. } => {
                self.status.set_label(&format!("Comprueba que {name} muestra este código y acéptalo también allí:"));
                self.show_code(&bluez::format_passkey(*passkey));
                self.accept.set_label("Coincide");
                self.accept.set_visible(true);
                self.pending.replace(Some((request, reply)));
            }
            AgentRequest::DisplayPasskey { passkey, .. } => {
                self.status.set_label(&format!("Escribe este código en {name} y pulsa Intro:"));
                self.show_code(&bluez::format_passkey(*passkey));
                reply.ok();
            }
            AgentRequest::DisplayPinCode { pin, .. } => {
                self.status.set_label(&format!("Escribe este PIN en {name} y pulsa Intro:"));
                self.show_code(pin);
                reply.ok();
            }
            AgentRequest::PinCode { .. } => {
                self.status.set_label(&format!("Escribe el PIN de {name} (suele ser 0000 o 1234):"));
                self.entry.set_text("");
                self.entry.set_input_purpose(gtk::InputPurpose::FreeForm);
                self.entry.set_visible(true);
                self.entry.grab_focus();
                self.accept.set_label("Emparejar");
                self.accept.set_visible(true);
                self.pending.replace(Some((request, reply)));
            }
            AgentRequest::Passkey { .. } => {
                self.status.set_label(&format!("Escribe el código de 6 cifras que muestra {name}:"));
                self.entry.set_text("");
                self.entry.set_input_purpose(gtk::InputPurpose::Digits);
                self.entry.set_visible(true);
                self.entry.grab_focus();
                self.accept.set_label("Emparejar");
                self.accept.set_visible(true);
                self.pending.replace(Some((request, reply)));
            }
            // Emparejamiento sin código o servicios del dispositivo que el
            // usuario está emparejando ahora mismo: se aceptan.
            AgentRequest::Authorization { .. } | AgentRequest::AuthorizeService { .. } => reply.ok(),
            AgentRequest::Cancel => {
                // BlueZ abandonó la pregunta anterior: ya no hay que contestarla.
                self.pending.borrow_mut().take();
                self.accept.set_visible(false);
                self.entry.set_visible(false);
                self.code.set_visible(false);
                self.status.set_label(&format!("{name} canceló el emparejamiento."));
                reply.ok();
            }
            AgentRequest::Release => reply.ok(),
        }
    }

    fn on_accept(&self) {
        let Some((request, reply)) = self.pending.borrow_mut().take() else { return };
        match request {
            AgentRequest::PinCode { .. } => {
                let pin = self.entry.text().to_string();
                if !bluez::valid_pin(&pin) {
                    self.status.set_label("El PIN tiene que tener entre 1 y 16 caracteres.");
                    self.pending.replace(Some((request, reply)));
                    return;
                }
                reply.pin(&pin);
            }
            AgentRequest::Passkey { .. } => {
                let Some(passkey) = bluez::parse_passkey(&self.entry.text()) else {
                    self.status.set_label("El código tiene que ser un número de hasta 6 cifras.");
                    self.pending.replace(Some((request, reply)));
                    return;
                };
                reply.passkey(passkey);
            }
            _ => reply.ok(),
        }
        self.accept.set_visible(false);
        self.entry.set_visible(false);
        self.status.set_label("Emparejando…");
    }

    fn on_close(&self) {
        if let Some((_, reply)) = self.pending.borrow_mut().take() {
            reply.cancel();
        }
        if self.in_progress.replace(false) {
            let bluez = self.bluez.clone();
            let path = self.device.path.clone();
            glib::MainContext::default().spawn_local(async move {
                let _ = bluez.cancel_pairing(&path).await;
            });
        }
        bluez::set_agent_handler(None);
    }
}
