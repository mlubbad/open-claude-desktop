// Tauri v2 entry. Hosts the built React client in a native WebView, wires the
// desktop-shell plugins, spawns the bundled backend sidecar, and adds a system tray.
//
// Building requires the Tauri prerequisites (Rust + platform WebView libs); see
// desktop/README.md.

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WebviewWindow,
};

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

// Spawn the bundled backend (PyInstaller) as a sidecar and pipe its output to the log.
// A no-op in dev, where the sidecar binary isn't bundled and the backend runs separately.
fn spawn_backend(app: &tauri::AppHandle) {
    use tauri_plugin_shell::process::CommandEvent;
    use tauri_plugin_shell::ShellExt;

    let cmd = match app.shell().sidecar("ocd-backend") {
        Ok(c) => c.env("OCD_PORT", "8000").env("OCD_HOST", "127.0.0.1"),
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
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_and_focus(app);
        }));
    }

    builder
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let handle = app.handle().clone();
            spawn_backend(&handle);
            build_tray(&handle)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Open Claude Desktop");
}
