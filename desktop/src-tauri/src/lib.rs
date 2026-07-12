// Tauri v2 entry. Hosts the built React client in a native WebView, wires the
// desktop-shell plugins, spawns the bundled backend sidecar, and adds a system tray.
//
// Building requires the Tauri prerequisites (Rust + platform WebView libs); see
// desktop/README.md.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WebviewWindow,
};

// Shell behavior the frontend drives at runtime (Settings → Desktop app). Close-to-
// tray defaults ON so a plain window-close never kills a running background task;
// the frontend re-applies the persisted preference on startup.
struct ShellPrefs {
    close_to_tray: AtomicBool,
}

impl Default for ShellPrefs {
    fn default() -> Self {
        Self { close_to_tray: AtomicBool::new(true) }
    }
}

#[tauri::command]
fn set_close_to_tray(state: tauri::State<'_, ShellPrefs>, enabled: bool) {
    state.close_to_tray.store(enabled, Ordering::Relaxed);
}

fn main_window(app: &tauri::AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window("main")
}

fn show_and_focus(app: &tauri::AppHandle) {
    if let Some(w) = main_window(app) {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn toggle_window(app: &tauri::AppHandle) {
    if let Some(w) = main_window(app) {
        if w.is_visible().unwrap_or(false) {
            let _ = w.hide();
        } else {
            show_and_focus(app);
        }
    }
}

// The Node runtime we ship next to the app executable (externalBin
// "binaries/ocd-node"), if this build bundled one. Handed to the backend as
// OCD_NODE so .mcpb extensions that launch `node` work on machines with no system
// Node install (P1-13). Named ocd-node, NOT node: the Linux .deb installs
// external binaries into /usr/bin, where a bare `node` would collide with the
// distro's nodejs package and abort the install.
fn bundled_node_path() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let name = if cfg!(windows) { "ocd-node.exe" } else { "ocd-node" };
    let p = exe.parent()?.join(name);
    p.is_file().then_some(p)
}

// Spawn the bundled backend (PyInstaller) as a sidecar and pipe its output to the log.
// A no-op in dev, where the sidecar binary isn't bundled and the backend runs separately.
fn spawn_backend(app: &tauri::AppHandle) {
    use tauri_plugin_shell::process::CommandEvent;
    use tauri_plugin_shell::ShellExt;

    let cmd = match app.shell().sidecar("ocd-backend") {
        Ok(c) => {
            let c = c.env("OCD_PORT", "8000").env("OCD_HOST", "127.0.0.1");
            match bundled_node_path() {
                Some(node) => c.env("OCD_NODE", node.to_string_lossy().to_string()),
                None => c,
            }
        }
        Err(_) => return, // not bundled (dev) — the dev backend runs on its own
    };
    match cmd.spawn() {
        Ok((mut rx, _child)) => {
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                            if let Ok(line) = String::from_utf8(bytes) {
                                eprintln!("[backend] {}", line.trim_end());
                            }
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] exited: {:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });
        }
        Err(e) => eprintln!("backend sidecar failed to start: {e}"),
    }
}

fn build_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show / Hide", true, None::<&str>)?;
    let new_chat = MenuItem::with_id(app, "new_chat", "New Chat", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &new_chat, &quit])?;

    let _tray = TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("bundled window icon"))
        .tooltip("Open Claude Desktop")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => toggle_window(app),
            "new_chat" => {
                show_and_focus(app);
                let _ = app.emit("tray://new-chat", ());
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_window(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    // Single-instance: on a second launch, focus the existing window instead of
    // opening another (desktop only). Registered first, per the plugin's guidance.
    // Autostart (launch at login) is desktop-only too; the frontend toggles it via
    // the plugin's JS API (Settings → Desktop app → Launch at login).
    #[cfg(desktop)]
    {
        builder = builder
            .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
                show_and_focus(app);
            }))
            .plugin(tauri_plugin_autostart::init(
                tauri_plugin_autostart::MacosLauncher::LaunchAgent,
                None,
            ));
    }

    builder
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(ShellPrefs::default())
        .invoke_handler(tauri::generate_handler![set_close_to_tray])
        // Close-to-tray: closing the main window hides it (the tray keeps the app —
        // and any running Cowork/scheduled work — alive). Quit lives in the tray
        // menu, and app.exit() there bypasses this handler by design.
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let prefs = window.app_handle().state::<ShellPrefs>();
                if window.label() == "main" && prefs.close_to_tray.load(Ordering::Relaxed) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            let handle = app.handle().clone();
            spawn_backend(&handle);
            build_tray(&handle)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Open Claude Desktop")
        .run(|_app, _event| {
            // macOS: after close-to-tray hides the window, clicking the Dock icon
            // fires Reopen — bring the window back (the tray isn't the only way in).
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = _event {
                show_and_focus(_app);
            }
        });
}
