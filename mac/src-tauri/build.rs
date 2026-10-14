fn main() {
    #[cfg(feature = "desktop")]
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "attention",
            "setup_info",
            "save_hub",
            "open_dashboard",
        ]),
    ))
    .expect("could not build Tauri app metadata");
}
