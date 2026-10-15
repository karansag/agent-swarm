use crate::{Attention, HubUrl, Settings};
use serde::Serialize;
use std::{path::PathBuf, sync::Mutex};
use tauri::{
    image::Image,
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    webview::NewWindowResponse,
    AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    WindowEvent,
};
use tauri_plugin_notification::NotificationExt;

struct AppState {
    hub: Option<HubUrl>,
    settings_path: PathBuf,
    settings_error: Option<String>,
    last_url: Mutex<Option<tauri::Url>>,
    attention: Mutex<Attention>,
}

impl AppState {
    fn dashboard_url(&self) -> Option<tauri::Url> {
        self.hub.as_ref().map(|hub| {
            self.last_url
                .lock()
                .ok()
                .and_then(|last| last.clone())
                .filter(|url| hub.allows(url))
                .unwrap_or_else(|| hub.url().clone())
        })
    }
}

fn remember_route(window: &WebviewWindow) {
    let state = window.state::<AppState>();
    let (Some(hub), Ok(url)) = (&state.hub, window.url()) else {
        return;
    };
    if !hub.allows(&url) {
        return;
    }
    let Ok(mut last) = state.last_url.lock() else {
        return;
    };
    if last.as_ref() == Some(&url) {
        return;
    }
    // WKWebView.URL().absoluteString includes same-document hash changes;
    // navigation callbacks alone would miss those changes.
    *last = Some(url.clone());
    if let Err(error) = Settings::save(&state.settings_path, hub, Some(&url)) {
        eprintln!("Could not save last dashboard page: {error}");
    }
}

// Defense in depth alongside the local-only setup capability. The remote
// dashboard can never invoke settings commands, even after a navigation.
fn require_setup(window: &WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if window.label() == "main" && url.scheme() == "tauri" && url.host_str() == Some("localhost") {
        Ok(())
    } else {
        Err("This command is only available on the bundled setup page".into())
    }
}

#[derive(Serialize)]
struct SetupInfo {
    hub_url: Option<String>,
    error: Option<String>,
}

#[tauri::command]
fn setup_info(window: WebviewWindow, state: State<AppState>) -> Result<SetupInfo, String> {
    require_setup(&window)?;
    Ok(SetupInfo {
        hub_url: state.hub.as_ref().map(|hub| hub.url().to_string()),
        error: state.settings_error.clone(),
    })
}

#[tauri::command]
fn save_hub(
    app: AppHandle,
    window: WebviewWindow,
    state: State<AppState>,
    url: String,
) -> Result<(), String> {
    require_setup(&window)?;
    let hub = HubUrl::parse(&url)?;
    if state
        .hub
        .as_ref()
        .is_some_and(|current| current.url() == hub.url())
    {
        if let Some(url) = state.dashboard_url() {
            Settings::save(&state.settings_path, &hub, Some(&url))?;
            window.navigate(url).map_err(|error| error.to_string())?;
        }
        return Ok(());
    }
    Settings::save(&state.settings_path, &hub, None)?;
    // Capabilities added at runtime cannot be removed. A fresh runtime drops
    // the old origin's grant rather than accumulating grants as URLs change.
    app.restart();
}

