use std::cell::{Cell, RefCell};
use std::path::PathBuf;
use std::rc::Rc;

use churros_tour::installation::{INSTALL_SCRIPT, InstallReport, InstallState, write_autostart};
use gio::prelude::*;
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
        "Descargaremos e instalaremos las aplicaciones seleccionadas en segundo plano.",
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
        self.progress.set_show_text(false);
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
        // Preserve retry on the next login even if the window is interrupted.
        if let Err(e) = handle_autostart(true) {
            self.failed(&format!("No se pudo conservar el inicio del Tour: {e}. Corrige el error y vuelve a intentarlo."));
            done(false);
            return;
        }
        if !churros_services::which("yay") {
            self.failed("No se encontró el gestor de paquetes yay en el sistema.");
            done(false);
            return;
        }

        self.state.set(InstallState::Running);
        let packages_rc = Rc::new(packages);
        let done_rc: Rc<dyn Fn(bool)> = Rc::new(done);
        install_package_step(self.clone(), packages_rc, 0, done_rc);
    }

    fn failed(&self, message: &str) {
        self.state.set(InstallState::Failed);
        self.progress.set_fraction(0.0);
        self.progress.set_show_text(false);
        self.show_error(message);
    }
}

fn parse_percent(line: &str) -> Option<f64> {
    if let Some(pos) = line.find('%') {
        let before = &line[..pos];
        let digits: String = before
            .chars()
            .rev()
            .take_while(|c| c.is_ascii_digit() || *c == '.')
            .collect();
        let digits: String = digits.chars().rev().collect();
        digits.parse::<f64>().ok()
    } else {
        None
    }
}

fn update_install_feedback(
    page: &InstallPage,
    app_name: &str,
    index: usize,
    total: usize,
    line: &str,
) {
    if let Some(pct) = parse_percent(line) {
        let intra = (pct / 100.0).clamp(0.0, 1.0);
        let fraction = (index as f64 + intra) / total as f64;
        page.progress.set_fraction(fraction);
        page.progress.set_text(Some(&format!("{}/{} ({app_name} {:.0}%)", index + 1, total, pct)));
        page.status.set_label(&format!("Descargando {app_name}... ({pct:.0}%)"));
    } else if line.contains("Making package") || line.contains("Compilando") || line.contains("Entering fakeroot") {
        let fraction = (index as f64 + 0.6) / total as f64;
        page.progress.set_fraction(fraction);
        page.status.set_label(&format!("Compilando {app_name}..."));
    } else if line.contains("installing ") || line.contains("Instalando ") {
        let fraction = (index as f64 + 0.85) / total as f64;
        page.progress.set_fraction(fraction);
        page.status.set_label(&format!("Instalando {app_name}..."));
    } else if line.contains("Synchronizing") || line.contains("Sincronizando") {
        page.status.set_label("Sincronizando repositorios...");
    }
}

fn track_output(
    stream: gio::DataInputStream,
    page: InstallPage,
    app_name: String,
    index: usize,
    total: usize,
    last_line: Rc<RefCell<String>>,
) {
    let page_clone = page.clone();
    let app_name_clone = app_name.clone();
    let stream_clone = stream.clone();
    let last_line_clone = last_line.clone();

    stream.read_line_utf8_async(glib::Priority::DEFAULT, gio::Cancellable::NONE, move |res| {
        if let Ok(Some(line)) = res {
            let trimmed = line.trim();
            if !trimmed.is_empty() {
                *last_line_clone.borrow_mut() = trimmed.to_string();
                update_install_feedback(&page_clone, &app_name_clone, index, total, trimmed);
            }
            track_output(stream_clone, page_clone, app_name_clone, index, total, last_line_clone);
        }
    });
}

fn install_package_step(
    page: InstallPage,
    packages: Rc<Vec<String>>,
    index: usize,
    done: Rc<dyn Fn(bool)>,
) {
    let total = packages.len();
    if index >= total {
        page.state.set(InstallState::Complete);
        page.progress.set_fraction(1.0);
        page.progress.set_show_text(true);
        page.progress.set_text(Some(&format!("{total}/{total} completadas")));
        page.status.set_label("¡Instalación completada! Puedes finalizar el recorrido.");
        done(true);
        return;
    }

    let pkg = &packages[index];
    let app_name = churros_tour::catalog::app_name(pkg);
    let fraction = index as f64 / total as f64;
    page.progress.set_fraction(fraction);
    page.progress.set_show_text(true);
    page.progress.set_text(Some(&format!("{index}/{total}")));
    page.status.set_label(&format!(
        "Instalando {app_name} ({}/{}) en segundo plano...",
        index + 1,
        total
    ));

    let report = match InstallReport::new() {
        Ok(report) => report,
        Err(e) => {
            page.failed(&format!("No se pudo preparar la instalación: {e}"));
            done(false);
            return;
        }
    };

    let args = [
        "sh".into(),
        "-c".into(),
        INSTALL_SCRIPT.into(),
        "churros-tour".into(),
        report.path().to_string_lossy().into_owned(),
        pkg.clone(),
    ];
    let os_args: Vec<_> = args.iter().map(std::ffi::OsStr::new).collect();
    let process = match gio::Subprocess::newv(
        &os_args,
        gio::SubprocessFlags::STDOUT_PIPE | gio::SubprocessFlags::STDERR_MERGE,
    ) {
        Ok(process) => process,
        Err(e) => {
            page.failed(&format!(
                "Error al iniciar la instalación de {app_name}: {e}. Vuelve atrás para reintentar."
            ));
            done(false);
            return;
        }
    };

    let last_line = Rc::new(RefCell::new(String::new()));
    if let Some(pipe) = process.stdout_pipe() {
        let stream = gio::DataInputStream::new(&pipe);
        track_output(
            stream,
            page.clone(),
            app_name.to_string(),
            index,
            total,
            last_line.clone(),
        );
    }

    let page_clone = page.clone();
    let packages_clone = packages.clone();
    let done_clone = done.clone();
    let app_name_clone = app_name.to_string();
    let waited = process.clone();
    let last_line_clone = last_line.clone();

    process.wait_async(gio::Cancellable::NONE, move |result| {
        let success = result.is_ok() && waited.is_successful() && report.succeeded();
        if success {
            install_package_step(page_clone, packages_clone, index + 1, done_clone);
        } else {
            let err_detail = last_line_clone.borrow();
            let msg = if err_detail.is_empty() {
                format!(
                    "La instalación de {app_name_clone} falló o fue interrumpida. Vuelve atrás para reintentar. El Tour seguirá disponible al iniciar."
                )
            } else {
                format!(
                    "La instalación de {app_name_clone} falló ({err_detail}). Vuelve atrás para reintentar. El Tour seguirá disponible al iniciar."
                )
            };
            page_clone.failed(&msg);
            done_clone(false);
        }
    });
}

fn handle_autostart(active: bool) -> std::io::Result<()> {
    if std::env::var_os("CHURROS_TOUR_PREVIEW").is_some() {
        return Ok(());
    }
    let home =
        std::env::var_os("HOME").ok_or_else(|| std::io::Error::other("HOME no está definido"))?;
    write_autostart(&PathBuf::from(home).join(".config"), active)
}
