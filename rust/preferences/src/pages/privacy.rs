// ==========================================
// PrivacyPage — permisos, firewall y diagnóstico
// (equivalente a pages/privacy.py)
// ==========================================


use gtk::prelude::*;

use crate::services::privacy::PrivacyService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator),
        "Privacidad",
        Some("Configuración de privacidad y seguridad"),
        None,
    );

    // Permisos
    let mut permissions = Group::new("Permisos");

    permissions.add(&SwitchRow::new(
        "Servicios de ubicación",
        Some("privacy.svg"),
        Some("Permitir que las aplicaciones accedan a la ubicación"),
        PrivacyService::location(),
        Some(Box::new(|v| PrivacyService::set_location(v))),
    ));

    // Sin un backend de revocación global, no mostrar permisos ficticios.
    for title in ["Acceso a la cámara", "Acceso al micrófono"] {
        let row = Row::new(
            title,
            Some("ChurrOS no bloquea este dispositivo desde Ajustes. Gestiona los permisos en cada aplicación; para impedir todo acceso, desactiva el dispositivo físicamente."),
            Some("privacy.svg"),
            Some("No disponible"),
            None,
            None,
        );
        row.widget().set_sensitive(false);
        permissions.add(&row);
    }

    page.add(permissions.widget());

    // Firewall
    let mut firewall = Group::new("Firewall");

    firewall.add(&SwitchRow::new(
        "Firewall (ufw)",
        Some("privacy.svg"),
        Some("Activar el firewall del sistema"),
        PrivacyService::firewall(),
        Some(Box::new(|v| {
            PrivacyService::set_firewall(v);
        })),
    ));

    page.add(firewall.widget());

    // Diagnóstico
    let mut diagnostics = Group::new("Diagnóstico");

    diagnostics.add(&SwitchRow::new(
        "Enviar estadísticas",
        Some("privacy.svg"),
        Some("Compartir información anónima para mejorar ChurrOS"),
        PrivacyService::telemetry(),
        Some(Box::new(|v| PrivacyService::set_telemetry(v))),
    ));

    page.add(diagnostics.widget());

    page
}
