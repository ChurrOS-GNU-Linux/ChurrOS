// ==========================================
// «Churr vuela» — minijuego del huevo de pascua de Ajustes
// ==========================================
//
// Desde la ventana de Churr (cinco toques en «Versión»), «¡Jugar con Churr!»
// abre un juego de un botón: Churr vuela batiendo las orejas y esquiva
// columnas de churro bañadas en chocolate. Clic, Espacio o ↑ para aletear;
// M silencia; Esc sale. El récord se guarda en los ajustes.
//
// Todo es propio y ligero: el dibujo (assets/churr-vuela.sprite y formas
// pixeladas con cairo) y la música, una melodía chiptune original que se
// sintetiza aquí mismo y suena con gtk::MediaFile. Ni crates ni ficheros de
// sonido nuevos.

use std::cell::{Cell, RefCell};
use std::collections::VecDeque;
use std::rc::Rc;

use gtk::cairo;
use gtk::prelude::*;
use serde_json::json;

use super::churr::{rasterize, Sprite};
use crate::services::settings;

const SPRITE_TEXT: &str = include_str!("../../assets/churr-vuela.sprite");
const FRAMES: [&str; 4] = ["FLY_0", "FLY_1", "FLY_2", "OUCH"];
const BEST_KEY: &str = "easter.churr_best";

// Mundo en píxeles del juego; se dibuja a ×3.
pub const WIDTH: f64 = 144.0;
pub const HEIGHT: f64 = 216.0;
pub const GROUND: f64 = 196.0;
const SCALE: f64 = 3.0;

const GRAVITY: f64 = 820.0;
const FLAP_SPEED: f64 = -235.0;
const MAX_FALL: f64 = 330.0;
pub const CHURR_X: f64 = 38.0;
const HIT_W: f64 = 14.0;
const HIT_H: f64 = 12.0;
pub const PILLAR_W: f64 = 18.0;
pub const GAP: f64 = 66.0;
const SPACING: f64 = 86.0;
const FIRST_PILLAR: f64 = WIDTH + 40.0;
const BASE_SPEED: f64 = 56.0;
const MAX_SPEED: f64 = 90.0;
/// Margen mínimo entre el hueco y el techo o el suelo.
const GAP_MARGIN: f64 = 20.0;
pub const STEP: f64 = 1.0 / 120.0;
/// Tras chocar, un momento antes de poder volver a empezar (evita reiniciar sin querer).
const RESTART_DELAY: f64 = 0.6;

// ------------------------------------------------------------------
// Lógica (pura, con tests)
// ------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    Ready,
    Playing,
    Over,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Event {
    Flap,
    Point,
    Hit,
}

#[derive(Clone, Debug)]
pub struct Pillar {
    pub x: f64,
    /// Centro del hueco.
    pub gap_y: f64,
    pub scored: bool,
}

impl Pillar {
    pub fn gap_top(&self) -> f64 {
        self.gap_y - GAP / 2.0
    }
    pub fn gap_bottom(&self) -> f64 {
        self.gap_y + GAP / 2.0
    }
}

pub struct World {
    pub phase: Phase,
    pub y: f64,
    pub vy: f64,
    pub pillars: VecDeque<Pillar>,
    pub score: u32,
    /// Distancia recorrida: mueve el suelo y el fondo.
    pub scroll: f64,
    pub time: f64,
    pub flap_time: f64,
    pub over_time: f64,
    rng: u64,
}

const START_Y: f64 = HEIGHT * 0.42;

impl World {
    pub fn new(seed: u64) -> Self {
        Self {
            phase: Phase::Ready,
            y: START_Y,
            vy: 0.0,
            pillars: VecDeque::new(),
            score: 0,
            scroll: 0.0,
            time: 0.0,
            flap_time: 1.0,
            over_time: 0.0,
            rng: seed | 1,
        }
    }

    /// Más rápido con cada punto, hasta un tope.
    pub fn speed(&self) -> f64 {
        (BASE_SPEED + f64::from(self.score) * 1.5).min(MAX_SPEED)
    }

    fn random(&mut self) -> f64 {
        // xorshift64*
        self.rng ^= self.rng >> 12;
        self.rng ^= self.rng << 25;
        self.rng ^= self.rng >> 27;
        let value = self.rng.wrapping_mul(0x2545_F491_4F6C_DD1D);
        (value >> 11) as f64 / (1u64 << 53) as f64
    }

    /// Centro de un hueco nuevo: siempre dentro del campo, y no más de
    /// 70 px por encima o por debajo del anterior (alcanzable a la carrera).
    fn next_gap(&mut self) -> f64 {
        let low = GAP_MARGIN + GAP / 2.0;
        let high = GROUND - GAP_MARGIN - GAP / 2.0;
        let (low, high) = match self.pillars.back() {
            Some(prev) => ((prev.gap_y - 70.0).max(low), (prev.gap_y + 70.0).min(high)),
            None => (low, high),
        };
        low + self.random() * (high - low)
    }

    pub fn flap(&mut self) -> Vec<Event> {
        match self.phase {
            Phase::Ready => {
                self.phase = Phase::Playing;
                self.vy = FLAP_SPEED;
                self.flap_time = 0.0;
                vec![Event::Flap]
            }
            Phase::Playing => {
                self.vy = FLAP_SPEED;
                self.flap_time = 0.0;
                vec![Event::Flap]
            }
            Phase::Over => {
                if self.over_time >= RESTART_DELAY {
                    let rng = self.rng;
                    *self = World::new(rng);
                }
                Vec::new()
            }
        }
    }

