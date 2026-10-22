// ==========================================
// ApplicationsPage — aplicaciones instaladas
// (equivalente a pages/applications.py)
// ==========================================


use crate::services::applications::ApplicationsService;
use crate::widgets::group::Group;
use crate::widgets::navigation_row;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(
        Some(navigator.clone()),
        "Aplicaciones",
        Some("Administrar aplicaciones instaladas"),
        None,
    );

    // ============ Información ============
    let mut info = Group::new("Información");

    info.add(&Row::new(
        "Aplicaciones instaladas",
        Some("Cantidad de aplicaciones"),
        Some("applications.svg"),
        Some(&ApplicationsService::count()),
        None,
        None,
    ));

    info.add(&Row::new(
        "Tienda",
        Some("Gestor principal"),
        Some("applications.svg"),
        Some(ApplicationsService::store()),
        None,
        None,
    ));

    page.add(info.widget());

    // ============ Opciones ============
    let mut options = Group::new("Opciones");

    options.add(&SwitchRow::new(
        "Buscar actualizaciones",
        Some("applications.svg"),
        Some("Comprobar nuevas versiones automáticamente"),
        ApplicationsService::auto_updates(),
        Some(Box::new(|active| {
            ApplicationsService::set_auto_updates(active);
        })),
    ));

    options.add(&SwitchRow::new(
        "Actualizar automáticamente",
        Some("applications.svg"),
        Some("Instalar actualizaciones automáticamente"),
        ApplicationsService::auto_install(),
        Some(Box::new(|active| {
            ApplicationsService::set_auto_install(active);
        })),
    ));

    page.add(options.widget());

    // ============ Gestión ============
    let mut manage = Group::new("Gestión");

    manage.add(&navigation_row::new(
        navigator,
        "Desinstalar aplicaciones",
        "applications.svg",
        "uninstall-apps",
        Some("Buscar y eliminar programas instalados"),
    ));

    page.add(manage.widget());

    page
}
