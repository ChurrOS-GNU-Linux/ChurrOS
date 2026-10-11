// ==========================================
// audio.rs — popup de audio / slide bar de volumen
// ==========================================

use std::cell::Cell;
use std::rc::Rc;
use std::time::{Duration, Instant};

use churros_services::audio;
use gtk::prelude::*;

use crate::popup::PopupWindow;

pub fn build(app: &gtk::Application) -> PopupWindow {
    let w = PopupWindow::new(app, "Audio", "󰕾", "audio.css");
    w.add(&volume_widget());
    w
}

fn update_icon_and_label(val: u8, muted: bool, icon: &gtk::Label, label: &gtk::Label) {
    let icon_char = if muted || val == 0 {
        "󰝟"
    } else if val < 30 {
        "󰕿"
    } else if val < 70 {
        "󰖀"
    } else {
        "󰕾"
    };
    icon.set_label(icon_char);
    if muted {
        label.set_label(&format!("{val}% (Silenciado)"));
    } else {
        label.set_label(&format!("{val}%"));
    }
}

/// Slider de volumen único, responsivo e instantáneo
fn volume_widget() -> gtk::Box {
    let vbox = gtk::Box::new(gtk::Orientation::Vertical, 12);
    vbox.add_css_class("volume-widget");

    let header_box = gtk::Box::new(gtk::Orientation::Horizontal, 10);

    let icon = gtk::Label::new(Some("󰕾"));
    icon.add_css_class("volume-icon");

    let label = gtk::Label::new(None);
    label.add_css_class("volume-label");
    label.set_xalign(0.0);
    label.set_hexpand(true);

    header_box.append(&icon);
    header_box.append(&label);
    vbox.append(&header_box);

    let slider = gtk::Scale::with_range(gtk::Orientation::Horizontal, 0.0, 100.0, 1.0);
    slider.set_draw_value(false);
    slider.set_hexpand(true);
    slider.set_digits(0);
    slider.set_round_digits(0);
    vbox.append(&slider);

    if !audio::available() {
        label.set_label("Audio no disponible");
        slider.set_value(0.0);
        slider.set_sensitive(false);
        return vbox;
    }

    let (initial_vol, initial_muted) = audio::get_volume_status();
    slider.set_value(initial_vol as f64);
    update_icon_and_label(initial_vol, initial_muted, &icon, &label);

    let last_user_time = Rc::new(Cell::new(Instant::now() - Duration::from_secs(60)));
    let last_sent_val = Rc::new(Cell::new(initial_vol));
    let is_muted = Rc::new(Cell::new(initial_muted));

    let ic1 = icon.clone();
    let lb1 = label.clone();
    let time1 = last_user_time.clone();
    let sent1 = last_sent_val.clone();
    let muted1 = is_muted.clone();

    slider.connect_value_changed(move |s| {
        let val = s.value().round() as u8;
        time1.set(Instant::now());

        // Si el usuario sube el volumen cuando estaba silenciado, desilenciar
        if muted1.get() && val > 0 {
            audio::set_mute(false);
            muted1.set(false);
        }

        update_icon_and_label(val, muted1.get(), &ic1, &lb1);

        if sent1.get() != val {
            sent1.set(val);
            audio::set_volume(val);
        }
    });

    // Clic en el icono para silenciar / reactivar instantáneamente
    let ic_click = icon.clone();
    let lb_click = label.clone();
    let slider_click = slider.clone();
    let muted_click = is_muted.clone();
    let time_click = last_user_time.clone();
    let click_gesture = gtk::GestureClick::new();
    click_gesture.connect_pressed(move |_, _, _, _| {
        time_click.set(Instant::now());
        let new_m = !muted_click.get();
        muted_click.set(new_m);
        audio::set_mute(new_m);
        let cur_v = slider_click.value().round() as u8;
        update_icon_and_label(cur_v, new_m, &ic_click, &lb_click);
    });
    icon.add_controller(click_gesture);

    // Refresco periódico (1s) sin pisar las interacciones activas del usuario
    let s2 = slider.clone();
    let ic2 = icon.clone();
    let lb2 = label.clone();
    let time2 = last_user_time.clone();
    let muted2 = is_muted.clone();

    glib::timeout_add_seconds_local(1, move || {
        if time2.get().elapsed() < Duration::from_millis(1500)
            || s2.state_flags().contains(gtk::StateFlags::ACTIVE)
        {
            return glib::ControlFlow::Continue;
        }

        let s3 = s2.clone();
        let ic3 = ic2.clone();
        let lb3 = lb2.clone();
        let muted3 = muted2.clone();
        crate::popup::run_bg(audio::get_volume_status, move |(cur_v, cur_m)| {
            let active = s3.state_flags().contains(gtk::StateFlags::ACTIVE);
            if !active {
                muted3.set(cur_m);
                if s3.value().round() as u8 != cur_v {
                    s3.set_value(cur_v as f64);
                }
                update_icon_and_label(cur_v, cur_m, &ic3, &lb3);
            }
        });

        glib::ControlFlow::Continue
    });

    vbox
}
