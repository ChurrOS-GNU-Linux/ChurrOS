// ==========================================
// UsersPage — cuenta del sistema y personalización de inicio de sesión
// ==========================================

use gtk::prelude::*;

use std::cell::Cell;
use std::rc::Rc;

use crate::services::users::UsersService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

pub fn build(navigator: gtk::Stack) -> Page {
    let navigator_for_greeter = navigator.clone();
    let page = Page::new(
        Some(navigator),
        "Usuarios y Login",
        Some("Administrar cuentas y pantalla de inicio de sesión"),
        None,
    );

    // Cuenta
    let mut account = Group::new("Cuenta");

    account.add(&Row::new(
        "Usuario",
        Some("Sesión actual"),
        Some("users.svg"),
        Some(&UsersService::username()),
        None,
        None,
    ));

    account.add(&Row::new(
        "Nombre",
        Some("Nombre completo"),
        Some("users.svg"),
        Some(&UsersService::full_name()),
        None,
        None,
    ));

    page.add(account.widget());

    // Pantalla de inicio de sesión (ReGreet / greetd)
    let mut login_screen = Group::new("Pantalla de inicio de sesión");

    // Autologin switch
    let autologin_row = SwitchRow::new(
        "Inicio automático",
        Some("users.svg"),
        Some("Iniciar sesión automáticamente sin solicitar contraseña"),
        UsersService::auto_login(),
        None,
    );
    let autologin_switch = autologin_row.switch.clone();
    let revert_guard = Rc::new(Cell::new(false));
    {
        let revert_guard = Rc::clone(&revert_guard);
        autologin_switch.connect_notify_local(Some("active"), move |switch, _| {
            if revert_guard.get() {
                return;
            }
            revert_guard.set(true);
            let active = switch.is_active();
            let ok = UsersService::set_auto_login(active);
            if !ok {
                switch.set_active(!active);
            }
            revert_guard.set(false);
        });
    }
    login_screen.add(&autologin_row);

    // Fondo, reloj, saludo, logo y color: Apariencia > Pantalla de inicio.
    login_screen.add(&crate::widgets::navigation_row::new(
        navigator_for_greeter,
        "Personalizar la pantalla de inicio",
        "lock_screen.svg",
        "greeter",
        Some("Fondo, reloj, saludo y colores"),
    ));

    page.add(login_screen.widget());

    page
}
