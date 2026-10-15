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

The output is `src-tauri/target/release/bundle/macos/Agent Swarm.app`. Copy it
to `/Applications`. (No DMG: its Finder styling step needs Automation permission
and fails from a plain terminal.) A local unsigned build may need to be
opened once using Finder's context menu → Open. Signed distribution builds
need Apple's signing and notarization setup; see [Tauri's Mac signing guide](https://v2.tauri.app/distribute/sign/macos/).

You can also install the Tauri CLI with `cargo install tauri-cli --locked` and
run `cargo tauri build` from `mac/`. Icons are already checked in; no Node
build step is required with the Cargo CLI. `npm run dev` runs the native app
for development. `npm run icons` regenerates the rounded app and menu-bar icons
from `../web/public/static/icon.svg`.

## Use it

On first launch, enter the hub dashboard's HTTPS URL, for example
`https://your-linux.your-tailnet.ts.net:8445/`. Keep Tailscale connected for a
Tailscale URL. HTTP is also accepted for a local test hub on localhost. The
address is saved in
`~/Library/Application Support/com.karansag.agent-swarm/settings.json`.

The menu-bar icon has **Open dashboard**, **Change hub URL…**, notification
controls, and **Quit Agent Swarm**. Closing the window hides it; the app stays
running. Click the Dock
icon or use Open dashboard to show it again. **⌘Q** quits. Changing the URL saves
it and restarts the wrapper only when the address actually changed. Cancel and
saving an unchanged address return to the page you left, including its agent
route. Quitting and relaunching restores that page too. Launching
the app again reopens its existing window rather than starting another copy.

The Dock badge counts unique agents needing attention. A notification appears
when an agent first enters that list, including agents already waiting on
launch. Returning to normal and later needing attention again generates a new
notification. Permit notifications for Agent Swarm in macOS System Settings if
prompted. The app uses `UNUserNotificationCenter`, requests permission on launch,
and presents banners even when its window is in front. **Enable notifications…**
requests permission (or opens notification settings after denial); **Test
notification** sends a local test without touching an agent. Clicking an agent's
notification opens its page. Notification delivery is best effort; Focus and OS notification
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
restart on URL change discards the previous origin's grant. Native notifications
use a small Objective-C bridge to Apple's UserNotifications framework, with no
notification IPC exposed to the page. Badge changes remain in Rust. This
replaces the Tauri plugin's deprecated `NSUserNotificationCenter` backend and
its desktop permission no-op.

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
   Also try **Test notification** while the app is in front, and click an
   agent notification to confirm it opens that agent's page.
4. Leave the window hidden for at least five minutes, then trigger attention
   on the scratch hub; check that the native notification still arrives.
5. Open an agent page, enter settings, and Cancel; check the exact agent page
   returns. Repeat with Save and the same URL, then ⌘Q and relaunch; check the
   same page remains. Change to a second scratch URL; check its main page loads
   and survives relaunch. Invalid URLs must not replace the saved address.
6. In a debug app's Web Inspector, invoke `setup_info` or `save_hub` from the
   remote page and confirm rejection; `attention` is the only allowed custom
   command. Check that navigating to another origin is blocked.

Linux validates the portable logic and config, but cannot verify Cocoa,
WKWebView, or native notifications. The Mac build and checks above are required.

For notification troubleshooting, first quit any running copy, then launch the
installed bundle's executable with stderr captured:

```sh
"/Applications/Agent Swarm.app/Contents/MacOS/agent-swarm-mac" 2> /tmp/agent-swarm-notifications.log
```

Or, from `mac/`, run the bundle in the build folder:

```sh
"src-tauri/target/release/bundle/macos/Agent Swarm.app/Contents/MacOS/agent-swarm-mac" 2> /tmp/agent-swarm-notifications.log
```

If authorization is refused without a prompt, check Agent Swarm in System
Settings → Notifications and test the installed copy in `/Applications`.
Keep the authorization error in the report; a successful build alone does not
verify notification permission or banner delivery.

The log records the authorization result and any error, plus queued/delivery
results. This matters for ad-hoc signed builds: a signing or authorization
failure must be checked on the actual Mac. A `queued` result confirms scheduling,
not that macOS displayed a banner; check Focus, notification settings, and the
foreground/background cases as well.