    fn hits(&self) -> bool {
        let (top, bottom) = (self.y - HIT_H / 2.0, self.y + HIT_H / 2.0);
        if bottom >= GROUND {
            return true;
        }
        let (left, right) = (CHURR_X - HIT_W / 2.0, CHURR_X + HIT_W / 2.0);
        self.pillars.iter().any(|p| {
            right > p.x && left < p.x + PILLAR_W && (top < p.gap_top() || bottom > p.gap_bottom())
        })
    }

    pub fn step(&mut self, dt: f64) -> Vec<Event> {
        let mut events = Vec::new();
        self.time += dt;
        self.flap_time += dt;
        match self.phase {
            Phase::Ready => {
                // Flota esperando, con las orejas en marcha.
                self.y = START_Y + (self.time * 3.0).sin() * 3.0;
                self.scroll += BASE_SPEED * dt;
            }
            Phase::Playing => {
                self.vy = (self.vy + GRAVITY * dt).min(MAX_FALL);
                self.y += self.vy * dt;
                // El techo no mata: frena (más amable para quien empieza).
                if self.y - HIT_H / 2.0 < 0.0 {
                    self.y = HIT_H / 2.0;
                    self.vy = self.vy.max(0.0);
                }
                let speed = self.speed();
                self.scroll += speed * dt;
                for pillar in &mut self.pillars {
                    pillar.x -= speed * dt;
                }
                while self.pillars.front().is_some_and(|p| p.x + PILLAR_W < -4.0) {
                    self.pillars.pop_front();
                }
                let next_x = self.pillars.back().map_or(FIRST_PILLAR, |p| p.x + SPACING);
                if next_x < WIDTH + 30.0 || self.pillars.is_empty() {
                    let gap_y = self.next_gap();
                    self.pillars.push_back(Pillar { x: next_x, gap_y, scored: false });
                }
                for pillar in &mut self.pillars {
                    if !pillar.scored && pillar.x + PILLAR_W < CHURR_X - HIT_W / 2.0 {
                        pillar.scored = true;
                        self.score += 1;
                        events.push(Event::Point);
                    }
                }
                if self.hits() {
                    self.phase = Phase::Over;
                    self.over_time = 0.0;
                    self.vy = self.vy.min(-80.0);
                    events.push(Event::Hit);
                }
            }
            Phase::Over => {
                self.over_time += dt;
                self.vy = (self.vy + GRAVITY * dt).min(MAX_FALL);
                self.y = (self.y + self.vy * dt).min(GROUND - HIT_H / 2.0 - 4.0);
            }
        }
        events
    }

    /// Inclinación al dibujar: hacia arriba al aletear, de morro al caer.
    pub fn tilt(&self) -> f64 {
        match self.phase {
            Phase::Ready => 0.0,
            _ => (self.vy / MAX_FALL * 0.7).clamp(-0.4, 1.0),
        }
    }

    /// Fotograma del sprite (índice en FRAMES).
    pub fn frame(&self) -> usize {
        match self.phase {
            Phase::Over => 3,
            // Aletea suave mientras espera.
            Phase::Ready => [0, 1, 2, 1][((self.time * 6.0) as usize) % 4],
            // Un golpe de orejas al aletear y luego planea.
            Phase::Playing if self.flap_time < 0.27 => [2, 1, 0][((self.flap_time / 0.09) as usize).min(2)],
            Phase::Playing => [1, 1, 2, 1, 0, 1][((self.time * 5.0) as usize) % 6],
        }
    }
}

// ------------------------------------------------------------------
// Sonido: síntesis chiptune propia (mono, 22 050 Hz, 16 bits)
// ------------------------------------------------------------------

pub mod sound {
    pub const RATE: u32 = 22_050;

    /// WAV PCM de 16 bits mono.
    pub fn wav(samples: &[f32]) -> Vec<u8> {
        let data_len = (samples.len() * 2) as u32;
        let mut out = Vec::with_capacity(44 + samples.len() * 2);
        out.extend_from_slice(b"RIFF");
        out.extend_from_slice(&(36 + data_len).to_le_bytes());
        out.extend_from_slice(b"WAVEfmt ");
        out.extend_from_slice(&16u32.to_le_bytes());
        out.extend_from_slice(&1u16.to_le_bytes()); // PCM
        out.extend_from_slice(&1u16.to_le_bytes()); // mono
        out.extend_from_slice(&RATE.to_le_bytes());
        out.extend_from_slice(&(RATE * 2).to_le_bytes());
        out.extend_from_slice(&2u16.to_le_bytes());
        out.extend_from_slice(&16u16.to_le_bytes());
        out.extend_from_slice(b"data");
        out.extend_from_slice(&data_len.to_le_bytes());
        for s in samples {
            out.extend_from_slice(&((s.clamp(-1.0, 1.0) * 32_000.0) as i16).to_le_bytes());
        }
        out
    }

    fn freq(midi: i32) -> f32 {
        440.0 * 2f32.powf((midi as f32 - 69.0) / 12.0)
    }

    /// "C5", "F#4", "A#3"... -> MIDI.
    pub fn note(name: &str) -> Option<i32> {
        let mut chars = name.chars();
        let letter = chars.next()?;
        let base = match letter {
            'C' => 0,
            'D' => 2,
            'E' => 4,
            'F' => 5,
            'G' => 7,
            'A' => 9,
            'B' => 11,
            _ => return None,
        };
        let rest: String = chars.collect();
        let (accidental, octave) = match rest.strip_prefix('#') {
            Some(octave) => (1, octave),
            None => (0, rest.as_str()),
        };
        let octave: i32 = octave.parse().ok()?;
        Some(12 * (octave + 1) + base + accidental)
    }

