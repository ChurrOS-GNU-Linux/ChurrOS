// ==========================================
// network.rs — tarjeta de red (port de widgets/network.py)
// ==========================================

use gtk::prelude::*;

use super::card::Card;
use super::open_popup;
use crate::widgets::SystemInfo;

pub struct NetworkCard {
    card: Card,
}

impl NetworkCard {
    pub fn new(window: &gtk::ApplicationWindow) -> Self {
        let card = Card::new("wifi.svg", "Network", "Loading...");

        let win = window.clone();
        card.button.connect_clicked(move |_| {
            open_popup(&win, "network");
        });

        Self { card }
    }

    pub fn button(&self) -> &gtk::Button {
        &self.card.button
    }

    pub fn apply_info(&self, info: &SystemInfo) {
        if info.ethernet_connected {
            let subtitle = if !info.ethernet_name.is_empty() {
                info.ethernet_name.clone()
            } else {
                "Ethernet".to_string()
            };
            let speed_str = if let Some(sp) = info.ethernet_speed {
                format!("{sp} Mbit/s")
            } else if !info.network_rate_down.is_empty() {
                format!("⇣ {}", info.network_rate_down)
            } else {
                String::new()
            };
            self.card.set_state(Some(&subtitle), Some("ethernet.svg"));
            self.card.set_detail(Some(&speed_str));
            let tooltip = format!(
                "Ethernet: {}\nVelocidad: {}",
                subtitle,
                if speed_str.is_empty() { "Conectado" } else { &speed_str }
            );
            self.card.button.set_tooltip_text(Some(&tooltip));
            return;
        }

        if !info.wifi_available {
            self.card.set_state(Some("Unavailable"), Some("wifi.svg"));
            self.card.set_detail(None);
            self.card.button.set_tooltip_text(Some("Sin adaptador Wi-Fi"));
            return;
        }

        if info.wifi_connected {
            self.card.set_state(Some(&info.wifi_name), Some("wifi.svg"));

            let mut speed_detail = String::new();
            if !info.wifi_speed.is_empty() {
                speed_detail.push_str(&info.wifi_speed);
            }
            if !info.network_rate_down.is_empty() {
                if !speed_detail.is_empty() {
                    speed_detail.push_str(" • ");
                }
                speed_detail.push_str(&info.network_rate_down);
            }

            self.card.set_detail(Some(&speed_detail));

            let tooltip = format!(
                "Wi-Fi: {}\nVelocidad de enlace: {}\nTráfico: {}\nSeñal: {}%",
                info.wifi_name,
                if info.wifi_speed.is_empty() { "—" } else { &info.wifi_speed },
                if info.network_rate_down.is_empty() { "—" } else { &info.network_rate_down },
                info.wifi_strength
            );
            self.card.button.set_tooltip_text(Some(&tooltip));
        } else {
            self.card.set_state(Some("Disconnected"), Some("wifi.svg"));
            self.card.set_detail(None);
            self.card.button.set_tooltip_text(Some("Desconectado"));
        }
    }
}