#[tauri::command]
fn open_dashboard(window: WebviewWindow, state: State<AppState>) -> Result<(), String> {
    require_setup(&window)?;
    if let Some(url) = state.dashboard_url() {
        window.navigate(url).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn attention(
    app: AppHandle,
    window: WebviewWindow,
    state: State<AppState>,
    agents: Vec<String>,
) -> Result<(), String> {
    let current_url = window.url().map_err(|e| e.to_string())?;
    if window.label() != "main"
        || !state
            .hub
            .as_ref()
            .is_some_and(|hub| hub.allows(&current_url))
    {
        return Err("Attention updates must come from the selected hub".into());
    }
    let mut tracker = state
        .attention
        .lock()
        .map_err(|_| "Attention state is unavailable")?;
    // Validate/diff before applying, but keep the previous state if the badge
    // fails: the page retries rejected invocations on its next poll.
    let mut next = tracker.clone();
    let (count, added) = next.update(agents)?;
    if let Err(error) = window.set_badge_count(if count == 0 { None } else { Some(count as i64) }) {
        return Err(error.to_string());
    }
    *tracker = next;
    for name in added {
        if let Err(error) = app
            .notification()
            .builder()
            .title("Agent needs attention")
            .body(format!("{name} is waiting for you."))
            .show()
        {
            // Notification delivery is best effort (e.g. OS permission denied).
            // Do not reject an applied list and spam repeats on every poll.
            eprintln!("Could not notify about {name}: {error}");
        }
    }
    Ok(())
}

fn show_dashboard(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        let state = app.state::<AppState>();
        if let Some(hub) = &state.hub {
            // Preserve an existing agent route when opening a hidden window.
            if !window.url().is_ok_and(|url| hub.allows(&url)) {
                if let Some(url) = state.dashboard_url() {
                    let _ = window.navigate(url);
                }
            }
        }
    }
}

fn show_setup(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        remember_route(&window);
        let _ = window.navigate(tauri::Url::parse("tauri://localhost/index.html").unwrap());
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn menu_action(app: &AppHandle, id: &str) {
    match id {
        "dashboard" => show_dashboard(app),
        "change-hub" => show_setup(app),
        "quit" => {
            if let Some(window) = app.get_webview_window("main") {
                remember_route(&window);
            }
            app.exit(0);
        }
        _ => (),
    }
}

fn open_in_browser(url: &tauri::Url) {
    if matches!(url.scheme(), "https" | "http") {
        // Fixed executable, no shell, no custom/file schemes. An ordinary link
        // opens in the user's browser instead of another privileged webview.
        if let Err(error) = std::process::Command::new("/usr/bin/open")
            .arg(url.as_str())
            .spawn()
        {
            eprintln!("Could not open link in browser: {error}");
        }
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            show_dashboard(app)
        }))
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            attention,
            setup_info,
            save_hub,
            open_dashboard
        ])
        .setup(|app| {
            let settings_path = app.path().app_config_dir()?.join("settings.json");
            let loaded = Settings::load(&settings_path);
            let saved_last = loaded
                .as_ref()
                .ok()
                .and_then(|settings| settings.last_url.clone());
            let (hub, settings_error) = match loaded {
                Ok(settings) => match settings.hub_url {
                    Some(url) => match HubUrl::parse(&url) {
                        Ok(hub) => (Some(hub), None),
                        Err(error) => (None, Some(error)),
                    },
                    None => (None, None),
                },
                Err(error) => (None, Some(error)),
            };
            if let Some(hub) = &hub {
                // Exact scheme/host/port, all dashboard routes, only attention.
                // All custom commands are declared in AppManifest in build.rs
                // so no command silently bypasses Tauri's capability system.
                app.add_capability(
                    tauri::ipc::CapabilityBuilder::new("selected-hub")
                        .window("main")
                        .local(false)
                        .remote(hub.origin_pattern())
                        .permission("allow-attention"),
                )?;
            }
            let restored = hub.as_ref().map(|hub| hub.restore(saved_last.as_deref()));
            let start = restored
                .as_ref()
                .map(|url| WebviewUrl::External(url.clone()))
                .unwrap_or_else(|| WebviewUrl::App("index.html".into()));
            let navigation_hub = hub.clone();
            let initial_size = if hub.is_some() {
                (1240.0, 860.0)
            } else {
                (640.0, 620.0)
            };
            app.manage(AppState {
                hub,
                settings_path,
                settings_error,
                last_url: Mutex::new(restored),
                attention: Mutex::default(),
            });
            let window = WebviewWindowBuilder::new(app, "main", start)
                .title("Agent Swarm")
                .inner_size(initial_size.0, initial_size.1)
                .min_inner_size(420.0, 480.0)
                .background_throttling(tauri::utils::config::BackgroundThrottlingPolicy::Disabled)
                .disable_drag_drop_handler()
                .on_navigation(move |url| {
                    let allowed = (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
                        || navigation_hub.as_ref().is_some_and(|hub| hub.allows(url));
                    if !allowed {
                        open_in_browser(url);
                    }
                    allowed
                })
                // External links must not create extra privileged app windows.
                .on_new_window(|url, _| {
                    open_in_browser(&url);
                    NewWindowResponse::Deny
                })
                .build()?;
            window.on_window_event({
                let window = window.clone();
                move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        remember_route(&window);
                        api.prevent_close();
                        let _ = window.hide();
                    }
                    if let WindowEvent::Focused(false) = event {
                        remember_route(&window);
                    }
                }
            });

            let dashboard = MenuItem::with_id(
                app,
                "dashboard",
                "Open dashboard",
                true,
                Some("CmdOrCtrl+1"),
            )?;
            let change_hub = MenuItem::with_id(
                app,
                "change-hub",
                "Change hub URL…",
                true,
                Some("CmdOrCtrl+,"),
            )?;
            let quit =
                MenuItem::with_id(app, "quit", "Quit Agent Swarm", true, Some("CmdOrCtrl+Q"))?;
            let tray_menu = Menu::with_items(
                app,
                &[
                    &dashboard,
                    &change_hub,
                    &PredefinedMenuItem::separator(app)?,
                    &quit,
                ],
            )?;
            TrayIconBuilder::with_id("swarm")
                .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .icon_as_template(true)
                .tooltip("Agent Swarm")
                .menu(&tray_menu)
                .build(app)?;

            let app_menu = Submenu::with_items(
                app,
                "Agent Swarm",
                true,
                &[
                    &PredefinedMenuItem::about(app, Some("About Agent Swarm"), None)?,
                    &PredefinedMenuItem::separator(app)?,
                    &dashboard,
                    &change_hub,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::hide(app, None)?,
                    &PredefinedMenuItem::hide_others(app, None)?,
                    &PredefinedMenuItem::show_all(app, None)?,
                    &PredefinedMenuItem::separator(app)?,
                    &quit,
                ],
            )?;
            let edit_menu = Submenu::with_items(
                app,
                "Edit",
                true,
                &[
                    &PredefinedMenuItem::undo(app, None)?,
                    &PredefinedMenuItem::redo(app, None)?,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::cut(app, None)?,
                    &PredefinedMenuItem::copy(app, None)?,
                    &PredefinedMenuItem::paste(app, None)?,
                    &PredefinedMenuItem::select_all(app, None)?,
                ],
            )?;
            let window_menu = Submenu::with_items(
                app,
                "Window",
                true,
                &[
                    &PredefinedMenuItem::minimize(app, None)?,
                    &PredefinedMenuItem::close_window(app, None)?,
                ],
            )?;
            app.set_menu(Menu::with_items(
                app,
                &[&app_menu, &edit_menu, &window_menu],
            )?)?;
            Ok(())
        })
        .on_menu_event(|app, event| menu_action(app, event.id.as_ref()))
        .build(tauri::generate_context!())
        .expect("could not start Agent Swarm");

    app.run(|app, event| {
        if let RunEvent::ExitRequested { .. } = event {
            if let Some(window) = app.get_webview_window("main") {
                remember_route(&window);
            }
        }
        if let RunEvent::Reopen { .. } = event {
            show_dashboard(app);
        }
    });
}
