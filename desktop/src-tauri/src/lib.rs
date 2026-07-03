// Tauri v2 entry. Hosts the built React client in a native WebView and wires the
// desktop-shell plugins. Deliberately kept to the minimal, high-confidence subset:
// plugin registration + single-instance focus. The system tray is a documented
// follow-up; the global summon hotkey and native notifications are driven from the
// frontend (src/platform.ts) via these plugins' JS APIs.
//
// NOTE: building this requires the Tauri prerequisites (Rust + platform WebView libs);
// see desktop/README.md.

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    // Single-instance: on a second launch, focus the existing window instead of
    // opening another (desktop only).
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
                let _ = window.show();
            }
        }));
    }

    builder
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .run(tauri::generate_context!())
        .expect("error while running Open Claude Desktop");
}
