// ==========================================
// BlueZ por D-Bus: dispositivos, búsqueda, emparejamiento y agente
// ==========================================
//
// Ajustes habla con bluetoothd directamente (bus de sistema, org.bluez) en
// vez de leer la salida de bluetoothctl, que cambia entre versiones y no
// puede responder a un código de emparejamiento sin una terminal.
//
// Emparejar un móvil o un teclado necesita un «agente»: el objeto al que
// BlueZ pregunta «¿coincide este código?» o «¿qué PIN escribo?». Ajustes
// registra el suyo (org.bluez.Agent1) y la ventana de emparejamiento contesta.
//
// Todo lo que interpreta respuestas de BlueZ es puro y tiene tests; las
// llamadas son asíncronas (gio) y no bloquean la interfaz.

use std::cell::RefCell;
use std::rc::Rc;

use gio::prelude::*;
use glib::variant::ObjectPath;
use glib::Variant;

const BLUEZ: &str = "org.bluez";
const ADAPTER: &str = "org.bluez.Adapter1";
const DEVICE: &str = "org.bluez.Device1";
const AGENT_MANAGER: &str = "org.bluez.AgentManager1";
pub const AGENT_PATH: &str = "/org/churros/settings/bluetooth_agent";
/// Teclado y pantalla: BlueZ puede pedir confirmar, mostrar o escribir códigos.
const AGENT_CAPABILITY: &str = "KeyboardDisplay";

const AGENT_XML: &str = r#"
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
    <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
    <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
    <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
    <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
    <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="Cancel"/>
  </interface>
</node>"#;

// ------------------------------------------------------------------
// Modelo
// ------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub struct Adapter {
    pub path: String,
    pub powered: bool,
    pub discovering: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Device {
    pub path: String,
    pub adapter: String,
    pub address: String,
    /// `Name` que anuncia el dispositivo (None si no anuncia ninguno).
    pub name: Option<String>,
    /// `Alias`: el nombre que ve el usuario (por defecto, el Name o la MAC).
    pub alias: String,
    pub icon: String,
    pub paired: bool,
    pub trusted: bool,
    pub connected: bool,
    pub rssi: Option<i16>,
}

impl Device {
    pub fn display_name(&self) -> String {
        if !self.alias.is_empty() {
            return self.alias.clone();
        }
        self.name.clone().unwrap_or_else(|| self.address.clone())
    }

    /// Tipo legible a partir del icono que da BlueZ (freedesktop icon name).
    pub fn kind(&self) -> &'static str {
        device_kind(&self.icon)
    }
}

pub fn device_kind(icon: &str) -> &'static str {
    match icon {
        "audio-headset" | "audio-headphones" => "Auriculares",
        "audio-card" => "Altavoz",
        "input-keyboard" => "Teclado",
        "input-mouse" => "Ratón",
        "input-gaming" => "Mando",
        "input-tablet" => "Tableta gráfica",
        "phone" => "Teléfono",
        "computer" => "Ordenador",
        "video-display" => "Pantalla",
        "printer" => "Impresora",
        "camera-photo" | "camera-video" => "Cámara",
        "modem" | "network-wireless" => "Red",
        _ => "Dispositivo",
    }
}

/// Lee `GetManagedObjects` (a{oa{sa{sv}}}): adaptadores y dispositivos.
pub fn parse_objects(objects: &Variant) -> (Vec<Adapter>, Vec<Device>) {
    let mut adapters = Vec::new();
    let mut devices = Vec::new();
    for i in 0..objects.n_children() {
        let entry = objects.child_value(i);
        let Some(path) = entry.child_value(0).str().map(str::to_string) else { continue };
        let interfaces = entry.child_value(1);
        if let Some(props) = interface_props(&interfaces, ADAPTER) {
            let props = glib::VariantDict::new(Some(&props));
            adapters.push(Adapter {
                path: path.clone(),
                powered: bool_prop(&props, "Powered"),
                discovering: bool_prop(&props, "Discovering"),
            });
        }
        if let Some(props) = interface_props(&interfaces, DEVICE) {
            let props = glib::VariantDict::new(Some(&props));
            let Some(address) = string_prop(&props, "Address") else { continue };
            devices.push(Device {
                adapter: object_prop(&props, "Adapter").unwrap_or_default(),
                path,
                name: string_prop(&props, "Name").filter(|n| !n.trim().is_empty()),
                alias: string_prop(&props, "Alias").unwrap_or_default(),
                icon: string_prop(&props, "Icon").unwrap_or_default(),
                paired: bool_prop(&props, "Paired"),
                trusted: bool_prop(&props, "Trusted"),
                connected: bool_prop(&props, "Connected"),
                rssi: props.lookup_value("RSSI", None).and_then(|v| v.get::<i16>()),
                address,
            });
        }
    }
    adapters.sort_by(|a, b| a.path.cmp(&b.path));
    (adapters, devices)
}

