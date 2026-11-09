// ==========================================
// GreeterService — pantalla de inicio (greetd + ReGreet)
//
// Dos mitades (docs/login-greeter.md):
// - Opciones del sistema (oscurecido, logo, acento, reloj): las aplica
//   churros-write-root-config greeter-set vía churros-pkexec, con
//   contraseña. Su estado se lee de /etc/greetd/churros-greeter.conf.
// - Fondo: lo escribe la sesión del usuario, sin root, en
//   /var/lib/churros/greeter (grupo wheel, tmpfiles.d/churros-greeter.conf).
//   `churros-settings --sync-greeter` lo regenera al cambiar el fondo del
//   escritorio (unidad de usuario churros-greeter-sync.path). Seguir el
//   fondo, difuminarlo y la imagen propia son preferencias del usuario
//   (settings.json).
// ==========================================

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use gtk::gdk_pixbuf::{Colorspace, InterpType, Pixbuf};

use crate::services::settings;
use crate::services::wallpaper::WallpaperService;

pub const GREETER_CONF: &str = "/etc/greetd/churros-greeter.conf";
pub const BACKGROUND_DIR: &str = "/var/lib/churros/greeter";
/// El que lee ReGreet (regreet.toml [background] path).
const BACKGROUND: &str = "/var/lib/churros/greeter/background.jpg";
const DEFAULT_BACKGROUND: &str = "/usr/share/churros/greeter/background.jpg";
const WRITE_ROOT_CONFIG: &str = "/usr/local/bin/churros-write-root-config";

/// Tamaño máximo del fondo nítido: el greeter lo escala con Cover.
const MAX_WIDTH: i32 = 1920;
const MAX_HEIGHT: i32 = 1080;
/// El difuminado se calcula en pequeño y se amplía: a esa escala unas
/// pasadas de caja equivalen a un desenfoque gaussiano grande.
const BLUR_WIDTH: i32 = 320;
const BLUR_RADIUS: usize = 4;
const BLUR_PASSES: usize = 3;
const BLUR_OUTPUT_WIDTH: i32 = 1280;

pub const ORANGE: &str = "#F97316";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GreeterConfig {
    /// Oscurecido del fondo, 0–80 %.
    pub dim: u8,
    pub avatar: bool,
    pub accent: String,
    pub clock24: bool,
    pub seconds: bool,
    pub date: bool,
    /// small | medium | large
    pub clock_size: String,
}

impl Default for GreeterConfig {
    fn default() -> Self {
        Self {
            dim: 48,
            avatar: true,
            accent: ORANGE.to_string(),
            clock24: true,
            seconds: false,
            date: true,
            clock_size: "medium".to_string(),
        }
    }
}

pub fn valid_accent(value: &str) -> bool {
    value.len() == 7
        && value.starts_with('#')
        && value[1..].chars().all(|c| c.is_ascii_hexdigit())
}

/// Lee churros-greeter.conf como el helper: una línea inválida deja el
/// valor por defecto.
pub fn parse_conf(text: &str) -> GreeterConfig {
    let mut cfg = GreeterConfig::default();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let on_off = |v: &str| match v {
            "on" => Some(true),
            "off" => Some(false),
            _ => None,
        };
        match key {
            "dim" => {
                if let Some(n) = value.parse::<u8>().ok().filter(|n| *n <= 80) {
                    cfg.dim = n;
                }
            }
            "avatar" => cfg.avatar = on_off(value).unwrap_or(cfg.avatar),
            "seconds" => cfg.seconds = on_off(value).unwrap_or(cfg.seconds),
            "date" => cfg.date = on_off(value).unwrap_or(cfg.date),
            "accent" if valid_accent(value) => cfg.accent = value.to_uppercase(),
            "clock" => match value {
                "24" => cfg.clock24 = true,
                "12" => cfg.clock24 = false,
                _ => {}
            },
            "clock_size" if matches!(value, "small" | "medium" | "large") => {
                cfg.clock_size = value.to_string()
            }
            _ => {}
        }
    }
    cfg
}

