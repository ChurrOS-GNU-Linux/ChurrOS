use std::io::Write;
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

static LOG_PATH: OnceLock<String> = OnceLock::new();

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

pub fn init(app: &str) {
    let path = churros_services::open_runtime_file(&format!("{app}.log"), true)
        .map(|(path, _)| path.display().to_string())
        .unwrap_or_default();
    let _ = LOG_PATH.set(path);
    log(&format!("inicio pid={}", std::process::id()));

    let path = LOG_PATH.get().cloned().unwrap_or_default();
    std::panic::set_hook(Box::new(move |info| {
        if let Some(name) = std::path::Path::new(&path).file_name().and_then(|name| name.to_str())
            && let Ok((_, mut f)) = churros_services::open_runtime_file(name, true) {
            let _ = writeln!(f, "[{}] PANIC: {info}", now());
        }
    }));
}

pub fn log(msg: &str) {
    if let Some(path) = LOG_PATH.get() {
        if let Some(name) = std::path::Path::new(path).file_name().and_then(|name| name.to_str())
            && let Ok((_, mut f)) = churros_services::open_runtime_file(name, true) {
            let _ = writeln!(f, "[{}] {msg}", now());
        }
    }
}
