// ==========================================
// Churr — huevo de pascua de Ajustes
// ==========================================
//
// Cinco toques seguidos en la fila «Versión» (Sistema o Acerca de) abren una
// ventanita con Churr, la mascota de ChurrOS, en pixel art: saluda con la
// mano, da saltitos, parpadea, suelta chispas y corazones y escribe «¡Gracias
// por usar ChurrOS!» letra a letra.
//
// El dibujo vive en assets/churr.sprite (una letra por píxel, editable a
// mano) y va dentro del binario: no depende de ninguna ruta en la ISO.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::time::{Duration, Instant};

use gtk::cairo;
use gtk::prelude::*;

const SPRITE_TEXT: &str = include_str!("../../assets/churr.sprite");

/// Toques seguidos que hacen falta y pausa máxima entre dos de ellos.
pub const TAPS_NEEDED: u32 = 5;
pub const MAX_GAP: Duration = Duration::from_millis(1500);

/// Capas de cada fotograma del saludo, en orden de pintado.
const WAVE_LAYERS: [&str; 3] = ["WAVE_0", "WAVE_1", "WAVE_2"];
/// Ida y vuelta de la mano: 0, 1, 2, 1, 0...
const WAVE_SEQUENCE: [usize; 4] = [0, 1, 2, 1];
const WAVE_FPS: f64 = 7.0;

/// Margen alrededor del sprite (en píxeles del sprite) para los saltos y las chispas.
const MARGIN_X: usize = 12;
const MARGIN_TOP: usize = 8;
const MARGIN_BOTTOM: usize = 4;
/// Tamaño en pantalla de cada píxel del sprite.
const PIXEL_SIZE: f64 = 4.0;

const THANKS: &str = "¡Gracias por usar ChurrOS!";

// ------------------------------------------------------------------
// Contador de toques
// ------------------------------------------------------------------

/// Cuenta toques seguidos; una pausa de más de `MAX_GAP` empieza de cero.
#[derive(Debug, Default)]
pub struct TapCounter {
    count: u32,
    last: Option<Instant>,
}

impl TapCounter {
    /// Registra un toque. Devuelve `true` en el quinto toque seguido y vuelve a cero.
    pub fn tap(&mut self, now: Instant) -> bool {
        let continues = self
            .last
            .is_some_and(|last| now.saturating_duration_since(last) <= MAX_GAP);
        self.count = if continues { self.count + 1 } else { 1 };
        self.last = Some(now);
        if self.count >= TAPS_NEEDED {
            self.count = 0;
            self.last = None;
            return true;
        }
        false
    }
}

/// Callback para la fila «Versión»: al quinto toque seguido, aparece Churr.
pub fn on_version_tap() -> Box<dyn Fn(&gtk::Button)> {
    let counter = Rc::new(RefCell::new(TapCounter::default()));
    Box::new(move |button: &gtk::Button| {
        if counter.borrow_mut().tap(Instant::now()) {
            let parent = button.root().and_then(|root| root.downcast::<gtk::Window>().ok());
            show(parent.as_ref());
        }
    })
}

// ------------------------------------------------------------------
// Sprite
// ------------------------------------------------------------------

#[derive(Debug)]
pub struct Sprite {
    pub width: usize,
    pub height: usize,
    palette: HashMap<char, [u8; 3]>,
    layers: HashMap<String, Vec<Vec<char>>>,
}