/// Primer `last-image` existente de xfce4-desktop.xml (fondo de XFCE).
pub fn xfce_wallpaper(xml: &str) -> Option<String> {
    for part in xml.split("name=\"last-image\"").skip(1) {
        let Some(start) = part.find("value=\"") else {
            continue;
        };
        let rest = &part[start + 7..];
        let Some(end) = rest.find('"') else {
            continue;
        };
        let value = rest[..end]
            .replace("&quot;", "\"")
            .replace("&apos;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&");
        if Path::new(&value).is_file() {
            return Some(value);
        }
    }
    None
}

/// Desenfoque de caja separable sobre píxeles RGB empaquetados (`channels`
/// bytes por píxel, filas de `rowstride` bytes), `passes` veces.
pub fn box_blur(
    buf: &mut [u8],
    width: usize,
    height: usize,
    rowstride: usize,
    channels: usize,
    radius: usize,
    passes: usize,
) {
    if width == 0 || height == 0 || radius == 0 {
        return;
    }
    let mut line = vec![0u8; width.max(height) * channels];
    for _ in 0..passes {
        // Horizontal
        for y in 0..height {
            let row = y * rowstride;
            for c in 0..channels {
                blur_line(
                    |i| buf[row + i * channels + c],
                    |i, v| line[i * channels + c] = v,
                    width,
                    radius,
                );
            }
            buf[row..row + width * channels].copy_from_slice(&line[..width * channels]);
        }
        // Vertical
        for x in 0..width {
            for c in 0..channels {
                blur_line(
                    |i| buf[i * rowstride + x * channels + c],
                    |i, v| line[i * channels + c] = v,
                    height,
                    radius,
                );
            }
            for y in 0..height {
                for c in 0..channels {
                    buf[y * rowstride + x * channels + c] = line[y * channels + c];
                }
            }
        }
    }
}

fn blur_line(get: impl Fn(usize) -> u8, mut set: impl FnMut(usize, u8), len: usize, radius: usize) {
    // Media de la ventana [i-r, i+r] con los bordes repetidos.
    let at = |i: isize| get(i.clamp(0, len as isize - 1) as usize) as u32;
    let window = (2 * radius + 1) as u32;
    let r = radius as isize;
    let mut sum: u32 = (-r..=r).map(at).sum();
    for i in 0..len as isize {
        set(i as usize, ((sum + window / 2) / window) as u8);
        sum += at(i + r + 1);
        sum -= at(i - r);
    }
}

pub struct GreeterService;

impl GreeterService {
    pub fn config() -> GreeterConfig {
        fs::read_to_string(GREETER_CONF)
            .map(|text| parse_conf(&text))
            .unwrap_or_default()
    }

    // ---- opciones del sistema (contraseña) -------------------------------

    pub fn set_dim(dim: u8) -> bool {
        let dim = dim.min(80);
        Self::greeter_set(&[format!("dim={dim}")])
    }

    pub fn set_avatar(on: bool) -> bool {
        Self::greeter_set(&[format!("avatar={}", on_off(on))])
    }

    pub fn set_accent(accent: &str) -> bool {
        if !valid_accent(accent) {
            return false;
        }
        Self::greeter_set(&[format!("accent={accent}")])
    }

    pub fn set_clock(clock24: bool, seconds: bool, date: bool, size: &str) -> bool {
        let clock = if clock24 { "24" } else { "12" };
        Self::greeter_set(&[
            format!("clock={clock}"),
            format!("seconds={}", on_off(seconds)),
            format!("date={}", on_off(date)),
            format!("clock_size={size}"),
        ])
    }

