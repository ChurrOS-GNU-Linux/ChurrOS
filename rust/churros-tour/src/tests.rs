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
    let completed = Rc::new(Cell::new(None));
    let copy = completed.clone();
    install.start(page.packages(), move |success| copy.set(Some(success)));
    assert_eq!(completed.get(), Some(true));
    install.finish(true).unwrap();
    assert!(!autostart.exists()); // Preview never modifies host/autostart.

    // Real execution path, but both terminal and package manager are local fakes.
    // Only this single-threaded, explicitly opted-in test changes its environment.
    let bin = home.join("fake-bin");
    std::fs::create_dir(&bin).unwrap();
    let terminal = "#!/bin/sh\nwhile [ \"$1\" != sh ]; do [ $# -gt 0 ] || exit 125; shift; done\nshift\nexec /bin/sh \"$@\" </dev/null\n";
    for name in ["foot", "konsole", "xfce4-terminal", "xterm"] {
        let path = bin.join(name);
        std::fs::write(&path, terminal).unwrap();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    let yay = bin.join("yay");
    std::fs::write(
        &yay,
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TOUR_TEST_ARGS\"\nexit \"$TOUR_TEST_EXIT\"\n",
    )
    .unwrap();
    std::fs::set_permissions(&yay, std::fs::Permissions::from_mode(0o700)).unwrap();
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
        while completed.get().is_none() && Instant::now() < deadline {
            while context.pending() {
                context.iteration(false);
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(completed.get(), Some(code == 0));
        assert!(!install.is_running());
        install.finish(false).unwrap();
        assert_eq!(autostart.exists(), code != 0);
        assert_eq!(
            std::fs::read_to_string(&args_file).unwrap(),
            "-Syu\n--needed\n--\nfirefox\nobs-studio\n"
        );
    }
    // A terminal that exits successfully without running the shell must not
    // turn a missing yay report into a completed installation.
    for name in ["foot", "konsole", "xfce4-terminal", "xterm"] {
        std::fs::write(bin.join(name), "#!/bin/sh\nexit 0\n").unwrap();
    }
    let completed = Rc::new(Cell::new(None));
    let copy = completed.clone();
    install.start(vec!["firefox".into()], move |success| {
        copy.set(Some(success))
    });
    let context = glib::MainContext::default();
    let deadline = Instant::now() + Duration::from_secs(5);
    while completed.get().is_none() && Instant::now() < deadline {
        while context.pending() {
            context.iteration(false);
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(completed.get(), Some(false));
    install.finish(false).unwrap();
    assert!(autostart.exists());

    // Simulate a terminal startup error without falling back to a real terminal.
    let which = bin.join("which");
    std::fs::write(&which, "#!/bin/sh\nexit 1\n").unwrap();
    std::fs::set_permissions(&which, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::remove_file(bin.join("xterm")).unwrap();
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