    fn square(phase: f32, duty: f32) -> f32 {
        if phase.fract() < duty {
            1.0
        } else {
            -1.0
        }
    }

    fn triangle(phase: f32) -> f32 {
        let p = phase.fract();
        if p < 0.5 {
            4.0 * p - 1.0
        } else {
            3.0 - 4.0 * p
        }
    }

    struct Noise(u32);
    impl Noise {
        fn next(&mut self) -> f32 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 17;
            self.0 ^= self.0 << 5;
            (self.0 as f32 / u32::MAX as f32) * 2.0 - 1.0
        }
    }

    pub const BPM: f32 = 132.0;

    /// La melodía, en corcheas: nota, "-" alarga la anterior y "." es silencio.
    /// Dos frases de 8 compases (Do, Lam, Fa, Sol) que se repiten en bucle.
    pub const MELODY: [&str; 16] = [
        "E5 G5 C6 G5 E5 D5 E5 G5",
        "A5 - G5 E5 C5 E5 G5 -",
        "F5 A5 C6 A5 G5 F5 E5 F5",
        "G5 - B5 D6 - B5 G5 .",
        "C6 B5 G5 E5 G5 C6 E6 -",
        "D6 C6 A5 - C6 - A5 G5",
        "F5 G5 A5 C6 D6 C6 A5 F5",
        "G5 A5 B5 D6 G5 - . .",
        "E6 - D6 C6 G5 - C6 -",
        "C6 - A5 G5 E5 - A5 -",
        "A5 C6 F6 - E6 C6 A5 C6",
        "B5 - G5 B5 D6 - B5 -",
        "C6 E6 G6 - E6 C6 G5 E5",
        "A5 G5 E5 C5 E5 G5 A5 -",
        "F5 - A5 C6 D6 - F6 -",
        "G6 - D6 B5 G5 - . .",
    ];
    /// Raíz del acorde de cada compás (bajo).
    pub const ROOTS: [&str; 16] = [
        "C3", "A2", "F2", "G2", "C3", "A2", "F2", "G2", "C3", "A2", "F2", "G2", "C3", "A2", "F2", "G2",
    ];

    fn eighth_seconds() -> f32 {
        60.0 / BPM / 2.0
    }

    pub fn loop_seconds() -> f32 {
        eighth_seconds() * 8.0 * MELODY.len() as f32
    }

    /// Notas de la melodía: (MIDI, corchea de inicio, corcheas de duración).
    pub fn melody_notes() -> Vec<(i32, usize, usize)> {
        let mut notes: Vec<(i32, usize, usize)> = Vec::new();
        let mut index = 0;
        for bar in MELODY {
            for token in bar.split_whitespace() {
                match token {
                    "-" => {
                        if let Some(last) = notes.last_mut().filter(|last| last.1 + last.2 == index) {
                            last.2 += 1;
                        }
                    }
                    "." => {}
                    name => {
                        if let Some(midi) = note(name) {
                            notes.push((midi, index, 1));
                        }
                    }
                }
                index += 1;
            }
        }
        notes
    }

    fn add(buffer: &mut [f32], start: usize, samples: impl Iterator<Item = f32>) {
        for (offset, value) in samples.enumerate() {
            if let Some(slot) = buffer.get_mut(start + offset) {
                *slot += value;
            }
        }
    }

    /// La música del juego: melodía (cuadrada con vibrato y eco), bajo
    /// (triangular), bombo y charles suaves. Un bucle de unos 29 s.
    pub fn music() -> Vec<f32> {
        let rate = RATE as f32;
        let eighth = eighth_seconds();
        let total = (loop_seconds() * rate) as usize;
        let mut buffer = vec![0.0f32; total];

        // Melodía.
        for (midi, start, length) in melody_notes() {
            let f = freq(midi);
            let samples = (length as f32 * eighth * rate) as usize;
            let begin = (start as f32 * eighth * rate) as usize;
            let voice = (0..samples).map(|i| {
                let t = i as f32 / rate;
                let vibrato = if t > 0.12 { (t * 32.0).sin() * 0.004 } else { 0.0 };
                let env_attack = (t / 0.006).min(1.0);
                let env_decay = 0.55 + 0.45 * (-t * 7.0).exp();
                let release = ((samples - i) as f32 / (0.02 * rate)).min(1.0);
                square(f * (1.0 + vibrato) * t, 0.25) * 0.16 * env_attack * env_decay * release
            });
            let voice: Vec<f32> = voice.collect();
            add(&mut buffer, begin, voice.iter().copied());
            // Eco a tres corcheas, más bajito (suena «amplio» sin reverb).
            let echo = (3.0 * eighth * rate) as usize;
            add(&mut buffer, (begin + echo) % total, voice.iter().map(|v| v * 0.28));
        }

        // Bajo: raíz, octava, raíz, quinta en negras.
        for (bar, root) in ROOTS.iter().enumerate() {
            let Some(root) = note(root) else { continue };
            for (beat, interval) in [0, 12, 0, 7].iter().enumerate() {
                let f = freq(root + interval);
                let begin = ((bar * 8 + beat * 2) as f32 * eighth * rate) as usize;
                let samples = (2.0 * eighth * rate * 0.9) as usize;
                add(
                    &mut buffer,
                    begin,
                    (0..samples).map(|i| {
                        let t = i as f32 / rate;
                        let env = (t / 0.005).min(1.0) * ((samples - i) as f32 / (0.03 * rate)).min(1.0);
                        triangle(f * t) * 0.22 * env
                    }),
                );
            }
        }

        // Batería: bombo en 1 y 3, charles en cada contratiempo.
        let mut noise = Noise(0x1234_5678);
        for eighth_index in 0..MELODY.len() * 8 {
            let begin = (eighth_index as f32 * eighth * rate) as usize;
            if eighth_index % 4 == 0 {
                let samples = (0.12 * rate) as usize;
                add(
                    &mut buffer,
                    begin,
                    (0..samples).map(|i| {
                        let t = i as f32 / rate;
                        let f = 110.0 * (-t * 25.0).exp() + 45.0;
                        (std::f32::consts::TAU * f * t).sin() * 0.30 * (-t * 22.0).exp()
                    }),
                );
            }
            if eighth_index % 2 == 1 {
                let samples = (0.035 * rate) as usize;
                let hat: Vec<f32> = (0..samples)
                    .map(|i| noise.next() * 0.045 * (-(i as f32 / rate) * 90.0).exp())
                    .collect();
                add(&mut buffer, begin, hat.into_iter());
            }
        }

        let peak = buffer.iter().fold(0.0f32, |m, s| m.max(s.abs())).max(1e-6);
        let gain = 0.8 / peak;
        buffer.iter_mut().for_each(|s| *s *= gain);
        buffer
    }

    fn sweep(seconds: f32, from: f32, to: f32, duty: f32, volume: f32) -> Vec<f32> {
        let rate = RATE as f32;
        let samples = (seconds * rate) as usize;
        let mut phase = 0.0f32;
        (0..samples)
            .map(|i| {
                let p = i as f32 / samples as f32;
                phase += (from + (to - from) * p) / rate;
                square(phase, duty) * volume * (1.0 - p).powf(1.5)
            })
            .collect()
    }

    /// «Fiu»: barrido hacia arriba (aleteo).
    pub fn flap() -> Vec<f32> {
        sweep(0.075, 380.0, 820.0, 0.5, 0.35)
    }

    /// «Ding-ding»: dos notas (punto).
    pub fn point() -> Vec<f32> {
        let mut out = sweep(0.06, freq(84), freq(84), 0.25, 0.32);
        out.extend(sweep(0.11, freq(91), freq(91), 0.25, 0.32));
        out
    }

    /// «Pof»: ruido y barrido hacia abajo (choque).
    pub fn hit() -> Vec<f32> {
        let rate = RATE as f32;
        let mut noise = Noise(0xBEEF);
        let mut out = sweep(0.28, 420.0, 70.0, 0.5, 0.35);
        for (i, s) in out.iter_mut().enumerate() {
            let t = i as f32 / rate;
            *s += noise.next() * 0.3 * (-t * 14.0).exp();
        }
        out
    }
}

