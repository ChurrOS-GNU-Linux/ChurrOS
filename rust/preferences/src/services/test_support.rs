// ==========================================
// Utilidades de los tests que escriben ~/.config/niri/config.kdl.
// cargo test corre los tests en hilos del mismo proceso y HOME es de todo
// el proceso: quien lo cambia lo hace con TempHome, que lo serializa.
// ==========================================

use serde_json::{json, Value};
use std::ffi::OsString;
use std::fs;
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};

static HOME_LOCK: Mutex<()> = Mutex::new(());

/// config.kdl de niri que lleva la ISO (skel).
pub const SKEL_NIRI_CONFIG: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../archiso/airootfs/etc/skel/.config/niri/config.kdl"
);

pub fn skel_niri_config() -> String {
    fs::read_to_string(SKEL_NIRI_CONFIG).expect("leer el config.kdl de niri del skel")
}

/// HOME temporal con `config` como ~/.config/niri/config.kdl. Mientras
/// vive, ningún otro test cambia HOME; al soltarlo se borra y HOME vuelve.
pub struct TempHome {
    pub root: PathBuf,
    previous: Option<OsString>,
    _lock: MutexGuard<'static, ()>,
}

impl TempHome {
    pub fn new(tag: &str, config: &str) -> Self {
        // Un test que falla con el lock cogido lo envenena; los demás siguen.
        let lock = HOME_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let root = std::env::temp_dir().join(format!("churros-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join(".config").join("niri")).expect("crear el HOME temporal");
        let home = TempHome { root, previous: std::env::var_os("HOME"), _lock: lock };
        home.write(config);
        unsafe { std::env::set_var("HOME", &home.root) };
        home
    }

    pub fn niri_config(&self) -> PathBuf {
        self.root.join(".config").join("niri").join("config.kdl")
    }

    pub fn read(&self) -> String {
        fs::read_to_string(self.niri_config()).expect("leer el config.kdl del HOME temporal")
    }

    pub fn write(&self, content: &str) {
        fs::write(self.niri_config(), content).expect("escribir el config.kdl del HOME temporal");
    }
}

impl Drop for TempHome {
    fn drop(&mut self) {
        match self.previous.take() {
            Some(home) => unsafe { std::env::set_var("HOME", home) },
            None => unsafe { std::env::remove_var("HOME") },
        }
        let _ = fs::remove_dir_all(&self.root);
    }
}

/// Lo que manda pages/window_rules.rs (on_edit_rule + on_update_rule) al
/// guardar la regla `rule` sin tocar el formulario.
pub fn rule_form(rule: &Value) -> Value {
    let switch = |field: &str| rule[field].as_bool().unwrap_or(false).then_some(true);
    json!({
        "app_id": rule["app_id"].as_str().unwrap_or(""),
        "title": rule["title"].as_str().unwrap_or(""),
        "opacity": rule["opacity"].as_f64().filter(|v| *v < 1.0),
        "corner_radius": rule["corner_radius"].as_f64().filter(|v| *v != 0.0),
        "open_floating": switch("open_floating"),
        "clip_to_geometry": switch("clip_to_geometry"),
        "blur": switch("blur"),
    })
}
