// ==========================================
// AboutPage — Acerca de ChurrOS
// (equivalente a pages/about.py)
// ==========================================

use crate::services::about::AboutService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;

pub fn build(_navigator: gtk::Stack) -> Page {
    let page = Page::new(None, "Acerca de", Some("Información de ChurrOS"), None);

    // ChurrOS
    let mut system = Group::new("ChurrOS");

    system.add(&Row::new(
        "Distribución",
        Some("Sistema operativo"),
        Some("system.svg"),
        Some(AboutService::distro()),
        None,
        None,
    ));
    system.add(&Row::new(
        "Versión",
        Some("Versión instalada"),
        Some("system.svg"),
        Some(AboutService::version()),
        None,
        Some(crate::widgets::churr::on_version_tap()),
    ));
    system.add(&Row::new(
        "Edición",
        Some("Canal de desarrollo"),
        Some("system.svg"),
        Some(AboutService::edition()),
        None,
        None,
    ));

    page.add(system.widget());

    // Software
    let mut software = Group::new("Software");

    software.add(&Row::new(
        "Kernel",
        Some("Versión del kernel"),
        Some("applications.svg"),
        Some(&AboutService::kernel()),
        None,
        None,
    ));
    software.add(&Row::new(
        "Base",
        Some("Distribución base"),
        Some("applications.svg"),
        Some(AboutService::base()),
        None,
        None,
    ));
    software.add(&Row::new(
        "Sesión",
        Some("Entorno actual"),
        Some("applications.svg"),
        Some(&AboutService::session()),
        None,
        None,
    ));

    page.add(software.widget());

    // Proyecto
    let mut project = Group::new("Proyecto");

    project.add(&Row::new(
        "Desarrollador",
        Some("Proyecto iniciado por"),
        Some("about.svg"),
        Some(AboutService::developer()),
        None,
        None,
    ));
    project.add(&Row::new(
        "Licencia",
        Some("Licencia del proyecto"),
        Some("about.svg"),
        Some(AboutService::license()),
        None,
        None,
    ));

    page.add(project.widget());

    page
}