/// Sonidos del juego sobre gtk::MediaFile (GStreamer). Si no hay backend
/// multimedia, el juego sigue en silencio.
struct Audio {
    music: gtk::MediaFile,
    flap: glib::Bytes,
    point: glib::Bytes,
    hit: glib::Bytes,
    playing: RefCell<Vec<gtk::MediaFile>>,
    muted: Cell<bool>,
}

fn media(bytes: &glib::Bytes) -> gtk::MediaFile {
    gtk::MediaFile::for_input_stream(&gio::MemoryInputStream::from_bytes(bytes))
}

impl Audio {
    fn new() -> Self {
        let music = media(&glib::Bytes::from_owned(sound::wav(&sound::music())));
        music.set_loop(true);
        music.set_volume(0.45);
        Self {
            music,
            flap: glib::Bytes::from_owned(sound::wav(&sound::flap())),
            point: glib::Bytes::from_owned(sound::wav(&sound::point())),
            hit: glib::Bytes::from_owned(sound::wav(&sound::hit())),
            playing: RefCell::new(Vec::new()),
            muted: Cell::new(false),
        }
    }

    fn effect(&self, event: Event) {
        if self.muted.get() {
            return;
        }
        let bytes = match event {
            Event::Flap => &self.flap,
            Event::Point => &self.point,
            Event::Hit => &self.hit,
        };
        let player = media(bytes);
        player.set_volume(0.6);
        player.play();
        let mut playing = self.playing.borrow_mut();
        playing.retain(|p| !p.is_ended());
        playing.push(player);
    }

    fn set_muted(&self, muted: bool) {
        self.muted.set(muted);
        self.music.set_muted(muted);
    }

    fn stop(&self) {
        self.music.set_playing(false);
        for player in self.playing.borrow().iter() {
            player.set_playing(false);
        }
    }
}

// ------------------------------------------------------------------
// Dibujo
// ------------------------------------------------------------------

/// Dígitos de 3×5 para la puntuación.
pub const DIGITS: [[&str; 5]; 10] = [
    ["XXX", "X.X", "X.X", "X.X", "XXX"],
    [".X.", "XX.", ".X.", ".X.", "XXX"],
    ["XXX", "..X", "XXX", "X..", "XXX"],
    ["XXX", "..X", ".XX", "..X", "XXX"],
    ["X.X", "X.X", "XXX", "..X", "..X"],
    ["XXX", "X..", "XXX", "..X", "XXX"],
    ["XXX", "X..", "XXX", "X.X", "XXX"],
    ["XXX", "..X", ".X.", ".X.", ".X."],
    ["XXX", "X.X", "XXX", "X.X", "XXX"],
    ["XXX", "X.X", "XXX", "..X", "XXX"],
];