/// Propiedades (a{sv}) de una interfaz dentro de a{sa{sv}}.
fn interface_props(interfaces: &Variant, name: &str) -> Option<Variant> {
    (0..interfaces.n_children())
        .map(|i| interfaces.child_value(i))
        .find(|entry| entry.child_value(0).str() == Some(name))
        .map(|entry| entry.child_value(1))
}

fn bool_prop(props: &glib::VariantDict, key: &str) -> bool {
    props.lookup_value(key, None).and_then(|v| v.get::<bool>()).unwrap_or(false)
}

fn string_prop(props: &glib::VariantDict, key: &str) -> Option<String> {
    props.lookup_value(key, None).and_then(|v| v.str().map(str::to_string))
}

fn object_prop(props: &glib::VariantDict, key: &str) -> Option<String> {
    string_prop(props, key)
}

/// Emparejados (conectados primero, luego por nombre) y disponibles para
/// emparejar: los que anuncian un nombre, del más cercano al más lejano.
/// Sin nombre suelen ser balizas o aparatos ajenos que no se pueden emparejar
/// desde aquí; mostrarlos llenaría la lista de direcciones MAC.
pub fn split_devices(devices: &[Device], adapter: &str) -> (Vec<Device>, Vec<Device>) {
    let mine = devices.iter().filter(|d| d.adapter.is_empty() || d.adapter == adapter);
    let mut paired: Vec<Device> = mine.clone().filter(|d| d.paired).cloned().collect();
    paired.sort_by(|a, b| {
        b.connected
            .cmp(&a.connected)
            .then_with(|| a.display_name().to_lowercase().cmp(&b.display_name().to_lowercase()))
    });
    let mut available: Vec<Device> = mine.filter(|d| !d.paired && d.name.is_some()).cloned().collect();
    available.sort_by(|a, b| {
        b.rssi
            .unwrap_or(i16::MIN)
            .cmp(&a.rssi.unwrap_or(i16::MIN))
            .then_with(|| a.display_name().to_lowercase().cmp(&b.display_name().to_lowercase()))
    });
    (paired, available)
}

/// Lista de «disponibles» durante una búsqueda: los que ya estaban conservan
/// su sitio (la señal cambia sin parar y la lista no debe bailar bajo el
/// dedo) y los nuevos se añaden al final, del más cercano al más lejano.
pub fn merge_found(previous: &[Device], fresh: Vec<Device>) -> Vec<Device> {
    let mut merged: Vec<Device> = previous
        .iter()
        .filter_map(|old| fresh.iter().find(|d| d.path == old.path).cloned())
        .collect();
    for device in fresh {
        if !merged.iter().any(|d| d.path == device.path) {
            merged.push(device);
        }
    }
    merged
}

/// Lo que se ve de un dispositivo en la lista (sin la señal, que cambia sola).
pub fn visible_key(devices: &[Device]) -> Vec<(String, String, String, bool, bool)> {
    devices
        .iter()
        .map(|d| (d.path.clone(), d.display_name(), d.icon.clone(), d.paired, d.connected))
        .collect()
}

// ------------------------------------------------------------------
// Agente
// ------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum AgentRequest {
    /// Hay que devolver un PIN (dispositivos antiguos).
    PinCode { device: String },
    /// Hay que devolver un número de 6 cifras.
    Passkey { device: String },
    /// Mostrar un PIN para escribirlo en el dispositivo.
    DisplayPinCode { device: String, pin: String },
    /// Mostrar un código para escribirlo en el dispositivo (teclados).
    DisplayPasskey { device: String, passkey: u32, entered: u16 },
    /// ¿Coincide el código con el que muestra el dispositivo? (móviles)
    Confirmation { device: String, passkey: u32 },
    /// Emparejamiento sin código: ¿se acepta?
    Authorization { device: String },
    /// Un dispositivo emparejado quiere usar un servicio.
    AuthorizeService { device: String, uuid: String },
    /// BlueZ cancela la petición en curso.
    Cancel,
    /// BlueZ ya no usa este agente.
    Release,
}

