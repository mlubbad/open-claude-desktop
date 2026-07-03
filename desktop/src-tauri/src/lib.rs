// Tauri v2 entry. Kept minimal for the foundation slice: it hosts the built React
// client in a native WebView. Later phases add the system tray, a global summon
// hotkey, the auto-updater, deep links, and OS-keychain access via Tauri plugins,
// plus the FastAPI backend as a bundled sidecar.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running Open Claude Desktop");
}