impl Sprite {
    /// Lee el formato de assets/churr.sprite: `[palette]` con `LETRA rrggbb`
    /// y una sección `[NOMBRE]` por capa. `#` empieza un comentario.
    pub fn parse(text: &str) -> Result<Self, String> {
        let mut palette = HashMap::new();
        let mut layers: HashMap<String, Vec<Vec<char>>> = HashMap::new();
        let mut order = Vec::new();
        let mut section: Option<String> = None;

        for (number, raw) in text.lines().enumerate() {
            let line = raw.trim_end();
            if line.trim_start().starts_with('#') || line.trim().is_empty() {
                continue;
            }
            if let Some(name) = line.strip_prefix('[').and_then(|l| l.strip_suffix(']')) {
                section = Some(name.to_string());
                if name != "palette" {
                    if layers.contains_key(name) {
                        return Err(format!("línea {}: la capa {name} está repetida", number + 1));
                    }
                    layers.insert(name.to_string(), Vec::new());
                    order.push(name.to_string());
                }
                continue;
            }
            match section.as_deref() {
                None => return Err(format!("línea {}: texto fuera de una sección", number + 1)),
                Some("palette") => {
                    let mut parts = line.split_whitespace();
                    let (Some(key), Some(hex)) = (parts.next(), parts.next()) else {
                        return Err(format!("línea {}: color sin valor", number + 1));
                    };
                    let mut chars = key.chars();
                    let (Some(letter), None) = (chars.next(), chars.next()) else {
                        return Err(format!("línea {}: la clave del color debe ser una letra", number + 1));
                    };
                    if letter == '.' {
                        return Err(format!("línea {}: «.» es el transparente", number + 1));
                    }
                    palette.insert(letter, parse_hex(hex).ok_or_else(|| format!("línea {}: color «{hex}» no válido", number + 1))?);
                }
                Some(name) => {
                    layers.get_mut(name).expect("sección registrada").push(line.chars().collect());
                }
            }
        }

        let first = order.first().ok_or("el sprite no tiene capas")?;
        let height = layers[first].len();
        let width = layers[first].first().map_or(0, Vec::len);
        if width == 0 || height == 0 {
            return Err(format!("la capa {first} está vacía"));
        }
        for name in &order {
            let rows = &layers[name];
            if rows.len() != height {
                return Err(format!("la capa {name} tiene {} filas y {first} {height}", rows.len()));
            }
            for (y, row) in rows.iter().enumerate() {
                if row.len() != width {
                    return Err(format!("capa {name}, fila {}: {} píxeles en vez de {width}", y + 1, row.len()));
                }
                if let Some(c) = row.iter().find(|c| **c != '.' && !palette.contains_key(*c)) {
                    return Err(format!("capa {name}, fila {}: «{c}» no está en la paleta", y + 1));
                }
            }
        }
        Ok(Self { width, height, palette, layers })
    }

    pub fn shipped() -> Self {
        Self::parse(SPRITE_TEXT).expect("assets/churr.sprite es válido (lo comprueban los tests)")
    }

    pub fn has_layer(&self, name: &str) -> bool {
        self.layers.contains_key(name)
    }

    /// Superpone capas: `None` es transparente.
    pub fn compose(&self, names: &[&str]) -> Vec<Vec<Option<[u8; 3]>>> {
        let mut out = vec![vec![None; self.width]; self.height];
        for name in names {
            let Some(rows) = self.layers.get(*name) else { continue };
            for (y, row) in rows.iter().enumerate() {
                for (x, c) in row.iter().enumerate() {
                    if *c != '.' {
                        out[y][x] = self.palette.get(c).copied();
                    }
                }
            }
        }
        out
    }
}

fn parse_hex(hex: &str) -> Option<[u8; 3]> {
    let hex = hex.strip_prefix('#').unwrap_or(hex);
    if hex.len() != 6 {
        return None;
    }
    let value = u32::from_str_radix(hex, 16).ok()?;
    Some([(value >> 16) as u8, (value >> 8) as u8, value as u8])
}

/// Capas de un fotograma: brazo `wave` (0..3) y, si toca, el parpadeo.
pub fn frame_layers(wave: usize, blinking: bool) -> Vec<&'static str> {
    let mut layers = vec!["BASE", "ARM_CHURRO", WAVE_LAYERS[wave % WAVE_LAYERS.len()]];
    if blinking {
        layers.push("BLINK");
    }
    layers
}

// ------------------------------------------------------------------
// Animación (funciones puras, en segundos desde que se abre)
// ------------------------------------------------------------------

/// Brazo que toca en el instante `t`.
pub fn wave_at(t: f64) -> usize {
    WAVE_SEQUENCE[((t.max(0.0) * WAVE_FPS) as usize) % WAVE_SEQUENCE.len()]
}

/// Parpadea 0,15 s cada 3,2 s (el primero, a los 1,6 s).
pub fn blinking_at(t: f64) -> bool {
    let cycle = (t + 1.6).rem_euclid(3.2);
    cycle < 0.15
}

/// Altura del saltito, en píxeles enteros del sprite (0 = en el suelo).
pub fn hop_at(t: f64) -> i32 {
    let phase = (t * 1.25).fract();
    // Medio segundo en el aire y el resto quieto, como un brinco de alegría.
    if phase < 0.4 {
        let x = phase / 0.4;
        (5.0 * (1.0 - (2.0 * x - 1.0).powi(2))).round() as i32
    } else {
        0
    }
}