    fn greeter_set(pairs: &[String]) -> bool {
        Command::new("churros-pkexec")
            .arg(WRITE_ROOT_CONFIG)
            .arg("greeter-set")
            .args(pairs)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    // ---- fondo (sesión del usuario, sin root) ----------------------------

    pub fn follows_wallpaper() -> bool {
        settings::get_bool("greeter.follow_wallpaper", true)
    }

    pub fn set_follows_wallpaper(on: bool) {
        settings::set("greeter.follow_wallpaper", serde_json::json!(on));
    }

    pub fn blur() -> bool {
        settings::get_bool("greeter.blur", true)
    }

    pub fn set_blur(on: bool) {
        settings::set("greeter.blur", serde_json::json!(on));
    }

    pub fn custom_image() -> String {
        settings::get_string("greeter.image", "")
    }

    pub fn set_custom_image(path: &str) {
        settings::set("greeter.image", serde_json::json!(path));
    }

    /// Fondo del escritorio: Noctalia / Ajustes y, en XFCE, xfdesktop.
    pub fn desktop_wallpaper() -> Option<String> {
        let current = WallpaperService::current();
        if !current.is_empty() {
            return Some(current);
        }
        let home = PathBuf::from(churros_services::home_dir());
        let xml = fs::read_to_string(
            home.join(".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"),
        )
        .ok()?;
        xfce_wallpaper(&xml)
    }

    /// Imagen de origen del fondo de la pantalla de inicio.
    pub fn source_image() -> String {
        let chosen = if Self::follows_wallpaper() {
            Self::desktop_wallpaper()
        } else {
            Some(Self::custom_image()).filter(|p| Path::new(p).is_file())
        };
        chosen.unwrap_or_else(|| DEFAULT_BACKGROUND.to_string())
    }

    fn stamp_path() -> PathBuf {
        PathBuf::from(churros_services::home_dir()).join(".cache/churros/greeter-sync")
    }

    /// Regenera /var/lib/churros/greeter/background.jpg si cambió el origen
    /// o el difuminado (o siempre con `force`). Ok(true) si escribió.
    pub fn sync(force: bool) -> Result<bool, String> {
        let dir = Path::new(BACKGROUND_DIR);
        if !dir.is_dir() {
            return Err(format!("{BACKGROUND_DIR} no existe (tmpfiles.d/churros-greeter.conf)"));
        }
        let source = Self::source_image();
        let blur = Self::blur() && source != DEFAULT_BACKGROUND;
        let meta = fs::metadata(&source).map_err(|e| format!("{source}: {e}"))?;
        let mtime = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let stamp = format!("{source}\n{mtime}\n{}\n{blur}\n", meta.len());
        let target = PathBuf::from(BACKGROUND);
        if !force
            && target.is_file()
            && fs::read_to_string(Self::stamp_path()).ok().as_deref() == Some(stamp.as_str())
        {
            return Ok(false);
        }

        let tmp = dir.join(format!(".background.{}.jpg", std::process::id()));
        let result = if source == DEFAULT_BACKGROUND {
            fs::copy(&source, &tmp).map(|_| ()).map_err(|e| e.to_string())
        } else {
            render(&source, blur).and_then(|pixbuf| {
                pixbuf
                    .savev(&tmp, "jpeg", &[("quality", "88")])
                    .map_err(|e| e.to_string())
            })
        };
        let result = result.and_then(|_| {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&tmp, fs::Permissions::from_mode(0o644)).map_err(|e| e.to_string())?;
            fs::rename(&tmp, &target).map_err(|e| e.to_string())
        });
        if let Err(e) = result {
            let _ = fs::remove_file(&tmp);
            return Err(format!("no se pudo escribir {}: {e}", target.display()));
        }
        if let Some(parent) = Self::stamp_path().parent() {
            let _ = fs::create_dir_all(parent);
        }
        let _ = fs::write(Self::stamp_path(), stamp);
        Ok(true)
    }
}

fn on_off(on: bool) -> &'static str {
    if on {
        "on"
    } else {
        "off"
    }
}

