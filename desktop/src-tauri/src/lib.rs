// Tauri v2 entry. Hosts the built React client in a native WebView, wires the
// desktop-shell plugins, spawns the bundled backend sidecar, and adds a system tray.
//
// Building requires the Tauri prerequisites (Rust + platform WebView libs); see
// desktop/README.md.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WebviewWindow,
};
use tauri_plugin_shell::process::CommandChild;

// What the sidecar needs to (re)start. Captured once and reused on every auto-restart so
// the API token keeps matching the one already injected into the webview.
struct BackendCfg {
    token: String,
    data_dir: Option<PathBuf>,
}

// State for the spawned backend sidecar: the live child (so we can terminate it on quit
// instead of orphaning it — an orphan holds the port and breaks the next launch), plus
// the plumbing for auto-restart (config to respawn with, a shutdown flag so we don't
// respawn a sidecar we killed on purpose, and a crash budget so a sidecar that dies on
// boot doesn't respawn forever).
#[derive(Default)]
struct Backend {
    child: Mutex<Option<CommandChild>>,
    shutting_down: AtomicBool,
    restarts: Mutex<(u32, Option<Instant>)>, // (count in window, window start)
    cfg: Mutex<Option<BackendCfg>>,
}

fn kill_backend(app: &tauri::AppHandle) {
    let st = app.state::<Backend>();
    st.shutting_down.store(true, Ordering::SeqCst); // stop the auto-restart loop
    if let Some(child) = st.child.lock().ok().and_then(|mut g| g.take()) {
        let _ = child.kill();
    }
}

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
//
// Hands the sidecar three things beyond stdio: a STABLE per-user data dir
// (AJ360_DATA_DIR) so a frozen build doesn't write into its ephemeral temp-extraction
// dir and lose everything on restart; the per-launch API token (OCD_API_TOKEN) that
// gates the loopback API against drive-by web requests; and the bundled Node path.
fn spawn_backend(app: &tauri::AppHandle, token: &str, data_dir: Option<PathBuf>) {
    // Record the launch config so an auto-restart reuses the SAME token (the webview's
    // injected window.__OCD_API_TOKEN__ must keep matching) and data dir.
    if let Ok(mut cfg) = app.state::<Backend>().cfg.lock() {
        *cfg = Some(BackendCfg { token: token.to_string(), data_dir });
    }
    do_spawn_backend(app);
}

// Actually launch the sidecar from the recorded config, wiring its output to the log and
// its termination to the auto-restart path. A no-op in dev (no bundled sidecar / no cfg).
fn do_spawn_backend(app: &tauri::AppHandle) {
    use tauri_plugin_shell::process::CommandEvent;
    use tauri_plugin_shell::ShellExt;

    let (token, data_dir) = match app.state::<Backend>().cfg.lock() {
        Ok(g) => match &*g {
            Some(c) => (c.token.clone(), c.data_dir.clone()),
            None => return,
        },
        Err(_) => return,
    };

    let cmd = match app.shell().sidecar("ocd-backend") {
        Ok(c) => {
            let mut c = c
                .env("OCD_PORT", "8000")
                .env("OCD_HOST", "127.0.0.1")
                .env("OCD_API_TOKEN", token);
            if let Some(dir) = data_dir {
                c = c.env("AJ360_DATA_DIR", dir.to_string_lossy().to_string());
            }
            match bundled_node_path() {
                Some(node) => c.env("OCD_NODE", node.to_string_lossy().to_string()),
                None => c,
            }
        }
        Err(_) => return, // not bundled (dev) — the dev backend runs on its own
    };
    match cmd.spawn() {
        Ok((mut rx, child)) => {
            // Keep the child so we can kill it on quit (see kill_backend).
            if let Ok(mut guard) = app.state::<Backend>().child.lock() {
                *guard = Some(child);
            }
            let app = app.clone();
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
                            maybe_restart_backend(&app);
                        }
                        _ => {}
                    }
                }
            });
        }
        Err(e) => eprintln!("backend sidecar failed to start: {e}"),
    }
}

// Respawn a sidecar that died on its own — unless we're quitting (we killed it), or it
// has already crashed too many times in a short window (a boot-time crash must not
// respawn forever; give up and leave the frontend's "backend unreachable" banner up).
fn maybe_restart_backend(app: &tauri::AppHandle) {
    let st = app.state::<Backend>();
    if st.shutting_down.load(Ordering::SeqCst) {
        return;
    }
    const MAX_RESTARTS: u32 = 5;
    let allowed = match st.restarts.lock() {
        Ok(mut g) => {
            let now = Instant::now();
            let fresh = g
                .1
                .map(|start| now.duration_since(start) < Duration::from_secs(60))
                .unwrap_or(false);
            if fresh {
                if g.0 >= MAX_RESTARTS {
                    false
                } else {
                    g.0 += 1;
                    true
                }
            } else {
                *g = (1, Some(now));
                true
            }
        }
        Err(_) => false,
    };
    if allowed {
        eprintln!("[backend] sidecar died — restarting");
        do_spawn_backend(app);
    } else {
        eprintln!("[backend] sidecar crashed repeatedly — not restarting");
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
        .manage(Backend::default())
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

            // Per-launch loopback API token (S / B3b). Minted here, handed to the
            // sidecar as OCD_API_TOKEN, and injected into the webview as
            // window.__OCD_API_TOKEN__ so the frontend can echo it back as X-OCD-Token.
            // A drive-by web page can reach 127.0.0.1:8000 but can't read this value,
            // so its requests 401. 64 hex chars (two v4 UUIDs) of entropy.
            let token = format!(
                "{}{}",
                uuid::Uuid::new_v4().simple(),
                uuid::Uuid::new_v4().simple()
            );

            // Stable per-user data dir (B1) so a frozen build persists across restarts
            // instead of writing into its ephemeral PyInstaller extraction dir. In dev
            // (no bundle) this resolves too, but spawn_backend is a no-op there and the
            // dev backend picks its own root, so it's harmless.
            let data_dir = app.path().app_data_dir().ok();

            spawn_backend(&handle, &token, data_dir);

            // Hand the token to the webview before it can issue API calls. The frontend
            // reads window.__OCD_API_TOKEN__ (desktop/src/api/client.ts) on first use.
            if let Some(w) = main_window(&handle) {
                let _ = w.eval(&format!("window.__OCD_API_TOKEN__={};", serde_json::to_string(&token).unwrap_or_else(|_| "\"\"".into())));
            }

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
            // On real quit, reap the backend sidecar so it doesn't outlive the shell
            // (an orphan keeps port 8000 and breaks the next launch).
            if let tauri::RunEvent::Exit = _event {
                kill_backend(_app);
            }
        });
}
