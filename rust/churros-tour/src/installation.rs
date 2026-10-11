//! Installation protocol independent of GTK. Tests use a fake yay in a private directory.
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

// Arguments are passed separately: never interpolate packages or paths into shell code.
// Keep the package manager's exit status even after displaying the error / reading Enter.
pub const INSTALL_SCRIPT: &str = r#"
report=$1
shift
yay -Syu --needed -- "$@"
status=$?
printf '%s\n' "$status" > "$report" || exit 125
if [ "$status" -eq 0 ]; then
    printf '\n[ChurrOS] ¡Instalación completada con éxito!\n'
else
    printf '\n[ChurrOS] Ocurrió un error (código %s). Presiona Enter para cerrar.\n' "$status"
    read -r answer
fi
exit "$status"
"#;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum InstallState {
    #[default]
    Idle,
    Running,
    Complete,
    Failed,
}

impl InstallState {
    pub fn can_finish(self) -> bool {
        self != Self::Running
    }

    pub fn can_disable_autostart(self) -> bool {
        self == Self::Complete
    }
}

pub struct InstallReport {
    directory: PathBuf,
}

impl InstallReport {
    pub fn new() -> io::Result<Self> {
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_nanos();
        for _ in 0..100 {
            let directory = std::env::temp_dir().join(format!(
                "churros-tour-{}-{timestamp}-{}",
                std::process::id(),
                COUNTER.fetch_add(1, Ordering::Relaxed)
            ));
            match std::fs::DirBuilder::new().mode(0o700).create(&directory) {
                Ok(()) => return Ok(Self { directory }),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(e) => return Err(e),
            }
        }
        Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            "No se pudo crear el informe de instalación",
        ))
    }

    pub fn path(&self) -> PathBuf {
        self.directory.join("status")
    }

    pub fn succeeded(&self) -> bool {
        std::fs::read_to_string(self.path())
            .ok()
            .and_then(|s| s.trim().parse::<u8>().ok())
            == Some(0)
    }
}

impl Drop for InstallReport {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(self.path());
        let _ = std::fs::remove_dir(&self.directory);
    }
}

pub fn write_autostart(config_home: &Path, active: bool) -> io::Result<()> {
    let directory = config_home.join("autostart");
    let path = directory.join("churros-tour.desktop");
    if active {
        std::fs::create_dir_all(directory)?;
        std::fs::write(
            path,
            "[Desktop Entry]\nType=Application\nName=ChurrOS Tour\nExec=churros-tour\nTerminal=false\nCategories=System;\n",
        )
    } else {
        match std::fs::remove_file(path) {
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            result => result,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    use std::process::{Command, Stdio};

    #[test]
    fn fake_package_manager_covers_success_failure_cancellation_and_exact_arguments() {
        let sandbox = InstallReport::new().unwrap();
        let yay = sandbox.directory.join("yay");
        let args_file = sandbox.directory.join("args");
        std::fs::write(
            &yay,
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TOUR_TEST_ARGS\"\nexit \"$TOUR_TEST_EXIT\"\n",
        )
        .unwrap();
        std::fs::set_permissions(&yay, std::fs::Permissions::from_mode(0o700)).unwrap();
        assert_eq!(
            std::fs::metadata(&sandbox.directory).unwrap().mode() & 0o777,
            0o700
        );
        for code in [0, 1, 42, 130] {
            let report = InstallReport::new().unwrap();
            assert!(!report.succeeded()); // A closed terminal / missing report is never success.
            let status = Command::new("/bin/sh")
                .args(["-c", INSTALL_SCRIPT, "churros-tour"])
                .arg(report.path())
                .args(["firefox", "obs-studio"])
                .env("PATH", &sandbox.directory)
                .env("TOUR_TEST_EXIT", code.to_string())
                .env("TOUR_TEST_ARGS", &args_file)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(code));
            assert_eq!(report.succeeded(), code == 0);
            assert_eq!(
                std::fs::read_to_string(&args_file).unwrap(),
                "-Syu\n--needed\n--\nfirefox\nobs-studio\n"
            );
        }
        std::fs::remove_file(yay).unwrap();
        std::fs::remove_file(args_file).unwrap();
    }

    #[test]
    fn failure_never_allows_disabling_autostart_and_running_cannot_finish() {
        assert!(!InstallState::Running.can_finish());
        for state in [
            InstallState::Idle,
            InstallState::Running,
            InstallState::Failed,
        ] {
            assert!(!state.can_disable_autostart());
        }
        assert!(InstallState::Failed.can_finish());
        assert!(InstallState::Complete.can_disable_autostart());
    }

    #[test]
    fn autostart_is_reversible_and_reports_write_errors_in_a_temporary_home() {
        let sandbox = InstallReport::new().unwrap();
        write_autostart(&sandbox.directory, true).unwrap();
        assert!(
            sandbox
                .directory
                .join("autostart/churros-tour.desktop")
                .is_file()
        );
        write_autostart(&sandbox.directory, false).unwrap();
        write_autostart(&sandbox.directory, false).unwrap();
        std::fs::remove_dir(sandbox.directory.join("autostart")).unwrap();
        std::fs::write(sandbox.path(), "not a directory").unwrap();
        assert!(write_autostart(&sandbox.path(), true).is_err());
    }
}