impl AgentRequest {
    pub fn device(&self) -> Option<&str> {
        match self {
            Self::PinCode { device }
            | Self::Passkey { device }
            | Self::DisplayPinCode { device, .. }
            | Self::DisplayPasskey { device, .. }
            | Self::Confirmation { device, .. }
            | Self::Authorization { device }
            | Self::AuthorizeService { device, .. } => Some(device),
            Self::Cancel | Self::Release => None,
        }
    }
}

/// Traduce una llamada a org.bluez.Agent1 (nombre del método y argumentos).
pub fn agent_request(method: &str, params: &Variant) -> Option<AgentRequest> {
    let arg = |i: usize| (i < params.n_children()).then(|| params.child_value(i));
    let device = || arg(0).and_then(|v| v.str().map(str::to_string));
    Some(match method {
        "RequestPinCode" => AgentRequest::PinCode { device: device()? },
        "RequestPasskey" => AgentRequest::Passkey { device: device()? },
        "DisplayPinCode" => AgentRequest::DisplayPinCode { device: device()?, pin: arg(1)?.str()?.to_string() },
        "DisplayPasskey" => AgentRequest::DisplayPasskey {
            device: device()?,
            passkey: arg(1)?.get::<u32>()?,
            entered: arg(2)?.get::<u16>()?,
        },
        "RequestConfirmation" => AgentRequest::Confirmation { device: device()?, passkey: arg(1)?.get::<u32>()? },
        "RequestAuthorization" => AgentRequest::Authorization { device: device()? },
        "AuthorizeService" => AgentRequest::AuthorizeService { device: device()?, uuid: arg(1)?.str()?.to_string() },
        "Cancel" => AgentRequest::Cancel,
        "Release" => AgentRequest::Release,
        _ => return None,
    })
}

/// Código de 6 cifras como lo muestran los móviles: «012 345».
pub fn format_passkey(passkey: u32) -> String {
    let digits = format!("{:06}", passkey % 1_000_000);
    format!("{} {}", &digits[..3], &digits[3..])
}