/// Carga, aplana (sin alfa, para JPEG), reduce y, si toca, difumina.
fn render(source: &str, blur: bool) -> Result<Pixbuf, String> {
    let src = Pixbuf::from_file(source).map_err(|e| format!("{source}: {e}"))?;
    let (w, h) = (src.width().max(1), src.height().max(1));

    let fit = |max_w: i32, max_h: i32| -> (i32, i32) {
        let scale = (max_w as f64 / w as f64).min(max_h as f64 / h as f64).min(1.0);
        (((w as f64 * scale).round() as i32).max(1), ((h as f64 * scale).round() as i32).max(1))
    };

    let (sw, sh) = if blur {
        let scale = BLUR_WIDTH as f64 / w as f64;
        (BLUR_WIDTH.min(w), ((h as f64 * scale).round() as i32).clamp(1, h))
    } else {
        fit(MAX_WIDTH, MAX_HEIGHT)
    };
    let scaled = src
        .scale_simple(sw, sh, InterpType::Bilinear)
        .ok_or("no se pudo escalar la imagen")?;
    let flat = flatten(&scaled)?;
    if !blur {
        return Ok(flat);
    }

    let (fw, fh, stride) = (flat.width() as usize, flat.height() as usize, flat.rowstride() as usize);
    let mut bytes = flat.read_pixel_bytes().to_vec();
    box_blur(&mut bytes, fw, fh, stride, 3, BLUR_RADIUS, BLUR_PASSES);
    let blurred = Pixbuf::from_bytes(
        &gtk::glib::Bytes::from_owned(bytes),
        Colorspace::Rgb,
        false,
        8,
        flat.width(),
        flat.height(),
        flat.rowstride(),
    );
    // Ampliado con interpolación: el greeter no tiene que escalar 4x.
    let out_h = ((fh as f64) * BLUR_OUTPUT_WIDTH as f64 / fw as f64).round() as i32;
    blurred
        .scale_simple(BLUR_OUTPUT_WIDTH, out_h.max(1), InterpType::Bilinear)
        .ok_or_else(|| "no se pudo ampliar la imagen".to_string())
}

/// RGB sin alfa: lo transparente queda sobre el color de fondo del greeter.
fn flatten(src: &Pixbuf) -> Result<Pixbuf, String> {
    if !src.has_alpha() {
        return Ok(src.clone());
    }
    let dest = Pixbuf::new(Colorspace::Rgb, false, 8, src.width(), src.height())
        .ok_or("sin memoria para la imagen")?;
    dest.fill(0x0B10_20FF);
    src.composite(
        &dest,
        0,
        0,
        src.width(),
        src.height(),
        0.0,
        0.0,
        1.0,
        1.0,
        InterpType::Nearest,
        255,
    );
    Ok(dest)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conf_defaults_and_invalid_lines() {
        assert_eq!(parse_conf(""), GreeterConfig::default());
        let cfg = parse_conf(
            "# comentario\ndim=30\navatar=off\naccent=#3b82f6\nclock=12\nseconds=on\ndate=off\nclock_size=large\n",
        );
        assert_eq!(cfg.dim, 30);
        assert!(!cfg.avatar);
        assert_eq!(cfg.accent, "#3B82F6");
        assert!(!cfg.clock24 && cfg.seconds && !cfg.date);
        assert_eq!(cfg.clock_size, "large");
        // Lo mismo que greeter_check del helper: inválido = por defecto.
        let bad = parse_conf("dim=90\naccent=red\nclock=13\nclock_size=huge\navatar=yes\n");
        assert_eq!(bad, GreeterConfig::default());
    }

    #[test]
    fn xfce_last_image_is_read() {
        let dir = std::env::temp_dir().join(format!("churros-greeter-test-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let img = dir.join("a & b.png");
        fs::write(&img, b"x").unwrap();
        let xml = format!(
            "<property name=\"last-image\" type=\"string\" value=\"/no/existe.png\"/>\n\
             <property name=\"last-image\" type=\"string\" value=\"{}\"/>",
            img.display().to_string().replace('&', "&amp;")
        );
        assert_eq!(xfce_wallpaper(&xml).as_deref(), Some(img.to_str().unwrap()));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn box_blur_spreads_and_keeps_flat_areas() {
        let (w, h, ch) = (9usize, 9usize, 3usize);
        let mut flat = vec![100u8; w * h * ch];
        box_blur(&mut flat, w, h, w * ch, ch, 2, 3);
        assert!(flat.iter().all(|&v| v == 100), "un área lisa no cambia");

        let mut dot = vec![0u8; w * h * ch];
        let centre = (4 * w + 4) * ch;
        dot[centre] = 255;
        box_blur(&mut dot, w, h, w * ch, ch, 1, 1);
        assert!(dot[centre] < 255 && dot[centre] > 0, "el punto se reparte");
        assert!(dot[(4 * w + 5) * ch] > 0, "llega al vecino");
        assert_eq!(dot[centre + 1], 0, "cada canal por separado");
    }
}
