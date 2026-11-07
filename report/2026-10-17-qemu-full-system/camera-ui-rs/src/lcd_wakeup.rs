use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime};

use eframe::egui;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;

const POLL_INTERVAL: Duration = Duration::from_millis(8);

#[derive(PartialEq, Eq)]
struct FileToken {
    modified: SystemTime,
    len: u64,
    #[cfg(unix)]
    inode: u64,
}

impl FileToken {
    fn read(path: &Path) -> io::Result<Self> {
        let metadata = fs::metadata(path)?;
        Ok(Self {
            modified: metadata.modified()?,
            len: metadata.len(),
            #[cfg(unix)]
            inode: metadata.ino(),
        })
    }
}

/// Owns one metadata watcher; dropping it stops and joins its worker.
pub struct LcdWakeup {
    stop: Sender<()>,
    worker: Option<JoinHandle<()>>,
}

impl LcdWakeup {
    pub fn new(path: &Path, ctx: egui::Context) -> io::Result<Self> {
        Self::with_notify(path.to_owned(), move || ctx.request_repaint())
    }

    fn with_notify(path: PathBuf, notify: impl Fn() + Send + 'static) -> io::Result<Self> {
        let (stop, receiver) = mpsc::channel();
        let worker = thread::Builder::new()
            .name("lcd-wakeup".into())
            .spawn(move || {
                let mut previous = None;
                // shortcut: bounded metadata polling until native watcher justified.
                loop {
                    match FileToken::read(&path) {
                        Ok(token) => {
                            if previous.as_ref() != Some(&token) {
                                previous = Some(token);
                                notify();
                            }
                        }
                        Err(_) => previous = None,
                    }
                    match receiver.recv_timeout(POLL_INTERVAL) {
                        Err(RecvTimeoutError::Timeout) => {}
                        Ok(()) | Err(RecvTimeoutError::Disconnected) => break,
                    }
                }
            })?;
        Ok(Self {
            stop,
            worker: Some(worker),
        })
    }
}

impl Drop for LcdWakeup {
    fn drop(&mut self) {
        let _ = self.stop.send(());
        if let Some(worker) = self.worker.take() {
            if let Err(panic) = worker.join() {
                std::panic::resume_unwind(panic);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc::{Receiver, RecvTimeoutError, TryRecvError};
    use std::time::UNIX_EPOCH;

    const WAIT: Duration = Duration::from_secs(2);
    const QUIET: Duration = Duration::from_millis(40);

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "camui-lcd-wakeup-{}-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos(),
                NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }

        fn frame(&self) -> PathBuf {
            self.0.join("live.ppm")
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    fn publish(path: &Path, bytes: &[u8]) {
        let temporary = path.with_extension("tmp");
        fs::write(&temporary, bytes).unwrap();
        fs::rename(temporary, path).unwrap();
    }

    fn watch(path: &Path) -> (LcdWakeup, Receiver<()>) {
        let (sender, receiver) = mpsc::channel();
        let worker = LcdWakeup::with_notify(path.to_owned(), move || {
            let _ = sender.send(());
        })
        .unwrap();
        (worker, receiver)
    }

    #[test]
    fn existing_frame_and_atomic_updates_wake_once_each() {
        let directory = TempDir::new();
        let path = directory.frame();
        publish(&path, b"first");
        let (worker, wakes) = watch(&path);
        wakes.recv_timeout(WAIT).unwrap();
        assert_eq!(wakes.recv_timeout(QUIET), Err(RecvTimeoutError::Timeout));

        publish(&path, b"second, different length");
        wakes.recv_timeout(WAIT).unwrap();
        assert_eq!(wakes.recv_timeout(QUIET), Err(RecvTimeoutError::Timeout));
        drop(worker);
        assert_eq!(wakes.try_recv(), Err(TryRecvError::Disconnected));
    }

    #[test]
    fn missing_file_stays_quiet_and_creation_or_reappearance_wakes() {
        let directory = TempDir::new();
        let path = directory.frame();
        let (worker, wakes) = watch(&path);
        assert_eq!(wakes.recv_timeout(QUIET), Err(RecvTimeoutError::Timeout));

        publish(&path, b"frame");
        wakes.recv_timeout(WAIT).unwrap();
        fs::remove_file(&path).unwrap();
        assert_eq!(wakes.recv_timeout(QUIET), Err(RecvTimeoutError::Timeout));
        publish(&path, b"frame");
        wakes.recv_timeout(WAIT).unwrap();
        assert_eq!(wakes.recv_timeout(QUIET), Err(RecvTimeoutError::Timeout));
        drop(worker);
        assert_eq!(wakes.try_recv(), Err(TryRecvError::Disconnected));
    }

    #[cfg(unix)]
    #[test]
    fn atomic_replacement_wakes_for_new_inode_with_identical_mtime_length_and_bytes() {
        let directory = TempDir::new();
        let path = directory.frame();
        publish(&path, b"same bytes");
        let original = fs::metadata(&path).unwrap();
        let (worker, wakes) = watch(&path);
        wakes.recv_timeout(WAIT).unwrap();

        let replacement = path.with_extension("tmp");
        fs::write(&replacement, b"same bytes").unwrap();
        fs::File::options()
            .write(true)
            .open(&replacement)
            .unwrap()
            .set_modified(original.modified().unwrap())
            .unwrap();
        let metadata = fs::metadata(&replacement).unwrap();
        assert_eq!(metadata.modified().unwrap(), original.modified().unwrap());
        assert_eq!(metadata.len(), original.len());
        assert_ne!(metadata.ino(), original.ino());
        fs::rename(replacement, &path).unwrap();

        wakes.recv_timeout(WAIT).unwrap();
        assert_eq!(wakes.recv_timeout(QUIET), Err(RecvTimeoutError::Timeout));
        drop(worker);
        assert_eq!(wakes.try_recv(), Err(TryRecvError::Disconnected));
    }

    #[test]
    fn drop_joins_each_owned_worker_and_releases_its_callback() {
        let directory = TempDir::new();
        for _ in 0..16 {
            let (worker, wakes) = watch(&directory.frame());
            assert_eq!(
                worker.worker.as_ref().unwrap().thread().name(),
                Some("lcd-wakeup")
            );
            drop(worker);
            assert_eq!(wakes.try_recv(), Err(TryRecvError::Disconnected));
        }
    }

    #[test]
    fn worker_panic_is_propagated_by_drop() {
        let directory = TempDir::new();
        let path = directory.frame();
        publish(&path, b"frame");
        let (sender, receiver) = mpsc::channel();
        let worker = LcdWakeup::with_notify(path, move || {
            sender.send(()).unwrap();
            panic!("lcd notify panic");
        })
        .unwrap();
        receiver.recv_timeout(WAIT).unwrap();
        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(worker)))
            .expect_err("worker panic must not be swallowed");
        assert_eq!(panic.downcast_ref::<&str>(), Some(&"lcd notify panic"));
    }
}