/// Valida lo que escribe el usuario cuando BlueZ pide un número (0-999999).
pub fn parse_passkey(text: &str) -> Option<u32> {
    let digits: String = text.chars().filter(|c| !c.is_whitespace()).collect();
    if digits.is_empty() || digits.len() > 6 || !digits.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

/// PIN clásico: de 1 a 16 caracteres imprimibles.
pub fn valid_pin(text: &str) -> bool {
    let len = text.chars().count();
    (1..=16).contains(&len) && text.chars().all(|c| !c.is_control())
}

/// Respuesta pendiente de una petición del agente.
pub struct Reply(gio::DBusMethodInvocation);

impl Reply {
    pub fn ok(self) {
        self.0.return_value(None);
    }

    pub fn pin(self, pin: &str) {
        self.0.return_value(Some(&(pin,).to_variant()));
    }

    pub fn passkey(self, passkey: u32) {
        self.0.return_value(Some(&(passkey,).to_variant()));
    }

    pub fn reject(self) {
        self.0.return_dbus_error("org.bluez.Error.Rejected", "Rechazado desde Ajustes de ChurrOS");
    }

    pub fn cancel(self) {
        self.0.return_dbus_error("org.bluez.Error.Canceled", "Cancelado desde Ajustes de ChurrOS");
    }
}

pub type AgentHandler = Rc<dyn Fn(AgentRequest, Reply)>;

thread_local! {
    /// Quién atiende ahora las peticiones del agente (la ventana de emparejar).
    static HANDLER: RefCell<Option<AgentHandler>> = const { RefCell::new(None) };
    static AGENT_REGISTERED: RefCell<bool> = const { RefCell::new(false) };
}

pub fn set_agent_handler(handler: Option<AgentHandler>) {
    HANDLER.with(|h| *h.borrow_mut() = handler);
}

fn dispatch(request: AgentRequest, reply: Reply) {
    let handler = HANDLER.with(|h| h.borrow().clone());
    match (handler, &request) {
        (Some(handler), _) => handler(request, reply),
        // Sin ventana abierta: Cancel y Release no esperan respuesta útil.
        (None, AgentRequest::Cancel | AgentRequest::Release) => reply.ok(),
        // Nadie emparejando: no se acepta nada a ciegas.
        (None, _) => reply.reject(),
    }
}

// ------------------------------------------------------------------
// Errores de BlueZ
// ------------------------------------------------------------------

/// Nombre D-Bus del error (org.bluez.Error.*), si lo hay.
pub fn error_name(err: &glib::Error) -> Option<String> {
    gio::DBusError::remote_error(err).map(|s| s.to_string())
}

/// Conectar algo ya conectado o desconectar algo ya desconectado no es un fallo.
pub fn already_done(name: Option<&str>) -> bool {
    matches!(
        name.unwrap_or_default().rsplit('.').next(),
        Some("AlreadyConnected" | "NotConnected")
    )
}

/// Mensaje en español para un error de BlueZ (por su nombre D-Bus).
pub fn error_message(name: Option<&str>) -> &'static str {
    match name.unwrap_or_default().rsplit('.').next().unwrap_or_default() {
        "AuthenticationFailed" => "El código no coincide o el dispositivo lo rechazó.",
        "AuthenticationCanceled" | "Canceled" => "Se canceló el emparejamiento.",
        "AuthenticationRejected" | "Rejected" => "El dispositivo rechazó el emparejamiento.",
        "AuthenticationTimeout" | "NoReply" | "Timeout" | "TimedOut" => {
            "El dispositivo no respondió a tiempo. Acércalo y vuelve a intentarlo."
        }
        "ConnectionAttemptFailed" | "PageTimeout" => {
            "No se pudo contactar con el dispositivo. Comprueba que esté encendido, cerca y en modo emparejamiento."
        }
        "AlreadyExists" => "Ese dispositivo ya estaba emparejado.",
        "InProgress" => "Ya hay una operación en curso con ese dispositivo. Espera un momento.",
        "NotReady" | "NotPowered" => "El Bluetooth está apagado.",
        "Blocked" => "El Bluetooth está bloqueado (modo avión o interruptor del equipo).",
        "DoesNotExist" | "UnknownObject" => "El dispositivo ya no está disponible. Vuelve a buscar.",
        "NotAvailable" | "NotSupported" | "ProfileUnavailable" => {
            "El dispositivo está emparejado, pero no ofrece nada que ChurrOS pueda usar directamente."
        }
        "ServiceUnknown" | "NameHasNoOwner" => "El servicio de Bluetooth no está en marcha.",
        _ => "No se pudo completar la operación de Bluetooth.",
    }
}

// ------------------------------------------------------------------
// Cliente
// ------------------------------------------------------------------

#[derive(Clone)]
pub struct Bluez {
    conn: gio::DBusConnection,
}

fn object_path(path: &str) -> Option<ObjectPath> {
    ObjectPath::try_from(path.to_string()).ok()
}

impl Bluez {
    /// Conexión al bus de sistema; None si no hay bus (contenedores, pruebas).
    pub fn system() -> Option<Self> {
        gio::bus_get_sync(gio::BusType::System, None::<&gio::Cancellable>)
            .ok()
            .map(|conn| Self { conn })
    }

    async fn call(
        &self,
        path: &str,
        interface: &str,
        method: &str,
        params: Option<Variant>,
        timeout_ms: i32,
    ) -> Result<Variant, glib::Error> {
        self.conn
            .call_future(
                Some(BLUEZ),
                path,
                interface,
                method,
                params.as_ref(),
                None,
                gio::DBusCallFlags::NONE,
                timeout_ms,
            )
            .await
    }

