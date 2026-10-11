use std::cell::Cell;
use std::path::PathBuf;
use std::rc::Rc;
use std::time::Duration;

use churros_tour::installation::{INSTALL_SCRIPT, InstallReport, InstallState, write_autostart};
use glib::ControlFlow;
use gtk::prelude::*;

#[derive(Clone)]
pub struct InstallPage {
    pub root: gtk::Box,
    progress: gtk::ProgressBar,
    status: gtk::Label,
    state: Rc<Cell<InstallState>>,
}

pub fn build() -> InstallPage {
    let container = gtk::Box::new(gtk::Orientation::Vertical, 10);
    container.set_valign(gtk::Align::Center);
    container.set_halign(gtk::Align::Center);

    let title = gtk::Label::new(Some("Instalando y Configurando"));
    title.add_css_class("page-title");
    let subtitle = gtk::Label::new(Some(
        "Actualizaremos el sistema e instalaremos las aplicaciones elegidas. Revisa y confirma la operación en la terminal.",
    ));
    subtitle.add_css_class("page-subtitle");
    subtitle.set_wrap(true);
    subtitle.set_max_width_chars(70);
    subtitle.set_justify(gtk::Justification::Center);

    let progress = gtk::ProgressBar::new();
    progress.set_margin_start(32);
    progress.set_margin_end(32);
    let status = gtk::Label::new(Some("Esperando para iniciar..."));
    status.set_wrap(true);
    status.set_max_width_chars(70);
    for widget in [
        title.upcast_ref::<gtk::Widget>(),
        subtitle.upcast_ref(),
        progress.upcast_ref(),
        status.upcast_ref(),
    ] {
        container.append(widget);
    }
    InstallPage {
        root: container,
        progress,
        status,
        state: Rc::new(Cell::new(InstallState::Idle)),
    }
}

fn detect_terminal() -> (String, Vec<String>) {
    let edition = churros_services::version::edition();
    let candidates: &[&str] = match edition.as_str() {
        "kde" => &["konsole", "foot", "xfce4-terminal", "xterm"],
        "xfce" => &["xfce4-terminal", "konsole", "xterm"],
        _ => &["foot", "konsole", "xfce4-terminal", "xterm"],
    };
    for &bin in candidates {
        if churros_services::which(bin) {
            let flags: &[&str] = match bin {
                // These must remain attached to the launched shell, even when a
                // terminal instance is already open in the desktop session.
                "konsole" => &["--separate", "--nofork", "--hide-menubar", "-e"],
                "xfce4-terminal" => &["--disable-server", "--hide-menubar", "-x"],
                "foot" => &["-a", "churros-installer", "-W", "80x24", "-e"],
                _ => &["-e"],
            };
            return (bin.into(), flags.iter().map(|s| (*s).into()).collect());
        }
    }
    // Sin terminal disponible: devolver error explícito en vez de un
    // binario que no existe (el usuario vería un error críptico de spawn).
    ("".into(), Vec::new())
}

impl InstallPage {
    pub fn is_running(&self) -> bool {
        self.state.get() == InstallState::Running
    }

    pub fn show_error(&self, message: &str) {
        self.status.set_label(message);
    }

    pub fn finish(&self, open_at_login: bool) -> std::io::Result<()> {
        if !self.state.get().can_finish() {
            return Err(std::io::Error::other("La instalación sigue en curso."));
        }
        if std::env::var_os("CHURROS_TOUR_PREVIEW").is_some() {
            return Ok(());
        }
        // Failed / interrupted jobs must be retried; never remove their autostart.
        handle_autostart(open_at_login || !self.state.get().can_disable_autostart())
    }

    pub fn start(&self, packages: Vec<String>, done: impl Fn(bool) + 'static) {
        if self.is_running() {
            return;
        }
        self.progress.set_fraction(0.0);
        // Host previews can navigate the whole flow but cannot install or write autostart.
        if std::env::var_os("CHURROS_TOUR_PREVIEW").is_some() {
            self.state.set(InstallState::Complete);
            self.status.set_label(&format!(
                "Vista previa: {} aplicaciones seleccionadas. No se ejecutó ninguna instalación.",
                packages.len()
            ));
            self.progress.set_fraction(1.0);
            done(true);
            return;
        }
        if packages.is_empty() {
            self.state.set(InstallState::Complete);
            self.status
                .set_label("No seleccionaste aplicaciones. Puedes finalizar el recorrido.");
            self.progress.set_fraction(1.0);
            done(true);
            return;
        }
        // Preserve retry on the next login even if the window or terminal is interrupted.
        if let Err(e) = handle_autostart(true) {
            self.failed(&format!("No se pudo conservar el inicio del Tour: {e}. Corrige el error y vuelve a intentarlo."));
            done(false);
            return;
        }
        let report = match InstallReport::new() {
            Ok(report) => report,
            Err(e) => {
                self.failed(&format!("No se pudo preparar la instalación: {e}"));
                done(false);
                return;
            }
        };
        let (terminal, flags) = detect_terminal();
        if terminal.is_empty() {
            self.failed("No hay terminal disponible para el instalador");
            done(false);
            return;
        }
        let mut args = vec![terminal];
        args.extend(flags);
        args.extend([
            "sh".into(),
            "-c".into(),
            INSTALL_SCRIPT.into(),
            "churros-tour".into(),
        ]);
        args.push(report.path().to_string_lossy().into_owned());
        args.extend(packages);
        let os_args: Vec<_> = args.iter().map(std::ffi::OsStr::new).collect();
        let process = match gio::Subprocess::newv(&os_args, gio::SubprocessFlags::NONE) {
            Ok(process) => process,
            Err(e) => {
                self.failed(&format!(
                    "Error al lanzar la terminal: {e}. Vuelve atrás para reintentar."
                ));
                done(false);
                return;
            }
        };
        self.state.set(InstallState::Running);
        self.status.set_label(
            "Actualizando e instalando. Revisa la terminal para confirmar la operación...",
        );
        let page = self.clone();
        glib::timeout_add_local(Duration::from_millis(100), move || {
            if !page.is_running() {
                return ControlFlow::Break;
            }
            page.progress.pulse();
            ControlFlow::Continue
        });
        let page = self.clone();
        let waited = process.clone();
        process.wait_async(gio::Cancellable::NONE, move |result| {
            // A terminal exiting is not evidence that yay succeeded. Both the
            // process and the private report from the shell must confirm success.
            let success = result.is_ok() && waited.is_successful() && report.succeeded();
            if success {
                page.state.set(InstallState::Complete);
                page.progress.set_fraction(1.0);
                page.status.set_label("¡Instalación completada! Puedes finalizar el recorrido.");
            } else {
                page.failed("La instalación falló o fue interrumpida. Revisa la terminal y vuelve atrás para reintentar. El Tour seguirá disponible al iniciar.");
            }
            done(success);
        });
    }

    fn failed(&self, message: &str) {
        self.state.set(InstallState::Failed);
        self.progress.set_fraction(0.0);
        self.show_error(message);
    }
}

fn handle_autostart(active: bool) -> std::io::Result<()> {
    if std::env::var_os("CHURROS_TOUR_PREVIEW").is_some() {
        return Ok(());
    }
    let home =
        std::env::var_os("HOME").ok_or_else(|| std::io::Error::other("HOME no está definido"))?;
    write_autostart(&PathBuf::from(home).join(".config"), active)
}