fn rgb(cr: &cairo::Context, hex: u32) {
    cr.set_source_rgb(
        f64::from((hex >> 16) & 0xff) / 255.0,
        f64::from((hex >> 8) & 0xff) / 255.0,
        f64::from(hex & 0xff) / 255.0,
    );
}

fn rect(cr: &cairo::Context, hex: u32, x: f64, y: f64, w: f64, h: f64) {
    rgb(cr, hex);
    cr.rectangle(x.floor(), y.floor(), w, h);
    let _ = cr.fill();
}

fn draw_score(cr: &cairo::Context, score: u32, center_x: f64, y: f64) {
    let text = score.to_string();
    let size = 2.0; // cada píxel del dígito, en píxeles del juego
    let width = text.len() as f64 * 4.0 * size - size;
    let left = (center_x - width / 2.0).floor();
    for (pass, color, offset) in [(0, 0x5b3b2f, 1.0), (1, 0xffffff, 0.0)] {
        let _ = pass;
        for (i, ch) in text.chars().enumerate() {
            let Some(digit) = ch.to_digit(10) else { continue };
            for (row, line) in DIGITS[digit as usize].iter().enumerate() {
                for (col, cell) in line.chars().enumerate() {
                    if cell == 'X' {
                        let x = left + (i as f64 * 4.0 + col as f64) * size;
                        let yy = y + row as f64 * size;
                        if offset > 0.0 {
                            // Contorno: el píxel y sus vecinos.
                            rect(cr, color, x - 1.0, yy - 1.0, size + 2.0, size + 2.0);
                        } else {
                            rect(cr, color, x, yy, size, size);
                        }
                    }
                }
            }
        }
    }
}

fn draw_background(cr: &cairo::Context, scroll: f64) {
    let sky = cairo::LinearGradient::new(0.0, 0.0, 0.0, GROUND);
    sky.add_color_stop_rgb(0.0, 1.0, 0.953, 0.851);
    sky.add_color_stop_rgb(1.0, 1.0, 0.835, 0.690);
    if cr.set_source(&sky).is_ok() {
        cr.rectangle(0.0, 0.0, WIDTH, GROUND);
        let _ = cr.fill();
    }
    // Sol suave.
    rgb(cr, 0xffe7b8);
    cr.arc(112.0, 34.0, 16.0, 0.0, std::f64::consts::TAU);
    let _ = cr.fill();

    // Nubes pixeladas (paralaje lento).
    let cloud_shift = (scroll * 0.2) % 96.0;
    for i in 0..3 {
        let x = (i as f64 * 96.0 - cloud_shift + if i % 2 == 0 { 0.0 } else { 40.0 }).floor();
        let y = 24.0 + (i % 2) as f64 * 22.0;
        for (dx, dy, w, h) in [(0.0, 4.0, 26.0, 6.0), (5.0, 0.0, 14.0, 5.0), (3.0, 9.0, 20.0, 2.0)] {
            rect(cr, 0xfffbf4, x + dx, y + dy, w, h);
            if x + dx + 96.0 * 3.0 < WIDTH {
                rect(cr, 0xfffbf4, x + dx + 288.0, y + dy, w, h);
            }
        }
    }

    // Colinas (paralaje medio), columna a columna.
    let hill_shift = scroll * 0.45;
    for x in 0..WIDTH as i32 {
        let p = f64::from(x) + hill_shift;
        let height = 26.0 + (p / 19.0).sin() * 7.0 + (p / 8.0).sin() * 3.0;
        let top = (GROUND - height).floor();
        rect(cr, 0xf3b483, f64::from(x), top + 2.0, 1.0, GROUND - top - 2.0);
        rect(cr, 0xe89a62, f64::from(x), top, 1.0, 2.0);
    }
}

fn draw_ground(cr: &cairo::Context, scroll: f64) {
    rect(cr, 0x7a3d1c, 0.0, GROUND, WIDTH, 3.0);
    rect(cr, 0xf2d3a8, 0.0, GROUND + 3.0, WIDTH, HEIGHT - GROUND - 3.0);
    let shift = (scroll % 16.0).floor();
    let mut x = -shift;
    let mut odd = false;
    while x < WIDTH {
        rect(cr, if odd { 0xe7bf8f } else { 0xdcaf7c }, x, GROUND + 6.0, 8.0, 5.0);
        rect(cr, if odd { 0xdcaf7c } else { 0xe7bf8f }, x, GROUND + 11.0, 8.0, 5.0);
        // Chorretones de chocolate del borde.
        if !odd {
            rect(cr, 0x7a3d1c, x + 3.0, GROUND + 3.0, 2.0, 2.0);
        }
        x += 8.0;
        odd = !odd;
    }
}

