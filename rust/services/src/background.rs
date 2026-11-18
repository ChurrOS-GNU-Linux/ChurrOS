// ==========================================
// deuda de UI: ejecutar trabajo bloqueante fuera del hilo de GTK
//
// Contexto (auditoría, issue A4): varios callbacks de la interfaz llamaban a
// `Command::status()` directamente. `.status()` espera a que el proceso
// termine; cuando ese proceso es `churros-pkexec`, espera además a que la
// persona teclee la contraseña de administrador en el diálogo de polkit.
// Durante ese tiempo el bucle principal de GTK está parado: la ventana no
// repinta y el compositor puede marcarla como «no responde».
//
// La forma correcta es lanzar el trabajo en un hilo y devolver el resultado
// por un canal que el hilo de UI vacía con glib::timeout_add_local. Eso ya se
// hace en pages/update.rs y pages/logs.rs; lo que faltaba era no repetir el
// patrón a mano en cada sitio.
// ==========================================

use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::thread;
use std::time::Duration;

/// Trabajo que corre en un hilo y publica su resultado.
///
/// `spawn` devuelve el receptor; el hilo de UI lo consulta sin bloquear con
/// `try_finish` desde un `glib::timeout_add_local`.
pub struct BackgroundJob<T> {
    receiver: Receiver<T>,
}

impl<T: Send + 'static> BackgroundJob<T> {
    /// Ejecuta `work` en un hilo aparte y devuelve el canal de resultado.
    ///
    /// Si el hilo entra en pánico el canal se cierra y `try_finish` devuelve
    /// `JobPoll::Disconnected`, para que la UI pueda rehabilitar el botón en
    /// vez de quedarse esperando para siempre.
    pub fn spawn<F>(work: F) -> Self
    where
        F: FnOnce() -> T + Send + 'static,
    {
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            // El receptor puede haberse ido (ventana cerrada): el envío falla
            // y no hay nada que hacer.
            let _ = sender.send(work());
        });
        Self { receiver }
    }

    /// Consulta sin bloquear.
    pub fn try_finish(&self) -> JobPoll<T> {
        match self.receiver.try_recv() {
            Ok(value) => JobPoll::Finished(value),
            Err(TryRecvError::Empty) => JobPoll::Pending,
            Err(TryRecvError::Disconnected) => JobPoll::Disconnected,
        }
    }
}

/// Estado de un trabajo en segundo plano.
#[derive(Debug, PartialEq, Eq)]
pub enum JobPoll<T> {
    Pending,
    Finished(T),
    /// El hilo terminó sin publicar nada: entró en pánico.
    Disconnected,
}

/// Intervalo con el que la UI consulta un trabajo en curso.
pub const POLL_INTERVAL: Duration = Duration::from_millis(100);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finishes_with_the_work_result() {
        let job = BackgroundJob::spawn(|| 42);
        let mut seen = JobPoll::Pending;
        for _ in 0..200 {
            seen = job.try_finish();
            if seen != JobPoll::Pending {
                break;
            }
            thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(seen, JobPoll::Finished(42));
    }

    /// Un pánico en el hilo no puede dejar la UI esperando para siempre.
    #[test]
    fn reports_disconnected_when_the_thread_panics() {
        let job: BackgroundJob<()> = BackgroundJob::spawn(|| panic!("fallo simulado"));
        let mut seen = JobPoll::Pending;
        for _ in 0..200 {
            seen = job.try_finish();
            if seen != JobPoll::Pending {
                break;
            }
            thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(seen, JobPoll::Disconnected);
    }

    #[test]
    fn pending_while_the_work_is_still_running() {
        let job = BackgroundJob::spawn(|| {
            thread::sleep(Duration::from_millis(150));
            1
        });
        assert_eq!(job.try_finish(), JobPoll::Pending);
        // No se espera al resultado aqui: el contrato es no bloquear.
    }

    #[test]
    fn polling_does_not_block() {
        let job = BackgroundJob::spawn(|| {
            thread::sleep(Duration::from_millis(300));
            7
        });
        let start = std::time::Instant::now();
        for _ in 0..5 {
            let _ = job.try_finish();
        }
        assert!(
            start.elapsed() < Duration::from_millis(250),
            "try_finish no puede bloquear al hilo de UI"
        );
    }
}
