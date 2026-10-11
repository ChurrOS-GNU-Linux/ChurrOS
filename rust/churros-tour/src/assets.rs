use std::path::PathBuf;

// En runtime (ISO instalada) los assets viven en /usr/share/churros/churros-tour/.
// En desarrollo (cargo run desde el repo) se usan los assets locales del crate.
const RUNTIME_ROOT: &str = "/usr/share/churros/churros-tour/assets";
const DEV_ROOT: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/assets");

fn assets_root() -> PathBuf {
    let runtime = PathBuf::from(RUNTIME_ROOT);
    if runtime.is_dir() {
        runtime
    } else {
        PathBuf::from(DEV_ROOT)
    }
}

pub fn css_path() -> PathBuf {
    assets_root().join("style.css")
}

#[allow(dead_code)]
pub fn icons_path(name: &str) -> PathBuf {
    assets_root().join("icons").join(name)
}

pub fn image_path(name: &str) -> PathBuf {
    assets_root().join(name)
}