/// Una columna de churro con su baño de chocolate hacia el hueco.
fn draw_pillar(cr: &cairo::Context, pillar: &Pillar) {
    let x = pillar.x.floor();
    let segments = [(0.0, pillar.gap_top(), true), (pillar.gap_bottom(), GROUND, false)];
    for (top, bottom, cap_at_bottom) in segments {
        let height = bottom - top;
        if height <= 0.0 {
            continue;
        }
        // Cuerpo con estrías.
        rect(cr, 0x5b3b2f, x - 1.0, top, PILLAR_W + 2.0, height);
        rect(cr, 0xe3a24c, x, top, PILLAR_W, height);
        rect(cr, 0xf2c27a, x + 2.0, top, 2.0, height);
        for stripe in [6.0, 10.0, 14.0] {
            rect(cr, 0xc98535, x + stripe, top, 1.0, height);
        }
        // Baño de chocolate en el extremo del hueco.
        let cap_h = 7.0;
        let cap_y = if cap_at_bottom { bottom - cap_h } else { top };
        rect(cr, 0x5b3b2f, x - 3.0, cap_y - 1.0, PILLAR_W + 6.0, cap_h + 2.0);
        rect(cr, 0x7a3d1c, x - 2.0, cap_y, PILLAR_W + 4.0, cap_h);
        rect(cr, 0x9b5427, x - 1.0, cap_y + 1.0, 4.0, 1.0);
        if cap_at_bottom {
            // Gotas que cuelgan.
            for (dx, len) in [(2.0, 3.0), (7.0, 5.0), (13.0, 2.0)] {
                rect(cr, 0x7a3d1c, x + dx, bottom, 2.0, len);
            }
        } else {
            // Virutas de colores encima.
            for (dx, color) in [(1.0, 0xf6b8a6), (6.0, 0xfffbf4), (11.0, 0xf97316), (15.0, 0xf6b8a6)] {
                rect(cr, color, x + dx, cap_y + 2.0, 2.0, 1.0);
            }
        }
    }
}

struct Frames {
    surfaces: Vec<cairo::ImageSurface>,
    width: f64,
    height: f64,
}

fn draw_churr(cr: &cairo::Context, frames: &Frames, world: &World) {
    let Some(surface) = frames.surfaces.get(world.frame()) else { return };
    let _ = cr.save();
    cr.translate(CHURR_X.floor(), world.y.floor());
    cr.rotate(world.tilt());
    cr.translate(-(frames.width / 2.0).floor(), -(frames.height / 2.0).floor());
    let pattern = cairo::SurfacePattern::create(surface);
    pattern.set_filter(cairo::Filter::Nearest);
    if cr.set_source(&pattern).is_ok() {
        let _ = cr.paint();
    }
    let _ = cr.restore();
}

fn draw(cr: &cairo::Context, frames: &Frames, world: &World) {
    cr.scale(SCALE, SCALE);
    // Al rotar a Churr se suaviza su borde; el resto queda en rejilla de píxel.
    cr.set_antialias(cairo::Antialias::None);
    draw_background(cr, world.scroll);
    for pillar in &world.pillars {
        draw_pillar(cr, pillar);
    }
    draw_ground(cr, world.scroll);
    draw_churr(cr, frames, world);
    if world.phase != Phase::Ready {
        draw_score(cr, world.score, WIDTH / 2.0, 12.0);
    }
}

// ------------------------------------------------------------------
// Ventana
// ------------------------------------------------------------------

fn best_score() -> u32 {
    settings::get_string(BEST_KEY, "0").parse().unwrap_or(0)
}

fn label(text: &str, class: &str, valign: gtk::Align, margin: i32) -> gtk::Label {
    let label = gtk::Label::new(Some(text));
    label.add_css_class(class);
    label.set_halign(gtk::Align::Center);
    label.set_valign(valign);
    label.set_justify(gtk::Justification::Center);
    label.set_wrap(true);
    label.set_can_target(false);
    if valign == gtk::Align::Start {
        label.set_margin_top(margin);
    } else {
        label.set_margin_bottom(margin);
    }
    label
}

