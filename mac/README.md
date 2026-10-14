# Agent Swarm for Mac

A separate Mac window for an existing hub dashboard. The hub keeps running on
its own machine. This app saves a URL, displays that page in system WebKit, and
adds a menu-bar icon, a Dock badge, and native notifications.

## Build and install

On the Mac, install Apple's Command Line Tools (`xcode-select --install`), current
stable Rust using [rustup](https://rustup.rs), and Node.js 22 or newer. Xcode.app
is not needed. Then, from this directory:

```sh
npm ci
npm run build
```

The output is `src-tauri/target/release/bundle/macos/Agent Swarm.app` and a DMG in
`src-tauri/target/release/bundle/dmg/`. Copy the app to `/Applications`, or open
the DMG and drag the app to Applications. A local unsigned build may need to be
opened once using Finder's context menu → Open. Signed distribution builds
need Apple's signing and notarization setup; see [Tauri's Mac signing guide](https://v2.tauri.app/distribute/sign/macos/).

You can also install the Tauri CLI with `cargo install tauri-cli --locked` and
run `cargo tauri build` from `mac/`. Icons are already checked in; no Node
build step is required with the Cargo CLI. `npm run dev` runs the native app
for development. `npm run icons` regenerates the rounded app and menu-bar icons
from `../web/public/static/icon.svg`.

## Use it

On first launch, enter the hub dashboard's HTTPS URL, for example
`https://karans-linux.tail7b7d19.ts.net:8445/`. Keep Tailscale connected for a
Tailscale URL. HTTP is also accepted for a local test hub on localhost. The
address is saved in
`~/Library/Application Support/com.karansag.agent-swarm/settings.json`.

The menu-bar icon has **Open dashboard**, **Change hub URL…**, and **Quit Agent
Swarm**. Closing the window hides it; the app stays running. Click the Dock
icon or use Open dashboard to show it again. **⌘Q** quits. Changing the URL saves
it and restarts the wrapper. Cancel returns to the current dashboard. Launching
the app again reopens its existing window rather than starting another copy.

The Dock badge counts unique agents needing attention. A notification appears
when an agent first enters that list, including agents already waiting on
launch. Returning to normal and later needing attention again generates a new
notification. Permit notifications for Agent Swarm in macOS System Settings if
prompted. Notification delivery is best effort; Focus and OS notification
settings can suppress it. The page keeps polling while the window is hidden on
macOS 14 and newer. On older macOS versions WebKit may pause background polling.
Notifications require the app to be running and the dashboard to be reachable;
these are dashboard updates, not server push notifications.

## Page integration and permissions

The hub page calls:

```js
await window.__TAURI__.core.invoke('attention', { agents: ['otter', 'stoat'] });
```

Send the complete list on the first poll and whenever it changes, including
`[]` to clear the badge. Duplicate names are counted once. The Rust state keeps
the prior list across page reloads during the same app run. A full app restart
starts a fresh list.

The chosen hub's exact origin (scheme, hostname, and port) receives a runtime
capability for **only `attention`**. All custom commands are subject to Tauri's
ACL. Settings commands are local-only and also verify the bundled page origin.
No filesystem, shell, HTTP, notification-plugin, or window-control permissions
are granted to the remote page. Cross-origin navigation and new windows are
kept out of the app; ordinary HTTP(S) links open in the default browser. A
restart on URL change discards the previous origin's grant. Native
notifications and badge changes are performed by Rust.

## Verify

Portable checks run on Linux or Mac without WebKit libraries:

```sh
npm test
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo check --manifest-path src-tauri/Cargo.toml --no-default-features
```

Build and exercise the installed `.app` on a Mac before merging:

1. First launch: enter a hub URL, save, and confirm the app restarts into that
   dashboard. Relaunch it and confirm the saved URL is retained.
2. Close the window; use the menu-bar menu and Dock icon to reopen it. Verify
   ⌘Q quits, and Copy/Paste works in the chat composer.
3. On a scratch hub, make an agent need attention. Check badge `1` and one
   notification. Repeated polls and a page reload should produce no duplicate.
   Add another agent, then clear the list; check badge `2`, then no badge.
4. Leave the window hidden for at least five minutes, then trigger attention
   on the scratch hub; check that the native notification still arrives.
5. Change to a second scratch URL and verify it survives relaunch. Invalid
   URLs show a setup error without replacing the saved address. Cancel works.
6. In a debug app's Web Inspector, invoke `setup_info` or `save_hub` from the
   remote page and confirm rejection; `attention` is the only allowed custom
   command. Check that navigating to another origin is blocked.

Linux validates the portable logic and config, but cannot verify Cocoa,
WKWebView, or native notifications. The Mac build and checks above are required.
