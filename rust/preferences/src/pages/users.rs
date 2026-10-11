// ==========================================
// UsersPage — cuenta del sistema y personalización de inicio de sesión
// ==========================================

use gtk::prelude::*;

use std::cell::Cell;
use std::rc::Rc;

use crate::services::users::UsersService;
use crate::services::wallpaper::WallpaperService;
use crate::widgets::group::Group;
use crate::widgets::page::Page;
use crate::widgets::row::Row;
use crate::widgets::switch_row::SwitchRow;

pub fn build(navigator: gtk::Stack) -> Page {
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

    // Sincronizar fondo del escritorio con la pantalla de login. Solo valen
    // los fondos del sistema: uno del home no lo puede leer el greeter.
    let sync_wp_row = Row::new(
        "Sincronizar fondo",
        Some("Aplicar el fondo del escritorio a la pantalla de login"),
        Some("wallpaper.svg"),
        None,
        None,
        None,
    );
    let feedback = sync_wp_row.subtitle_label().cloned();
    sync_wp_row.button.connect_clicked(move |_| {
        let wp = WallpaperService::current();
        if wp.is_empty() {
            return;
        }
        let text = if UsersService::set_regreet_wallpaper(&wp) {
            "Fondo aplicado a la pantalla de login"
        } else {
            "No se pudo aplicar: la pantalla de login solo usa fondos del sistema \
             (/usr/share/churros/wallpapers o /usr/share/backgrounds)"
        };
        if let Some(label) = &feedback {
            label.set_label(text);
        }
    });
    login_screen.add(&sync_wp_row);

    // Mensaje de bienvenida
    let greeting = UsersService::regreet_greeting();
    let greeting_row = Row::new(
        "Mensaje de bienvenida",
        Some("Texto mostrado en la pantalla de inicio"),
        Some("theme.svg"),
        Some(&greeting),
        None,
        None,
    );
    login_screen.add(&greeting_row);

    page.add(login_screen.widget());

    page
}