/// Entrada con rebote: de 0,6 a 1 con un pequeño pasado (ease-out-back).
pub fn pop_scale(t: f64) -> f64 {
    let x = (t / 0.45).clamp(0.0, 1.0);
    let c1 = 1.70158;
    let c3 = c1 + 1.0;
    let eased = 1.0 + c3 * (x - 1.0).powi(3) + c1 * (x - 1.0).powi(2);
    0.6 + 0.4 * eased
}

/// Letras del agradecimiento visibles en `t` (empieza a escribir a los 0,6 s).
pub fn typed_chars(t: f64) -> usize {
    let total = THANKS.chars().count();
    (((t - 0.6) * 18.0).max(0.0) as usize).min(total)
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ParticleKind {
    Star,
    Heart,
    Dot,
}

#[derive(Debug, Clone, Copy)]
pub struct Particle {
    pub kind: ParticleKind,
    /// Posición en píxeles del lienzo (sprite + márgenes).
    pub x: f64,
    pub y: f64,
    /// 0 transparente, 1 opaca.
    pub alpha: f64,
}

/// Pseudoaleatorio fijo por índice (sin depender de un crate de azar).
fn hash01(i: u32, salt: u32) -> f64 {
    let mut h = i.wrapping_mul(2_654_435_761) ^ salt.wrapping_mul(2_246_822_519);
    h ^= h >> 15;
    h = h.wrapping_mul(2_246_822_519);
    h ^= h >> 13;
    f64::from(h % 10_000) / 10_000.0
}

pub const PARTICLES: u32 = 14;

/// Chispas, corazones y puntitos que suben desde abajo.
pub fn particles_at(t: f64, canvas_w: f64, canvas_h: f64) -> Vec<Particle> {
    (0..PARTICLES)
        .filter_map(|i| {
            let start = 0.5 + hash01(i, 1) * 1.2;
            if t < start {
                return None;
            }
            let period = 2.2 + hash01(i, 2) * 1.6;
            let life = ((t - start) / period).fract();
            let kind = match i % 5 {
                0 | 3 => ParticleKind::Star,
                1 => ParticleKind::Heart,
                _ => ParticleKind::Dot,
            };
            // A los lados del sprite, para no tapar la cara.
            let side = if i % 2 == 0 { 0.05 } else { 0.72 };
            let x = canvas_w * (side + hash01(i, 3) * 0.23) + (life * 9.0 + f64::from(i)).sin() * 1.5;
            let y = canvas_h * (0.95 - life * 0.9);
            let alpha = if life < 0.15 { life / 0.15 } else { ((1.0 - life) / 0.6).min(1.0) };
            Some(Particle { kind, x, y, alpha: alpha.clamp(0.0, 1.0) })
        })
        .collect()
}

// ------------------------------------------------------------------
// Dibujo
// ------------------------------------------------------------------

/// Fotograma ya rasterizado (un píxel de superficie por píxel del sprite).
pub(crate) fn rasterize(sprite: &Sprite, layers: &[&str]) -> Option<cairo::ImageSurface> {
    let pixels = sprite.compose(layers);
    let mut surface = cairo::ImageSurface::create(cairo::Format::ARgb32, sprite.width as i32, sprite.height as i32).ok()?;
    let stride = surface.stride() as usize;
    {
        let mut data = surface.data().ok()?;
        for (y, row) in pixels.iter().enumerate() {
            for (x, px) in row.iter().enumerate() {
                let offset = y * stride + x * 4;
                let argb: u32 = match px {
                    Some([r, g, b]) => 0xff00_0000 | (u32::from(*r) << 16) | (u32::from(*g) << 8) | u32::from(*b),
                    None => 0,
                };
                data[offset..offset + 4].copy_from_slice(&argb.to_ne_bytes());
            }
        }
    }
    Some(surface)
}

const HEART: [&str; 4] = [".X.X.", "XXXXX", ".XXX.", "..X.."];
const STAR: [&str; 3] = [".X.", "XXX", ".X."];

fn draw_pixels(cr: &cairo::Context, pattern: &[&str], x: f64, y: f64, rgb: (f64, f64, f64), alpha: f64) {
    cr.set_source_rgba(rgb.0, rgb.1, rgb.2, alpha);
    let (x0, y0) = (x.round(), y.round());
    for (dy, row) in pattern.iter().enumerate() {
        for (dx, c) in row.chars().enumerate() {
            if c == 'X' {
                cr.rectangle(x0 + dx as f64, y0 + dy as f64, 1.0, 1.0);
            }
        }
    }
    let _ = cr.fill();
}

struct Frames {
    /// [brazo][parpadeo]
    surfaces: Vec<[cairo::ImageSurface; 2]>,
    width: f64,
    height: f64,
}

fn build_frames(sprite: &Sprite) -> Option<Frames> {
    let mut surfaces = Vec::new();
    for wave in 0..WAVE_LAYERS.len() {
        surfaces.push([
            rasterize(sprite, &frame_layers(wave, false))?,
            rasterize(sprite, &frame_layers(wave, true))?,
        ]);
    }
    Some(Frames { surfaces, width: sprite.width as f64, height: sprite.height as f64 })
}

fn draw_scene(cr: &cairo::Context, frames: &Frames, t: f64, animated: bool) {
    let canvas_w = frames.width + 2.0 * MARGIN_X as f64;
    let canvas_h = frames.height + (MARGIN_TOP + MARGIN_BOTTOM) as f64;
    cr.scale(PIXEL_SIZE, PIXEL_SIZE);

    let (wave, blink, hop, scale) = if animated {
        (wave_at(t), blinking_at(t), hop_at(t), pop_scale(t))
    } else {
        (1, false, 0, 1.0)
    };

    // Sombra en el suelo: más pequeña cuanto más alto el salto.
    let ground = MARGIN_TOP as f64 + frames.height - 1.5;
    let shadow_w = (frames.width * 0.42) * (1.0 - f64::from(hop) * 0.04);
    cr.save().ok();
    cr.translate(canvas_w / 2.0, ground);
    cr.scale(shadow_w, 2.2);
    cr.arc(0.0, 0.0, 1.0, 0.0, std::f64::consts::TAU);
    cr.restore().ok();
    cr.set_source_rgba(0.0, 0.0, 0.0, 0.18 * scale.min(1.0));
    let _ = cr.fill();

    // Partículas detrás de Churr.
    if animated {
        for p in particles_at(t, canvas_w, canvas_h) {
            match p.kind {
                ParticleKind::Heart => draw_pixels(cr, &HEART, p.x, p.y, (0.96, 0.45, 0.33), p.alpha),
                ParticleKind::Star => draw_pixels(cr, &STAR, p.x, p.y, (0.98, 0.45, 0.09), p.alpha),
                ParticleKind::Dot => draw_pixels(cr, &["X"], p.x, p.y, (0.89, 0.64, 0.30), p.alpha),
            }
        }
    }

    // Churr, con el rebote de entrada y el saltito.
    let surface = &frames.surfaces[wave][usize::from(blink)];
    let cx = canvas_w / 2.0;
    let feet = MARGIN_TOP as f64 + frames.height;
    cr.save().ok();
    cr.translate(cx, feet - f64::from(hop));
    cr.scale(scale, scale);
    cr.translate(-frames.width / 2.0, -frames.height);
    let pattern = cairo::SurfacePattern::create(surface);
    pattern.set_filter(cairo::Filter::Nearest);
    if cr.set_source(&pattern).is_ok() {
        let _ = cr.paint();
    }
    cr.restore().ok();
}

// ------------------------------------------------------------------
// Ventana
// ------------------------------------------------------------------

pub fn show(parent: Option<&gtk::Window>) {
    let sprite = Sprite::shipped();
    let Some(frames) = build_frames(&sprite) else { return };
    let frames = Rc::new(frames);

    let window = gtk::Window::builder()
        .title("Churr")
        .modal(true)
        .resizable(false)
        .build();
    window.add_css_class("churr-egg");
    if let Some(parent) = parent {
        window.set_transient_for(Some(parent));
        if parent.has_css_class("light") {
            window.add_css_class("light");
        }
    }

    let content = gtk::Box::new(gtk::Orientation::Vertical, 8);
    content.set_margin_top(20);
    content.set_margin_bottom(22);
    content.set_margin_start(28);
    content.set_margin_end(28);

    let canvas_w = (sprite.width + 2 * MARGIN_X) as f64 * PIXEL_SIZE;
    let canvas_h = (sprite.height + MARGIN_TOP + MARGIN_BOTTOM) as f64 * PIXEL_SIZE;
    let area = gtk::DrawingArea::new();
    area.set_content_width(canvas_w as i32);
    area.set_content_height(canvas_h as i32);
    area.set_halign(gtk::Align::Center);

    let animated = gtk::Settings::default().is_none_or(|s| s.is_gtk_enable_animations());
    let started = Rc::new(RefCell::new(None::<i64>));
    let now_t = Rc::new(RefCell::new(0.0_f64));
    {
        let frames = frames.clone();
        let now_t = now_t.clone();
        area.set_draw_func(move |_, cr, _, _| draw_scene(cr, &frames, *now_t.borrow(), animated));
    }

    let title = gtk::Label::new(Some(if animated { "" } else { THANKS }));
    title.add_css_class("churr-egg-title");
    title.set_wrap(true);
    title.set_justify(gtk::Justification::Center);
    // Reserva la altura del texto completo para que no salte al escribirse.
    title.set_width_chars(THANKS.chars().count() as i32);

    let subtitle = gtk::Label::new(Some("Churr y toda la comunidad te mandan un abrazo con sabor a chocolate."));
    subtitle.add_css_class("churr-egg-subtitle");
    subtitle.set_wrap(true);
    subtitle.set_max_width_chars(34);
    subtitle.set_justify(gtk::Justification::Center);

    let close = gtk::Button::with_label("¡Hola, Churr!");
    close.add_css_class("churr-egg-button");
    {
        let window = window.clone();
        close.connect_clicked(move |_| window.close());
    }
    // El minijuego (widgets/churr_game.rs): se abre sobre la ventana de
    // Ajustes y cierra esta.
    let play = gtk::Button::with_label("¡Jugar con Churr!");
    play.add_css_class("churr-egg-button");
    play.add_css_class("churr-egg-play");
    {
        let window = window.clone();
        let parent = parent.cloned();
        play.connect_clicked(move |_| {
            window.close();
            super::churr_game::open(parent.as_ref());
        });
    }
    let buttons = gtk::Box::new(gtk::Orientation::Horizontal, 10);
    buttons.set_halign(gtk::Align::Center);
    buttons.set_margin_top(10);
    buttons.append(&close);
    buttons.append(&play);

    let keys = gtk::EventControllerKey::new();
    {
        let window = window.clone();
        keys.connect_key_pressed(move |_, key, _, _| {
            if key == gtk::gdk::Key::Escape {
                window.close();
                return glib::Propagation::Stop;
            }
            glib::Propagation::Proceed
        });
    }
    window.add_controller(keys);

    content.append(&area);
    content.append(&title);
    content.append(&subtitle);
    content.append(&buttons);
    window.set_child(Some(&content));

    if animated {
        let title = title.clone();
        let shown = std::cell::Cell::new(0usize);
        area.add_tick_callback(move |area, clock| {
            let frame_time = clock.frame_time();
            let start = *started.borrow_mut().get_or_insert(frame_time);
            let t = (frame_time - start) as f64 / 1_000_000.0;
            *now_t.borrow_mut() = t;
            let typed = typed_chars(t);
            if typed != shown.get() {
                shown.set(typed);
                title.set_label(&THANKS.chars().take(typed).collect::<String>());
            }
            area.queue_draw();
            glib::ControlFlow::Continue
        });
    }

    close.grab_focus();
    window.present();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shipped_sprite_parses_with_every_layer() {
        let sprite = Sprite::parse(SPRITE_TEXT).expect("churr.sprite válido");
        for name in ["BASE", "ARM_CHURRO", "BLINK"].iter().chain(WAVE_LAYERS.iter()) {
            assert!(sprite.has_layer(name), "falta la capa {name}");
        }
        assert!(sprite.width >= 32 && sprite.height >= 32, "{}x{}", sprite.width, sprite.height);
    }

    #[test]
    fn every_frame_draws_churr_with_the_logo_eye_and_a_waving_paw() {
        let sprite = Sprite::shipped();
        let orange = Some([0xf9, 0x73, 0x16]);
        let base = sprite.compose(&["BASE", "ARM_CHURRO"]);
        let mut previous: Option<Vec<Vec<Option<[u8; 3]>>>> = None;
        for wave in 0..WAVE_LAYERS.len() {
            for blink in [false, true] {
                let frame = sprite.compose(&frame_layers(wave, blink));
                let opaque = frame.iter().flatten().filter(|p| p.is_some()).count();
                assert!(opaque > sprite.width * sprite.height / 4, "fotograma {wave}/{blink} casi vacío");
                assert!(frame.iter().flatten().any(|p| *p == orange), "sin el naranja del logo");
            }
            // Cada posición del brazo cambia el dibujo respecto a la base y a la anterior.
            let frame = sprite.compose(&frame_layers(wave, false));
            assert_ne!(frame, base, "WAVE_{wave} no añade el brazo");
            if let Some(prev) = &previous {
                assert_ne!(&frame, prev, "WAVE_{wave} es igual que la anterior");
            }
            previous = Some(frame);
        }
        assert_ne!(
            sprite.compose(&frame_layers(1, true)),
            sprite.compose(&frame_layers(1, false)),
            "BLINK no cambia nada"
        );
    }

    #[test]
    fn sprite_errors_are_reported() {
        assert!(Sprite::parse("[palette]\nK 000000\n[A]\nKK\nK\n").unwrap_err().contains("píxeles"));
        assert!(Sprite::parse("[palette]\nK 000000\n[A]\nKZ\n").unwrap_err().contains("«Z»"));
        assert!(Sprite::parse("[palette]\nK 0000\n[A]\nK\n").unwrap_err().contains("no válido"));
        assert!(Sprite::parse("[palette]\nK 000000\n[A]\nKK\n[B]\nKK\nKK\n").unwrap_err().contains("filas"));
        assert!(Sprite::parse("[palette]\nK 000000\n").is_err());
        let ok = Sprite::parse("# c\n[palette]\nK 0a0b0c  # comentario\n[A]\nK.\n").unwrap();
        assert_eq!(ok.compose(&["A"]), vec![vec![Some([10, 11, 12]), None]]);
    }

    #[test]
    fn five_quick_taps_open_churr_and_a_pause_starts_over() {
        let t0 = Instant::now();
        let ms = |n: u64| t0 + Duration::from_millis(n);
        let mut counter = TapCounter::default();
        for (i, at) in [0, 300, 600, 900].into_iter().enumerate() {
            assert!(!counter.tap(ms(at)), "abrió en el toque {}", i + 1);
        }
        assert!(counter.tap(ms(1200)), "el quinto toque seguido no abrió");
        // Vuelve a cero: hacen falta otros cinco.
        for at in [1300, 1600, 1900, 2200] {
            assert!(!counter.tap(ms(at)));
        }
        assert!(counter.tap(ms(2500)));

        // Una pausa larga a mitad reinicia la cuenta.
        let mut counter = TapCounter::default();
        for at in [0, 200, 400] {
            assert!(!counter.tap(ms(at)));
        }
        let late = 400 + MAX_GAP.as_millis() as u64 + 1;
        for at in [late, late + 200, late + 400, late + 600] {
            assert!(!counter.tap(ms(at)), "contó toques de antes de la pausa");
        }
        assert!(counter.tap(ms(late + 800)));
    }

    #[test]
    fn animation_stays_in_bounds() {
        let (w, h) = (80.0, 71.0);
        let mut waves = std::collections::HashSet::new();
        let mut blinked = false;
        let mut hopped = false;
        for step in 0..2000 {
            let t = f64::from(step) * 0.01;
            waves.insert(wave_at(t));
            blinked |= blinking_at(t);
            let hop = hop_at(t);
            assert!((0..=MARGIN_TOP as i32).contains(&hop), "salto {hop} sale del lienzo");
            hopped |= hop > 0;
            let s = pop_scale(t);
            assert!((0.55..=1.12).contains(&s), "escala {s}");
            for p in particles_at(t, w, h) {
                assert!(p.x >= -2.0 && p.x <= w + 2.0 && p.y >= -2.0 && p.y <= h, "{p:?}");
                assert!((0.0..=1.0).contains(&p.alpha));
            }
        }
        assert_eq!(waves.len(), WAVE_LAYERS.len(), "no usa las tres posiciones del brazo");
        assert!(blinked && hopped);
        assert_eq!(pop_scale(10.0), 1.0);
        assert_eq!(typed_chars(0.0), 0);
        assert_eq!(typed_chars(60.0), THANKS.chars().count());
    }
}