pub fn open(parent: Option<&gtk::Window>) {
    let Ok(sprite) = Sprite::parse(SPRITE_TEXT) else { return };
    let surfaces: Vec<_> = FRAMES.iter().filter_map(|name| rasterize(&sprite, &[name])).collect();
    if surfaces.len() != FRAMES.len() {
        return;
    }
    let frames = Rc::new(Frames { surfaces, width: sprite.width as f64, height: sprite.height as f64 });

    let window = gtk::Window::builder().title("Churr vuela").modal(true).resizable(false).build();
    window.add_css_class("churr-game");
    if let Some(parent) = parent {
        window.set_transient_for(Some(parent));
    }

    let seed = glib::monotonic_time() as u64 ^ 0x9E37_79B9_7F4A_7C15;
    let world = Rc::new(RefCell::new(World::new(seed)));
    let audio = Rc::new(Audio::new());
    let best = Rc::new(Cell::new(best_score()));

    let area = gtk::DrawingArea::new();
    area.set_content_width((WIDTH * SCALE) as i32);
    area.set_content_height((HEIGHT * SCALE) as i32);
    area.set_focusable(true);
    {
        let (frames, world) = (Rc::clone(&frames), Rc::clone(&world));
        area.set_draw_func(move |_, cr, _, _| draw(cr, &frames, &world.borrow()));
    }

    let overlay = gtk::Overlay::new();
    overlay.set_child(Some(&area));
    let title = label("Churr vuela", "churr-game-title", gtk::Align::Start, 70);
    let hint = label("Toca, haz clic o pulsa Espacio para volar", "churr-game-hint", gtk::Align::End, 70);
    let card = label("", "churr-game-card", gtk::Align::Center, 0);
    card.set_visible(false);
    let mute = gtk::Button::with_label("♪");
    mute.add_css_class("churr-game-mute");
    mute.set_tooltip_text(Some("Silenciar (M)"));
    mute.set_halign(gtk::Align::End);
    mute.set_valign(gtk::Align::Start);
    mute.set_margin_top(8);
    mute.set_margin_end(8);
    mute.set_focusable(false);
    for widget in [title.upcast_ref::<gtk::Widget>(), hint.upcast_ref(), card.upcast_ref(), mute.upcast_ref()] {
        overlay.add_overlay(widget);
    }
    window.set_child(Some(&overlay));

    let toggle_mute = {
        let (audio, mute) = (Rc::clone(&audio), mute.clone());
        Rc::new(move || {
            let muted = !audio.muted.get();
            audio.set_muted(muted);
            mute.set_label(if muted { "×" } else { "♪" });
        })
    };
    {
        let toggle = Rc::clone(&toggle_mute);
        mute.connect_clicked(move |_| toggle());
    }

    let flap = {
        let (world, audio) = (Rc::clone(&world), Rc::clone(&audio));
        Rc::new(move || {
            for event in world.borrow_mut().flap() {
                audio.effect(event);
            }
        })
    };
    let click = gtk::GestureClick::new();
    {
        let flap = Rc::clone(&flap);
        click.connect_pressed(move |_, _, _, _| flap());
    }
    area.add_controller(click);

    let keys = gtk::EventControllerKey::new();
    {
        let (flap, toggle, window) = (Rc::clone(&flap), Rc::clone(&toggle_mute), window.clone());
        keys.connect_key_pressed(move |_, key, _, _| {
            use gtk::gdk::Key;
            match key {
                Key::space | Key::Up | Key::w | Key::W | Key::k | Key::KP_Space => flap(),
                Key::m | Key::M => toggle(),
                Key::Escape => window.close(),
                _ => return glib::Propagation::Proceed,
            }
            glib::Propagation::Stop
        });
    }
    window.add_controller(keys);

    {
        let audio = Rc::clone(&audio);
        window.connect_close_request(move |_| {
            audio.stop();
            glib::Propagation::Proceed
        });
    }

    let last_frame = Cell::new(None::<i64>);
    let accumulator = Cell::new(0.0f64);
    let shown_phase = Cell::new(Phase::Ready);
    {
        let (world, audio, best, window) = (Rc::clone(&world), Rc::clone(&audio), Rc::clone(&best), window.clone());
        area.add_tick_callback(move |area, clock| {
            let now = clock.frame_time();
            let dt = last_frame.get().map_or(0.0, |prev| (now - prev) as f64 / 1_000_000.0).min(0.05);
            last_frame.set(Some(now));
            // Sin foco (otra ventana delante) el juego se detiene.
            if window.is_active() {
                accumulator.set(accumulator.get() + dt);
                let mut world = world.borrow_mut();
                while accumulator.get() >= STEP {
                    accumulator.set(accumulator.get() - STEP);
                    for event in world.step(STEP) {
                        audio.effect(event);
                        if event == Event::Hit && world.score > best.get() {
                            best.set(world.score);
                            settings::set(BEST_KEY, json!(world.score));
                        }
                    }
                }
                let phase = world.phase;
                if phase != shown_phase.get() {
                    shown_phase.set(phase);
                    title.set_visible(phase == Phase::Ready);
                    hint.set_visible(phase == Phase::Ready);
                    card.set_visible(phase == Phase::Over);
                    if phase == Phase::Over {
                        let record = if world.score > 0 && world.score == best.get() { "  ¡Nuevo récord!" } else { "" };
                        card.set_label(&format!(
                            "¡Ay!\nPuntos: {}   Récord: {}{record}\n\nToca para volver a volar",
                            world.score,
                            best.get()
                        ));
                    }
                }
            }
            area.queue_draw();
            glib::ControlFlow::Continue
        });
    }

    window.present();
    area.grab_focus();
    audio.music.play();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn playing(seed: u64) -> World {
        let mut world = World::new(seed);
        world.flap();
        world
    }

    #[test]
    fn churr_sprite_has_every_frame_the_same_size() {
        let sprite = Sprite::parse(SPRITE_TEXT).expect("churr-vuela.sprite válido");
        for name in FRAMES {
            assert!(sprite.has_layer(name), "falta {name}");
        }
        let orange = Some([0xf9, 0x73, 0x16]);
        for name in &FRAMES[..3] {
            assert!(sprite.compose(&[name]).iter().flatten().any(|p| *p == orange), "{name} sin el ojo naranja");
        }
    }

    #[test]
    fn waits_until_the_first_flap_then_gravity_and_flaps_work() {
        let mut world = World::new(7);
        for _ in 0..240 {
            assert!(world.step(STEP).is_empty());
        }
        assert_eq!(world.phase, Phase::Ready);
        assert!(world.pillars.is_empty(), "no aparecen columnas antes de empezar");
        assert_eq!(world.flap(), vec![Event::Flap]);
        assert_eq!(world.phase, Phase::Playing);
        let y0 = world.y;
        for _ in 0..12 {
            world.step(STEP);
        }
        assert!(world.y < y0, "el aleteo sube");
        for _ in 0..60 {
            world.step(STEP);
        }
        assert!(world.vy > 0.0, "luego cae");
    }

    #[test]
    fn the_ceiling_stops_churr_but_the_ground_ends_the_game() {
        let mut world = playing(3);
        for _ in 0..200 {
            world.flap();
            world.step(STEP);
            assert!(world.y >= HIT_H / 2.0 - 1e-9);
        }
        let mut world = playing(3);
        let mut events = Vec::new();
        for _ in 0..600 {
            events.extend(world.step(STEP));
        }
        assert_eq!(world.phase, Phase::Over);
        assert_eq!(events.iter().filter(|e| **e == Event::Hit).count(), 1);
    }

    #[test]
    fn a_pillar_ends_the_game_and_its_gap_scores_once() {
        let mut world = playing(11);
        world.pillars.push_back(Pillar { x: CHURR_X - 2.0, gap_y: 30.0, scored: false });
        world.y = 150.0;
        world.vy = 0.0;
        assert_eq!(world.step(STEP), vec![Event::Hit]);

        let mut world = playing(11);
        world.pillars.push_back(Pillar { x: CHURR_X + 4.0, gap_y: world.y, scored: false });
        let mut points = 0;
        for _ in 0..240 {
            // Mantenerse en el centro del hueco.
            world.y = world.pillars.front().map_or(world.y, |p| p.gap_y);
            world.vy = 0.0;
            points += world.step(STEP).iter().filter(|e| **e == Event::Point).count();
            if world.phase == Phase::Over {
                break;
            }
        }
        assert_eq!(world.phase, Phase::Playing, "el hueco no debe chocar");
        assert_eq!(points, 1, "cada columna da un punto, una vez");
        assert_eq!(world.score, 1);
    }

    #[test]
    fn gaps_always_fit_and_follow_each_other_within_reach() {
        let mut world = playing(0xC0FFEE);
        let mut previous: Option<f64> = None;
        for _ in 0..200 {
            let gap = world.next_gap();
            assert!(gap - GAP / 2.0 >= GAP_MARGIN - 1e-9 && gap + GAP / 2.0 <= GROUND - GAP_MARGIN + 1e-9, "{gap}");
            if let Some(prev) = previous {
                assert!((gap - prev).abs() <= 70.0 + 1e-9, "{prev} -> {gap}");
            }
            world.pillars.push_back(Pillar { x: 0.0, gap_y: gap, scored: false });
            previous = Some(gap);
        }
    }

    #[test]
    fn a_simple_pilot_can_play_for_a_long_time() {
        // Demuestra que el juego es justo: aletear al ir cayendo por debajo
        // del centro del hueco siguiente basta para pasar muchas columnas
        // (un aleteo sube unos 34 px: la mitad del hueco).
        for seed in [1, 2, 3, 42, 0xC0FFEE] {
            let mut world = playing(seed);
            for _ in 0..(120 * 90) {
                let target = world
                    .pillars
                    .iter()
                    .find(|p| p.x + PILLAR_W > CHURR_X - HIT_W / 2.0)
                    .map_or(HEIGHT * 0.45, |p| p.gap_y + 12.0);
                if world.y > target && world.vy >= 0.0 {
                    world.flap();
                }
                world.step(STEP);
                if world.phase == Phase::Over {
                    break;
                }
            }
            assert!(world.score >= 25, "semilla {seed}: solo {} puntos", world.score);
            assert!(world.speed() <= MAX_SPEED);
        }
    }

    #[test]
    fn restart_needs_a_short_pause_and_starts_from_zero() {
        let mut world = playing(5);
        world.score = 4;
        world.phase = Phase::Over;
        world.over_time = 0.1;
        assert!(world.flap().is_empty());
        assert_eq!(world.phase, Phase::Over, "un toque nervioso no reinicia");
        world.over_time = RESTART_DELAY;
        world.flap();
        assert_eq!(world.phase, Phase::Ready);
        assert_eq!(world.score, 0);
        assert!(world.pillars.is_empty());
    }

    #[test]
    fn frames_and_tilt_stay_in_range() {
        let mut world = World::new(9);
        for i in 0..2000 {
            if i % 37 == 0 {
                world.flap();
            }
            world.step(STEP);
            assert!(world.frame() < FRAMES.len());
            assert!((-0.4..=1.0).contains(&world.tilt()));
        }
    }

    #[test]
    fn the_music_is_a_clean_loop_and_effects_are_short() {
        let music = sound::music();
        let seconds = music.len() as f32 / sound::RATE as f32;
        assert!((seconds - sound::loop_seconds()).abs() < 0.01);
        assert!((25.0..35.0).contains(&seconds), "{seconds} s");
        assert!(music.iter().all(|s| s.is_finite() && s.abs() <= 0.81));
        assert!(music.iter().any(|s| s.abs() > 0.5), "demasiado bajo");
        for melody in sound::MELODY {
            assert_eq!(melody.split_whitespace().count(), 8, "{melody}: cada compás tiene 8 corcheas");
            for token in melody.split_whitespace() {
                assert!(matches!(token, "-" | ".") || sound::note(token).is_some(), "{token}");
            }
        }
        assert!(sound::melody_notes().len() > 80);
        for effect in [sound::flap(), sound::point(), sound::hit()] {
            let seconds = effect.len() as f32 / sound::RATE as f32;
            assert!(seconds > 0.05 && seconds < 0.4, "{seconds}");
            assert!(effect.iter().all(|s| s.is_finite() && s.abs() <= 1.0));
        }
        let wav = sound::wav(&[0.0, 0.5, -0.5]);
        assert_eq!(&wav[..4], b"RIFF");
        assert_eq!(&wav[8..16], b"WAVEfmt ");
        assert_eq!(wav.len(), 44 + 6);
        assert_eq!(u32::from_le_bytes(wav[40..44].try_into().unwrap()), 6);
    }

    #[test]
    fn digits_cover_every_number() {
        for digit in DIGITS {
            assert!(digit.iter().all(|row| row.len() == 3));
        }
    }

    /// Para escucharla: CHURR_MUSIC=/ruta/musica.wav cargo test dump_music
    /// (sin la variable no escribe nada).
    #[test]
    fn dump_music() {
        let Ok(path) = std::env::var("CHURR_MUSIC") else { return };
        let mut all = sound::music();
        all.extend(sound::flap());
        all.extend(vec![0.0; 2000]);
        all.extend(sound::point());
        all.extend(vec![0.0; 2000]);
        all.extend(sound::hit());
        std::fs::write(path, sound::wav(&all)).unwrap();
    }
}
