#[cfg(all(feature = "desktop", target_os = "macos"))]
fn main() {
    agent_swarm_mac::app::run();
}

#[cfg(not(all(feature = "desktop", target_os = "macos")))]
fn main() {
    eprintln!(
        "Build the desktop app on macOS. Portable checks: cargo test --no-default-features --lib"
    );
    std::process::exit(1);
}