    pub async fn objects(&self) -> Result<(Vec<Adapter>, Vec<Device>), glib::Error> {
        let reply = self
            .call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None, 5_000)
            .await?;
        Ok(parse_objects(&reply.child_value(0)))
    }

    pub async fn start_discovery(&self, adapter: &str) -> Result<(), glib::Error> {
        self.call(adapter, ADAPTER, "StartDiscovery", None, 5_000).await.map(|_| ())
    }

    pub async fn stop_discovery(&self, adapter: &str) -> Result<(), glib::Error> {
        self.call(adapter, ADAPTER, "StopDiscovery", None, 5_000).await.map(|_| ())
    }

    /// Empareja. Puede tardar: el usuario tiene que confirmar el código.
    pub async fn pair(&self, device: &str) -> Result<(), glib::Error> {
        self.call(device, DEVICE, "Pair", None, 120_000).await.map(|_| ())
    }

    pub async fn cancel_pairing(&self, device: &str) -> Result<(), glib::Error> {
        self.call(device, DEVICE, "CancelPairing", None, 5_000).await.map(|_| ())
    }

    pub async fn connect(&self, device: &str) -> Result<(), glib::Error> {
        self.call(device, DEVICE, "Connect", None, 30_000).await.map(|_| ())
    }

    pub async fn disconnect(&self, device: &str) -> Result<(), glib::Error> {
        self.call(device, DEVICE, "Disconnect", None, 15_000).await.map(|_| ())
    }

    /// De confianza: se vuelve a conectar solo, sin preguntar.
    pub async fn set_trusted(&self, device: &str, trusted: bool) -> Result<(), glib::Error> {
        let params = (DEVICE, "Trusted", trusted.to_variant()).to_variant();
        self.call(device, "org.freedesktop.DBus.Properties", "Set", Some(params), 5_000)
            .await
            .map(|_| ())
    }

    /// Olvidar: BlueZ borra el emparejamiento y las claves.
    pub async fn remove(&self, adapter: &str, device: &str) -> Result<(), glib::Error> {
        let Some(path) = object_path(device) else {
            return Err(glib::Error::new(gio::IOErrorEnum::InvalidArgument, "ruta de dispositivo no válida"));
        };
        self.call(adapter, ADAPTER, "RemoveDevice", Some((path,).to_variant()), 10_000)
            .await
            .map(|_| ())
    }

    /// Registra el agente de Ajustes como agente por defecto (una vez por proceso).
    pub async fn ensure_agent(&self) -> Result<(), glib::Error> {
        if AGENT_REGISTERED.with(|r| *r.borrow()) {
            return Ok(());
        }
        let node = gio::DBusNodeInfo::for_xml(AGENT_XML)?;
        let Some(interface) = node.lookup_interface("org.bluez.Agent1") else {
            return Err(glib::Error::new(gio::IOErrorEnum::Failed, "interfaz del agente no encontrada"));
        };
        self.conn
            .register_object(AGENT_PATH, &interface)
            .method_call(|_, _, _, _, method, params, invocation| match agent_request(method, &params) {
                Some(request) => dispatch(request, Reply(invocation)),
                None => invocation.return_dbus_error("org.bluez.Error.Rejected", "método desconocido"),
            })
            .build()?;
        AGENT_REGISTERED.with(|r| *r.borrow_mut() = true);

        let Some(path) = object_path(AGENT_PATH) else {
            return Err(glib::Error::new(gio::IOErrorEnum::InvalidArgument, "ruta del agente no válida"));
        };
        let register = (path.clone(), AGENT_CAPABILITY).to_variant();
        if let Err(err) = self.call("/org/bluez", AGENT_MANAGER, "RegisterAgent", Some(register), 5_000).await {
            // AlreadyExists: ya registrado por esta conexión; lo demás sí es un fallo.
            if error_name(&err).as_deref() != Some("org.bluez.Error.AlreadyExists") {
                return Err(err);
            }
        }
        // Que BlueZ pregunte a Ajustes también cuando empareja otro (el móvil).
        let _ = self
            .call("/org/bluez", AGENT_MANAGER, "RequestDefaultAgent", Some((path,).to_variant()), 5_000)
            .await;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const OBJECTS: &str = "{
        objectpath '/org/bluez': {'org.bluez.AgentManager1': @a{sv} {}},
        objectpath '/org/bluez/hci0': {'org.bluez.Adapter1': {'Powered': <true>, 'Discovering': <false>, 'Address': <'00:11:22:33:44:55'>}},
        objectpath '/org/bluez/hci0/dev_AA_AA_AA_AA_AA_01': {'org.bluez.Device1': {
            'Address': <'AA:AA:AA:AA:AA:01'>, 'Name': <'WH-1000XM4'>, 'Alias': <'Mis cascos'>,
            'Icon': <'audio-headset'>, 'Paired': <true>, 'Trusted': <true>, 'Connected': <true>,
            'Adapter': <objectpath '/org/bluez/hci0'>}},
        objectpath '/org/bluez/hci0/dev_AA_AA_AA_AA_AA_02': {'org.bluez.Device1': {
            'Address': <'AA:AA:AA:AA:AA:02'>, 'Name': <'Logitech K380'>, 'Alias': <'Logitech K380'>,
            'Icon': <'input-keyboard'>, 'Paired': <true>, 'Connected': <false>,
            'Adapter': <objectpath '/org/bluez/hci0'>}},
        objectpath '/org/bluez/hci0/dev_AA_AA_AA_AA_AA_03': {'org.bluez.Device1': {
            'Address': <'AA:AA:AA:AA:AA:03'>, 'Name': <'Pixel 8'>, 'Alias': <'Pixel 8'>,
            'Icon': <'phone'>, 'Paired': <false>, 'RSSI': <int16 -48>,
            'Adapter': <objectpath '/org/bluez/hci0'>}},
        objectpath '/org/bluez/hci0/dev_AA_AA_AA_AA_AA_04': {'org.bluez.Device1': {
            'Address': <'AA:AA:AA:AA:AA:04'>, 'Name': <'JBL Flip 5'>, 'Alias': <'JBL Flip 5'>,
            'Icon': <'audio-card'>, 'Paired': <false>, 'RSSI': <int16 -80>,
            'Adapter': <objectpath '/org/bluez/hci0'>}},
        objectpath '/org/bluez/hci0/dev_AA_AA_AA_AA_AA_05': {'org.bluez.Device1': {
            'Address': <'AA:AA:AA:AA:AA:05'>, 'Alias': <'AA-AA-AA-AA-AA-05'>, 'Paired': <false>, 'RSSI': <int16 -30>,
            'Adapter': <objectpath '/org/bluez/hci0'>}}
    }";

    fn objects() -> Variant {
        Variant::parse(Some(glib::VariantTy::new("a{oa{sa{sv}}}").unwrap()), OBJECTS).expect("variant de prueba")
    }

    #[test]
    fn managed_objects_become_adapters_and_devices() {
        let (adapters, devices) = parse_objects(&objects());
        assert_eq!(adapters, vec![Adapter { path: "/org/bluez/hci0".into(), powered: true, discovering: false }]);
        assert_eq!(devices.len(), 5);
        let cascos = &devices[0];
        assert_eq!(cascos.display_name(), "Mis cascos");
        assert_eq!(cascos.kind(), "Auriculares");
        assert!(cascos.paired && cascos.trusted && cascos.connected);
        assert_eq!(cascos.adapter, "/org/bluez/hci0");
        let anonymous = devices.iter().find(|d| d.address.ends_with("05")).unwrap();
        assert_eq!(anonymous.name, None);
        assert_eq!(anonymous.rssi, Some(-30));
    }

    #[test]
    fn paired_first_connected_on_top_and_available_by_signal_without_nameless() {
        let (_, devices) = parse_objects(&objects());
        let (paired, available) = split_devices(&devices, "/org/bluez/hci0");
        let names = |list: &[Device]| list.iter().map(Device::display_name).collect::<Vec<_>>();
        assert_eq!(names(&paired), ["Mis cascos", "Logitech K380"]);
        // El sin nombre (balizas) no aparece aunque sea el más cercano.
        assert_eq!(names(&available), ["Pixel 8", "JBL Flip 5"]);
        // Dispositivos de otro adaptador no se mezclan.
        let (paired, available) = split_devices(&devices, "/org/bluez/hci1");
        assert!(paired.is_empty() && available.is_empty());
    }

    #[test]
    fn found_devices_keep_their_place_while_scanning() {
        let (_, devices) = parse_objects(&objects());
        let (_, first) = split_devices(&devices, "/org/bluez/hci0");
        assert_eq!(first.iter().map(Device::display_name).collect::<Vec<_>>(), ["Pixel 8", "JBL Flip 5"]);
        // Ahora el JBL suena más fuerte y aparece un mando nuevo.
        let mut moved = devices.clone();
        for d in &mut moved {
            if d.display_name() == "JBL Flip 5" {
                d.rssi = Some(-20);
            }
        }
        let mut mando = moved[2].clone();
        mando.path = "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_09".into();
        mando.alias = "Mando".into();
        mando.name = Some("Mando".into());
        mando.rssi = Some(-10);
        moved.push(mando);
        let (_, fresh) = split_devices(&moved, "/org/bluez/hci0");
        let merged = merge_found(&first, fresh);
        assert_eq!(merged.iter().map(Device::display_name).collect::<Vec<_>>(), ["Pixel 8", "JBL Flip 5", "Mando"]);
        // La señal no cuenta como cambio visible; un dispositivo nuevo sí.
        let mut louder = first.clone();
        louder[0].rssi = Some(-5);
        assert_eq!(visible_key(&first), visible_key(&louder));
        assert_ne!(visible_key(&first), visible_key(&merged));
        // Los que dejan de anunciarse desaparecen.
        assert_eq!(merge_found(&merged, Vec::new()), Vec::<Device>::new());
    }

    #[test]
    fn agent_calls_are_understood() {
        let dev = "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_03";
        let path = || ObjectPath::try_from(dev.to_string()).unwrap();
        assert_eq!(
            agent_request("RequestConfirmation", &(path(), 123_456u32).to_variant()),
            Some(AgentRequest::Confirmation { device: dev.into(), passkey: 123_456 })
        );
        assert_eq!(
            agent_request("DisplayPasskey", &(path(), 42u32, 3u16).to_variant()),
            Some(AgentRequest::DisplayPasskey { device: dev.into(), passkey: 42, entered: 3 })
        );
        assert_eq!(
            agent_request("RequestPinCode", &(path(),).to_variant()),
            Some(AgentRequest::PinCode { device: dev.into() })
        );
        assert_eq!(
            agent_request("RequestPasskey", &(path(),).to_variant()),
            Some(AgentRequest::Passkey { device: dev.into() })
        );
        assert_eq!(
            agent_request("DisplayPinCode", &(path(), "0000").to_variant()),
            Some(AgentRequest::DisplayPinCode { device: dev.into(), pin: "0000".into() })
        );
        assert_eq!(
            agent_request("AuthorizeService", &(path(), "0000110b").to_variant()),
            Some(AgentRequest::AuthorizeService { device: dev.into(), uuid: "0000110b".into() })
        );
        assert_eq!(agent_request("Cancel", &().to_variant()), Some(AgentRequest::Cancel));
        assert_eq!(agent_request("Release", &().to_variant()), Some(AgentRequest::Release));
        // Argumentos que faltan o método desconocido: nada (el agente rechaza).
        assert_eq!(agent_request("RequestConfirmation", &(path(),).to_variant()), None);
        assert_eq!(agent_request("Format", &().to_variant()), None);
        // La interfaz del XML declara exactamente esos métodos.
        let node = gio::DBusNodeInfo::for_xml(AGENT_XML).expect("XML del agente");
        let iface = node.lookup_interface("org.bluez.Agent1").expect("Agent1");
        for method in [
            "Release", "RequestPinCode", "DisplayPinCode", "RequestPasskey", "DisplayPasskey",
            "RequestConfirmation", "RequestAuthorization", "AuthorizeService", "Cancel",
        ] {
            assert!(iface.lookup_method(method).is_some(), "falta {method} en AGENT_XML");
        }
    }

    #[test]
    fn codes_are_shown_and_read_like_on_a_phone() {
        assert_eq!(format_passkey(123_456), "123 456");
        assert_eq!(format_passkey(42), "000 042");
        assert_eq!(parse_passkey("123 456"), Some(123_456));
        assert_eq!(parse_passkey("000042"), Some(42));
        assert_eq!(parse_passkey("1234567"), None);
        assert_eq!(parse_passkey("12a456"), None);
        assert_eq!(parse_passkey(""), None);
        assert!(valid_pin("0000"));
        assert!(!valid_pin(""));
        assert!(!valid_pin("12345678901234567"));
    }

    #[test]
    fn bluez_errors_are_explained_in_spanish() {
        assert_eq!(
            error_message(Some("org.bluez.Error.AuthenticationFailed")),
            "El código no coincide o el dispositivo lo rechazó."
        );
        assert!(error_message(Some("org.bluez.Error.ConnectionAttemptFailed")).contains("modo emparejamiento"));
        assert!(error_message(Some("org.freedesktop.DBus.Error.ServiceUnknown")).contains("no está en marcha"));
        assert_eq!(error_message(None), "No se pudo completar la operación de Bluetooth.");
        assert_eq!(error_message(Some("org.bluez.Error.Algo")), "No se pudo completar la operación de Bluetooth.");
        assert!(already_done(Some("org.bluez.Error.AlreadyConnected")));
        assert!(already_done(Some("org.bluez.Error.NotConnected")));
        assert!(!already_done(Some("org.bluez.Error.Failed")));
        assert!(!already_done(None));
        for kind in ["audio-headset", "input-mouse", "phone", "desconocido"] {
            assert!(!device_kind(kind).is_empty());
        }
    }
}
