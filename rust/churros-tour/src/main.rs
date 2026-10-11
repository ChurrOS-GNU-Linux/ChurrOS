#![allow(deprecated)]

mod app;
mod assets;
mod pages;

use gtk::prelude::*;
use std::path::Path;

const APP_ID: &str = "org.churros.tour";

fn main() -> glib::ExitCode {
    unsafe {
        libc::signal(libc::SIGPIPE, libc::SIG_IGN);
    }

    // El tour no debe ejecutarse en el entorno live CD de instalación.
    // Si detectamos /run/archiso, salimos silenciosamente.
    if std::env::var("CHURROS_TOUR_PREVIEW").is_err() && Path::new("/run/archiso").exists() {
        println!("Detectado entorno Live CD. ChurrOS Tour solo corre en el sistema instalado.");
        return glib::ExitCode::SUCCESS;
    }

    let application = gtk::Application::builder().application_id(APP_ID).build();

    application.connect_activate(app::activate);

    application.run_with_args(&[] as &[&str])
}

#[cfg(test)]
mod tests;
