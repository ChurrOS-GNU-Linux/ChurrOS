use super::*;
use std::cell::{Cell, RefCell};
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::rc::Rc;
use std::time::{Duration, Instant};

fn descendants(widget: &gtk::Widget, output: &mut Vec<gtk::Widget>) {
    output.push(widget.clone());
    let mut child = widget.first_child();
    while let Some(current) = child {
        descendants(&current, output);
        child = current.next_sibling();
    }
}

#[test]
#[ignore = "Needs an isolated GTK display, temporary HOME and --test-threads=1; uses only fake terminal/yay"]
fn gtk_selection_preview_and_installation_failures() {
    gtk::init().expect("GTK display required");
    let home =
        PathBuf::from(std::env::var_os("TOUR_TEST_HOME").expect("temporary test home required"));
    assert!(home.starts_with("/tmp"));
    assert_eq!(
        std::env::var_os("HOME"),
        Some(home.clone().into_os_string())
    );
    assert!(std::env::var_os("CHURROS_TOUR_PREVIEW").is_some());
    let autostart = home.join(".config/autostart/churros-tour.desktop");
    assert!(!autostart.exists());

    let page = pages::customization::build();
    let mut widgets = Vec::new();
    descendants(page.root.upcast_ref(), &mut widgets);
    let profile = widgets
        .iter()
        .find_map(|w| w.clone().downcast::<gtk::DropDown>().ok())
        .unwrap();
    let checks: Vec<_> = widgets
        .iter()
        .filter_map(|w| w.clone().downcast::<gtk::CheckButton>().ok())
        .collect();
    let expanders: Vec<_> = widgets
        .iter()
        .filter_map(|w| w.clone().downcast::<gtk::Expander>().ok())
        .collect();
    assert_eq!(checks.len(), 37);
    assert_eq!(expanders.len(), 6);
    assert!(expanders.iter().all(|e| e.is_expanded()));
    for (index, preset) in churros_tour::catalog::PRESETS.iter().enumerate().skip(1) {
        profile.set_selected(index as u32);
        let mut expected: Vec<_> = preset.iter().map(|s| s.to_string()).collect();
        expected.sort();
        assert_eq!(page.packages(), expected);
        profile.set_selected(0);
        assert_eq!(page.packages(), expected); // Custom preserves the preset.
    }
    for check in &checks {
        check.set_active(false);
    }
    assert!(page.packages().is_empty());
    profile.set_selected(2); // Gaming; individual edit becomes custom.
    checks[0].set_active(true);
    assert_eq!(profile.selected(), 0);
    assert_eq!(page.packages().len(), 6);
    for check in &checks {
        check.set_active(true);
    }
    assert_eq!(page.packages().len(), 37);
    checks[0].set_active(false);
    assert_eq!(page.packages().len(), 36);
    assert!(pages::customization::build().packages().is_empty());

    let install = pages::install::build();
    let mut install_widgets = Vec::new();
    descendants(install.root.upcast_ref(), &mut install_widgets);
    let progress = install_widgets
        .iter()
        .find_map(|w| w.clone().downcast::<gtk::ProgressBar>().ok())
        .unwrap();
    let completed = Rc::new(Cell::new(None));
    let copy = completed.clone();
    install.start(page.packages(), move |success| copy.set(Some(success)));
    assert_eq!(completed.get(), Some(true));
    install.finish(true).unwrap();
    assert!(!autostart.exists()); // Preview never modifies host/autostart.

    // Real execution path, but package manager is a local fake.
    // Only this single-threaded, explicitly opted-in test changes its environment.
    let bin = home.join("fake-bin");
    std::fs::create_dir(&bin).unwrap();
    let yay = bin.join("yay");
    std::fs::write(
        &yay,
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TOUR_TEST_ARGS\"\nprintf 'Downloading 25%%\\r'\nsleep 0.3\nprintf 'final detail without newline'\nexit \"$TOUR_TEST_EXIT\"\n",
    )
    .unwrap();
    std::fs::set_permissions(&yay, std::fs::Permissions::from_mode(0o700)).unwrap();
    let sh = bin.join("sh");
    std::fs::write(&sh, "#!/bin/sh\nexec /bin/sh \"$@\"\n").unwrap();
    std::fs::set_permissions(&sh, std::fs::Permissions::from_mode(0o700)).unwrap();
    let terminals = [bin.join("foot"), bin.join("xfce4-terminal")];
    for terminal in &terminals {
        std::fs::write(terminal, "#!/bin/sh\ncase \"$1\" in -e) shift ;; --disable-server) shift; [ \"$1\" = --execute ] || exit 99; shift ;; *) exit 98 ;; esac\nexec \"$@\"\n").unwrap();
        std::fs::set_permissions(terminal, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    // Never let the preparation commands use the host's package manager or keyring.
    for name in ["sudo", "git", "gpg"] {
        let path = bin.join(name);
        std::fs::write(&path, "#!/bin/sh\nexit 0\n").unwrap();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    let args_file = home.join("args");
    unsafe {
        std::env::remove_var("CHURROS_TOUR_PREVIEW");
        std::env::set_var("PATH", format!("{}:/usr/bin", bin.display()));
        std::env::set_var("TOUR_TEST_ARGS", &args_file);
    }
    for code in [1, 42, 130, 0] {
        unsafe {
            std::env::set_var("TOUR_TEST_EXIT", code.to_string());
        }
        let completed = Rc::new(Cell::new(None));
        let copy = completed.clone();
        install.start(
            vec!["firefox".into(), "obs-studio".into()],
            move |success| copy.set(Some(success)),
        );
        assert!(install.is_running());
        assert!(install.finish(false).is_err());
        assert!(autostart.exists());
        let deadline = Instant::now() + Duration::from_secs(5);
        let context = glib::MainContext::default();
        let mut saw_progress = false;
        while completed.get().is_none() && Instant::now() < deadline {
            while context.pending() {
                context.iteration(false);
            }
            saw_progress |= (progress.fraction() - 0.125).abs() < 0.001;
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(saw_progress, "incremental CR-delimited progress must reach GTK");
        assert_eq!(completed.get(), Some(code == 0));
        if code != 0 {
            assert!(install_widgets.iter().any(|widget| {
                widget.clone().downcast::<gtk::Label>().is_ok_and(|label| {
                    label.text().contains("final detail without newline")
                })
            }), "the final unterminated error line must be drained before reporting failure");
        }
        assert!(!install.is_running());
        install.finish(false).unwrap();
        assert_eq!(autostart.exists(), code != 0);
        let expected_args = if code == 0 {
            "-S\n--needed\n--noconfirm\n--mflags\n--skippgpcheck\n--answerclean\nNone\n--answerdiff\nNone\n--\nobs-studio\n"
        } else {
            "-S\n--needed\n--noconfirm\n--mflags\n--skippgpcheck\n--answerclean\nNone\n--answerdiff\nNone\n--\nfirefox\n"
        };
        assert_eq!(
            std::fs::read_to_string(&args_file).unwrap(),
            expected_args
        );
    }

    // A terminal that closes without a report must never count as success,
    // even if its own exit status is zero.
    for body in ["#!/bin/sh\nexit 0\n", "#!/bin/sh\nkill -TERM \"$$\"\n"] {
        for terminal in &terminals {
            std::fs::write(terminal, body).unwrap();
        }
        let completed = Rc::new(Cell::new(None));
        let copy = completed.clone();
        install.start(vec!["firefox".into()], move |success| copy.set(Some(success)));
        let deadline = Instant::now() + Duration::from_secs(5);
        let context = glib::MainContext::default();
        while completed.get().is_none() && Instant::now() < deadline {
            while context.pending() {
                context.iteration(false);
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(completed.get(), Some(false));
        install.finish(false).unwrap();
        assert!(autostart.exists());
    }
    for terminal in &terminals {
        std::fs::remove_file(terminal).unwrap();
    }
    unsafe {
        std::env::set_var("PATH", &bin);
    }
    let completed = Rc::new(Cell::new(None));
    let copy = completed.clone();
    install.start(vec!["firefox".into()], move |success| copy.set(Some(success)));
    assert_eq!(completed.get(), Some(false));
    install.finish(false).unwrap();
    assert!(autostart.exists());

    // Restore fake terminals so yay presence would actually start the background process
    // instead of failing early on missing terminal.
    for terminal in &terminals {
        std::fs::write(
            terminal,
            "#!/bin/sh\ncase \"$1\" in -e) shift ;; --disable-server) shift; [ \"$1\" = --execute ] || exit 99; shift ;; *) exit 98 ;; esac\nexec \"$@\"\n",
        )
        .unwrap();
        std::fs::set_permissions(terminal, std::fs::Permissions::from_mode(0o700)).unwrap();
    }

    // Simulate yay startup error without falling back to a real package manager.
    // churros_services::which() looks for PATH/<bin> (it never runs `which`),
    // so fake yay has to go: with it present, start() spawns it
    // asynchronously and the synchronous assert below sees None.
    std::fs::remove_file(&yay).unwrap();
    unsafe {
        std::env::set_var("PATH", &bin);
    }
    let result = Rc::new(RefCell::new(None));
    let copy = result.clone();
    install.start(vec!["firefox".into()], move |success| {
        *copy.borrow_mut() = Some(success)
    });
    assert_eq!(*result.borrow(), Some(false));
    install.finish(false).unwrap();
    assert!(autostart.exists());
}
