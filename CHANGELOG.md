# What's Changed

## v1.0.77 — 2026-11-20

**Changed**
- The window corners are actually round now. The mask is built by drawing the rounded rect at 8× with antialiasing, scaling it back down and taking the alpha channel as a 1-bit mask. The previous version approximated the arc with a polygon, which is why every corner looked like a small square had been bitten out of it.
- The request and response panes can sit side by side. A small button in the bottom-right corner flips between stacked and side-by-side; the icon rotates 90° with an easing transition, the split itself slides into place, and the chosen direction is remembered in settings.
- "Disconnect" is red everywhere once a connection is live — WebSocket, Socket.IO and SSE share the same button, and the mock server's "Stop service" follows the same rule.

**Fixed**
- Import and export are the original full panel again: drag & drop, per-item selection and page tabs all work as before. The popover from 1.0.76 is gone.

**Added**
- SSE has a page of its own instead of looking like WebSocket with the composer removed. A handshake strip shows the HTTP status code, `Content-Type` and the event rate; event names that actually arrive become filter chips; heartbeats get their own chip and stay out of the main list by default.
- SSE can be paused. High-frequency streams freeze the list while events keep buffering, the buffered count is shown in the stats line, and resuming releases them in one go.
- SSE failures explain themselves. A 401 or 500 now records the status code and writes the server's error body into the log, so "missing token" and "wrong path" look different.

**Verified**
- Smoke suite: 821 checks (new: handshake status, error body capture, dynamic event chips, pause buffering, red disconnect, layout toggle and icon rotation, bitmap corner mask). Brand suite: 268 checks. Bundled self-test: 8/8.

## v1.0.76 — 2026-11-20

**Added**
- SSE requests. "New request → SSE request" gives you a full page in the same style as WebSocket: enter an http(s) URL, connect, and server-pushed events stream into the log line by line. Automatic reconnect with backoff, `Last-Event-ID` resume, filtering by event name or heartbeat, and log export. Import and export understand SSE requests too — the connection options ride along in `x-ocelot`.
- Mock responses can loop and paginate. `{{for size}} … {{/for}}` expands according to `?size=`, `{{@i}}` is the row within the page and `{{@row}}` the continuous index across pages; `{{@page}}`, `{{@size}}` and `{{@total(86)}}` describe paging, so `?page=2&size=20` returns page two without writing any repeated data by hand. Expansion is capped at 500 rows so a typo cannot eat memory.
- "AI generate" in the route editor writes a whole response template from one sentence, loops and pagination included. The "Examples" menu next to it inserts ready-made snippets (paginated list, five-row loop, conditional fields) at the cursor.
- Import and export are now a small popover attached to the button: pick a source or a format, the system file dialog opens, and a toast reports the result. No full-screen blurred window for a two-click task; the full panel is still one menu item away when you want drag & drop.

**Changed**
- "Quick Mock" is now "Generate Mock route", and "Mock Data…" is "Mock Server…" everywhere — menu, window title and settings all use the same name.
- Fixed the window corner mask. The rounded path was flattened into a polygon, leaving the bottom-right corner looking clipped. The mask is built from analytic circle regions now, one pixel per scanline, so the arc is smooth.
- The title bar's right side is aligned again: 16 px on both sides, with the two icons grouped (2 px inside the group, 10 px before it) instead of the gear sitting closer to the edge than the traffic lights do.

**Fixed**
- Exporting a normal request could mark it as WebSocket, because the editor attached a default `ws` block to every request and the exporter trusted its presence. Export and import now go by the method, and the editor only fills in the protocol block that matches the request.

**Verified**
- Smoke suite: 802 checks (SSE round-trip, template loops and pagination, AI body parsing, popover entry, corner mask shape). Brand suite: 245 checks. Bundled self-test: 8/8.

## v1.0.75 — 2026-11-20

**Fixed**
- Creating a folder crashed the app: the sidebar's focus ring called `QPen.setAlphaF`, which does not exist, and Qt took the process down with it. The alpha now goes on the colour, and the animation still plays.
- "Use this route to create a request" left the keyboard focus on the mock window, so typing afterwards went nowhere. The main window is raised and focused before the request is sent.

**Changed**
- Quick Mock moved into the request bar's "More" menu next to "Mock Data…", so the URL bar is back to three actions: save, code, more.
- Automatic memory cleanup is a single switch again: a fixed 15-minute interval, no 5/15/30-minutes picker and no "release now" button. The timer does it quietly; there is nothing to tune.
- The running-mock pill lost its outline and keeps only a faint fill, which sits better with the status row next to it.

**Added**
- Accidentally closing a tab no longer costs you the edits. A tab closed with unsaved changes keeps a 60-second draft: reopening the same request brings back params, headers and body, flagged as unsaved. ⌘⇧T restores the last closed tabs as they were, response included.
- The resource manager gained a "Storage notes" view: what each file owns, why the data is split this way, and what checksums, atomic writes and the quarantine folder actually protect against — in plain language, in the same panel as the file list so switching does not resize anything.

**Verified**
- Smoke suite: 771 checks, including the draft round-trip, ⌘⇧T restore, storage notes content and the fixed 15-minute trimmer. Brand suite: 222 checks. Bundled self-test: 8/8.

## v1.0.74 — 2026-11-20

**Changed**
- The store is modular now: `state.json` only holds the index (settings, environments, the list of collections), every collection lives in its own `collections/<id>.json`, history and trash get their own `history.json` / `trash.json`, disposable caches go to `cache.json`, and backups go to `backups/`. A 60-entry history used to make the one file 120 KB before every save; now the index is under 9 KB and writing history touches one file. One damaged file costs you one piece, not the whole dataset.
- Each collection file carries its own checksum. Writes are `tmp → fsync → rename`, so a crash leaves a `.tmp` at worst; reads that fail the checksum quarantine the file and fall back to that collection's own backup, then skip just that one.
- The index is written last: modules land first, so a stale index only means "index is a bit behind" and files win on the next read. A broken index is recovered from a full snapshot, with the original moved to `corrupted/`.
- Two extra safety nets: collection files that are on disk but missing from the index are re-attached instead of ignored, and deleted ones are moved to `backups/` rather than unlinked.
- The old single-file store migrates on first launch, with a copy of the original kept; old `state.json.bak` and corrupt files are moved into the new folders.
- Growth is bounded: history 500 entries / 24 MB, trash 400 entries / 32 MB, op log 200, open tabs 60, backups 3 full snapshots plus a 96 MB budget — oldest goes first, the very first backup stays.
- Cloud sync uploads a complete snapshot (with schema and real stats) and restores by rewriting modules, after taking a full snapshot. Also fixed the variable count in the stats, which was always zero.
- The resource manager speaks storage now: size split across index / collections / backups / quarantine, one line of integrity status with "Check integrity" and "Rebuild index", collection chips that jump straight to the file, and internal files (`.lock`, `.DS_Store`) hidden.
- Fixed new folders: repeated use used to nest one inside another; now they are siblings with numbered names, visible when created from the history view, and the list status bar no longer gets stuck behind the previous toast.
- Removed the `.oce` collection files and the CLI added in 1.0.73 — local files belong to JSON, and the complexity was not worth it. JSON redundancy is the thing worth doing well.

**Verified**
- Smoke suite: 735 checks, including module round-trip, single-file corruption isolation, orphan recovery, index recovery from a snapshot, legacy migration, retention caps, integrity check and rebuild.

## v1.0.72 — 2026-11-20

**Fixed**
- The packaged build shipped without `app/assets`, so every third-party logo in the import dialog (Postman / Apifox / Hoppscotch / Insomnia / OpenAPI) rendered as blank space. The assets now travel with the bundle, and the bundle self-test fails the build if they go missing again.
- The `Info.plist` version is now stamped from `app/store.py`, so a 1.0.72 DMG no longer reports 1.0.70 in Get Info.

**Changed**
- The mock center is a normal window now instead of a modal dialog: you can switch requests, send them and edit collections with it open. "Try" no longer closes it.
- Every window carries its own title (Mock 中心, 设置 · 通用, 资源管理器, 回收站, 导入导出 …), so ⌘` and the system Window menu stop showing "Ocelot" for all of them.

**Data safety**
- Snapshots are backed up automatically: before each save the previous file is kept as `state.json.bak-<time>`, at most five copies, at most one per 10 minutes. Right-click any of them in the file manager to restore it; the current data is backed up first.
- A state file that fails to parse is no longer silently replaced with sample data. It is quarantined as `state.json.corrupt-<time>`, the newest readable backup is restored automatically, and the window says what happened.
- "Restore from cloud" asks for confirmation when the cloud snapshot holds fewer requests than this Mac, and "clean old files" now keeps the three newest backups, only pruning those older than 30 days.

**Verified**
- Smoke suite: 709 checks. Brand suite: 178 checks. Packaged-bundle self-test: 8/8.

## v1.0.71 — 2026-11-20

**Added**
- Automatic memory cleanup: every 15 minutes the app collects the Python heap, drops the rebuildable icon cache and asks the allocator to return free pages to the OS (`malloc_zone_pressure_relief` on macOS, `malloc_trim` on Linux). Off by default would be wrong here — it is on, with a switch and a 5 / 15 / 30 minute interval under Settings → General, plus a "clean up now" button.

**Changed**
- The resource manager is now a file manager instead of a metrics dashboard. Process memory, system memory, the health score and the trend chart are gone; in their place: breadcrumb navigation, sorting by name / size / modified, a filter box, double-click to open, reveal in Finder, new folder, rename, and delete.
- Deleting moves items to the system trash rather than unlinking them, so a misclick is recoverable. Folders always sort above files.
- The top of the window is a single line of storage facts — app data size, breakdown by file kind, free disk — next to "Clean old files", which purges expired trash, backups older than 7 days and cached analyses.

**Verified**
- Smoke suite: 695 checks. Brand suite: 160 checks. Packaged-bundle self-test: 6/6.

## v1.0.70 — 2026-11-20

**Added**
- macOS packaging: `python3 tools/build_app.py` builds `Ocelot.app` and a DMG in one go. The bundle carries its own Python runtime, so the app runs by double-clicking, with no Python install.
- `--self-test`: imports every module, starts a real mock server, loads a media file and renders the main window offscreen. The build script uses it to verify the packaged bundle, so a missing Qt module fails the build instead of the user's first click.

**Changed**
- Bundle slimmed from 93 MB to 62 MB (DMG 27 MB): unused Qt frameworks and plugins are dropped, QtMultimedia keeps only the macOS AVFoundation backend (that alone removes the 17 MB ffmpeg runtime), Qt translations are cut to Chinese, and the remaining Mach-O binaries are stripped and re-signed ad hoc.
- Built as a one-directory bundle, not one-file: no per-launch extraction, so cold start stays around 0.6 s from process start to first frame.

**Verified**
- Packaged bundle self-test: 6/6 pass. Smoke suite: 680 checks. Brand suite: 146 checks.

## v1.0.69 — 2026-11-20

**Fixed**
- Fixed the window turning into a square, translucent-looking block after leaving maximize/fullscreen. The card used to keep 8px of transparent padding for a drop shadow; macOS re-flags the window as opaque when it comes back from fullscreen, so that padding showed up as a white rectangle around the rounded card. The card now fills the whole window and the corners are cut by a window mask, so the result is the same whether the compositor keeps the window translucent or not.
- The rounded-corner mask is now always cleared while maximized (it previously could linger and clip the screen corners).
- Replaced the drop shadow with a 1px hairline edge, so the window still reads clearly on a light wallpaper.

**Changed**
- Welcome tagline now reads "接口调试、Mock 服务、接口文档，离线可用". The old line promised everything in one window, which was not accurate — the app has several windows.
- README trimmed to roughly half its length: what it is, how to install, the three things it does well, and a short reference section. Removed the feature-list padding.

**Verified**
- Smoke suite: 680 checks pass. Brand suite: 137 checks pass.

## v1.0.68 — 2026-11-20

**Fixed**
- Removed the faint semi-transparent rim that showed around the window edge after a fullscreen/maximize → command-palette sequence. Each paint now clears the whole frameless window first, the card no longer draws a light 1px stroke, and the backdrop plus the rounded-corner mask resync on every window-state change.
- Replaced the welcome-page tagline with a plainer line that no longer mentions macOS.
- Repaired the README screenshot generator, which broke after the multi-instance mock refactor.

**Changed**
- Rewrote the README in plain language: advantages and quick start first, features grouped by topic, and real screenshots for the mock tree, request log, LAN QR code, command palette, cloud-sync stats and light theme.

**Verified**
- Full smoke suite: 679 checks pass; brand suite: 128 checks pass.

## v1.0.67 — 2026-11-20

**Fixed**
- The Mock status strip now lives at the bottom of the **right pane only**. The sidebar — including the "New Request" row — stays exactly where it was; nothing on the left half shifts.
- Stopping the mock collapses the whole strip again, so the right pane immediately returns to its original height with no leftover 28px gap.
- Removed "Environment Variables…" from the macOS app menu; the environment selector in the title bar already covers it, so the menu now holds only About / Settings / Quit.

**Verified**
- Full smoke suite: 679 checks pass; brand suite: 121 checks pass.

## v1.0.66 — 2026-11-20

**Fixed**
- Removed the separator line above the status bar — the badge now floats cleanly in the bottom-right corner.
- The status bar keeps its 28px slot at all times. Starting/stopping a mock only toggles the badge, so the sidebar and content area no longer jump up and down.
- Fixed the stretched row spacing in the Mock center after creating a second instance: the scroll area (which carries `stretch=1`) was being hidden when there were no routes, so Qt spread the leftover height across the other rows — about 89px per row.

**Added**
- **macOS native app menu** (click the app name at the top-left): About Ocelot, Settings…, Environment Variables…, Quit Ocelot. Only the basics — enough to find settings without cluttering the bar.

**Verified**
- Full smoke suite: 679 checks pass; brand suite: 116 checks pass.

## v1.0.65 — 2026-11-20

**Changed**
- **The status bar only exists while a mock server is running.** The capsule badge moved to the bottom-right and replaced the version number; when nothing is running the whole strip (divider included) collapses, giving the content area 28px back.
- **The "AI test cases" button is gone.** The AI dialog already had two modes — generate routes / generate test cases — so one entry covers both: routes get inserted, cases open their cURL list.
- **The QR button only appears when LAN is on.** No LAN, no address to scan, so it no longer takes up a slot.
- The instance menu dropped its extra separator; the instance list now follows the actions directly.

**Performance**
- **Request log updates are incremental**: a new entry inserts one row and drops one once the list is full, instead of rebuilding all 150 rows. Measured 0.43 ms per entry versus 4.94 ms — about 91% faster, so bursty traffic no longer stutters. Closing the panel frees those rows immediately.
- Hand-drawn rows (log, group) now cache fonts, font metrics and icons; scrolling stops creating a `QFont`/`QPixmap` per frame.
- The badge timer only ticks while the server runs and is fully stopped when idle.
- Removed dead code and unused imports (the separate test-case entry, the empty status hint, a handful of unused symbols).

**Verified**
- Full smoke suite: 679 checks pass; brand suite: 107 checks pass.

## v1.0.64 — 2026-11-20

**Added**
- **Multiple mock instances**: each instance owns its own port and route list, and they can all run at once — no more editing the port back and forth when one service calls another.
- **One-click mock**: a button in the request bar turns the current method, path and real response body into a local mock route. If the server is stopped it starts it, then confirms with "added to local mock service". Hitting it again on the same path updates the route.
- **Tree groups for routes**: `orders/payments` style nesting, collapsible and renameable. Importing an OpenAPI (3 / Swagger 2) or Postman collection builds the whole tree automatically from tags and folders.
- **Full OpenAPI / Postman import**: example JSON is generated from schemas, path params become prefix wildcards, and up to 400 routes land in one go.
- **AI for mock**: describe the business in one sentence and get a coherent set of routes with realistic bodies; or generate test cases for existing routes (happy path, missing params, boundaries, auth failures), each copyable as cURL.
- **LAN debugging with a QR code**: enabling LAN binds `0.0.0.0`, shows the LAN URL and renders a QR code (pure-stdlib encoder, no new dependency) so a phone can connect straight away.
- **Status-bar badge**: a permanent `● Mock: 8787 running` capsule at the bottom; click it to jump back to the mock center. Multiple instances list all their ports.

**Changed**
- **Mock center restructured into three tabs**: local mock / public APIs / request log, with a narrower toolbar so the route list keeps the width.
- **Request log is fully hand-drawn**: timestamps no longer collapse to `00:34:0`, the size column is never pushed out of the window, and hundreds of rows scroll without spawning child widgets.
- **Self-check on every start**: after binding, the server is probed — if the port answers but the server does not, the badge turns to "not responding" in a warning colour; an occupied port or duplicate `method + path` routes are named in the start message.
- The request log now also reports response size, client IP, content type and instance; logs from every instance merge in reverse chronological order.
- **What's New** lays out as range summary → category sections (new features / improvements / fixes) → per-version entries, with the range picker moved into the title bar and accent dots on section headers.
- The Ocelot row in the import/export page now uses the app mark itself instead of a generic grid icon.
- Dock icon strokes thickened from 3.6% to 4.2% (1.1px floor at small sizes); the face, spots and ink-writing animation are unchanged.
- **Cloud sync reports real numbers**: local and cloud snapshots each show collections / requests / environments / mock routes / size, and push writes a metadata row in the same batch, so the panel shows what the cloud actually holds.
- Auto cloud sync no longer drops the last edit when a push is still in flight — it marks the snapshot dirty and re-pushes as soon as the worker finishes.

**Verified**
- Full smoke suite: 679 checks pass; the QR encoder was cross-checked byte-for-byte against a reference implementation across random payloads and masks.

## v1.0.63 — 2026-11-19

**Changed**
- **What's New loads lazily**: it now opens with only the 10 most recent versions and a range picker in the top-right (since last update / 10 / 20 / 50 / 100 versions). Instead of building all 63 versions up front, it builds 289 widgets rather than 1816 — about 84% fewer, so the dialog opens much faster.
- **Real source icons in the collection import/export page**: Postman, Apifox, Hoppscotch, Insomnia and OpenAPI now use their own brand marks — cut out to transparent silhouettes, sized uniformly and tinted to the current theme.
- **Finer logo strokes**: outline stroke reduced from 4% to 3.6% of the mark size, with a 0.98px floor at small sizes. The two eyes, inverted-triangle nose and two spots are untouched, and so is the ink-writing hover with sequential feature lighting.
- The dock icon keeps its white rounded square with near-black fine strokes — clean on both light and dark desktops.

**Optimized**
- The app icon (11 pixmap sizes, ~21MB) is now a cached singleton — the main window, tray and dialogs no longer redraw it on every request.
- Changelog and brand/source icons share caches; switching themes only re-tints, never re-cuts the artwork.

**Verified**
- Full smoke suite: 663 checks pass, no new bugs found.

## v1.0.62 — 2026-11-19

**Added**
- **The mark has a face now**: two small vertical-ellipse eyes and a tiny inverted-triangle nose (wide on top, pointed at the bottom — the direction a cat nose actually points).
- **Two ocelot spots**: a medium one on the left cheek and a smaller one under the jaw, deliberately asymmetric so it reads as a wildcat rather than a symmetric doll face.
- Detail is tiered by size so nothing smears: 21px draws only the eyes (title bar), 32px adds the nose, 48px adds the spots (welcome page / empty state only).

**Changed**
- The outline is back to the original ear angle: taller tips with the inner edge hugging the outer edge before easing into the crown, so the ears are a tight triangle again instead of spreading wide.
- The ink-writing hover is kept: once the stroke passes the halfway point the eyes, nose and spots light up in sequence rather than all at once, and each spot blooms a soft glow.
- Welcome-page mark 62px → 78px, About-page mark 44px → 52px, so the new features are actually readable.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.61 — 2026-11-19

**Changed**
- **Back to the thin-line ocelot head you picked**, and this round only makes it accurate rather than redesigning it.
- **The crown is fixed**: the two inner-ear curves meet the middle on one shared horizontal tangent, so the seam has no kink — it reads as a single arc from ear to ear instead of two triangles with a plateau between them.
- **The jaw is rounded**: the base narrows and closes on a real circular arc, so the face no longer reads as a cup or a bag.
- The widest point moved to eye height, with the outline narrowing both above and below; the ear root carries only one very light turn instead of a shoulder.
- Stroke dropped from 4.5% to 4% — finer and crisper at large sizes, still floored at 1.05px for small ones.
- The ink-writing hover animation is kept and refined: a three-dot trail behind the nib gives the stroke some speed, and each spot blooms a soft glow instead of a drawn ring.
- After the stroke finishes, the mark eases back slightly (4.5% → 3.9% scale) while staying lit — like a hand releasing the pen.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.60 — 2026-11-19

**Changed**
- **The mark is now a solid silhouette**: a standing ocelot facing right, tail sweeping up behind into a fine arc. Built the way magpie's icon is built — one solid mass, with the background cut out to describe structure, instead of stroked line art.
- Only two negative spaces, both structural: an arch under the belly and a round eye. The head sits on the shoulder with no gap; round haunch, slim front leg, small round paws, low in front and high at the back.
- **Hover animation rebuilt for a solid mark**: the mark lifts 1% and scales 3.5%, the tail swings 4° around its root, and a point of light blooms inside the eye's cut-out — like the cat opening its eye. Everything eases back in 640ms on leave.
- Re-checked at small sizes: ears, legs and tail still read at 16px, and the 21px title bar no longer smears.
- The dock icon keeps the white rounded square, now with a near-black silhouette inside.
- Exported SVG assets are filled paths now (fill-rule: evenodd), so the asset and the app are the same shape.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.59 — 2026-11-19

**Changed**
- **The mark is redrawn thinner and sharper.** Stroke went from 5 to 4.3 units (~4.5% of the size) and the head is now one continuous curve — pointed ears, round cheeks, narrow chin — so it no longer smears into a blob at 21px in the title bar.
- **Hover animation is now "ink writing itself"**: a bright line leaves the chin, traces the whole contour, a small firefly rides the pen tip, and each spot blooms as the ink reaches it. The mark lifts, a faint light rises around it, and on leave the ink retracts along the same path in 620ms.
- Fixed why the old animation looked static: Qt measures dash length in pen widths, so the whole outline lit up at once instead of being drawn.
- The animation is no longer clipped by the widget bounds (6% inner margin, no more head tilt).
- At 40px and up the mark breathes — one 7-second cycle, so it is never quite still.

**Added**
- The dock icon is now a white rounded square with near-black line work, clean on any wallpaper.
- The response panel's "ready" empty state uses the brand mark and draws it once on open.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.58 — 2026-11-19

**Added**
- Line-art ocelot wordmark as the app logo: the welcome screen, the title bar (left of the title), the About card and the Dock icon now share one vector mark that follows the theme.
- Hover animation on the mark: the outline redraws itself from start to end, the whole mark lifts and scales slightly, and the two spots pop in with a spring. Leaving reverses the same curve. The About page plays it once on open.

**Changed**
- **Resource Manager trimmed down**: four metric tiles and six panels became three blocks — memory, storage, health — so there is nothing extra to interpret.
- The window shrank from 1080×800 to 656×452 and lost its scroll area.
- The maintenance strip went from four buttons to two: **Free memory** and **Clean up** (expired trash + backups older than 7 days + cached analyses), with a single combined report.
- Dropped the object-type scan (which walked tens of thousands of Python objects every refresh) and runtime widget counters; sampling is now every 3 seconds, so the dashboard costs less memory and CPU itself.
- Disk free space folded into the storage card as one line instead of its own card.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.57 — 2026-11-19

**Added**
- **Resource Manager** (settings menu, top-right): a real dashboard for memory, storage and runtime, fully bilingual and theme-aware.
- Memory: resident size read straight from libproc (no `ps` subprocess, works in restricted environments), peak, whole-machine pressure, and a 2-second sampler that draws the last three minutes with min / avg / max.
- Storage: app data split into state file / auto backups / logs / other, with proportion bars and per-group sizes, plus disk free space. The data folder path lives in a tooltip so it does not eat the layout.
- Runtime and assets: top 5 object types, threads, widgets, allocated blocks, and six counters for requests, collections, history, trash, environments and tabs.
- Maintenance strip: free memory (GC + icon / pixmap caches), clear analysis cache, purge expired trash, remove backups older than 7 days — each reports how much was released.
- Health score: weighted from system memory pressure, app data size, history volume and expired trash, with up to three actionable hints.

**Changed**
- AI analysis cache now expires after **8 minutes** instead of 30; the "Cached" tooltip follows the real value.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.56 — 2026-11-19

**Fixed**
- Trash folder detail: labels and values now share the same top alignment, so the three rows sit on one baseline instead of stepping down.
- English UI: AI status line, API-key hint, model heading, variables note, history count, about-page data path and settings title were built by string concatenation at runtime, so the generic translator could not match them as whole sentences. They are now rebuilt from templates on language change, in both directions.
- The conclusion block no longer has the text sitting above/below its side rule: the rule spans the full block and the text is vertically centred.

**Changed**
- Conclusion is now a theme-coloured quote block with a small theme-coloured dot before each section heading.
- Response panel's Auto / UTF-8 switches lost their pill border and fill, matching the rest of the toolbar.
- Hovering "Cached" shows the real expiry time (30 minutes) and a hint to re-analyse; translated in English too.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.55 — 2026-11-19

**Fixed**
- "Analyzing" no longer jitters: the status text stays put while only the spinner moves; streaming refreshes are throttled to 90ms.
- AI analysis layout rebuilt: the conclusion is a card with a side rule, evidence and recommendation lists use a separate bullet / 01-02 column so wrapped lines align with the text instead of snapping back to the left margin. Body text is brighter and larger, and bold fragments are highlighted.

**Added**
- Analysis cache: reopening an already analysed tab shows the saved result instantly instead of calling the AI again. Results are keyed by tab + request + response, shown as "Cached", capped at 8 entries, expired after 30 minutes, and cleared on close or data reload.
- "AI-generated · verify against the raw response" hint in the dialog footer.

**Changed**
- The analysis prompt is now a professional troubleshooting framework: HTTP status and business codes are strictly separated, findings are ranked (blocking / warning / note / normal), and every claim must cite a concrete field and value. All 11 tabs have their own focus; output budget raised to 1400 tokens, and a duplicated "focus:" prefix in the prompt was removed.
- Entry fade-in is 190ms; cache hits get a very light 160ms content softening without delaying the instant display.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.54 — 2026-11-19

**Fixed**
- AI no longer calls a successful HTTP 200 response an "error code" just because the body contains `code: 1`. Business codes are interpreted from `msg` / `data` / `success`, not from the number alone.
- AI-renamed requests now update the collection node and matching history entries, so the sidebar shows the new name immediately.
- Global fix for IME composition: placeholder text is hidden while candidate words are being composed and restored afterwards, for every text input.

**Added**
- "AI response analysis" dialog: streaming Markdown output with fade-in animation and spinner, copy and re-analyze buttons, and an entry on the response tab row.
- Tab-aware analysis: pretty / tree / raw / headers / cookies / console / preview / diff / extract / timeline / network error each get their own evidence and focus points.
- Stale-response notice now has a close (x) button and "Never remind me" (persisted in settings).

**Changed**
- API docs code sample is collapsed by default; expand with the chevron.
- Removed AI script writing from pre/post script pages and removed DeepSeek from AI settings (GLM only).
- Rewrote all prompts for data generation, response analysis, docs and naming to be evidence-based and specific.

**Verified**
- 654 smoke checks plus 57 targeted checks pass.

## v1.0.53 — 2026-11-19

**Added**
- The code sample section in the API docs window now has a collapse arrow (the same chevron used in the collection tree): collapse it and the document takes the whole height.
- "AI content" switch in the docs window: hide or show the AI-written sections at any time; while off, copy and "Save .md" produce the purely generated document.

**Changed**
- Script AI is far less strict: it treats every request as a coding task and writes runnable JavaScript instead of refusing when the description is vague or off-topic. Only a plain prose answer (no code at all) is reported back.
- AI prompt dialog now sizes itself from its content, so the text box no longer runs under the buttons when the hint wraps or the font is larger.

**Removed**
- "New request from a sentence" is gone from the welcome screen, the command palette and the code behind it.

**Verified**
- 654 smoke checks plus 53 targeted checks pass.

## v1.0.52 — 2026-11-19

**Changed**
- Settings now has a single "Variables" page: environment variables and global variables sit behind one segmented switch, with the override rule (environment wins) stated right in the header. The old separate nav entries are gone.
- The AI settings page was rebuilt: switch → provider → key → models → advanced, with a single status line (ready / not configured / off) instead of colored decoration.

**Added**
- AI master switch: keep the key but turn AI off, and every AI entry point goes quiet; key and model choice are preserved.
- DeepSeek support next to Zhipu GLM (DeepSeek-V3 and R1 cards). Each provider keeps its own key and switching brings the right one back.
- "New request from a sentence" on the welcome screen and in the command palette: method, URL, headers, query params and body are filled in, with Content-Type added for JSON.
- "Save response field as variable" in the response more menu: pick a field, get a suggested name, store it globally or in the current environment.
- AI auto-naming with a switch: unnamed or URL-derived request names become human-readable after sending; hand-renamed requests are never touched, and each URL is only asked once.
- "AI script" as the first button on the pre-request and post-response script pages: describe the goal in a sentence and get JavaScript that only uses this sandbox's API; off-topic requests are refused and never written into the editor.
- "AI fill" in the API docs window: appends overview, field meanings and common errors to the generated document — included in copy and "Save .md", and the response sent to the model is redacted while the redact switch is on.

**Verified**
- 654 smoke checks plus 52 targeted checks (variable precedence, per-provider keys, AI switch, script refusal, doc append, one-sentence requests) all pass.

## v1.0.51 — 2026-11-19

**Fixed**
- Tab drag-and-drop is smooth again: reordering now reports once on mouse release instead of syncing `state.json` on every frame, tab widths/rects are cached, and the indicator snaps instead of restarting an animation mid-drag.

**Added**
- Global variables: available in every environment and request via `{{name}}`; a same-named environment variable overrides them. Manage them in Settings → Global variables.
- AI settings page: paste a Zhipu GLM API key and go. Four preset model cards (GLM-4-Flash 250414/latest, GLM-4.5, GLM-4.1V), one-click connection test, plus custom model ID and base URL for proxies or self-hosted gateways.
- AI body generation: in a JSON body, "AI generate" builds realistic data from the existing field names (or param keys), streams it into the editor and formats it when done.
- AI error explanation: available on the failure page and in the response "more" menu — returns the cause plus concrete fixes.

**Changed**
- Sidebar methods longer than 4 characters are abbreviated to 3 letters (PATCH → PAT, DELETE → DEL, OPTIONS → OPT) so names get more room.
- The Params tab of HTTP, WebSocket and Socket.IO no longer offers the File type (query params can't carry files); multipart form uploads keep it.

## v1.0.50 — 2026-11-19

**Changed**
- Request tabs now lift and follow the mouse while being dragged to reorder, leaving a translucent placeholder at the original spot — matching the sidebar's drag feel.
- WebSocket and Socket.IO "Params" pages now include "Paste" and "Bulk Edit", fully on par with HTTP params: bulk import from clipboard, key: value bulk editing, comment lines mark rows disabled, and the final-URL preview updates live.

## v1.0.49 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use three tabs: Chat / Params / Protocol (Auth). Added a real query-parameter table that is appended to the URL on connect, with bulk edit and a final-URL preview.
- Socket.IO Chat page first row is now "Event name" with matching English text; namespace moved into the Auth page; all rows share one left alignment with no functionality lost.
- Sidebar drops the duplicate "New Folder" button; the trash entry moves to the bottom action bar and the delete animation now flies to the new spot.
- Creating a folder now jumps focus to it with a highlight pulse and opens inline rename with a default name: confirm to keep it, type to replace.
- The search box now filters both Collections and History, keeps its text across tab switches, and hides empty history groups.
- Fixed the trash detail popup misalignment in English (truncated labels / uneven value column) with a language-aware label width; also reduced redundant history row rebuilds.

## v1.0.48 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now align their tabs, toolbar rows and inputs to the same left edge as the method badge; both protocols share one baseline.
- Protocol and Auth pages drop the full grey card background, keeping only group titles and thin dividers for a cleaner look.
- Removed leftover collapsed-card state, unused message counters and duplicate helpers to cut dead code.

## v1.0.47 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use the same underline tab style as HTTP requests: WebSocket splits into Chat / Protocol, Socket.IO into Chat / Auth.
- The Chat page keeps only day-to-day sending: namespace, event name, payload, JSON/Text switch, format, save and send.
- Low-frequency settings moved to a second tab: connection parameters for WebSocket, handshake auth and ACK/reconnect options for Socket.IO.
- Socket.IO payload input gains a JSON/Text switch (controls highlighting and formatting), and its "More" menu now shows Socket.IO-specific actions: copy URL, export/clear event log.

## v1.0.46 — 2026-11-19

**Changed**
- Unified the layout of the WebSocket and Socket.IO pages into one skeleton: options row / composer row / editor / frequent chips — matching the HTTP request view while keeping only useful controls.
- The method badge on realtime pages now shrinks to a compact label, giving the room back to the URL field and removing the empty gap after the method name.
- Protocol fields (subprotocol, namespace, auth, event name) now stretch to fill the row and action buttons sit flush right for a cleaner look.
- Low-frequency switches are grouped on their own row and aligned with the handshake-headers button; both realtime pages now look identical, with no clipping in English or Chinese.

## v1.0.45 — 2026-11-18

**Added**
- Socket.IO requests with a dedicated "Events" page, creatable from the New Request menu and command palette.
- Lightweight Engine.IO v4 / Socket.IO v4 over websocket transport: handshake, namespaces, auth JSON, event emit/listen, ACK receipts, heartbeat and auto-reconnect — no extra dependency.
- Distinctive touches: auto-discovered events with one-click filtering, frequent events for one-click reload, double-click an event to load it back, JSON payload highlighting and formatting, clear-after-send.

**Fixed**
- Initialized the ACK registry to prevent a crash, and stopped treating ordinary integer data as an ACK id on server events that request a receipt.
- Auto-reconnect now keeps the namespace and auth; Socket.IO connections are fully closed on exit, leaving no orphans.
- Complete Chinese/English strings for namespace, auth, events, ACK and discovered events.

## v1.0.44 — 2026-11-18

**Changed**
- Trash time groups now use the same chevron as the collection tree, with the item count aligned right like history groups.
- Removed the redundant "Oldest deleted" strip above the trash list.
- Fixed hover cursors: collection tree and history rows now show the pointing-hand cursor again.
- Slightly widened the trash window and filter sidebar so English "Custom" and the date inputs are no longer clipped.
- Filled in missing English strings for the trash tooltip and WebSocket "Connecting to …" log line.
- Added a light dissolve animation for deleting a single history entry and clearing all history: sweep line, soft ring, fade-and-collapse.

## v1.0.43 — 2026-11-18

**Changed**
- Group trash items by deletion time (within 1 hour / today / yesterday / 7 days / 30 days / older), with collapsible headers and expand animations.
- Detail popup now fills with params / headers / body / cookies / auth / variables / sub-requests and scrolls.
- Unified method colors with the theme palette; WS / HEAD / OPTIONS are no longer grey.
- Fixed the transparent context menu by drawing an opaque rounded background; full CN/EN strings.
- Extended clear / restore / delete animations by ~0.5s for a calmer feel.
- Added a lightweight arc-to-trash-button fly animation when deleting from the sidebar.

## v1.0.42 — 2026-11-18

**Changed**
- Calendar weekday header switched to the theme's dark palette instead of the
  system light-grey strip.
- Removed the always-on trash detail panel so deleted records use the whole
  area; "Oldest deleted" moved above the list and aligned with the row icon.
- A small "Details" pill appears on row hover and opens a lightweight detail
  popup, keeping the layout clean.
- Added a 1px hairline separator between the filter sidebar and the list.
- Empty / restore / permanent-delete now play a light artistic animation
  (expanding ring + icon fade-in) with minimal resource use.

## v1.0.41 — 2026-11-18

**Changed**
- Trash stats bar items all aligned left again as before; search box now has a
  visible border so it reads clearly against the dark background.
- Refresh button icon spins one full turn on click for clear feedback.
- Widened the trash filter sidebar so the custom date range inputs are no
  longer clipped.
- Command palette gained "Open Trash" and "Trash auto-clean settings" actions.
- Trash detail simplified back to a short list (URL / contains / deleted at /
  original location) with type and method pills on the title row.

## v1.0.40 — 2026-11-18

**Changed**
- Trash window re-laid out: search moved into the top-right stats bar, the
  redundant activity timeline removed, and the detail panel made richer and
  scrollable (type / method / URL / params / headers / body / env vars /
  original location / exact delete time).
- Custom date range picker restyled to follow the pure-black theme — the
  system calendar's white background, red weekends and purple selection are
  gone.

**Added**
- "Trash auto-clean" switch (on by default) and retention period (7 / 30 / 90
  days) in Settings · Data. Expired items are permanently removed when saving
  settings and on launch.
- Cascade restore hints: selecting a folder also selects its independent child
  entries in the trash, and restoring prompts how many requests come back with
  it. Requests referencing `{{variables}}` get an undefined-variable warning.
- Saving a request now scrolls the left collection tree to the saved item;
  restoring from the trash refreshes the sidebar and reveals items at their
  original position. The Refresh button now re-reads state from disk.

**Verified**
- Self-test suite: 593 checks, 0 failures. Real launch with Trash window OK.

## v1.0.39 — 2026-11-18

**Added**
- Trash for deleted collections / folders / requests. Deletes now move items to
  the trash instead of erasing them, and restore puts the whole subtree back at
  its original position.
- A blurred, fixed Trash window with a distinctive three-part layout: filter
  rail on the left, item list on the right, detail panel at the bottom. Pure
  black minimal theme, no gradients or colored outlines.
- Full trash toolkit: restore, delete permanently, empty, detail view, search
  by name / URL / method, date-range filtering (today / 7d / 30d / custom),
  refresh, multi-select batch actions, an activity timeline and exact delete
  timestamps. Sidebar entry shows the item count.

**Fixed / Changed**
- HTML / XML code highlighting now uses the unified One Dark scheme (blue tags,
  amber attributes, green values, gray punctuation, colored inline script /
  style). `xml` was previously downgraded to the Python highlighter, leaving
  markup almost entirely gray.
- Sidebar delete is now "Move to Trash" with an accurate, reassuring prompt
  instead of an irreversible-delete warning.

**Verified**
- Self-test suite: 579 checks, 0 failures.

## v1.0.38 — 2026-11-18

**Fixed**
- Two expanded message cards could overlap. The list laid out rows using an
  80px estimate for a not-yet-created card, so once the real card turned out to
  be several hundred pixels tall the following rows were drawn right on top of
  it. Layout now creates and measures every expanded card first, then positions
  rows, and checks convergence against the row offsets themselves (not against
  whether card properties changed, which broke out of the loop too early).
- Scrolling to the bottom still hid the last message: the list height omitted
  the expanded card on the final row. Total height now includes that card in
  full, so the bottom edge is reachable.
- Resizing the window narrower reflows long text and changes card height; the
  whole list is now re-laid out on resize instead of only repositioning cards.

**Changed**
- Detail cards no longer show the "响应体" label; the Raw tab and the code box
  are aligned to the same left edge.

**Verified**
- Self-test suite: 554 checks, 0 failures.

## v1.0.37 — 2026-11-18

**Fixed**
- Scrolling over an expanded message card now scrolls the whole log again. The
  read-only code view was swallowing every wheel event (it still scrolled its
  own 1px), so the outer list never moved — the mouse sat on the card and
  nothing happened. Wheel events are now forwarded to the log scroll area.
- The scroll area no longer depends solely on its easing animation to move:
  it lands on the target value even when the animation cannot fire, so the
  wheel always works (including in safe mode).
- Tabs are chosen by **content** again: a plain-text frame shows only **Raw**,
  a real JSON payload shows **JSON / Raw**. Previously every text frame was
  given a JSON tab, so a plain "hello" message and even ERR system messages
  sported a meaningless JSON tab.
- Removed the collapse chevron from the top-left of detail cards; cards stay
  open with their full content visible.

**Changed**
- Code surface background moved closer to the window base (`#171717`-like),
  matching the response panel look the user compared against.

**Verified**
- Self-test suite: 549 checks, 0 failures.

## v1.0.36 — 2026-11-18

**Fixed**
- WebSocket detail code frames no longer render on a dead-black viewport: the
  background now follows the theme's code background (a shade close to the
  window base), so keys / strings / numbers keep the full syntax-highlight
  palette against a surface that matches the app.
- Plain-text frames whose payload is JSON now get the **JSON** tab and syntax
  highlighting too. Previously only frames tagged `json` at send time did,
  which left a JSON body showing a lone **Raw** tab with no colours.
- Expanding a log card no longer lets later frames cover it. The incremental
  append path now uses each open card's real height instead of a fixed 80px,
  and auto-scroll pauses while any card is open — so the expanded content
  stays in view and can be scrolled through.
- The "…" button in the response header now does something in a WebSocket
  session. It opens a WS-specific menu: connect / disconnect, copy URL, copy
  session stats, export the message log and clear it.

**Removed**
- The "Saved messages: store anything you send often…" empty-state hint in the
  WebSocket composer; the chips and their tooltips speak for themselves.

**Verified**
- Self-test suite extended to 550 checks.

## v1.0.35 — 2026-11-18

**Changed**
- WebSocket detail cards were rebuilt around content only: no repeated timestamp / preview
  from the row above. Tabs, copy button and a clean bordered code frame make the hierarchy
  clearer.
- Every expand arrow now uses the same chevron as the collection tree (right when collapsed,
  down when expanded) — both in log rows and in detail cards.
- The code frame can be collapsed. JSON keys and values no longer render in bold.
- The code frame has no scrollbars: it grows to fit all content and the outer log area
  handles scrolling.

**Fixed**
- Multi-line JSON in a log row used to overlap the rows below. Previews are now compacted
  to one horizontal line regardless of how the original was formatted.

**Verified**
- Self-test suite extended to 544 checks; startup-to-show ~547ms; clean exit with an open
  WebSocket connection.

## v1.0.34 — 2026-11-18

**Fixed**
- The URL-bar button still read **Connect** while a WebSocket was open (and after switching
  tabs); it now reads **Disconnect** and stays that way.
- Messages in progress were lost when switching tabs. Drafts and the text / JSON / binary
  choice are stored with the request.
- The input hint showed through Chinese IME preedit text (e.g. `ni'hao` overlaid the hint).
  The placeholder now hides while composing and returns afterwards.

**Changed**
- Log rows expand into inline detail cards: Raw / JSON / Hex tabs, line numbers and a copy
  button. Several rows can stay open at once (capped at 12, oldest closes first so the UI
  never accumulates thousands of text documents).
- JSON details keep their indented layout; row previews stay on a single elided line.
- Counters (received / sent / bytes, uptime / traffic) animate over 280ms instead of jumping.

**Improved**
- Appending frames is incremental and stats use cached counters: 4000 frames append in
  ~2ms, and painting remains limited to visible rows.
- Self-test suite extended to 539 checks.

## v1.0.33 — 2026-11-18

**Fixed**
- Occasional hard crash (`zsh: bus error`, `crash.log` showing `<no Python frame>`) when
  quitting. Shutdown now stops every animation, drops graphics effects, closes sockets and
  tears the window down explicitly instead of relying on Qt / Cocoa destruction order.
- The WebSocket log's empty hint was squeezed into a 1px line (the list is 8px tall when it
  has no rows). It now has its own centred page, with a different message when a filter
  matches nothing.
- **Settings → Appearance → Text size** did nothing: the dialog saved the value and closed,
  so the rebuild step saw "no change". It now zooms in place — the settings page stays open
  and the whole UI resizes as you click.

**Changed**
- WebSocket is a request *kind*, not a method: `WS` is gone from the method dropdown, and a
  WS request is created only from **New request → WebSocket request**.
- WS requests get a dedicated page with only what they need: message editor (text / JSON /
  binary), saved messages, subprotocol, heartbeat, auto-reconnect, clear-after-send, and a
  collapsible handshake-headers editor. The HTTP-only tabs are gone.
- "Export this folder" is now **Export collection**.
- The command palette is shorter — a floating panel rather than a full-height sheet.

**Improved**
- Welcome cards and empty states scale with the text-size setting, so 150% no longer
  overlaps lines.
- Self-test suite extended to 529 checks (WS page, handshake headers, live text scaling,
  palette height).

## v1.0.32 — 2026-11-18

**Added**
- **WebSocket requests.** Create one from **New request**, or switch any request's method to
  `WS`. Addresses accept `ws://` / `wss://`; pasted `http(s)` URLs are rewritten.
- Full WS feature set: text / JSON / binary messages, handshake headers + cookies + auth,
  subprotocols, ping heartbeat with real round-trip latency, exponential-backoff
  auto-reconnect, and live connection stats (uptime, frames and bytes in/out).
- A frame log with direction, type, time and size; filter by Received / Sent, search the
  contents, click a row for the full payload, copy, export to JSON or text, clear. Capped at
  4000 frames so long-running subscriptions stay light.
- Common messages: save recurring payloads as chips, click to load them back. They travel with
  the request in Ocelot / Postman export and come back intact.
- Double-click any received frame in the log to **replay** it: the payload is loaded back into
  the editor so you can tweak it and send again — no copy-paste.
- Settings → Appearance → **Text size** (100% / 110% / 125% / 150%). Scales the whole UI and
  the code area; applies instantly and returns you to the same settings page (unsaved tabs
  are carried over).
- Right-click a folder in the collection tree → **Export this folder** (Ocelot, Postman,
  OpenAPI, HAR). The default file name is the folder name and the exported file keeps the
  same folder structure.

**Fixed**
- Hovering "response time" after a failed request still showed a bogus `9 ms` card. Time,
  size and type are now hidden on failure, and the hover cards are gone.
- In English the `failed` pill was narrower than its label, so the text spilled out of the
  rounded background. Pills now size themselves from real glyph metrics.

**Improved**
- The command palette only paints the rows that are on screen; the rest render as you
  scroll, while search still matches every entry.
- Batch-running a collection skips WebSocket requests.
- Self-test suite extended to 519 checks, including a real local WebSocket server covering
  connect, echo, heartbeat, replay, disconnect and refused connections.

## v1.0.31 — 2026-11-18

**Fixed**
- The backdrop blur was not aligned with the window: it covered the whole window rect
  (including the 8 px shadow margin) and its corners stayed square. It now covers only the
  window card and is clipped to the same 12 px radius, so the arcs line up.
- The command palette had no blurred backdrop, and opening it made the card jump vertically.
  Layout is now fully computed before the palette is shown, and it fades in from 10 px
  above with a 120 ms animation.
- On the failed-request page the **Clear / Copy all** buttons were too loud. They are now
  compact and sit on the same line as the output summary, flush with the content edge.
- History mode showed two **Clear History** buttons (a text one and an icon one); the icon
  one is gone.
- Preview tabs stayed italic after double-clicking a collection item or sending the request.
  They are promoted to a normal tab now.
- The import source list had a large gap between **Import from URL** and **Export all
  collections**; the dialog height now follows the content.

**Added**
- Deleting a collection, folder or request (and clearing history) now asks for
  confirmation. Deleting a folder tells you how many requests go with it.

**Improved**
- The "Blur All Dialogs" description in Settings is a single short sentence.
- Self-test suite extended to 482 checks, all passing.

## v1.0.30 — 2026-11-18

**Fixed**
- The tab pill slide had disappeared: clicking a tab calls `set_current` twice (once from
  the click, once from the selection callback) and the second call snapped the animation
  that had just started. The pill now slides with a subtle velocity stretch, and the
  outgoing/incoming tab labels and method badges cross-fade.
- The modal backdrop was only blurred on the left-hand side. Replaced the Qt blur render
  with a two-stage downsample blur that is uniform across the whole window (about 3.5 ms
  for 1600×1000, a few hundred KB peak memory).
- The success check on the import result page sat left of centre: its icon was centred
  using device pixels, which is 2× off on Retina. It is now centred in logical pixels and
  gets a small expanding halo when it appears.
- Imported collections had the wrong name. The name now comes from the file
  (`info.name`, Apifox collection name, Insomnia workspace, OpenAPI title) or the file
  name, and the collection is created as a folder with that name — inner folders keep
  their hierarchy. A single-request JSON still imports as one request.

**Added**
- `Collections / History` segmented control: the selected pill slides between the two
  labels and the text colour cross-fades.
- Every dialog is centred on its parent window, including when a page change resizes it.
  Only Settings and Import/Export are blurred and immovable by default; other dialogs
  stay unblurred and can be dragged by their title bar.
- New setting **Appearance → Blur All Dialogs**: turn it on and every dialog becomes
  blurred and immovable.
- Command palette: the five most-used commands are pinned under a **Frequently used**
  heading (ordered by real usage, so the list adapts), followed by **All commands**. The
  card is centred and slides down as it fades in.
- **Import from URL**: paste a remote JSON / YAML link (8 MB limit); it downloads and runs
  through the same detection pipeline as a local file.

**Improved**
- Export file names default to the collection (folder) name instead of
  `ocelot-collection`.
- Removed a batch of unused imports and redundant work; the self-test suite now covers
  467 checks and passes.

## v1.0.29 — 2026-11-18

**Fixed**
- The selected tab pill no longer overlaps the neighbouring tab at launch. A pending
  indicator animation kept writing a stale rectangle after the geometry had been snapped;
  the pill now always derives from live geometry, and restoring a session no longer
  animates once per tab.
- Changing the request method (POST → GET) now updates the method badge in the collection
  tree. The editor, the tab badge, the stored node and the saved file stay in sync.
- Switching method after a request no longer throws the response away. The previous result
  stays on screen with a slim "Request changed · showing the previous response" bar that
  offers a **Send again** action.
- Importing a Postman file could fail with "no importable requests": Apifox
  `apiCollection` payloads and Insomnia exports whose requests hang under a workspace were
  parsed as empty. Postman data dumps, Postman v1 collections, Hoppscotch v2 objects,
  files with a UTF-8 BOM and bare single-request files are now recognized too.

**Added**
- Import / export result page: a large check, the title, and a breakdown of what was
  brought in (collections, requests, folders, pre-request scripts, post-response scripts,
  auth, environment variables). Export results offer **Show in Folder**.
- The file page reports what was detected before importing (format plus counts), and the
  sidebar reveals and expands the newly imported collection.
- Environments travel with the collection: Postman dumps, Apifox and Insomnia environment
  resources are imported alongside the requests.
- Dialogs and the settings panel now blur and dim the main window behind them, and the
  modal is pinned in the centre of its parent instead of being draggable.

**Improved**
- The collection search field fills the width up to the import / export button.
- The export page states what will be written ("Exporting 1 collection, 5 requests") and
  disables the rows when there is nothing to export.

## v1.0.28 — 2026-11-18

**Added**
- A **Console** tab in the response panel: `console.log / warn / error` output and `test()`
  assertions from pre-request and post-response scripts, color-coded by level with Pre/Post
  badges, one-click copy, and inline output on the error page so a failing pre-request script
  is still visible when no response arrives. The console also records the outgoing request
  and the final status line.
- An **Import / Export** button next to the collection search field. A single dialog handles
  both directions with a back arrow: import from Ocelot JSON, Postman, Apifox, Hoppscotch,
  Insomnia, OpenAPI 3.x (JSON or YAML) and HAR, plus clipboard import; export as Ocelot JSON,
  Postman v2.1, OpenAPI 3.1 (JSON / YAML) or HAR. Files can be dropped onto the dialog, and
  the chosen file is parsed and summarized before importing.
- **Ocelot JSON** uses Postman v2.1 plus an `x-ocelot` block, so Postman / Apifox can import
  it directly while a round trip through Ocelot keeps scripts, auth and cookies.
- **Rename** in the tab context menu: updates the collection node, the tab title and the
  request itself, saves immediately, and pushes to the cloud when auto-sync is on.
- Clicking a tab now reveals the matching request in the sidebar: switches back to
  collections, expands the parents, clears a hiding filter and scrolls the row into view.

**Improved**
- Script engine hardened: `res.body` / `res.text` now return real text instead of a bound
  method, `req.setHeader` keeps existing rows disabled as before, and `res.json()`,
  `res.setHeader()`, `pw.env.has()`, `pw.env.toObject()` and `test()` were added. Syntax
  errors report the line number the user sees, and endless loops are stopped after 2 seconds
  by a deadline check injected into loop bodies (no background thread, so the process can
  never be aborted by a leftover thread at exit).
- Snippet buttons insert on a fresh line instead of mid-line; post-response scripts get
  response-reading and assertion snippets.
- Body badge no longer copies the whole body on every keystroke.

**Fixed**
- Editing a request and saving never wrote the changes back to the collection node, so
  reopening showed the old content. Tabs now sync into their node on every save.
- After an unclean exit, the next launch starts with animations temporarily disabled to
  avoid the macOS graphics-layer hard crash; focus is released before the window closes.
- All 429 self-tests pass.

## v1.0.27 — 2026-11-18

**Improved**
- The script run status now pairs a thin check/cross icon with the text. Success shows only
  "Ran successfully"; the line is left-aligned with the editor above and sits right beneath
  it, fades in when it appears, and uses the theme's success/danger colors. The icon uses a
  light stroke weight.
- Language switching now walks the widget tree once instead of twice; history group counts
  are computed in a single pass. Duplicate imports and redundant calls were consolidated.

**Added**
- A **Raw** body mode with a JSON / XML / HTML / Text language selector. The selected
  language drives syntax highlighting, formatting and `Content-Type`. All send paths and
  code generators now share one normalization helper.

**Fixed**
- History group titles are translated at paint time, so switching between Chinese and
  English updates them immediately instead of leaving the old language on screen.
- All 395 self-tests pass and repeated real GUI startups are crash-free.

## v1.0.26 — 2026-11-18

**Improved**
- Script **Run test** results now appear in a dedicated dialog. The status line shows only
  "Ran successfully", left-aligned with comfortable padding and a subtle fade-in when the
  text appears. The inline log panel at the bottom of the page is gone.

**Added**
- Params now has a **Bulk Edit** button, so you can edit all query parameters at once as
  `key: value` text.
- History is grouped into **Within the last hour / Today / Yesterday**, with each group's
  collapsed state remembered independently. Group headers now share the same subtle hover
  animation as the other buttons.

**Fixed**
- Fixed an intermittent startup `bus error` crash. The frameless translucent window now fades
  in using native window opacity instead of a graphics effect, and pages hosting native video
  views no longer get a `QGraphicsOpacityEffect` applied.
- All 395 self-tests pass.

## v1.0.25 — 2026-11-17

**Fixed**
- The run status on the script page is now a single line. `console.log()` output from both
  **Run test** and real requests is written to a read-only log panel directly below, so the
  "see logs below" message finally points at something real.
- Editing a pre-request or post-response script no longer wipes out the last response. Script
  changes update the request data and the dirty flag only; the response panel keeps showing
  what you were looking at.

**Improved**
- The auth type name **Inherit** is now always shown in English, matching Bearer, Basic,
  API Key and JWT.
- Params, Body, Headers, Cookies and Auth pages now each get a slim scrollbar. When their
  content is taller than the request pane they scroll on their own instead of being clipped.
- The collection runner uses the theme's subtle hover color for the current row instead of a
  bright gray bar. Clicking a finished row opens that request with its captured response, so
  you can inspect the result directly.
- All 395 self-tests pass.

## v1.0.24 — 2026-11-17

**Improved**
- The script editor is now split into two dedicated pages, **Pre-request Script** and
  **Post-response Script**; the redundant in-page tab switch is gone. The reference panel
  on the right scrolls independently with a slim scrollbar, so overflow no longer pushes
  the controls below out of place. `Run` becomes a clearer **Run test** button with a
  tooltip explaining that it runs the script locally without sending a request.
- History groups now use the same chevron as the collection tree. Click a group header to
  collapse or expand it, and the state is remembered across restarts.

**Added**
- **JWT auth** — auto-generate a signed token with HS256 / HS384 / HS512 or paste one
  manually. Payload and secret support environment variables, and the token is sent as
  `Authorization: Bearer <token>`. Generated tokens match the jwt.io standard exactly.
- **Inherit auth** — walk up the request's collection to find the nearest folder auth.
  Configure it from the folder's right-click **Configure auth…** menu. Both JWT and Inherit
  work on the direct and relay send paths.

**Optimized**
- All 395 self-tests pass.

## v1.0.23 — 2026-11-17

**Added**
- **Pre-request and post-response scripts** powered by Qt's built-in JavaScript engine
  (QJSEngine, zero extra dependencies). Modify the URL, headers and query params before
  sending; parse the response after it arrives. `pw.env.set()` writes variables into the
  active environment and persists them, `console.log()` output is visible, and a broken
  script never blocks the request.
- **Complete body type set** — none / form-data / x-www-form-urlencoded / JSON / XML /
  Text / Binary, with names aligned to mainstream API clients. XML is a new first-class
  type with syntax highlighting, validation, one-click formatting and automatic
  `application/xml` content type.

**Improved**
- Code editor now supports automatic bracket and quote pairing, smart indentation on
  Enter, Tab indentation and wrapping a selection in a pair. JSON and XML can be
  formatted in one click; JSONC line comments are handled.
- One unified syntax highlighting scheme across the whole app — JSON and Python /
  JavaScript / Go / Java and more share a single One Dark style token palette (declaration
  keywords in pink, functions in blue, strings in green, numbers in orange). Request
  bodies, responses, code examples and the script editor all use it.
- The response size card now counts header bytes including the status line, and adds a
  **Request Size** section with separate Header / Body figures. Card background is darker.
- History is grouped by date (Today / Yesterday / N days ago) with a count per group.

**Optimized**
- All 395 self-tests pass.

## v1.0.22 — 2026-11-17

**Fixed**
- **Switching the language in Settings left the right-hand page in Chinese**: the Settings
  window is a separate top-level window that the main window's translation pass could not
  reach. It now re-translates itself on switch, including the page title and nav width.
- **An extra divider line above the response area**: when the metrics bar was hidden, the
  divider below it stayed visible and overlapped the splitter handle. The divider now shows
  and hides together with the metrics bar, leaving a single line.
- **"New Mock Route" / "New Condition Rule" dialog titles were not translated** in English.
- **Timeline stats and "No Wrap" were not translated**: hit count / success rate / average /
  P95 / slowest, plus the raw view's wrap toggle, stayed in Chinese under English.

**Improved**
- Request panel tab order is now Params / Body / Headers / Cookies / Auth, with the most
  used Body tab moved to second place.
- Code examples in the API doc now share one fixed height: switching languages no longer
  makes the block jump between sizes; overflow scrolls inside.

**Optimized**
- All 395 self-tests pass.

## v1.0.21 — 2026-11-17

**Fixed**
- **The history list went blank in English**: the sidebar's segmented tabs did not recompute
  their widths after a language switch, clipping the `History` segment. Tabs now re-measure.
- **Command palette action names stayed in Chinese**: new request / send current request and
  others were untranslated, as were "Default" in the format menu and "Click to choose a
  file…" in file cells.
- **A chosen file in the request body could not be sent**: the code used the display text
  as the path, which becomes `No file chosen` in English and was treated as empty. The path
  is now stored separately from its display text.

**Improved**
- Settings header and footer hints wrap automatically, so long English text is no longer
  clipped at the window edge.
- English copy reviewed throughout; terminology keeps aligning with Postman.

**Optimized**
- All 395 self-tests pass.

## v1.0.20 — 2026-11-17

**Fixed**
- **Square window corners**: the rectangular content layer covered the window's own rounded
  corners. The content layer now has a rounded mask that follows the window, disabled when
  maximized.
- **Gray squares next to selected response-tree rows**: the indent cell got a system hover
  background. The highlight is now fully transparent while selected text stays highlighted.
- **Two rapid requests crossed streams**: an old request's `finished` signal treated the new
  request as done, leaving the spinner running or showing the wrong response. Results are
  now matched by signal source and stale ones are discarded.

**Improved**
- Settings / What's New footers no longer print `Ocelot x.y.z · Python + PyQt6`.
- The About page drops the runtime (Python / PyQt6) and "native macOS window" tags.
- Full English pass: toasts, placeholders, tooltips, Settings pages, Mock hub; terminology
  aligned with Postman (Send / Params / Headers / Cookies / Environments / Mock Server),
  with no source text lost when switching languages.

**Optimized**
- Large arrays only render the first 300 items with a "… {n} more" trailing row; even
  200,000 items open instantly.
- Added a crash log: hard crashes and uncaught exceptions are written to `crash.log` in the
  data directory.
- 395 self-tests.

## v1.0.19 — 2026-11-17

**Fixed**
- **Clicking "More → Mock data…" crashed**: the editor was missing the `mockRequested`
  signal and raised `AttributeError`; "Copy request" in the same menu had the same issue and
  was fixed too.
- Mock / Copy request in the More menu are now forwarded uniformly by the editor, with a
  single signal connection — one click no longer opens two windows.

**Improved**
- Response tree view: row height 16 → 21; the key column is sized to its content so
  `two_factor` is no longer truncated to `two_fa…`.
- The API doc footer now prefixes the status line with a "Status" label instead of showing
  a bare string of words.

## v1.0.18 — 2026-11-17

**Fixed**
- **Right-clicking inside an input crashed**: `QApplication` has no `cursor()` method and
  raised `AttributeError` when resolving the click position. The context menu now uses the
  screen coordinates carried by the event, falling back to the mouse position only if needed.
- **Mock showed "Stopped" but a browser refresh still worked**: stopping closed the listen
  port, but an existing HTTP keep-alive connection kept being served. Stopping now actively
  drops all live connections and responses no longer request connection reuse.
- Stopping now disconnects in-flight connections before closing the port, so no response can
  "arrive after stopping".

**Optimized**
- Self-tests expanded to 382 checks, including right-click positioning and the guarantee
  that stopped services return no data.

## v1.0.17 — 2026-11-17

**Added**
- **Mock conditional rules**: one route can return different results based on request
  header / query param / body / method — return VIP data with a `token`, 401 without it,
  covering both happy and error paths. Rules support equals / contains / exists / not
  exists, with their own status code, delay and response body.
- **Mock dynamic data**: write placeholders like `{{@id}}` `{{@uuid}}` `{{@name}}`
  `{{@cname}}` `{{@email}}` `{{@now}}` `{{@int(1,99)}}` `{{@pick(a,b)}}` in the response body;
  each request recomputes them. Editing a route offers "Preview random data".
- **Mock request log**: a new "Request Log" page shows each request's method, path, status,
  latency and matched route / rule in real time, with 2xx / 4xx / average-latency counters
  and a one-click clear.
- Route lists show a hit count per route.

**Improved**
- The start button now follows the real state: "Start Service" when stopped, "Stop Service"
  when running (previously hard-coded).
- The API doc table was rebuilt: a dedicated header bar, row dividers, a first column
  measured and clamped to 96–210, and word wrap for long content.
- Code examples: language labels align strictly with the code body; long lines are wrapped
  and sized by their real line count, with no half-cut lines or stray scrollbars.
- The Settings menu's "Settings…" is now a gear icon; "Switch Light / Dark" was removed
  (the theme is still under Settings → Appearance).
- The About page drops file names and class names for a user-facing capability list and a
  "what one request goes through" walkthrough.

**Fixed**
- Stopping could leave the port occupied (another instance or a leftover process): it now
  waits for the port to be truly released and reports honestly; if another Ocelot owns the
  port, it says so and switches automatically.
- Dynamic data containing Chinese characters broke the HTTP response when written into a
  header; it is now safely encoded.

**Optimized**
- Self-tests expanded to **374 checks**: menu entries, button states, placeholder randomness,
  rule matching, log latency, table column widths, code-block alignment and long-code scroll.

## v1.0.16 — 2026-11-17

**Added**
- **A real local Mock service**: an actual HTTP server on `127.0.0.1` whose routes, methods,
  status codes, delays and bodies you define. Supports prefix wildcards `/api/users/*`,
  echo mode (returns the request verbatim), CORS, and can be reached directly from a browser
  or script; "Try" builds a request in one click, and it can start with the app. If the port
  is taken it switches automatically.
- **Two Mock hub pages**: local Mock manages routes (create / edit / copy address / delete),
  while the public API catalog keeps 28 free endpoints (click a row to fill a request).
- **Shortcut settings**: all 16 actions are editable — click a keycap to record, clear in one
  click, restore defaults. Two actions competing for the same key make the older one step
  aside, and changes take effect immediately.
- **Fuller API docs**: overview (method / URL / status / latency / size / content type), auth
  notes, cookie table, response header table and status-code semantics; copying or saving
  produces a deliverable document.

**Improved**
- API doc window reflowed: a request card on top with status / latency / size metrics, a left
  outline that tracks scrolling, and cached code examples per language.
- Ten languages in code examples share syntax highlighting (CLI flags, URLs, strings and
  numbers each colored); code aligns strictly with the language label.
- Command palette entries are no longer clipped: a scrollable list with eased wheel input,
  keyboard selection auto-follow and cards clipped by whole rows.
- Mock public API list rebuilt as sub-widgets + layout: method / URL / description align
  strictly; search debounced at 120ms.
- The title bar's settings button is a real gear icon (previously a sun-like set of rays).
- Settings dialog widened to 940×700; About drops the shortcut table for four "Why Ocelot"
  advantages and a six-layer architecture note.

**Fixed**
- A query param already present in the URL was appended again in code generation and docs
  (`?a=1&a=1`); it now compares first, then appends.
- The Mock panel's status pill and button enable state were out of sync after start / stop.

**Optimized**
- Self-tests expanded to **351 checks**: a real local service for route / echo / 404,
  shortcut recording and conflict hand-off, command palette scroll, code-block alignment and
  highlighting, and the new doc sections.

## v1.0.15 — 2026-11-17

**Added**
- **API doc window**: "View API Doc" under "More →" at the top right of the response. Method /
  URL / param table / headers / body / response example on one page, a left outline to jump
  between sections, ten languages of code examples at the bottom with one-click switching,
  a toggle to mask tokens, and copy / save as `.md`.
- **Mock data panel**: 28 built-in free public APIs (httpbin / JSONPlaceholder / DummyJSON /
  ReqRes / random images…), searchable and grouped; a click fills a ready-made request.
- **Response timeline**: a new "Timeline" tab plots this URL's latency history as bars colored
  by status code, with hit count / success rate / average / P95 / slowest on top and hover
  details for each run.
- Command palette ⌘K gains Mock Data, API Doc, Copy Current Request and Close Tab.

**Improved**
- Param table headers align with data rows (checkbox placeholders are real controls, the
  "Type" header is centered).
- URL history completion is a custom-drawn overlay: rounded, clock icon, monospace URL,
  up/down to select.
- Settings reflowed: cloud sync address / token / button on one row, no longer squeezed;
  dialog widened to 900×672.
- About page rebuilt: a large title, version pill, three-column runtime info, two-column
  shortcuts and a copy-version action.

**Fixed**
- Right-click on selectable text in response headers and doc bodies still used the system
  menu (English, translucent); it is now taken over consistently.

**Optimized**
- Self-tests expanded to 312 checks.

## v1.0.14 — 2026-11-17

**Added**
- **One-click API docs**: "More →" in the response copies a full Markdown document (method,
  URL, query, headers, body, status code, latency, size, response example). A tab right-click
  offers "Copy API Doc (Markdown)" so each request can be exported without hand-writing docs.
- **Secret masking**: the same menu can "Copy response body (masked)" or export a doc with
  "secrets masked". `token` / `cookie` / `password` / `authorization` / JWT / `Bearer xxx`
  become `••••••` (long values keep the last four characters so you can confirm it is the
  same key). Safe to paste into chat, tickets or screenshots.

**Improved**
- Code generation (cURL / Python / JavaScript / HTTPie) now merges rows from the Cookies tab
  into the `Cookie` header; disabled rows are not exported, so generated code matches what
  "Send" actually does.

**Fixed**
- Runtime log prefixes still saying `Reqly` (save response / save config failures) are
  unified to `Ocelot`.

**Optimized**
- Self-tests expanded to 312 checks: every doc section, masking rules, long-value truncation,
  JSON structure comparison and cookies in generated code.

## v1.0.13 — 2026-11-17

**Renamed**
- Reqly → **Ocelot**. Title bar, About page, menus, User-Agent and data directory all changed;
  on first launch the old `~/Library/Application Support/Reqly` data is migrated so nothing
  is lost.

**Added**
- Requests gain a **Cookies** tab: table rows are merged into the `Cookie` header (coexisting
  with a hand-written one), and `Set-Cookie` in a response can be imported in one click so
  login sessions carry over.
- **Cloud sync (Turso)**: set a database URL and Auth Token in Settings; "Test Connection"
  runs a single `SELECT 1`; upload / restore from cloud (restoring backs up `state.json.bak`
  first), with an option to auto-upload on exit. Uses only Turso's HTTP pipeline, no new
  dependencies.
- URL bar completes from history: focusing it lists previously used URLs containing the
  current text, so a few keystrokes are enough.
- Command palette ⌘K can switch environments and jump straight to Appearance / Cloud Sync.

**Improved**
- The accent color now drives more than buttons: selection backgrounds, focus outlines,
  hover badges, tab titles and underlines, sidebar selection markers and Settings nav all
  follow it, with body text tinted slightly toward the accent — one coherent color temperature.
- Param type pills drop their outline; Auto gets its own warm-sand color at a larger size,
  clearly distinct from Null's gray and JSON's orange.

**Fixed**
- A black ring around checked checkboxes (the default pen also drew one) — the checked state
  is now a solid block only.
- The first accent swatch's selection ring was clipped by the card edge.
- Tab right-click "Copy as cURL" did nothing (`to_curl` was not imported, `NameError`).
- Qt's implicit cookie jar silently rewrote hand-written `Cookie` headers; it is now neither
  read nor written, and cookies are managed explicitly by the Cookies tab.

**Optimized**
- Removed two unreachable blocks in Settings, duplicate and unused imports in the main window;
  request counts and cookie hints merge into one refresh.

## v1.0.12 — 2026-11-17

**Added**
- Settings · Appearance gains an **Accent Color**: seven swatches (auto / ocean blue / pine /
  moss / terracotta / crimson / violet); buttons, switches, checkboxes and the send key follow
  immediately. "Auto" keeps the original black-and-white inversion.

**Improved**
- The param type menu's Auto now has its own color (warm sand), clearly distinct from Null's
  gray and JSON's orange.

**Fixed**
- Switching color scheme / accent rebuilt a destroyed hover detail card and crashed while
  painting — destroyed widgets are now skipped.
- Switching schemes only refreshes visible widgets; hidden ones repaint naturally when shown,
  making large windows much smoother.

**Self-tests**
- 228 checks: accent switching and persistence, swatch count and clicks, Auto vs Null contrast.

## v1.0.11 — 2026-11-16

**Fixed**
- After launch, tabs did not respond and content would not switch: the tab strip now emits
  its change signal unconditionally; the main window also self-heals a wrong editor request
  or a ghost tab, re-checking when the window regains focus.
- An error midway through `RequestEditor.load` left the loading flag stuck at True, so every
  later edit stopped writing back ("clicking does nothing") — a `finally` block now clears it.

**Optimized**
- Sidebar collapse / expand stutter: the splitter was clamped to the sidebar's minimum size
  (≈158), so the first two thirds of the animation did nothing and the last frame vanished.
  During animation the minimum size and size policy are relaxed, then restored — the slide is
  now truly frame-by-frame.
- Switching tabs and receiving responses no longer writes to disk synchronously (batched to
  one write per 700ms); the history list refreshes incrementally instead of rebuilding
  hundreds of widgets.
- Re-clicking the current tab no longer re-formats the whole response, making large JSON
  switches noticeably smoother.
- Large responses render on demand: the JSON tree and "Raw" tab are built only when opened —
  a 190KB response drops from 1 second to 60ms. Above 600KB only the first 600KB is previewed
  with a hint to "Save As" for the full text, and syntax highlighting is skipped above 180KB.

**Added**
- Extract results can be "Saved as Variable": one click writes into the current environment
  for later `{{name}}` references, so a login token no longer needs copying by hand.
- Middle-click a tab to close it; double-click the divider between request and response to
  restore a 50/50 split.
- Double-clicking an italic preview tab pins it (VSCode behavior); previously double-clicking
  a tab did nothing.

**Self-tests**
- 219 checks: tab self-healing, middle-click close, divider reset, save-as-variable,
  frame-by-frame sidebar animation and incremental history refresh.

## v1.0.10 — 2026-11-16

**Added**
- **Collection runner**: right-click a folder → "Run Collection" or ⌘⇧R to run every request
  in tree order, showing status / latency / size per request and a success / failure / total
  time summary; stop at any time, copy the whole result table (TSV pastes straight into a
  spreadsheet), and click a row to open that request.
- Param type gains File: pick a local file in a form row and upload it as real multipart, with
  code generation reflecting the file param.
- cURL import dialog: paste to parse with live preview, supporting `-X / -H / -d / -F / -u /
  -G / --data-urlencode` and merged short flags like `-sSL`.
- Request tab right-click: Close Others / Close All / Duplicate Tab / Copy as cURL.

**Improved**
- Code snippets expanded to 10 languages (adding Go / Java / PHP / C# / Kotlin /
  PowerShell), all syntax highlighted.
- Format / encoding / type dropdowns are custom-drawn, no more garbled native checkmarks;
  the method palette was reordered to match the reference image and "Custom" removed.

**Fixed**
- Pretty-printing squeezed HTML into one line, or into a staircase running right: it is now a
  token stream — inline tags stay on one line, `script` / `style` / `pre` content is preserved,
  CDATA is not split, and unclosed tags are tolerated.
- Detail card icons never lined up — root cause was `QPixmap.width()` returning device pixels
  (2× on Retina); the dpr is now factored in to center them correctly.
- Clicking a request tab's content did not switch pages and edits were lost — the tab strip
  now genuinely emits a change event.

**Self-tests**
- 196 checks: runner order and summary, file type, pretty-print structure, icon centering and
  tab switching.

## v1.0.9 — 2026-11-16

**Improved**
- Param types use capitalized English names (Auto / String / Number / Boolean / Null / JSON),
  each with a semantic color; String is green.
- HTTP method palette matches the reference: GET green / POST orange / PUT·HEAD·OPTIONS blue /
  DELETE red / PATCH pink / TRACE purple, with "Custom" removed.

**Added**
- Code snippets add Go / Java / PHP / C# / Kotlin / PowerShell, with multilingual highlighting.

**Fixed**
- Type / format / encoding dropdowns switched to custom-drawn menus, eliminating garbled
  macOS native checkmark glyphs.
- The "Expand All / Collapse All" buttons that appeared when selecting text are now fully
  hidden, leaving only format and encoding in the toolbar.
- Detail card icons misaligned and footer text overlapping the Body row: the title and metric
  row icons now share one size and x position, and all blocks accumulate sequentially.
- Clicking a request tab did not switch content and lost edits — TabStrip now emits
  currentChanged correctly.

**Self-tests**
- 186 checks: type colors, custom menus, detail-card alignment, code languages and tab
  switching.

## v1.0.8 — 2026-11-16

**Improved**
- Response Time / Size hover cards use a fixed anchor instead of following the mouse; the
  custom-drawn layout was rebuilt with segmented icons.
- Format / encoding buttons now use the same custom control, shown only on the "Pretty" tab.

**Added**
- The size card adds a Header / Body allocation bar; the time card adds an "estimated" note
  so each segment is not misread.

**Fixed**
- After changing the URL to time-tx, the previous image response was still shown — any
  request edit now invalidates the old response.
- After opening several request tabs their content merged together — responses, format,
  encoding and the current response sub-tab are now stored per tab.
- After dragging the sidebar width the URL bar disappeared and the description floated up —
  an interrupted animation now restores its paint state completely.

**Self-tests**
- 167 checks: fixed cards, button isolation, per-tab responses and animation-interrupt recovery.

## v1.0.7 — 2026-11-16

**Fixed**
- Sidebar collapse froze in two stages — the animation wrote to disk on every frame via
  `splitterMoved`. The signal is now disconnected during animation with a single write at
  the end.
- A new empty tab and an opened old request ended up with identical content — each tab is now
  an independent snapshot and collection tree changes only sync titles, not edits.
- The spinner never started on send, making the app look stuck — it now really spins with a
  skeleton shimmer.

**Added**
- Single-click a sidebar item enters VSCode-style preview (italic title, reused preview tab);
  double-click pins it.
- Param types use English names (auto / string / number / boolean / null / JSON).
- Settings → General adds a language switch (简体中文 / English), translated naturally and
  applied immediately across the whole UI.
- Node speed tests now cover every node (previously only 8), with controlled concurrency,
  a progress indicator, and a note that speed does not imply availability or overall latency.
- Response gains a format switch (Auto/JSON/XML/HTML/Text) and 11 encodings (UTF-8/GBK/Base64…).
- Hover detail cards over response time / size: segmented bar chart (DNS/TCP/SSL/TTFB/
  download) plus size breakdown.

**Self-tests**
- 155 checks: tab isolation, preview open, language switch, format / encoding, timing detail
  and spinner state.

## v1.0.6 — 2026-11-16

**Fixed**
- Only 22 nodes were listed — now the full 221 IPv4 / 130 IPv6 nodes are fetched, refreshable
  at any time.
- The gray bar in the method menu / command palette kept following the mouse after leaving —
  hover is now strictly bounds-checked.
- Sidebar collapse / expand stutter — the content repaint was frozen frame-by-frame during
  animation and the collection tree was no longer fully rebuilt at the end.
- Image / audio responses showed a row of question marks in Pretty / Raw — now a hint plus
  hex view, defaulting to Preview.
- After a title changed the pill width did not follow, swallowing the "+" into the pill; the
  collection tree showed left/right arrow cursors.
- A toast's underlying object was destroyed but still called, causing a crash.

**Added**
- Online nodes really work: the selected node forwards requests via a node server, with exit
  IP, region and latency annotated in the response metrics.
- The "Local" button moves to the right of Send; the node panel gains a refresh button and
  IPv4 / IPv6 counts.
- Preview gains "Save": images / audio / video / PDF / binary can all be saved locally.
- Settings gains an "About Ocelot" page and a "View What's New" entry; the changelog panel
  is color-coded by category.
- Param table gains a "Description (optional)" column used only as a note, never sent.

**Self-tests**
- 134 checks: indent gray block, menu reuse, zero-latency hover, toast sizing, three preview
  types, node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding
  and media container detection.

## v1.0.5 — 2026-11-16

**Fixed**
- Gray blocks to the left of selected collection-tree rows (the base class painted the indent
  area with the selection color) — the indent area is no longer painted and the selection
  background is transparent.
- Opening the method menu a second time crashed (`RuntimeError: MethodMenu has been deleted`)
  — the menu is now reused as a persistent object.
- The command palette's gray hover bar lagged behind the mouse — tweening was removed for
  zero-latency following, and the keyboard row uses a thin border instead of stealing focus.
- System toasts were large and empty — replaced with a custom-drawn toast sized to its text.
- Right-clicking an input opened the English system menu — replaced with a custom Chinese menu
  (Undo / Redo / Cut / Copy / Paste / Delete / Select All) with icons.
- gzip / deflate / br compressed bodies showed as gibberish or blank — they are now decompressed
  by `Content-Encoding` (with gzip-header sniffing as fallback).
- GBK / GB18030 pages showed garbled Chinese — when no charset is declared, UTF-8 then
  GB18030 are tried in order.

**Appearance**
- Unified base color: sidebar and workspace both use `#19191C`, removing the "half dark, half
  lighter" look and leaving a single 1px divider.
- Settings gains six color schemes: Graphite (default `#19191C`) / Slate / Warm Gray / Pine /
  Ink / Light; click a thumbnail to switch.
- Settings was rebuilt: section cards, scrollable content and a clearer information hierarchy.
- Sidebar is draggable 200–420 px and remembers its width; the title bar gains a collapse
  button (⌘B still works).
- The selected tab pill drops its outline.

**Added**
- "Preview" upgraded: image wheel zoom / drag pan / double-click fit / checkerboard transparency;
  embedded audio and video playback; PDF and binary get an "Open" and hex view; image / audio /
  video responses auto-switch to Preview.
- Media containers are detected by magic bytes (wav / mp3 / ogg / flac / m4a / webm / mov)
  instead of all being saved as unplayable `.bin`.
- "Nodes": the URL bar can select IPv4 / IPv6 nodes, searchable by region and ISP with one-click
  speed tests (TCP + DNS round trip), defaulting to "Direct". socks5 / http proxy nodes can be
  added and requests genuinely route through them, with metrics annotated.
- Network settings gain a default User-Agent; data settings gain a history limit.

**Self-tests**
- 108 checks: indent blocks, menu reuse, zero-latency hover, toast sizing, three preview types,
  node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding and
  media format detection.

## v1.0.4 — 2026-11-16

**Look & feel**
- Dark theme rebalanced around `#19191C`: five levels of gray for window / panel / card /
  overlay / selection; a content surface between sidebar and workspace so the boundary is no
  longer blurred.
- Method menu is custom-drawn: each method has a color, the current item shows a checkmark,
  row heights align and there are no native-menu rough edges.
- Removed all colored dots (collection tree, environments, tab strip) in favor of vector icons
  and status badges.
- Hover toasts use a rounded capsule style (smaller text, looser line height, no border burrs).
- Command palette hover uses a soft gray layer with 120ms easing, selected row gets a thin
  border instead of a hard cut.
- The tab strip's "×" and "+" were reflowed with ≥10px spacing.

**Params (rebuilt)**
- Add, remove, move up / down and copy / delete any row at any time.
- A new "Type" column: Auto / String / Number / Boolean / null / JSON, applied with the correct
  type when sent.
- Smart paste: `token=abc&debug=true`, `{"q":"x"}`, multi-line `k: v` or Tab-separated and `#`
  comment lines are split into rows in one paste, with comments auto-disabled.
- URL ↔ param table two-way sync: a URL with `?a=1&b=2` is split into the table and the URL
  keeps only the base; clearing params no longer leaves ghost params that break the request.

**Added**
- "Compare": auto line-by-line diff of this URL's response against the previous one, marking
  status code and latency changes, with a manual "Set as baseline".
- "Extract": use a JSON path like `a.b[0].c` or `*` to pull a field, with a hint listing valid
  top-level fields on error and one-click copy.

**Settings**
- Consolidated into a single page of six sections (General / Appearance / Network /
  Environments / Data / What's New) instead of nested dialogs.
- Code font size in three steps (Small / Standard / Large), applied to all open code areas
  immediately.
- The changelog panel was rebuilt: blocks per version, colored by category, word-wrapped,
  with a scroll that no longer stutters or overlaps.

**Self-tests**
- 80 assertions: param type inference, URL split, no ghost params, three paste formats, six
  Settings pages, diff stats and JSON path extraction.

## v1.0.3 — 2026-11-16

- Fixed a crash when the mouse moved over the collection tree (`RuntimeError: wrapped C/C++
  object of type QVariantAnimation has been deleted`) — the hover animation is now a
  persistent object instead of being destroyed at animation end.
- Added a "repeated hover" regression: sweep the collection tree three times, wait for each
  animation to finish and destroy before triggering again — 56 assertions.
- Sidebar-collapsed interaction tests now expand the sidebar first so no checks are skipped.

## v1.0.2 — 2026-11-16

- Fixed a crash when hovering the tab strip (`TypeError`: `QRectF.contains` only accepts
  `QPointF`, but got `QPoint`) that also killed the app when launched from the IDE.
- Startup self-check: on an old interpreter or missing PyQt6, print the interpreter path and
  a fix command instead of dumping a traceback.
- When launched from the run panel, bring the window to the front (`raise` + `activateWindow`).
- Added mouse-interaction regression: tab hover / click-to-switch / double-click blank to
  create, sidebar and segmented control sweeps — 53 assertions.
- Screenshot scripts now use a temporary state file instead of overwriting the real session
  (history, theme, open tabs).

## v1.0.1 — 2026-11-16

- Fixed: after switching from dark to light theme, JSON property names became nearly white
  and invisible on the light background (re-colored on theme switch).
- Fixed: the screenshot script overwrote real session data (now reads / writes a temp file).

## v1.0.0 — 2026-11-16

The first version: a pure-black, minimal API debugging tool with native macOS polish.

**Interface & motion**
- Borderless rounded window + traffic-light buttons (icons on hover), edge drag-resize,
  double-click title bar to zoom.
- Dark / light themes, pure-black layers, inverted solid primary buttons, no gradients or
  colored glows.
- All icons are 24×24 custom-drawn vector strokes, theme-colored and crisp on Retina.
- Animation: window fade-in, page cross-fade, response fade-in, segmented tab sliding underline,
  sliding selection pill, counting latency numbers, toast slide-up, sidebar collapse and
  loading skeleton shimmer.

**Request building**
- Method picker, URL input, query params and headers (enable switch / auto-append empty row /
  header autocomplete / bulk edit).
- Body: none / JSON / text / form (multipart with `@file` upload) / x-www-form-urlencoded /
  binary.
- Live JSON validation and format / minify.
- Auth: Bearer / Basic / API Key (Header or Query injection).
- Environment variables with `{{$timestamp}}` / `{{$uuid}}` / `{{$randomInt}}` dynamic variables.

**Send & response**
- Async cancellable send, timeout / follow-redirects / SSL-verify toggles, proxy (auto /
  system / direct), cookie persistence and parsing.
- Response metrics (status, latency, size, type, final URL).
- Six response views: Pretty / Tree / Raw / Headers / Cookies / Preview; in-response find and
  highlight.
- Copy response body, save to file, error-state hints.

**Organization & reuse**
- Collection tree (unlimited depth, drag sort, right-click menu, search filter, open-state dots).
- History (click to restore, hover to delete, clear).
- Multi-tab (drag reorder, sliding indicator, session restore).
- Environment variable management with active switching.
- Code generation: cURL / Python / JavaScript / HTTPie.
- cURL import, collection import / export (Postman v2.1 compatible).
- Command palette ⌘K, global shortcuts, Settings and What's New dialogs.
## v1.0.60 — 2026-11-19

**Changed**
- **The mark is now a solid silhouette**: a standing ocelot facing right, tail sweeping up behind into a fine arc. Built the way magpie's icon is built — one solid mass, with the background cut out to describe structure, instead of stroked line art.
- Only two negative spaces, both structural: an arch under the belly and a round eye. The head sits on the shoulder with no gap; round haunch, slim front leg, small round paws, low in front and high at the back.
- **Hover animation rebuilt for a solid mark**: the mark lifts 1% and scales 3.5%, the tail swings 4° around its root, and a point of light blooms inside the eye's cut-out — like the cat opening its eye. Everything eases back in 640ms on leave.
- Re-checked at small sizes: ears, legs and tail still read at 16px, and the 21px title bar no longer smears.
- The dock icon keeps the white rounded square, now with a near-black silhouette inside.
- Exported SVG assets are filled paths now (fill-rule: evenodd), so the asset and the app are the same shape.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.59 — 2026-11-19

**Changed**
- **The mark is redrawn thinner and sharper.** Stroke went from 5 to 4.3 units (~4.5% of the size) and the head is now one continuous curve — pointed ears, round cheeks, narrow chin — so it no longer smears into a blob at 21px in the title bar.
- **Hover animation is now "ink writing itself"**: a bright line leaves the chin, traces the whole contour, a small firefly rides the pen tip, and each spot blooms as the ink reaches it. The mark lifts, a faint light rises around it, and on leave the ink retracts along the same path in 620ms.
- Fixed why the old animation looked static: Qt measures dash length in pen widths, so the whole outline lit up at once instead of being drawn.
- The animation is no longer clipped by the widget bounds (6% inner margin, no more head tilt).
- At 40px and up the mark breathes — one 7-second cycle, so it is never quite still.

**Added**
- The dock icon is now a white rounded square with near-black line work, clean on any wallpaper.
- The response panel's "ready" empty state uses the brand mark and draws it once on open.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.58 — 2026-11-19

**Added**
- Line-art ocelot wordmark as the app logo: the welcome screen, the title bar (left of the title), the About card and the Dock icon now share one vector mark that follows the theme.
- Hover animation on the mark: the outline redraws itself from start to end, the whole mark lifts and scales slightly, and the two spots pop in with a spring. Leaving reverses the same curve. The About page plays it once on open.

**Changed**
- **Resource Manager trimmed down**: four metric tiles and six panels became three blocks — memory, storage, health — so there is nothing extra to interpret.
- The window shrank from 1080×800 to 656×452 and lost its scroll area.
- The maintenance strip went from four buttons to two: **Free memory** and **Clean up** (expired trash + backups older than 7 days + cached analyses), with a single combined report.
- Dropped the object-type scan (which walked tens of thousands of Python objects every refresh) and runtime widget counters; sampling is now every 3 seconds, so the dashboard costs less memory and CPU itself.
- Disk free space folded into the storage card as one line instead of its own card.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.57 — 2026-11-19

**Added**
- **Resource Manager** (settings menu, top-right): a real dashboard for memory, storage and runtime, fully bilingual and theme-aware.
- Memory: resident size read straight from libproc (no `ps` subprocess, works in restricted environments), peak, whole-machine pressure, and a 2-second sampler that draws the last three minutes with min / avg / max.
- Storage: app data split into state file / auto backups / logs / other, with proportion bars and per-group sizes, plus disk free space. The data folder path lives in a tooltip so it does not eat the layout.
- Runtime and assets: top 5 object types, threads, widgets, allocated blocks, and six counters for requests, collections, history, trash, environments and tabs.
- Maintenance strip: free memory (GC + icon / pixmap caches), clear analysis cache, purge expired trash, remove backups older than 7 days — each reports how much was released.
- Health score: weighted from system memory pressure, app data size, history volume and expired trash, with up to three actionable hints.

**Changed**
- AI analysis cache now expires after **8 minutes** instead of 30; the "Cached" tooltip follows the real value.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.56 — 2026-11-19

**Fixed**
- Trash folder detail: labels and values now share the same top alignment, so the three rows sit on one baseline instead of stepping down.
- English UI: AI status line, API-key hint, model heading, variables note, history count, about-page data path and settings title were built by string concatenation at runtime, so the generic translator could not match them as whole sentences. They are now rebuilt from templates on language change, in both directions.
- The conclusion block no longer has the text sitting above/below its side rule: the rule spans the full block and the text is vertically centred.

**Changed**
- Conclusion is now a theme-coloured quote block with a small theme-coloured dot before each section heading.
- Response panel's Auto / UTF-8 switches lost their pill border and fill, matching the rest of the toolbar.
- Hovering "Cached" shows the real expiry time (30 minutes) and a hint to re-analyse; translated in English too.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.55 — 2026-11-19

**Fixed**
- "Analyzing" no longer jitters: the status text stays put while only the spinner moves; streaming refreshes are throttled to 90ms.
- AI analysis layout rebuilt: the conclusion is a card with a side rule, evidence and recommendation lists use a separate bullet / 01-02 column so wrapped lines align with the text instead of snapping back to the left margin. Body text is brighter and larger, and bold fragments are highlighted.

**Added**
- Analysis cache: reopening an already analysed tab shows the saved result instantly instead of calling the AI again. Results are keyed by tab + request + response, shown as "Cached", capped at 8 entries, expired after 30 minutes, and cleared on close or data reload.
- "AI-generated · verify against the raw response" hint in the dialog footer.

**Changed**
- The analysis prompt is now a professional troubleshooting framework: HTTP status and business codes are strictly separated, findings are ranked (blocking / warning / note / normal), and every claim must cite a concrete field and value. All 11 tabs have their own focus; output budget raised to 1400 tokens, and a duplicated "focus:" prefix in the prompt was removed.
- Entry fade-in is 190ms; cache hits get a very light 160ms content softening without delaying the instant display.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.54 — 2026-11-19

**Fixed**
- AI no longer calls a successful HTTP 200 response an "error code" just because the body contains `code: 1`. Business codes are interpreted from `msg` / `data` / `success`, not from the number alone.
- AI-renamed requests now update the collection node and matching history entries, so the sidebar shows the new name immediately.
- Global fix for IME composition: placeholder text is hidden while candidate words are being composed and restored afterwards, for every text input.

**Added**
- "AI response analysis" dialog: streaming Markdown output with fade-in animation and spinner, copy and re-analyze buttons, and an entry on the response tab row.
- Tab-aware analysis: pretty / tree / raw / headers / cookies / console / preview / diff / extract / timeline / network error each get their own evidence and focus points.
- Stale-response notice now has a close (x) button and "Never remind me" (persisted in settings).

**Changed**
- API docs code sample is collapsed by default; expand with the chevron.
- Removed AI script writing from pre/post script pages and removed DeepSeek from AI settings (GLM only).
- Rewrote all prompts for data generation, response analysis, docs and naming to be evidence-based and specific.

**Verified**
- 654 smoke checks plus 57 targeted checks pass.

## v1.0.53 — 2026-11-19

**Added**
- The code sample section in the API docs window now has a collapse arrow (the same chevron used in the collection tree): collapse it and the document takes the whole height.
- "AI content" switch in the docs window: hide or show the AI-written sections at any time; while off, copy and "Save .md" produce the purely generated document.

**Changed**
- Script AI is far less strict: it treats every request as a coding task and writes runnable JavaScript instead of refusing when the description is vague or off-topic. Only a plain prose answer (no code at all) is reported back.
- AI prompt dialog now sizes itself from its content, so the text box no longer runs under the buttons when the hint wraps or the font is larger.

**Removed**
- "New request from a sentence" is gone from the welcome screen, the command palette and the code behind it.

**Verified**
- 654 smoke checks plus 53 targeted checks pass.

## v1.0.52 — 2026-11-19

**Changed**
- Settings now has a single "Variables" page: environment variables and global variables sit behind one segmented switch, with the override rule (environment wins) stated right in the header. The old separate nav entries are gone.
- The AI settings page was rebuilt: switch → provider → key → models → advanced, with a single status line (ready / not configured / off) instead of colored decoration.

**Added**
- AI master switch: keep the key but turn AI off, and every AI entry point goes quiet; key and model choice are preserved.
- DeepSeek support next to Zhipu GLM (DeepSeek-V3 and R1 cards). Each provider keeps its own key and switching brings the right one back.
- "New request from a sentence" on the welcome screen and in the command palette: method, URL, headers, query params and body are filled in, with Content-Type added for JSON.
- "Save response field as variable" in the response more menu: pick a field, get a suggested name, store it globally or in the current environment.
- AI auto-naming with a switch: unnamed or URL-derived request names become human-readable after sending; hand-renamed requests are never touched, and each URL is only asked once.
- "AI script" as the first button on the pre-request and post-response script pages: describe the goal in a sentence and get JavaScript that only uses this sandbox's API; off-topic requests are refused and never written into the editor.
- "AI fill" in the API docs window: appends overview, field meanings and common errors to the generated document — included in copy and "Save .md", and the response sent to the model is redacted while the redact switch is on.

**Verified**
- 654 smoke checks plus 52 targeted checks (variable precedence, per-provider keys, AI switch, script refusal, doc append, one-sentence requests) all pass.

## v1.0.51 — 2026-11-19

**Fixed**
- Tab drag-and-drop is smooth again: reordering now reports once on mouse release instead of syncing `state.json` on every frame, tab widths/rects are cached, and the indicator snaps instead of restarting an animation mid-drag.

**Added**
- Global variables: available in every environment and request via `{{name}}`; a same-named environment variable overrides them. Manage them in Settings → Global variables.
- AI settings page: paste a Zhipu GLM API key and go. Four preset model cards (GLM-4-Flash 250414/latest, GLM-4.5, GLM-4.1V), one-click connection test, plus custom model ID and base URL for proxies or self-hosted gateways.
- AI body generation: in a JSON body, "AI generate" builds realistic data from the existing field names (or param keys), streams it into the editor and formats it when done.
- AI error explanation: available on the failure page and in the response "more" menu — returns the cause plus concrete fixes.

**Changed**
- Sidebar methods longer than 4 characters are abbreviated to 3 letters (PATCH → PAT, DELETE → DEL, OPTIONS → OPT) so names get more room.
- The Params tab of HTTP, WebSocket and Socket.IO no longer offers the File type (query params can't carry files); multipart form uploads keep it.

## v1.0.50 — 2026-11-19

**Changed**
- Request tabs now lift and follow the mouse while being dragged to reorder, leaving a translucent placeholder at the original spot — matching the sidebar's drag feel.
- WebSocket and Socket.IO "Params" pages now include "Paste" and "Bulk Edit", fully on par with HTTP params: bulk import from clipboard, key: value bulk editing, comment lines mark rows disabled, and the final-URL preview updates live.

## v1.0.49 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use three tabs: Chat / Params / Protocol (Auth). Added a real query-parameter table that is appended to the URL on connect, with bulk edit and a final-URL preview.
- Socket.IO Chat page first row is now "Event name" with matching English text; namespace moved into the Auth page; all rows share one left alignment with no functionality lost.
- Sidebar drops the duplicate "New Folder" button; the trash entry moves to the bottom action bar and the delete animation now flies to the new spot.
- Creating a folder now jumps focus to it with a highlight pulse and opens inline rename with a default name: confirm to keep it, type to replace.
- The search box now filters both Collections and History, keeps its text across tab switches, and hides empty history groups.
- Fixed the trash detail popup misalignment in English (truncated labels / uneven value column) with a language-aware label width; also reduced redundant history row rebuilds.

## v1.0.48 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now align their tabs, toolbar rows and inputs to the same left edge as the method badge; both protocols share one baseline.
- Protocol and Auth pages drop the full grey card background, keeping only group titles and thin dividers for a cleaner look.
- Removed leftover collapsed-card state, unused message counters and duplicate helpers to cut dead code.

## v1.0.47 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use the same underline tab style as HTTP requests: WebSocket splits into Chat / Protocol, Socket.IO into Chat / Auth.
- The Chat page keeps only day-to-day sending: namespace, event name, payload, JSON/Text switch, format, save and send.
- Low-frequency settings moved to a second tab: connection parameters for WebSocket, handshake auth and ACK/reconnect options for Socket.IO.
- Socket.IO payload input gains a JSON/Text switch (controls highlighting and formatting), and its "More" menu now shows Socket.IO-specific actions: copy URL, export/clear event log.

## v1.0.46 — 2026-11-19

**Changed**
- Unified the layout of the WebSocket and Socket.IO pages into one skeleton: options row / composer row / editor / frequent chips — matching the HTTP request view while keeping only useful controls.
- The method badge on realtime pages now shrinks to a compact label, giving the room back to the URL field and removing the empty gap after the method name.
- Protocol fields (subprotocol, namespace, auth, event name) now stretch to fill the row and action buttons sit flush right for a cleaner look.
- Low-frequency switches are grouped on their own row and aligned with the handshake-headers button; both realtime pages now look identical, with no clipping in English or Chinese.

## v1.0.45 — 2026-11-18

**Added**
- Socket.IO requests with a dedicated "Events" page, creatable from the New Request menu and command palette.
- Lightweight Engine.IO v4 / Socket.IO v4 over websocket transport: handshake, namespaces, auth JSON, event emit/listen, ACK receipts, heartbeat and auto-reconnect — no extra dependency.
- Distinctive touches: auto-discovered events with one-click filtering, frequent events for one-click reload, double-click an event to load it back, JSON payload highlighting and formatting, clear-after-send.

**Fixed**
- Initialized the ACK registry to prevent a crash, and stopped treating ordinary integer data as an ACK id on server events that request a receipt.
- Auto-reconnect now keeps the namespace and auth; Socket.IO connections are fully closed on exit, leaving no orphans.
- Complete Chinese/English strings for namespace, auth, events, ACK and discovered events.

## v1.0.44 — 2026-11-18

**Changed**
- Trash time groups now use the same chevron as the collection tree, with the item count aligned right like history groups.
- Removed the redundant "Oldest deleted" strip above the trash list.
- Fixed hover cursors: collection tree and history rows now show the pointing-hand cursor again.
- Slightly widened the trash window and filter sidebar so English "Custom" and the date inputs are no longer clipped.
- Filled in missing English strings for the trash tooltip and WebSocket "Connecting to …" log line.
- Added a light dissolve animation for deleting a single history entry and clearing all history: sweep line, soft ring, fade-and-collapse.

## v1.0.43 — 2026-11-18

**Changed**
- Group trash items by deletion time (within 1 hour / today / yesterday / 7 days / 30 days / older), with collapsible headers and expand animations.
- Detail popup now fills with params / headers / body / cookies / auth / variables / sub-requests and scrolls.
- Unified method colors with the theme palette; WS / HEAD / OPTIONS are no longer grey.
- Fixed the transparent context menu by drawing an opaque rounded background; full CN/EN strings.
- Extended clear / restore / delete animations by ~0.5s for a calmer feel.
- Added a lightweight arc-to-trash-button fly animation when deleting from the sidebar.

## v1.0.42 — 2026-11-18

**Changed**
- Calendar weekday header switched to the theme's dark palette instead of the
  system light-grey strip.
- Removed the always-on trash detail panel so deleted records use the whole
  area; "Oldest deleted" moved above the list and aligned with the row icon.
- A small "Details" pill appears on row hover and opens a lightweight detail
  popup, keeping the layout clean.
- Added a 1px hairline separator between the filter sidebar and the list.
- Empty / restore / permanent-delete now play a light artistic animation
  (expanding ring + icon fade-in) with minimal resource use.

## v1.0.41 — 2026-11-18

**Changed**
- Trash stats bar items all aligned left again as before; search box now has a
  visible border so it reads clearly against the dark background.
- Refresh button icon spins one full turn on click for clear feedback.
- Widened the trash filter sidebar so the custom date range inputs are no
  longer clipped.
- Command palette gained "Open Trash" and "Trash auto-clean settings" actions.
- Trash detail simplified back to a short list (URL / contains / deleted at /
  original location) with type and method pills on the title row.

## v1.0.40 — 2026-11-18

**Changed**
- Trash window re-laid out: search moved into the top-right stats bar, the
  redundant activity timeline removed, and the detail panel made richer and
  scrollable (type / method / URL / params / headers / body / env vars /
  original location / exact delete time).
- Custom date range picker restyled to follow the pure-black theme — the
  system calendar's white background, red weekends and purple selection are
  gone.

**Added**
- "Trash auto-clean" switch (on by default) and retention period (7 / 30 / 90
  days) in Settings · Data. Expired items are permanently removed when saving
  settings and on launch.
- Cascade restore hints: selecting a folder also selects its independent child
  entries in the trash, and restoring prompts how many requests come back with
  it. Requests referencing `{{variables}}` get an undefined-variable warning.
- Saving a request now scrolls the left collection tree to the saved item;
  restoring from the trash refreshes the sidebar and reveals items at their
  original position. The Refresh button now re-reads state from disk.

**Verified**
- Self-test suite: 593 checks, 0 failures. Real launch with Trash window OK.

## v1.0.39 — 2026-11-18

**Added**
- Trash for deleted collections / folders / requests. Deletes now move items to
  the trash instead of erasing them, and restore puts the whole subtree back at
  its original position.
- A blurred, fixed Trash window with a distinctive three-part layout: filter
  rail on the left, item list on the right, detail panel at the bottom. Pure
  black minimal theme, no gradients or colored outlines.
- Full trash toolkit: restore, delete permanently, empty, detail view, search
  by name / URL / method, date-range filtering (today / 7d / 30d / custom),
  refresh, multi-select batch actions, an activity timeline and exact delete
  timestamps. Sidebar entry shows the item count.

**Fixed / Changed**
- HTML / XML code highlighting now uses the unified One Dark scheme (blue tags,
  amber attributes, green values, gray punctuation, colored inline script /
  style). `xml` was previously downgraded to the Python highlighter, leaving
  markup almost entirely gray.
- Sidebar delete is now "Move to Trash" with an accurate, reassuring prompt
  instead of an irreversible-delete warning.

**Verified**
- Self-test suite: 579 checks, 0 failures.

## v1.0.38 — 2026-11-18

**Fixed**
- Two expanded message cards could overlap. The list laid out rows using an
  80px estimate for a not-yet-created card, so once the real card turned out to
  be several hundred pixels tall the following rows were drawn right on top of
  it. Layout now creates and measures every expanded card first, then positions
  rows, and checks convergence against the row offsets themselves (not against
  whether card properties changed, which broke out of the loop too early).
- Scrolling to the bottom still hid the last message: the list height omitted
  the expanded card on the final row. Total height now includes that card in
  full, so the bottom edge is reachable.
- Resizing the window narrower reflows long text and changes card height; the
  whole list is now re-laid out on resize instead of only repositioning cards.

**Changed**
- Detail cards no longer show the "响应体" label; the Raw tab and the code box
  are aligned to the same left edge.

**Verified**
- Self-test suite: 554 checks, 0 failures.

## v1.0.37 — 2026-11-18

**Fixed**
- Scrolling over an expanded message card now scrolls the whole log again. The
  read-only code view was swallowing every wheel event (it still scrolled its
  own 1px), so the outer list never moved — the mouse sat on the card and
  nothing happened. Wheel events are now forwarded to the log scroll area.
- The scroll area no longer depends solely on its easing animation to move:
  it lands on the target value even when the animation cannot fire, so the
  wheel always works (including in safe mode).
- Tabs are chosen by **content** again: a plain-text frame shows only **Raw**,
  a real JSON payload shows **JSON / Raw**. Previously every text frame was
  given a JSON tab, so a plain "hello" message and even ERR system messages
  sported a meaningless JSON tab.
- Removed the collapse chevron from the top-left of detail cards; cards stay
  open with their full content visible.

**Changed**
- Code surface background moved closer to the window base (`#171717`-like),
  matching the response panel look the user compared against.

**Verified**
- Self-test suite: 549 checks, 0 failures.

## v1.0.36 — 2026-11-18

**Fixed**
- WebSocket detail code frames no longer render on a dead-black viewport: the
  background now follows the theme's code background (a shade close to the
  window base), so keys / strings / numbers keep the full syntax-highlight
  palette against a surface that matches the app.
- Plain-text frames whose payload is JSON now get the **JSON** tab and syntax
  highlighting too. Previously only frames tagged `json` at send time did,
  which left a JSON body showing a lone **Raw** tab with no colours.
- Expanding a log card no longer lets later frames cover it. The incremental
  append path now uses each open card's real height instead of a fixed 80px,
  and auto-scroll pauses while any card is open — so the expanded content
  stays in view and can be scrolled through.
- The "…" button in the response header now does something in a WebSocket
  session. It opens a WS-specific menu: connect / disconnect, copy URL, copy
  session stats, export the message log and clear it.

**Removed**
- The "Saved messages: store anything you send often…" empty-state hint in the
  WebSocket composer; the chips and their tooltips speak for themselves.

**Verified**
- Self-test suite extended to 550 checks.

## v1.0.35 — 2026-11-18

**Changed**
- WebSocket detail cards were rebuilt around content only: no repeated timestamp / preview
  from the row above. Tabs, copy button and a clean bordered code frame make the hierarchy
  clearer.
- Every expand arrow now uses the same chevron as the collection tree (right when collapsed,
  down when expanded) — both in log rows and in detail cards.
- The code frame can be collapsed. JSON keys and values no longer render in bold.
- The code frame has no scrollbars: it grows to fit all content and the outer log area
  handles scrolling.

**Fixed**
- Multi-line JSON in a log row used to overlap the rows below. Previews are now compacted
  to one horizontal line regardless of how the original was formatted.

**Verified**
- Self-test suite extended to 544 checks; startup-to-show ~547ms; clean exit with an open
  WebSocket connection.

## v1.0.34 — 2026-11-18

**Fixed**
- The URL-bar button still read **Connect** while a WebSocket was open (and after switching
  tabs); it now reads **Disconnect** and stays that way.
- Messages in progress were lost when switching tabs. Drafts and the text / JSON / binary
  choice are stored with the request.
- The input hint showed through Chinese IME preedit text (e.g. `ni'hao` overlaid the hint).
  The placeholder now hides while composing and returns afterwards.

**Changed**
- Log rows expand into inline detail cards: Raw / JSON / Hex tabs, line numbers and a copy
  button. Several rows can stay open at once (capped at 12, oldest closes first so the UI
  never accumulates thousands of text documents).
- JSON details keep their indented layout; row previews stay on a single elided line.
- Counters (received / sent / bytes, uptime / traffic) animate over 280ms instead of jumping.

**Improved**
- Appending frames is incremental and stats use cached counters: 4000 frames append in
  ~2ms, and painting remains limited to visible rows.
- Self-test suite extended to 539 checks.

## v1.0.33 — 2026-11-18

**Fixed**
- Occasional hard crash (`zsh: bus error`, `crash.log` showing `<no Python frame>`) when
  quitting. Shutdown now stops every animation, drops graphics effects, closes sockets and
  tears the window down explicitly instead of relying on Qt / Cocoa destruction order.
- The WebSocket log's empty hint was squeezed into a 1px line (the list is 8px tall when it
  has no rows). It now has its own centred page, with a different message when a filter
  matches nothing.
- **Settings → Appearance → Text size** did nothing: the dialog saved the value and closed,
  so the rebuild step saw "no change". It now zooms in place — the settings page stays open
  and the whole UI resizes as you click.

**Changed**
- WebSocket is a request *kind*, not a method: `WS` is gone from the method dropdown, and a
  WS request is created only from **New request → WebSocket request**.
- WS requests get a dedicated page with only what they need: message editor (text / JSON /
  binary), saved messages, subprotocol, heartbeat, auto-reconnect, clear-after-send, and a
  collapsible handshake-headers editor. The HTTP-only tabs are gone.
- "Export this folder" is now **Export collection**.
- The command palette is shorter — a floating panel rather than a full-height sheet.

**Improved**
- Welcome cards and empty states scale with the text-size setting, so 150% no longer
  overlaps lines.
- Self-test suite extended to 529 checks (WS page, handshake headers, live text scaling,
  palette height).

## v1.0.32 — 2026-11-18

**Added**
- **WebSocket requests.** Create one from **New request**, or switch any request's method to
  `WS`. Addresses accept `ws://` / `wss://`; pasted `http(s)` URLs are rewritten.
- Full WS feature set: text / JSON / binary messages, handshake headers + cookies + auth,
  subprotocols, ping heartbeat with real round-trip latency, exponential-backoff
  auto-reconnect, and live connection stats (uptime, frames and bytes in/out).
- A frame log with direction, type, time and size; filter by Received / Sent, search the
  contents, click a row for the full payload, copy, export to JSON or text, clear. Capped at
  4000 frames so long-running subscriptions stay light.
- Common messages: save recurring payloads as chips, click to load them back. They travel with
  the request in Ocelot / Postman export and come back intact.
- Double-click any received frame in the log to **replay** it: the payload is loaded back into
  the editor so you can tweak it and send again — no copy-paste.
- Settings → Appearance → **Text size** (100% / 110% / 125% / 150%). Scales the whole UI and
  the code area; applies instantly and returns you to the same settings page (unsaved tabs
  are carried over).
- Right-click a folder in the collection tree → **Export this folder** (Ocelot, Postman,
  OpenAPI, HAR). The default file name is the folder name and the exported file keeps the
  same folder structure.

**Fixed**
- Hovering "response time" after a failed request still showed a bogus `9 ms` card. Time,
  size and type are now hidden on failure, and the hover cards are gone.
- In English the `failed` pill was narrower than its label, so the text spilled out of the
  rounded background. Pills now size themselves from real glyph metrics.

**Improved**
- The command palette only paints the rows that are on screen; the rest render as you
  scroll, while search still matches every entry.
- Batch-running a collection skips WebSocket requests.
- Self-test suite extended to 519 checks, including a real local WebSocket server covering
  connect, echo, heartbeat, replay, disconnect and refused connections.

## v1.0.31 — 2026-11-18

**Fixed**
- The backdrop blur was not aligned with the window: it covered the whole window rect
  (including the 8 px shadow margin) and its corners stayed square. It now covers only the
  window card and is clipped to the same 12 px radius, so the arcs line up.
- The command palette had no blurred backdrop, and opening it made the card jump vertically.
  Layout is now fully computed before the palette is shown, and it fades in from 10 px
  above with a 120 ms animation.
- On the failed-request page the **Clear / Copy all** buttons were too loud. They are now
  compact and sit on the same line as the output summary, flush with the content edge.
- History mode showed two **Clear History** buttons (a text one and an icon one); the icon
  one is gone.
- Preview tabs stayed italic after double-clicking a collection item or sending the request.
  They are promoted to a normal tab now.
- The import source list had a large gap between **Import from URL** and **Export all
  collections**; the dialog height now follows the content.

**Added**
- Deleting a collection, folder or request (and clearing history) now asks for
  confirmation. Deleting a folder tells you how many requests go with it.

**Improved**
- The "Blur All Dialogs" description in Settings is a single short sentence.
- Self-test suite extended to 482 checks, all passing.

## v1.0.30 — 2026-11-18

**Fixed**
- The tab pill slide had disappeared: clicking a tab calls `set_current` twice (once from
  the click, once from the selection callback) and the second call snapped the animation
  that had just started. The pill now slides with a subtle velocity stretch, and the
  outgoing/incoming tab labels and method badges cross-fade.
- The modal backdrop was only blurred on the left-hand side. Replaced the Qt blur render
  with a two-stage downsample blur that is uniform across the whole window (about 3.5 ms
  for 1600×1000, a few hundred KB peak memory).
- The success check on the import result page sat left of centre: its icon was centred
  using device pixels, which is 2× off on Retina. It is now centred in logical pixels and
  gets a small expanding halo when it appears.
- Imported collections had the wrong name. The name now comes from the file
  (`info.name`, Apifox collection name, Insomnia workspace, OpenAPI title) or the file
  name, and the collection is created as a folder with that name — inner folders keep
  their hierarchy. A single-request JSON still imports as one request.

**Added**
- `Collections / History` segmented control: the selected pill slides between the two
  labels and the text colour cross-fades.
- Every dialog is centred on its parent window, including when a page change resizes it.
  Only Settings and Import/Export are blurred and immovable by default; other dialogs
  stay unblurred and can be dragged by their title bar.
- New setting **Appearance → Blur All Dialogs**: turn it on and every dialog becomes
  blurred and immovable.
- Command palette: the five most-used commands are pinned under a **Frequently used**
  heading (ordered by real usage, so the list adapts), followed by **All commands**. The
  card is centred and slides down as it fades in.
- **Import from URL**: paste a remote JSON / YAML link (8 MB limit); it downloads and runs
  through the same detection pipeline as a local file.

**Improved**
- Export file names default to the collection (folder) name instead of
  `ocelot-collection`.
- Removed a batch of unused imports and redundant work; the self-test suite now covers
  467 checks and passes.

## v1.0.29 — 2026-11-18

**Fixed**
- The selected tab pill no longer overlaps the neighbouring tab at launch. A pending
  indicator animation kept writing a stale rectangle after the geometry had been snapped;
  the pill now always derives from live geometry, and restoring a session no longer
  animates once per tab.
- Changing the request method (POST → GET) now updates the method badge in the collection
  tree. The editor, the tab badge, the stored node and the saved file stay in sync.
- Switching method after a request no longer throws the response away. The previous result
  stays on screen with a slim "Request changed · showing the previous response" bar that
  offers a **Send again** action.
- Importing a Postman file could fail with "no importable requests": Apifox
  `apiCollection` payloads and Insomnia exports whose requests hang under a workspace were
  parsed as empty. Postman data dumps, Postman v1 collections, Hoppscotch v2 objects,
  files with a UTF-8 BOM and bare single-request files are now recognized too.

**Added**
- Import / export result page: a large check, the title, and a breakdown of what was
  brought in (collections, requests, folders, pre-request scripts, post-response scripts,
  auth, environment variables). Export results offer **Show in Folder**.
- The file page reports what was detected before importing (format plus counts), and the
  sidebar reveals and expands the newly imported collection.
- Environments travel with the collection: Postman dumps, Apifox and Insomnia environment
  resources are imported alongside the requests.
- Dialogs and the settings panel now blur and dim the main window behind them, and the
  modal is pinned in the centre of its parent instead of being draggable.

**Improved**
- The collection search field fills the width up to the import / export button.
- The export page states what will be written ("Exporting 1 collection, 5 requests") and
  disables the rows when there is nothing to export.

## v1.0.28 — 2026-11-18

**Added**
- A **Console** tab in the response panel: `console.log / warn / error` output and `test()`
  assertions from pre-request and post-response scripts, color-coded by level with Pre/Post
  badges, one-click copy, and inline output on the error page so a failing pre-request script
  is still visible when no response arrives. The console also records the outgoing request
  and the final status line.
- An **Import / Export** button next to the collection search field. A single dialog handles
  both directions with a back arrow: import from Ocelot JSON, Postman, Apifox, Hoppscotch,
  Insomnia, OpenAPI 3.x (JSON or YAML) and HAR, plus clipboard import; export as Ocelot JSON,
  Postman v2.1, OpenAPI 3.1 (JSON / YAML) or HAR. Files can be dropped onto the dialog, and
  the chosen file is parsed and summarized before importing.
- **Ocelot JSON** uses Postman v2.1 plus an `x-ocelot` block, so Postman / Apifox can import
  it directly while a round trip through Ocelot keeps scripts, auth and cookies.
- **Rename** in the tab context menu: updates the collection node, the tab title and the
  request itself, saves immediately, and pushes to the cloud when auto-sync is on.
- Clicking a tab now reveals the matching request in the sidebar: switches back to
  collections, expands the parents, clears a hiding filter and scrolls the row into view.

**Improved**
- Script engine hardened: `res.body` / `res.text` now return real text instead of a bound
  method, `req.setHeader` keeps existing rows disabled as before, and `res.json()`,
  `res.setHeader()`, `pw.env.has()`, `pw.env.toObject()` and `test()` were added. Syntax
  errors report the line number the user sees, and endless loops are stopped after 2 seconds
  by a deadline check injected into loop bodies (no background thread, so the process can
  never be aborted by a leftover thread at exit).
- Snippet buttons insert on a fresh line instead of mid-line; post-response scripts get
  response-reading and assertion snippets.
- Body badge no longer copies the whole body on every keystroke.

**Fixed**
- Editing a request and saving never wrote the changes back to the collection node, so
  reopening showed the old content. Tabs now sync into their node on every save.
- After an unclean exit, the next launch starts with animations temporarily disabled to
  avoid the macOS graphics-layer hard crash; focus is released before the window closes.
- All 429 self-tests pass.

## v1.0.27 — 2026-11-18

**Improved**
- The script run status now pairs a thin check/cross icon with the text. Success shows only
  "Ran successfully"; the line is left-aligned with the editor above and sits right beneath
  it, fades in when it appears, and uses the theme's success/danger colors. The icon uses a
  light stroke weight.
- Language switching now walks the widget tree once instead of twice; history group counts
  are computed in a single pass. Duplicate imports and redundant calls were consolidated.

**Added**
- A **Raw** body mode with a JSON / XML / HTML / Text language selector. The selected
  language drives syntax highlighting, formatting and `Content-Type`. All send paths and
  code generators now share one normalization helper.

**Fixed**
- History group titles are translated at paint time, so switching between Chinese and
  English updates them immediately instead of leaving the old language on screen.
- All 395 self-tests pass and repeated real GUI startups are crash-free.

## v1.0.26 — 2026-11-18

**Improved**
- Script **Run test** results now appear in a dedicated dialog. The status line shows only
  "Ran successfully", left-aligned with comfortable padding and a subtle fade-in when the
  text appears. The inline log panel at the bottom of the page is gone.

**Added**
- Params now has a **Bulk Edit** button, so you can edit all query parameters at once as
  `key: value` text.
- History is grouped into **Within the last hour / Today / Yesterday**, with each group's
  collapsed state remembered independently. Group headers now share the same subtle hover
  animation as the other buttons.

**Fixed**
- Fixed an intermittent startup `bus error` crash. The frameless translucent window now fades
  in using native window opacity instead of a graphics effect, and pages hosting native video
  views no longer get a `QGraphicsOpacityEffect` applied.
- All 395 self-tests pass.

## v1.0.25 — 2026-11-17

**Fixed**
- The run status on the script page is now a single line. `console.log()` output from both
  **Run test** and real requests is written to a read-only log panel directly below, so the
  "see logs below" message finally points at something real.
- Editing a pre-request or post-response script no longer wipes out the last response. Script
  changes update the request data and the dirty flag only; the response panel keeps showing
  what you were looking at.

**Improved**
- The auth type name **Inherit** is now always shown in English, matching Bearer, Basic,
  API Key and JWT.
- Params, Body, Headers, Cookies and Auth pages now each get a slim scrollbar. When their
  content is taller than the request pane they scroll on their own instead of being clipped.
- The collection runner uses the theme's subtle hover color for the current row instead of a
  bright gray bar. Clicking a finished row opens that request with its captured response, so
  you can inspect the result directly.
- All 395 self-tests pass.

## v1.0.24 — 2026-11-17

**Improved**
- The script editor is now split into two dedicated pages, **Pre-request Script** and
  **Post-response Script**; the redundant in-page tab switch is gone. The reference panel
  on the right scrolls independently with a slim scrollbar, so overflow no longer pushes
  the controls below out of place. `Run` becomes a clearer **Run test** button with a
  tooltip explaining that it runs the script locally without sending a request.
- History groups now use the same chevron as the collection tree. Click a group header to
  collapse or expand it, and the state is remembered across restarts.

**Added**
- **JWT auth** — auto-generate a signed token with HS256 / HS384 / HS512 or paste one
  manually. Payload and secret support environment variables, and the token is sent as
  `Authorization: Bearer <token>`. Generated tokens match the jwt.io standard exactly.
- **Inherit auth** — walk up the request's collection to find the nearest folder auth.
  Configure it from the folder's right-click **Configure auth…** menu. Both JWT and Inherit
  work on the direct and relay send paths.

**Optimized**
- All 395 self-tests pass.

## v1.0.23 — 2026-11-17

**Added**
- **Pre-request and post-response scripts** powered by Qt's built-in JavaScript engine
  (QJSEngine, zero extra dependencies). Modify the URL, headers and query params before
  sending; parse the response after it arrives. `pw.env.set()` writes variables into the
  active environment and persists them, `console.log()` output is visible, and a broken
  script never blocks the request.
- **Complete body type set** — none / form-data / x-www-form-urlencoded / JSON / XML /
  Text / Binary, with names aligned to mainstream API clients. XML is a new first-class
  type with syntax highlighting, validation, one-click formatting and automatic
  `application/xml` content type.

**Improved**
- Code editor now supports automatic bracket and quote pairing, smart indentation on
  Enter, Tab indentation and wrapping a selection in a pair. JSON and XML can be
  formatted in one click; JSONC line comments are handled.
- One unified syntax highlighting scheme across the whole app — JSON and Python /
  JavaScript / Go / Java and more share a single One Dark style token palette (declaration
  keywords in pink, functions in blue, strings in green, numbers in orange). Request
  bodies, responses, code examples and the script editor all use it.
- The response size card now counts header bytes including the status line, and adds a
  **Request Size** section with separate Header / Body figures. Card background is darker.
- History is grouped by date (Today / Yesterday / N days ago) with a count per group.

**Optimized**
- All 395 self-tests pass.

## v1.0.22 — 2026-11-17

**Fixed**
- **Switching the language in Settings left the right-hand page in Chinese**: the Settings
  window is a separate top-level window that the main window's translation pass could not
  reach. It now re-translates itself on switch, including the page title and nav width.
- **An extra divider line above the response area**: when the metrics bar was hidden, the
  divider below it stayed visible and overlapped the splitter handle. The divider now shows
  and hides together with the metrics bar, leaving a single line.
- **"New Mock Route" / "New Condition Rule" dialog titles were not translated** in English.
- **Timeline stats and "No Wrap" were not translated**: hit count / success rate / average /
  P95 / slowest, plus the raw view's wrap toggle, stayed in Chinese under English.

**Improved**
- Request panel tab order is now Params / Body / Headers / Cookies / Auth, with the most
  used Body tab moved to second place.
- Code examples in the API doc now share one fixed height: switching languages no longer
  makes the block jump between sizes; overflow scrolls inside.

**Optimized**
- All 395 self-tests pass.

## v1.0.21 — 2026-11-17

**Fixed**
- **The history list went blank in English**: the sidebar's segmented tabs did not recompute
  their widths after a language switch, clipping the `History` segment. Tabs now re-measure.
- **Command palette action names stayed in Chinese**: new request / send current request and
  others were untranslated, as were "Default" in the format menu and "Click to choose a
  file…" in file cells.
- **A chosen file in the request body could not be sent**: the code used the display text
  as the path, which becomes `No file chosen` in English and was treated as empty. The path
  is now stored separately from its display text.

**Improved**
- Settings header and footer hints wrap automatically, so long English text is no longer
  clipped at the window edge.
- English copy reviewed throughout; terminology keeps aligning with Postman.

**Optimized**
- All 395 self-tests pass.

## v1.0.20 — 2026-11-17

**Fixed**
- **Square window corners**: the rectangular content layer covered the window's own rounded
  corners. The content layer now has a rounded mask that follows the window, disabled when
  maximized.
- **Gray squares next to selected response-tree rows**: the indent cell got a system hover
  background. The highlight is now fully transparent while selected text stays highlighted.
- **Two rapid requests crossed streams**: an old request's `finished` signal treated the new
  request as done, leaving the spinner running or showing the wrong response. Results are
  now matched by signal source and stale ones are discarded.

**Improved**
- Settings / What's New footers no longer print `Ocelot x.y.z · Python + PyQt6`.
- The About page drops the runtime (Python / PyQt6) and "native macOS window" tags.
- Full English pass: toasts, placeholders, tooltips, Settings pages, Mock hub; terminology
  aligned with Postman (Send / Params / Headers / Cookies / Environments / Mock Server),
  with no source text lost when switching languages.

**Optimized**
- Large arrays only render the first 300 items with a "… {n} more" trailing row; even
  200,000 items open instantly.
- Added a crash log: hard crashes and uncaught exceptions are written to `crash.log` in the
  data directory.
- 395 self-tests.

## v1.0.19 — 2026-11-17

**Fixed**
- **Clicking "More → Mock data…" crashed**: the editor was missing the `mockRequested`
  signal and raised `AttributeError`; "Copy request" in the same menu had the same issue and
  was fixed too.
- Mock / Copy request in the More menu are now forwarded uniformly by the editor, with a
  single signal connection — one click no longer opens two windows.

**Improved**
- Response tree view: row height 16 → 21; the key column is sized to its content so
  `two_factor` is no longer truncated to `two_fa…`.
- The API doc footer now prefixes the status line with a "Status" label instead of showing
  a bare string of words.

## v1.0.18 — 2026-11-17

**Fixed**
- **Right-clicking inside an input crashed**: `QApplication` has no `cursor()` method and
  raised `AttributeError` when resolving the click position. The context menu now uses the
  screen coordinates carried by the event, falling back to the mouse position only if needed.
- **Mock showed "Stopped" but a browser refresh still worked**: stopping closed the listen
  port, but an existing HTTP keep-alive connection kept being served. Stopping now actively
  drops all live connections and responses no longer request connection reuse.
- Stopping now disconnects in-flight connections before closing the port, so no response can
  "arrive after stopping".

**Optimized**
- Self-tests expanded to 382 checks, including right-click positioning and the guarantee
  that stopped services return no data.

## v1.0.17 — 2026-11-17

**Added**
- **Mock conditional rules**: one route can return different results based on request
  header / query param / body / method — return VIP data with a `token`, 401 without it,
  covering both happy and error paths. Rules support equals / contains / exists / not
  exists, with their own status code, delay and response body.
- **Mock dynamic data**: write placeholders like `{{@id}}` `{{@uuid}}` `{{@name}}`
  `{{@cname}}` `{{@email}}` `{{@now}}` `{{@int(1,99)}}` `{{@pick(a,b)}}` in the response body;
  each request recomputes them. Editing a route offers "Preview random data".
- **Mock request log**: a new "Request Log" page shows each request's method, path, status,
  latency and matched route / rule in real time, with 2xx / 4xx / average-latency counters
  and a one-click clear.
- Route lists show a hit count per route.

**Improved**
- The start button now follows the real state: "Start Service" when stopped, "Stop Service"
  when running (previously hard-coded).
- The API doc table was rebuilt: a dedicated header bar, row dividers, a first column
  measured and clamped to 96–210, and word wrap for long content.
- Code examples: language labels align strictly with the code body; long lines are wrapped
  and sized by their real line count, with no half-cut lines or stray scrollbars.
- The Settings menu's "Settings…" is now a gear icon; "Switch Light / Dark" was removed
  (the theme is still under Settings → Appearance).
- The About page drops file names and class names for a user-facing capability list and a
  "what one request goes through" walkthrough.

**Fixed**
- Stopping could leave the port occupied (another instance or a leftover process): it now
  waits for the port to be truly released and reports honestly; if another Ocelot owns the
  port, it says so and switches automatically.
- Dynamic data containing Chinese characters broke the HTTP response when written into a
  header; it is now safely encoded.

**Optimized**
- Self-tests expanded to **374 checks**: menu entries, button states, placeholder randomness,
  rule matching, log latency, table column widths, code-block alignment and long-code scroll.

## v1.0.16 — 2026-11-17

**Added**
- **A real local Mock service**: an actual HTTP server on `127.0.0.1` whose routes, methods,
  status codes, delays and bodies you define. Supports prefix wildcards `/api/users/*`,
  echo mode (returns the request verbatim), CORS, and can be reached directly from a browser
  or script; "Try" builds a request in one click, and it can start with the app. If the port
  is taken it switches automatically.
- **Two Mock hub pages**: local Mock manages routes (create / edit / copy address / delete),
  while the public API catalog keeps 28 free endpoints (click a row to fill a request).
- **Shortcut settings**: all 16 actions are editable — click a keycap to record, clear in one
  click, restore defaults. Two actions competing for the same key make the older one step
  aside, and changes take effect immediately.
- **Fuller API docs**: overview (method / URL / status / latency / size / content type), auth
  notes, cookie table, response header table and status-code semantics; copying or saving
  produces a deliverable document.

**Improved**
- API doc window reflowed: a request card on top with status / latency / size metrics, a left
  outline that tracks scrolling, and cached code examples per language.
- Ten languages in code examples share syntax highlighting (CLI flags, URLs, strings and
  numbers each colored); code aligns strictly with the language label.
- Command palette entries are no longer clipped: a scrollable list with eased wheel input,
  keyboard selection auto-follow and cards clipped by whole rows.
- Mock public API list rebuilt as sub-widgets + layout: method / URL / description align
  strictly; search debounced at 120ms.
- The title bar's settings button is a real gear icon (previously a sun-like set of rays).
- Settings dialog widened to 940×700; About drops the shortcut table for four "Why Ocelot"
  advantages and a six-layer architecture note.

**Fixed**
- A query param already present in the URL was appended again in code generation and docs
  (`?a=1&a=1`); it now compares first, then appends.
- The Mock panel's status pill and button enable state were out of sync after start / stop.

**Optimized**
- Self-tests expanded to **351 checks**: a real local service for route / echo / 404,
  shortcut recording and conflict hand-off, command palette scroll, code-block alignment and
  highlighting, and the new doc sections.

## v1.0.15 — 2026-11-17

**Added**
- **API doc window**: "View API Doc" under "More →" at the top right of the response. Method /
  URL / param table / headers / body / response example on one page, a left outline to jump
  between sections, ten languages of code examples at the bottom with one-click switching,
  a toggle to mask tokens, and copy / save as `.md`.
- **Mock data panel**: 28 built-in free public APIs (httpbin / JSONPlaceholder / DummyJSON /
  ReqRes / random images…), searchable and grouped; a click fills a ready-made request.
- **Response timeline**: a new "Timeline" tab plots this URL's latency history as bars colored
  by status code, with hit count / success rate / average / P95 / slowest on top and hover
  details for each run.
- Command palette ⌘K gains Mock Data, API Doc, Copy Current Request and Close Tab.

**Improved**
- Param table headers align with data rows (checkbox placeholders are real controls, the
  "Type" header is centered).
- URL history completion is a custom-drawn overlay: rounded, clock icon, monospace URL,
  up/down to select.
- Settings reflowed: cloud sync address / token / button on one row, no longer squeezed;
  dialog widened to 900×672.
- About page rebuilt: a large title, version pill, three-column runtime info, two-column
  shortcuts and a copy-version action.

**Fixed**
- Right-click on selectable text in response headers and doc bodies still used the system
  menu (English, translucent); it is now taken over consistently.

**Optimized**
- Self-tests expanded to 312 checks.

## v1.0.14 — 2026-11-17

**Added**
- **One-click API docs**: "More →" in the response copies a full Markdown document (method,
  URL, query, headers, body, status code, latency, size, response example). A tab right-click
  offers "Copy API Doc (Markdown)" so each request can be exported without hand-writing docs.
- **Secret masking**: the same menu can "Copy response body (masked)" or export a doc with
  "secrets masked". `token` / `cookie` / `password` / `authorization` / JWT / `Bearer xxx`
  become `••••••` (long values keep the last four characters so you can confirm it is the
  same key). Safe to paste into chat, tickets or screenshots.

**Improved**
- Code generation (cURL / Python / JavaScript / HTTPie) now merges rows from the Cookies tab
  into the `Cookie` header; disabled rows are not exported, so generated code matches what
  "Send" actually does.

**Fixed**
- Runtime log prefixes still saying `Reqly` (save response / save config failures) are
  unified to `Ocelot`.

**Optimized**
- Self-tests expanded to 312 checks: every doc section, masking rules, long-value truncation,
  JSON structure comparison and cookies in generated code.

## v1.0.13 — 2026-11-17

**Renamed**
- Reqly → **Ocelot**. Title bar, About page, menus, User-Agent and data directory all changed;
  on first launch the old `~/Library/Application Support/Reqly` data is migrated so nothing
  is lost.

**Added**
- Requests gain a **Cookies** tab: table rows are merged into the `Cookie` header (coexisting
  with a hand-written one), and `Set-Cookie` in a response can be imported in one click so
  login sessions carry over.
- **Cloud sync (Turso)**: set a database URL and Auth Token in Settings; "Test Connection"
  runs a single `SELECT 1`; upload / restore from cloud (restoring backs up `state.json.bak`
  first), with an option to auto-upload on exit. Uses only Turso's HTTP pipeline, no new
  dependencies.
- URL bar completes from history: focusing it lists previously used URLs containing the
  current text, so a few keystrokes are enough.
- Command palette ⌘K can switch environments and jump straight to Appearance / Cloud Sync.

**Improved**
- The accent color now drives more than buttons: selection backgrounds, focus outlines,
  hover badges, tab titles and underlines, sidebar selection markers and Settings nav all
  follow it, with body text tinted slightly toward the accent — one coherent color temperature.
- Param type pills drop their outline; Auto gets its own warm-sand color at a larger size,
  clearly distinct from Null's gray and JSON's orange.

**Fixed**
- A black ring around checked checkboxes (the default pen also drew one) — the checked state
  is now a solid block only.
- The first accent swatch's selection ring was clipped by the card edge.
- Tab right-click "Copy as cURL" did nothing (`to_curl` was not imported, `NameError`).
- Qt's implicit cookie jar silently rewrote hand-written `Cookie` headers; it is now neither
  read nor written, and cookies are managed explicitly by the Cookies tab.

**Optimized**
- Removed two unreachable blocks in Settings, duplicate and unused imports in the main window;
  request counts and cookie hints merge into one refresh.

## v1.0.12 — 2026-11-17

**Added**
- Settings · Appearance gains an **Accent Color**: seven swatches (auto / ocean blue / pine /
  moss / terracotta / crimson / violet); buttons, switches, checkboxes and the send key follow
  immediately. "Auto" keeps the original black-and-white inversion.

**Improved**
- The param type menu's Auto now has its own color (warm sand), clearly distinct from Null's
  gray and JSON's orange.

**Fixed**
- Switching color scheme / accent rebuilt a destroyed hover detail card and crashed while
  painting — destroyed widgets are now skipped.
- Switching schemes only refreshes visible widgets; hidden ones repaint naturally when shown,
  making large windows much smoother.

**Self-tests**
- 228 checks: accent switching and persistence, swatch count and clicks, Auto vs Null contrast.

## v1.0.11 — 2026-11-16

**Fixed**
- After launch, tabs did not respond and content would not switch: the tab strip now emits
  its change signal unconditionally; the main window also self-heals a wrong editor request
  or a ghost tab, re-checking when the window regains focus.
- An error midway through `RequestEditor.load` left the loading flag stuck at True, so every
  later edit stopped writing back ("clicking does nothing") — a `finally` block now clears it.

**Optimized**
- Sidebar collapse / expand stutter: the splitter was clamped to the sidebar's minimum size
  (≈158), so the first two thirds of the animation did nothing and the last frame vanished.
  During animation the minimum size and size policy are relaxed, then restored — the slide is
  now truly frame-by-frame.
- Switching tabs and receiving responses no longer writes to disk synchronously (batched to
  one write per 700ms); the history list refreshes incrementally instead of rebuilding
  hundreds of widgets.
- Re-clicking the current tab no longer re-formats the whole response, making large JSON
  switches noticeably smoother.
- Large responses render on demand: the JSON tree and "Raw" tab are built only when opened —
  a 190KB response drops from 1 second to 60ms. Above 600KB only the first 600KB is previewed
  with a hint to "Save As" for the full text, and syntax highlighting is skipped above 180KB.

**Added**
- Extract results can be "Saved as Variable": one click writes into the current environment
  for later `{{name}}` references, so a login token no longer needs copying by hand.
- Middle-click a tab to close it; double-click the divider between request and response to
  restore a 50/50 split.
- Double-clicking an italic preview tab pins it (VSCode behavior); previously double-clicking
  a tab did nothing.

**Self-tests**
- 219 checks: tab self-healing, middle-click close, divider reset, save-as-variable,
  frame-by-frame sidebar animation and incremental history refresh.

## v1.0.10 — 2026-11-16

**Added**
- **Collection runner**: right-click a folder → "Run Collection" or ⌘⇧R to run every request
  in tree order, showing status / latency / size per request and a success / failure / total
  time summary; stop at any time, copy the whole result table (TSV pastes straight into a
  spreadsheet), and click a row to open that request.
- Param type gains File: pick a local file in a form row and upload it as real multipart, with
  code generation reflecting the file param.
- cURL import dialog: paste to parse with live preview, supporting `-X / -H / -d / -F / -u /
  -G / --data-urlencode` and merged short flags like `-sSL`.
- Request tab right-click: Close Others / Close All / Duplicate Tab / Copy as cURL.

**Improved**
- Code snippets expanded to 10 languages (adding Go / Java / PHP / C# / Kotlin /
  PowerShell), all syntax highlighted.
- Format / encoding / type dropdowns are custom-drawn, no more garbled native checkmarks;
  the method palette was reordered to match the reference image and "Custom" removed.

**Fixed**
- Pretty-printing squeezed HTML into one line, or into a staircase running right: it is now a
  token stream — inline tags stay on one line, `script` / `style` / `pre` content is preserved,
  CDATA is not split, and unclosed tags are tolerated.
- Detail card icons never lined up — root cause was `QPixmap.width()` returning device pixels
  (2× on Retina); the dpr is now factored in to center them correctly.
- Clicking a request tab's content did not switch pages and edits were lost — the tab strip
  now genuinely emits a change event.

**Self-tests**
- 196 checks: runner order and summary, file type, pretty-print structure, icon centering and
  tab switching.

## v1.0.9 — 2026-11-16

**Improved**
- Param types use capitalized English names (Auto / String / Number / Boolean / Null / JSON),
  each with a semantic color; String is green.
- HTTP method palette matches the reference: GET green / POST orange / PUT·HEAD·OPTIONS blue /
  DELETE red / PATCH pink / TRACE purple, with "Custom" removed.

**Added**
- Code snippets add Go / Java / PHP / C# / Kotlin / PowerShell, with multilingual highlighting.

**Fixed**
- Type / format / encoding dropdowns switched to custom-drawn menus, eliminating garbled
  macOS native checkmark glyphs.
- The "Expand All / Collapse All" buttons that appeared when selecting text are now fully
  hidden, leaving only format and encoding in the toolbar.
- Detail card icons misaligned and footer text overlapping the Body row: the title and metric
  row icons now share one size and x position, and all blocks accumulate sequentially.
- Clicking a request tab did not switch content and lost edits — TabStrip now emits
  currentChanged correctly.

**Self-tests**
- 186 checks: type colors, custom menus, detail-card alignment, code languages and tab
  switching.

## v1.0.8 — 2026-11-16

**Improved**
- Response Time / Size hover cards use a fixed anchor instead of following the mouse; the
  custom-drawn layout was rebuilt with segmented icons.
- Format / encoding buttons now use the same custom control, shown only on the "Pretty" tab.

**Added**
- The size card adds a Header / Body allocation bar; the time card adds an "estimated" note
  so each segment is not misread.

**Fixed**
- After changing the URL to time-tx, the previous image response was still shown — any
  request edit now invalidates the old response.
- After opening several request tabs their content merged together — responses, format,
  encoding and the current response sub-tab are now stored per tab.
- After dragging the sidebar width the URL bar disappeared and the description floated up —
  an interrupted animation now restores its paint state completely.

**Self-tests**
- 167 checks: fixed cards, button isolation, per-tab responses and animation-interrupt recovery.

## v1.0.7 — 2026-11-16

**Fixed**
- Sidebar collapse froze in two stages — the animation wrote to disk on every frame via
  `splitterMoved`. The signal is now disconnected during animation with a single write at
  the end.
- A new empty tab and an opened old request ended up with identical content — each tab is now
  an independent snapshot and collection tree changes only sync titles, not edits.
- The spinner never started on send, making the app look stuck — it now really spins with a
  skeleton shimmer.

**Added**
- Single-click a sidebar item enters VSCode-style preview (italic title, reused preview tab);
  double-click pins it.
- Param types use English names (auto / string / number / boolean / null / JSON).
- Settings → General adds a language switch (简体中文 / English), translated naturally and
  applied immediately across the whole UI.
- Node speed tests now cover every node (previously only 8), with controlled concurrency,
  a progress indicator, and a note that speed does not imply availability or overall latency.
- Response gains a format switch (Auto/JSON/XML/HTML/Text) and 11 encodings (UTF-8/GBK/Base64…).
- Hover detail cards over response time / size: segmented bar chart (DNS/TCP/SSL/TTFB/
  download) plus size breakdown.

**Self-tests**
- 155 checks: tab isolation, preview open, language switch, format / encoding, timing detail
  and spinner state.

## v1.0.6 — 2026-11-16

**Fixed**
- Only 22 nodes were listed — now the full 221 IPv4 / 130 IPv6 nodes are fetched, refreshable
  at any time.
- The gray bar in the method menu / command palette kept following the mouse after leaving —
  hover is now strictly bounds-checked.
- Sidebar collapse / expand stutter — the content repaint was frozen frame-by-frame during
  animation and the collection tree was no longer fully rebuilt at the end.
- Image / audio responses showed a row of question marks in Pretty / Raw — now a hint plus
  hex view, defaulting to Preview.
- After a title changed the pill width did not follow, swallowing the "+" into the pill; the
  collection tree showed left/right arrow cursors.
- A toast's underlying object was destroyed but still called, causing a crash.

**Added**
- Online nodes really work: the selected node forwards requests via a node server, with exit
  IP, region and latency annotated in the response metrics.
- The "Local" button moves to the right of Send; the node panel gains a refresh button and
  IPv4 / IPv6 counts.
- Preview gains "Save": images / audio / video / PDF / binary can all be saved locally.
- Settings gains an "About Ocelot" page and a "View What's New" entry; the changelog panel
  is color-coded by category.
- Param table gains a "Description (optional)" column used only as a note, never sent.

**Self-tests**
- 134 checks: indent gray block, menu reuse, zero-latency hover, toast sizing, three preview
  types, node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding
  and media container detection.

## v1.0.5 — 2026-11-16

**Fixed**
- Gray blocks to the left of selected collection-tree rows (the base class painted the indent
  area with the selection color) — the indent area is no longer painted and the selection
  background is transparent.
- Opening the method menu a second time crashed (`RuntimeError: MethodMenu has been deleted`)
  — the menu is now reused as a persistent object.
- The command palette's gray hover bar lagged behind the mouse — tweening was removed for
  zero-latency following, and the keyboard row uses a thin border instead of stealing focus.
- System toasts were large and empty — replaced with a custom-drawn toast sized to its text.
- Right-clicking an input opened the English system menu — replaced with a custom Chinese menu
  (Undo / Redo / Cut / Copy / Paste / Delete / Select All) with icons.
- gzip / deflate / br compressed bodies showed as gibberish or blank — they are now decompressed
  by `Content-Encoding` (with gzip-header sniffing as fallback).
- GBK / GB18030 pages showed garbled Chinese — when no charset is declared, UTF-8 then
  GB18030 are tried in order.

**Appearance**
- Unified base color: sidebar and workspace both use `#19191C`, removing the "half dark, half
  lighter" look and leaving a single 1px divider.
- Settings gains six color schemes: Graphite (default `#19191C`) / Slate / Warm Gray / Pine /
  Ink / Light; click a thumbnail to switch.
- Settings was rebuilt: section cards, scrollable content and a clearer information hierarchy.
- Sidebar is draggable 200–420 px and remembers its width; the title bar gains a collapse
  button (⌘B still works).
- The selected tab pill drops its outline.

**Added**
- "Preview" upgraded: image wheel zoom / drag pan / double-click fit / checkerboard transparency;
  embedded audio and video playback; PDF and binary get an "Open" and hex view; image / audio /
  video responses auto-switch to Preview.
- Media containers are detected by magic bytes (wav / mp3 / ogg / flac / m4a / webm / mov)
  instead of all being saved as unplayable `.bin`.
- "Nodes": the URL bar can select IPv4 / IPv6 nodes, searchable by region and ISP with one-click
  speed tests (TCP + DNS round trip), defaulting to "Direct". socks5 / http proxy nodes can be
  added and requests genuinely route through them, with metrics annotated.
- Network settings gain a default User-Agent; data settings gain a history limit.

**Self-tests**
- 108 checks: indent blocks, menu reuse, zero-latency hover, toast sizing, three preview types,
  node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding and
  media format detection.

## v1.0.4 — 2026-11-16

**Look & feel**
- Dark theme rebalanced around `#19191C`: five levels of gray for window / panel / card /
  overlay / selection; a content surface between sidebar and workspace so the boundary is no
  longer blurred.
- Method menu is custom-drawn: each method has a color, the current item shows a checkmark,
  row heights align and there are no native-menu rough edges.
- Removed all colored dots (collection tree, environments, tab strip) in favor of vector icons
  and status badges.
- Hover toasts use a rounded capsule style (smaller text, looser line height, no border burrs).
- Command palette hover uses a soft gray layer with 120ms easing, selected row gets a thin
  border instead of a hard cut.
- The tab strip's "×" and "+" were reflowed with ≥10px spacing.

**Params (rebuilt)**
- Add, remove, move up / down and copy / delete any row at any time.
- A new "Type" column: Auto / String / Number / Boolean / null / JSON, applied with the correct
  type when sent.
- Smart paste: `token=abc&debug=true`, `{"q":"x"}`, multi-line `k: v` or Tab-separated and `#`
  comment lines are split into rows in one paste, with comments auto-disabled.
- URL ↔ param table two-way sync: a URL with `?a=1&b=2` is split into the table and the URL
  keeps only the base; clearing params no longer leaves ghost params that break the request.

**Added**
- "Compare": auto line-by-line diff of this URL's response against the previous one, marking
  status code and latency changes, with a manual "Set as baseline".
- "Extract": use a JSON path like `a.b[0].c` or `*` to pull a field, with a hint listing valid
  top-level fields on error and one-click copy.

**Settings**
- Consolidated into a single page of six sections (General / Appearance / Network /
  Environments / Data / What's New) instead of nested dialogs.
- Code font size in three steps (Small / Standard / Large), applied to all open code areas
  immediately.
- The changelog panel was rebuilt: blocks per version, colored by category, word-wrapped,
  with a scroll that no longer stutters or overlaps.

**Self-tests**
- 80 assertions: param type inference, URL split, no ghost params, three paste formats, six
  Settings pages, diff stats and JSON path extraction.

## v1.0.3 — 2026-11-16

- Fixed a crash when the mouse moved over the collection tree (`RuntimeError: wrapped C/C++
  object of type QVariantAnimation has been deleted`) — the hover animation is now a
  persistent object instead of being destroyed at animation end.
- Added a "repeated hover" regression: sweep the collection tree three times, wait for each
  animation to finish and destroy before triggering again — 56 assertions.
- Sidebar-collapsed interaction tests now expand the sidebar first so no checks are skipped.

## v1.0.2 — 2026-11-16

- Fixed a crash when hovering the tab strip (`TypeError`: `QRectF.contains` only accepts
  `QPointF`, but got `QPoint`) that also killed the app when launched from the IDE.
- Startup self-check: on an old interpreter or missing PyQt6, print the interpreter path and
  a fix command instead of dumping a traceback.
- When launched from the run panel, bring the window to the front (`raise` + `activateWindow`).
- Added mouse-interaction regression: tab hover / click-to-switch / double-click blank to
  create, sidebar and segmented control sweeps — 53 assertions.
- Screenshot scripts now use a temporary state file instead of overwriting the real session
  (history, theme, open tabs).

## v1.0.1 — 2026-11-16

- Fixed: after switching from dark to light theme, JSON property names became nearly white
  and invisible on the light background (re-colored on theme switch).
- Fixed: the screenshot script overwrote real session data (now reads / writes a temp file).

## v1.0.0 — 2026-11-16

The first version: a pure-black, minimal API debugging tool with native macOS polish.

**Interface & motion**
- Borderless rounded window + traffic-light buttons (icons on hover), edge drag-resize,
  double-click title bar to zoom.
- Dark / light themes, pure-black layers, inverted solid primary buttons, no gradients or
  colored glows.
- All icons are 24×24 custom-drawn vector strokes, theme-colored and crisp on Retina.
- Animation: window fade-in, page cross-fade, response fade-in, segmented tab sliding underline,
  sliding selection pill, counting latency numbers, toast slide-up, sidebar collapse and
  loading skeleton shimmer.

**Request building**
- Method picker, URL input, query params and headers (enable switch / auto-append empty row /
  header autocomplete / bulk edit).
- Body: none / JSON / text / form (multipart with `@file` upload) / x-www-form-urlencoded /
  binary.
- Live JSON validation and format / minify.
- Auth: Bearer / Basic / API Key (Header or Query injection).
- Environment variables with `{{$timestamp}}` / `{{$uuid}}` / `{{$randomInt}}` dynamic variables.

**Send & response**
- Async cancellable send, timeout / follow-redirects / SSL-verify toggles, proxy (auto /
  system / direct), cookie persistence and parsing.
- Response metrics (status, latency, size, type, final URL).
- Six response views: Pretty / Tree / Raw / Headers / Cookies / Preview; in-response find and
  highlight.
- Copy response body, save to file, error-state hints.

**Organization & reuse**
- Collection tree (unlimited depth, drag sort, right-click menu, search filter, open-state dots).
- History (click to restore, hover to delete, clear).
- Multi-tab (drag reorder, sliding indicator, session restore).
- Environment variable management with active switching.
- Code generation: cURL / Python / JavaScript / HTTPie.
- cURL import, collection import / export (Postman v2.1 compatible).
- Command palette ⌘K, global shortcuts, Settings and What's New dialogs.
## v1.0.61 — 2026-11-19

**Changed**
- **Back to the thin-line ocelot head you picked**, and this round only makes it accurate rather than redesigning it.
- **The crown is fixed**: the two inner-ear curves meet the middle on one shared horizontal tangent, so the seam has no kink — it reads as a single arc from ear to ear instead of two triangles with a plateau between them.
- **The jaw is rounded**: the base narrows and closes on a real circular arc, so the face no longer reads as a cup or a bag.
- The widest point moved to eye height, with the outline narrowing both above and below; the ear root carries only one very light turn instead of a shoulder.
- Stroke dropped from 4.5% to 4% — finer and crisper at large sizes, still floored at 1.05px for small ones.
- The ink-writing hover animation is kept and refined: a three-dot trail behind the nib gives the stroke some speed, and each spot blooms a soft glow instead of a drawn ring.
- After the stroke finishes, the mark eases back slightly (4.5% → 3.9% scale) while staying lit — like a hand releasing the pen.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.60 — 2026-11-19

**Changed**
- **The mark is now a solid silhouette**: a standing ocelot facing right, tail sweeping up behind into a fine arc. Built the way magpie's icon is built — one solid mass, with the background cut out to describe structure, instead of stroked line art.
- Only two negative spaces, both structural: an arch under the belly and a round eye. The head sits on the shoulder with no gap; round haunch, slim front leg, small round paws, low in front and high at the back.
- **Hover animation rebuilt for a solid mark**: the mark lifts 1% and scales 3.5%, the tail swings 4° around its root, and a point of light blooms inside the eye's cut-out — like the cat opening its eye. Everything eases back in 640ms on leave.
- Re-checked at small sizes: ears, legs and tail still read at 16px, and the 21px title bar no longer smears.
- The dock icon keeps the white rounded square, now with a near-black silhouette inside.
- Exported SVG assets are filled paths now (fill-rule: evenodd), so the asset and the app are the same shape.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.59 — 2026-11-19

**Changed**
- **The mark is redrawn thinner and sharper.** Stroke went from 5 to 4.3 units (~4.5% of the size) and the head is now one continuous curve — pointed ears, round cheeks, narrow chin — so it no longer smears into a blob at 21px in the title bar.
- **Hover animation is now "ink writing itself"**: a bright line leaves the chin, traces the whole contour, a small firefly rides the pen tip, and each spot blooms as the ink reaches it. The mark lifts, a faint light rises around it, and on leave the ink retracts along the same path in 620ms.
- Fixed why the old animation looked static: Qt measures dash length in pen widths, so the whole outline lit up at once instead of being drawn.
- The animation is no longer clipped by the widget bounds (6% inner margin, no more head tilt).
- At 40px and up the mark breathes — one 7-second cycle, so it is never quite still.

**Added**
- The dock icon is now a white rounded square with near-black line work, clean on any wallpaper.
- The response panel's "ready" empty state uses the brand mark and draws it once on open.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.58 — 2026-11-19

**Added**
- Line-art ocelot wordmark as the app logo: the welcome screen, the title bar (left of the title), the About card and the Dock icon now share one vector mark that follows the theme.
- Hover animation on the mark: the outline redraws itself from start to end, the whole mark lifts and scales slightly, and the two spots pop in with a spring. Leaving reverses the same curve. The About page plays it once on open.

**Changed**
- **Resource Manager trimmed down**: four metric tiles and six panels became three blocks — memory, storage, health — so there is nothing extra to interpret.
- The window shrank from 1080×800 to 656×452 and lost its scroll area.
- The maintenance strip went from four buttons to two: **Free memory** and **Clean up** (expired trash + backups older than 7 days + cached analyses), with a single combined report.
- Dropped the object-type scan (which walked tens of thousands of Python objects every refresh) and runtime widget counters; sampling is now every 3 seconds, so the dashboard costs less memory and CPU itself.
- Disk free space folded into the storage card as one line instead of its own card.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.57 — 2026-11-19

**Added**
- **Resource Manager** (settings menu, top-right): a real dashboard for memory, storage and runtime, fully bilingual and theme-aware.
- Memory: resident size read straight from libproc (no `ps` subprocess, works in restricted environments), peak, whole-machine pressure, and a 2-second sampler that draws the last three minutes with min / avg / max.
- Storage: app data split into state file / auto backups / logs / other, with proportion bars and per-group sizes, plus disk free space. The data folder path lives in a tooltip so it does not eat the layout.
- Runtime and assets: top 5 object types, threads, widgets, allocated blocks, and six counters for requests, collections, history, trash, environments and tabs.
- Maintenance strip: free memory (GC + icon / pixmap caches), clear analysis cache, purge expired trash, remove backups older than 7 days — each reports how much was released.
- Health score: weighted from system memory pressure, app data size, history volume and expired trash, with up to three actionable hints.

**Changed**
- AI analysis cache now expires after **8 minutes** instead of 30; the "Cached" tooltip follows the real value.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.56 — 2026-11-19

**Fixed**
- Trash folder detail: labels and values now share the same top alignment, so the three rows sit on one baseline instead of stepping down.
- English UI: AI status line, API-key hint, model heading, variables note, history count, about-page data path and settings title were built by string concatenation at runtime, so the generic translator could not match them as whole sentences. They are now rebuilt from templates on language change, in both directions.
- The conclusion block no longer has the text sitting above/below its side rule: the rule spans the full block and the text is vertically centred.

**Changed**
- Conclusion is now a theme-coloured quote block with a small theme-coloured dot before each section heading.
- Response panel's Auto / UTF-8 switches lost their pill border and fill, matching the rest of the toolbar.
- Hovering "Cached" shows the real expiry time (30 minutes) and a hint to re-analyse; translated in English too.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.55 — 2026-11-19

**Fixed**
- "Analyzing" no longer jitters: the status text stays put while only the spinner moves; streaming refreshes are throttled to 90ms.
- AI analysis layout rebuilt: the conclusion is a card with a side rule, evidence and recommendation lists use a separate bullet / 01-02 column so wrapped lines align with the text instead of snapping back to the left margin. Body text is brighter and larger, and bold fragments are highlighted.

**Added**
- Analysis cache: reopening an already analysed tab shows the saved result instantly instead of calling the AI again. Results are keyed by tab + request + response, shown as "Cached", capped at 8 entries, expired after 30 minutes, and cleared on close or data reload.
- "AI-generated · verify against the raw response" hint in the dialog footer.

**Changed**
- The analysis prompt is now a professional troubleshooting framework: HTTP status and business codes are strictly separated, findings are ranked (blocking / warning / note / normal), and every claim must cite a concrete field and value. All 11 tabs have their own focus; output budget raised to 1400 tokens, and a duplicated "focus:" prefix in the prompt was removed.
- Entry fade-in is 190ms; cache hits get a very light 160ms content softening without delaying the instant display.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.54 — 2026-11-19

**Fixed**
- AI no longer calls a successful HTTP 200 response an "error code" just because the body contains `code: 1`. Business codes are interpreted from `msg` / `data` / `success`, not from the number alone.
- AI-renamed requests now update the collection node and matching history entries, so the sidebar shows the new name immediately.
- Global fix for IME composition: placeholder text is hidden while candidate words are being composed and restored afterwards, for every text input.

**Added**
- "AI response analysis" dialog: streaming Markdown output with fade-in animation and spinner, copy and re-analyze buttons, and an entry on the response tab row.
- Tab-aware analysis: pretty / tree / raw / headers / cookies / console / preview / diff / extract / timeline / network error each get their own evidence and focus points.
- Stale-response notice now has a close (x) button and "Never remind me" (persisted in settings).

**Changed**
- API docs code sample is collapsed by default; expand with the chevron.
- Removed AI script writing from pre/post script pages and removed DeepSeek from AI settings (GLM only).
- Rewrote all prompts for data generation, response analysis, docs and naming to be evidence-based and specific.

**Verified**
- 654 smoke checks plus 57 targeted checks pass.

## v1.0.53 — 2026-11-19

**Added**
- The code sample section in the API docs window now has a collapse arrow (the same chevron used in the collection tree): collapse it and the document takes the whole height.
- "AI content" switch in the docs window: hide or show the AI-written sections at any time; while off, copy and "Save .md" produce the purely generated document.

**Changed**
- Script AI is far less strict: it treats every request as a coding task and writes runnable JavaScript instead of refusing when the description is vague or off-topic. Only a plain prose answer (no code at all) is reported back.
- AI prompt dialog now sizes itself from its content, so the text box no longer runs under the buttons when the hint wraps or the font is larger.

**Removed**
- "New request from a sentence" is gone from the welcome screen, the command palette and the code behind it.

**Verified**
- 654 smoke checks plus 53 targeted checks pass.

## v1.0.52 — 2026-11-19

**Changed**
- Settings now has a single "Variables" page: environment variables and global variables sit behind one segmented switch, with the override rule (environment wins) stated right in the header. The old separate nav entries are gone.
- The AI settings page was rebuilt: switch → provider → key → models → advanced, with a single status line (ready / not configured / off) instead of colored decoration.

**Added**
- AI master switch: keep the key but turn AI off, and every AI entry point goes quiet; key and model choice are preserved.
- DeepSeek support next to Zhipu GLM (DeepSeek-V3 and R1 cards). Each provider keeps its own key and switching brings the right one back.
- "New request from a sentence" on the welcome screen and in the command palette: method, URL, headers, query params and body are filled in, with Content-Type added for JSON.
- "Save response field as variable" in the response more menu: pick a field, get a suggested name, store it globally or in the current environment.
- AI auto-naming with a switch: unnamed or URL-derived request names become human-readable after sending; hand-renamed requests are never touched, and each URL is only asked once.
- "AI script" as the first button on the pre-request and post-response script pages: describe the goal in a sentence and get JavaScript that only uses this sandbox's API; off-topic requests are refused and never written into the editor.
- "AI fill" in the API docs window: appends overview, field meanings and common errors to the generated document — included in copy and "Save .md", and the response sent to the model is redacted while the redact switch is on.

**Verified**
- 654 smoke checks plus 52 targeted checks (variable precedence, per-provider keys, AI switch, script refusal, doc append, one-sentence requests) all pass.

## v1.0.51 — 2026-11-19

**Fixed**
- Tab drag-and-drop is smooth again: reordering now reports once on mouse release instead of syncing `state.json` on every frame, tab widths/rects are cached, and the indicator snaps instead of restarting an animation mid-drag.

**Added**
- Global variables: available in every environment and request via `{{name}}`; a same-named environment variable overrides them. Manage them in Settings → Global variables.
- AI settings page: paste a Zhipu GLM API key and go. Four preset model cards (GLM-4-Flash 250414/latest, GLM-4.5, GLM-4.1V), one-click connection test, plus custom model ID and base URL for proxies or self-hosted gateways.
- AI body generation: in a JSON body, "AI generate" builds realistic data from the existing field names (or param keys), streams it into the editor and formats it when done.
- AI error explanation: available on the failure page and in the response "more" menu — returns the cause plus concrete fixes.

**Changed**
- Sidebar methods longer than 4 characters are abbreviated to 3 letters (PATCH → PAT, DELETE → DEL, OPTIONS → OPT) so names get more room.
- The Params tab of HTTP, WebSocket and Socket.IO no longer offers the File type (query params can't carry files); multipart form uploads keep it.

## v1.0.50 — 2026-11-19

**Changed**
- Request tabs now lift and follow the mouse while being dragged to reorder, leaving a translucent placeholder at the original spot — matching the sidebar's drag feel.
- WebSocket and Socket.IO "Params" pages now include "Paste" and "Bulk Edit", fully on par with HTTP params: bulk import from clipboard, key: value bulk editing, comment lines mark rows disabled, and the final-URL preview updates live.

## v1.0.49 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use three tabs: Chat / Params / Protocol (Auth). Added a real query-parameter table that is appended to the URL on connect, with bulk edit and a final-URL preview.
- Socket.IO Chat page first row is now "Event name" with matching English text; namespace moved into the Auth page; all rows share one left alignment with no functionality lost.
- Sidebar drops the duplicate "New Folder" button; the trash entry moves to the bottom action bar and the delete animation now flies to the new spot.
- Creating a folder now jumps focus to it with a highlight pulse and opens inline rename with a default name: confirm to keep it, type to replace.
- The search box now filters both Collections and History, keeps its text across tab switches, and hides empty history groups.
- Fixed the trash detail popup misalignment in English (truncated labels / uneven value column) with a language-aware label width; also reduced redundant history row rebuilds.

## v1.0.48 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now align their tabs, toolbar rows and inputs to the same left edge as the method badge; both protocols share one baseline.
- Protocol and Auth pages drop the full grey card background, keeping only group titles and thin dividers for a cleaner look.
- Removed leftover collapsed-card state, unused message counters and duplicate helpers to cut dead code.

## v1.0.47 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use the same underline tab style as HTTP requests: WebSocket splits into Chat / Protocol, Socket.IO into Chat / Auth.
- The Chat page keeps only day-to-day sending: namespace, event name, payload, JSON/Text switch, format, save and send.
- Low-frequency settings moved to a second tab: connection parameters for WebSocket, handshake auth and ACK/reconnect options for Socket.IO.
- Socket.IO payload input gains a JSON/Text switch (controls highlighting and formatting), and its "More" menu now shows Socket.IO-specific actions: copy URL, export/clear event log.

## v1.0.46 — 2026-11-19

**Changed**
- Unified the layout of the WebSocket and Socket.IO pages into one skeleton: options row / composer row / editor / frequent chips — matching the HTTP request view while keeping only useful controls.
- The method badge on realtime pages now shrinks to a compact label, giving the room back to the URL field and removing the empty gap after the method name.
- Protocol fields (subprotocol, namespace, auth, event name) now stretch to fill the row and action buttons sit flush right for a cleaner look.
- Low-frequency switches are grouped on their own row and aligned with the handshake-headers button; both realtime pages now look identical, with no clipping in English or Chinese.

## v1.0.45 — 2026-11-18

**Added**
- Socket.IO requests with a dedicated "Events" page, creatable from the New Request menu and command palette.
- Lightweight Engine.IO v4 / Socket.IO v4 over websocket transport: handshake, namespaces, auth JSON, event emit/listen, ACK receipts, heartbeat and auto-reconnect — no extra dependency.
- Distinctive touches: auto-discovered events with one-click filtering, frequent events for one-click reload, double-click an event to load it back, JSON payload highlighting and formatting, clear-after-send.

**Fixed**
- Initialized the ACK registry to prevent a crash, and stopped treating ordinary integer data as an ACK id on server events that request a receipt.
- Auto-reconnect now keeps the namespace and auth; Socket.IO connections are fully closed on exit, leaving no orphans.
- Complete Chinese/English strings for namespace, auth, events, ACK and discovered events.

## v1.0.44 — 2026-11-18

**Changed**
- Trash time groups now use the same chevron as the collection tree, with the item count aligned right like history groups.
- Removed the redundant "Oldest deleted" strip above the trash list.
- Fixed hover cursors: collection tree and history rows now show the pointing-hand cursor again.
- Slightly widened the trash window and filter sidebar so English "Custom" and the date inputs are no longer clipped.
- Filled in missing English strings for the trash tooltip and WebSocket "Connecting to …" log line.
- Added a light dissolve animation for deleting a single history entry and clearing all history: sweep line, soft ring, fade-and-collapse.

## v1.0.43 — 2026-11-18

**Changed**
- Group trash items by deletion time (within 1 hour / today / yesterday / 7 days / 30 days / older), with collapsible headers and expand animations.
- Detail popup now fills with params / headers / body / cookies / auth / variables / sub-requests and scrolls.
- Unified method colors with the theme palette; WS / HEAD / OPTIONS are no longer grey.
- Fixed the transparent context menu by drawing an opaque rounded background; full CN/EN strings.
- Extended clear / restore / delete animations by ~0.5s for a calmer feel.
- Added a lightweight arc-to-trash-button fly animation when deleting from the sidebar.

## v1.0.42 — 2026-11-18

**Changed**
- Calendar weekday header switched to the theme's dark palette instead of the
  system light-grey strip.
- Removed the always-on trash detail panel so deleted records use the whole
  area; "Oldest deleted" moved above the list and aligned with the row icon.
- A small "Details" pill appears on row hover and opens a lightweight detail
  popup, keeping the layout clean.
- Added a 1px hairline separator between the filter sidebar and the list.
- Empty / restore / permanent-delete now play a light artistic animation
  (expanding ring + icon fade-in) with minimal resource use.

## v1.0.41 — 2026-11-18

**Changed**
- Trash stats bar items all aligned left again as before; search box now has a
  visible border so it reads clearly against the dark background.
- Refresh button icon spins one full turn on click for clear feedback.
- Widened the trash filter sidebar so the custom date range inputs are no
  longer clipped.
- Command palette gained "Open Trash" and "Trash auto-clean settings" actions.
- Trash detail simplified back to a short list (URL / contains / deleted at /
  original location) with type and method pills on the title row.

## v1.0.40 — 2026-11-18

**Changed**
- Trash window re-laid out: search moved into the top-right stats bar, the
  redundant activity timeline removed, and the detail panel made richer and
  scrollable (type / method / URL / params / headers / body / env vars /
  original location / exact delete time).
- Custom date range picker restyled to follow the pure-black theme — the
  system calendar's white background, red weekends and purple selection are
  gone.

**Added**
- "Trash auto-clean" switch (on by default) and retention period (7 / 30 / 90
  days) in Settings · Data. Expired items are permanently removed when saving
  settings and on launch.
- Cascade restore hints: selecting a folder also selects its independent child
  entries in the trash, and restoring prompts how many requests come back with
  it. Requests referencing `{{variables}}` get an undefined-variable warning.
- Saving a request now scrolls the left collection tree to the saved item;
  restoring from the trash refreshes the sidebar and reveals items at their
  original position. The Refresh button now re-reads state from disk.

**Verified**
- Self-test suite: 593 checks, 0 failures. Real launch with Trash window OK.

## v1.0.39 — 2026-11-18

**Added**
- Trash for deleted collections / folders / requests. Deletes now move items to
  the trash instead of erasing them, and restore puts the whole subtree back at
  its original position.
- A blurred, fixed Trash window with a distinctive three-part layout: filter
  rail on the left, item list on the right, detail panel at the bottom. Pure
  black minimal theme, no gradients or colored outlines.
- Full trash toolkit: restore, delete permanently, empty, detail view, search
  by name / URL / method, date-range filtering (today / 7d / 30d / custom),
  refresh, multi-select batch actions, an activity timeline and exact delete
  timestamps. Sidebar entry shows the item count.

**Fixed / Changed**
- HTML / XML code highlighting now uses the unified One Dark scheme (blue tags,
  amber attributes, green values, gray punctuation, colored inline script /
  style). `xml` was previously downgraded to the Python highlighter, leaving
  markup almost entirely gray.
- Sidebar delete is now "Move to Trash" with an accurate, reassuring prompt
  instead of an irreversible-delete warning.

**Verified**
- Self-test suite: 579 checks, 0 failures.

## v1.0.38 — 2026-11-18

**Fixed**
- Two expanded message cards could overlap. The list laid out rows using an
  80px estimate for a not-yet-created card, so once the real card turned out to
  be several hundred pixels tall the following rows were drawn right on top of
  it. Layout now creates and measures every expanded card first, then positions
  rows, and checks convergence against the row offsets themselves (not against
  whether card properties changed, which broke out of the loop too early).
- Scrolling to the bottom still hid the last message: the list height omitted
  the expanded card on the final row. Total height now includes that card in
  full, so the bottom edge is reachable.
- Resizing the window narrower reflows long text and changes card height; the
  whole list is now re-laid out on resize instead of only repositioning cards.

**Changed**
- Detail cards no longer show the "响应体" label; the Raw tab and the code box
  are aligned to the same left edge.

**Verified**
- Self-test suite: 554 checks, 0 failures.

## v1.0.37 — 2026-11-18

**Fixed**
- Scrolling over an expanded message card now scrolls the whole log again. The
  read-only code view was swallowing every wheel event (it still scrolled its
  own 1px), so the outer list never moved — the mouse sat on the card and
  nothing happened. Wheel events are now forwarded to the log scroll area.
- The scroll area no longer depends solely on its easing animation to move:
  it lands on the target value even when the animation cannot fire, so the
  wheel always works (including in safe mode).
- Tabs are chosen by **content** again: a plain-text frame shows only **Raw**,
  a real JSON payload shows **JSON / Raw**. Previously every text frame was
  given a JSON tab, so a plain "hello" message and even ERR system messages
  sported a meaningless JSON tab.
- Removed the collapse chevron from the top-left of detail cards; cards stay
  open with their full content visible.

**Changed**
- Code surface background moved closer to the window base (`#171717`-like),
  matching the response panel look the user compared against.

**Verified**
- Self-test suite: 549 checks, 0 failures.

## v1.0.36 — 2026-11-18

**Fixed**
- WebSocket detail code frames no longer render on a dead-black viewport: the
  background now follows the theme's code background (a shade close to the
  window base), so keys / strings / numbers keep the full syntax-highlight
  palette against a surface that matches the app.
- Plain-text frames whose payload is JSON now get the **JSON** tab and syntax
  highlighting too. Previously only frames tagged `json` at send time did,
  which left a JSON body showing a lone **Raw** tab with no colours.
- Expanding a log card no longer lets later frames cover it. The incremental
  append path now uses each open card's real height instead of a fixed 80px,
  and auto-scroll pauses while any card is open — so the expanded content
  stays in view and can be scrolled through.
- The "…" button in the response header now does something in a WebSocket
  session. It opens a WS-specific menu: connect / disconnect, copy URL, copy
  session stats, export the message log and clear it.

**Removed**
- The "Saved messages: store anything you send often…" empty-state hint in the
  WebSocket composer; the chips and their tooltips speak for themselves.

**Verified**
- Self-test suite extended to 550 checks.

## v1.0.35 — 2026-11-18

**Changed**
- WebSocket detail cards were rebuilt around content only: no repeated timestamp / preview
  from the row above. Tabs, copy button and a clean bordered code frame make the hierarchy
  clearer.
- Every expand arrow now uses the same chevron as the collection tree (right when collapsed,
  down when expanded) — both in log rows and in detail cards.
- The code frame can be collapsed. JSON keys and values no longer render in bold.
- The code frame has no scrollbars: it grows to fit all content and the outer log area
  handles scrolling.

**Fixed**
- Multi-line JSON in a log row used to overlap the rows below. Previews are now compacted
  to one horizontal line regardless of how the original was formatted.

**Verified**
- Self-test suite extended to 544 checks; startup-to-show ~547ms; clean exit with an open
  WebSocket connection.

## v1.0.34 — 2026-11-18

**Fixed**
- The URL-bar button still read **Connect** while a WebSocket was open (and after switching
  tabs); it now reads **Disconnect** and stays that way.
- Messages in progress were lost when switching tabs. Drafts and the text / JSON / binary
  choice are stored with the request.
- The input hint showed through Chinese IME preedit text (e.g. `ni'hao` overlaid the hint).
  The placeholder now hides while composing and returns afterwards.

**Changed**
- Log rows expand into inline detail cards: Raw / JSON / Hex tabs, line numbers and a copy
  button. Several rows can stay open at once (capped at 12, oldest closes first so the UI
  never accumulates thousands of text documents).
- JSON details keep their indented layout; row previews stay on a single elided line.
- Counters (received / sent / bytes, uptime / traffic) animate over 280ms instead of jumping.

**Improved**
- Appending frames is incremental and stats use cached counters: 4000 frames append in
  ~2ms, and painting remains limited to visible rows.
- Self-test suite extended to 539 checks.

## v1.0.33 — 2026-11-18

**Fixed**
- Occasional hard crash (`zsh: bus error`, `crash.log` showing `<no Python frame>`) when
  quitting. Shutdown now stops every animation, drops graphics effects, closes sockets and
  tears the window down explicitly instead of relying on Qt / Cocoa destruction order.
- The WebSocket log's empty hint was squeezed into a 1px line (the list is 8px tall when it
  has no rows). It now has its own centred page, with a different message when a filter
  matches nothing.
- **Settings → Appearance → Text size** did nothing: the dialog saved the value and closed,
  so the rebuild step saw "no change". It now zooms in place — the settings page stays open
  and the whole UI resizes as you click.

**Changed**
- WebSocket is a request *kind*, not a method: `WS` is gone from the method dropdown, and a
  WS request is created only from **New request → WebSocket request**.
- WS requests get a dedicated page with only what they need: message editor (text / JSON /
  binary), saved messages, subprotocol, heartbeat, auto-reconnect, clear-after-send, and a
  collapsible handshake-headers editor. The HTTP-only tabs are gone.
- "Export this folder" is now **Export collection**.
- The command palette is shorter — a floating panel rather than a full-height sheet.

**Improved**
- Welcome cards and empty states scale with the text-size setting, so 150% no longer
  overlaps lines.
- Self-test suite extended to 529 checks (WS page, handshake headers, live text scaling,
  palette height).

## v1.0.32 — 2026-11-18

**Added**
- **WebSocket requests.** Create one from **New request**, or switch any request's method to
  `WS`. Addresses accept `ws://` / `wss://`; pasted `http(s)` URLs are rewritten.
- Full WS feature set: text / JSON / binary messages, handshake headers + cookies + auth,
  subprotocols, ping heartbeat with real round-trip latency, exponential-backoff
  auto-reconnect, and live connection stats (uptime, frames and bytes in/out).
- A frame log with direction, type, time and size; filter by Received / Sent, search the
  contents, click a row for the full payload, copy, export to JSON or text, clear. Capped at
  4000 frames so long-running subscriptions stay light.
- Common messages: save recurring payloads as chips, click to load them back. They travel with
  the request in Ocelot / Postman export and come back intact.
- Double-click any received frame in the log to **replay** it: the payload is loaded back into
  the editor so you can tweak it and send again — no copy-paste.
- Settings → Appearance → **Text size** (100% / 110% / 125% / 150%). Scales the whole UI and
  the code area; applies instantly and returns you to the same settings page (unsaved tabs
  are carried over).
- Right-click a folder in the collection tree → **Export this folder** (Ocelot, Postman,
  OpenAPI, HAR). The default file name is the folder name and the exported file keeps the
  same folder structure.

**Fixed**
- Hovering "response time" after a failed request still showed a bogus `9 ms` card. Time,
  size and type are now hidden on failure, and the hover cards are gone.
- In English the `failed` pill was narrower than its label, so the text spilled out of the
  rounded background. Pills now size themselves from real glyph metrics.

**Improved**
- The command palette only paints the rows that are on screen; the rest render as you
  scroll, while search still matches every entry.
- Batch-running a collection skips WebSocket requests.
- Self-test suite extended to 519 checks, including a real local WebSocket server covering
  connect, echo, heartbeat, replay, disconnect and refused connections.

## v1.0.31 — 2026-11-18

**Fixed**
- The backdrop blur was not aligned with the window: it covered the whole window rect
  (including the 8 px shadow margin) and its corners stayed square. It now covers only the
  window card and is clipped to the same 12 px radius, so the arcs line up.
- The command palette had no blurred backdrop, and opening it made the card jump vertically.
  Layout is now fully computed before the palette is shown, and it fades in from 10 px
  above with a 120 ms animation.
- On the failed-request page the **Clear / Copy all** buttons were too loud. They are now
  compact and sit on the same line as the output summary, flush with the content edge.
- History mode showed two **Clear History** buttons (a text one and an icon one); the icon
  one is gone.
- Preview tabs stayed italic after double-clicking a collection item or sending the request.
  They are promoted to a normal tab now.
- The import source list had a large gap between **Import from URL** and **Export all
  collections**; the dialog height now follows the content.

**Added**
- Deleting a collection, folder or request (and clearing history) now asks for
  confirmation. Deleting a folder tells you how many requests go with it.

**Improved**
- The "Blur All Dialogs" description in Settings is a single short sentence.
- Self-test suite extended to 482 checks, all passing.

## v1.0.30 — 2026-11-18

**Fixed**
- The tab pill slide had disappeared: clicking a tab calls `set_current` twice (once from
  the click, once from the selection callback) and the second call snapped the animation
  that had just started. The pill now slides with a subtle velocity stretch, and the
  outgoing/incoming tab labels and method badges cross-fade.
- The modal backdrop was only blurred on the left-hand side. Replaced the Qt blur render
  with a two-stage downsample blur that is uniform across the whole window (about 3.5 ms
  for 1600×1000, a few hundred KB peak memory).
- The success check on the import result page sat left of centre: its icon was centred
  using device pixels, which is 2× off on Retina. It is now centred in logical pixels and
  gets a small expanding halo when it appears.
- Imported collections had the wrong name. The name now comes from the file
  (`info.name`, Apifox collection name, Insomnia workspace, OpenAPI title) or the file
  name, and the collection is created as a folder with that name — inner folders keep
  their hierarchy. A single-request JSON still imports as one request.

**Added**
- `Collections / History` segmented control: the selected pill slides between the two
  labels and the text colour cross-fades.
- Every dialog is centred on its parent window, including when a page change resizes it.
  Only Settings and Import/Export are blurred and immovable by default; other dialogs
  stay unblurred and can be dragged by their title bar.
- New setting **Appearance → Blur All Dialogs**: turn it on and every dialog becomes
  blurred and immovable.
- Command palette: the five most-used commands are pinned under a **Frequently used**
  heading (ordered by real usage, so the list adapts), followed by **All commands**. The
  card is centred and slides down as it fades in.
- **Import from URL**: paste a remote JSON / YAML link (8 MB limit); it downloads and runs
  through the same detection pipeline as a local file.

**Improved**
- Export file names default to the collection (folder) name instead of
  `ocelot-collection`.
- Removed a batch of unused imports and redundant work; the self-test suite now covers
  467 checks and passes.

## v1.0.29 — 2026-11-18

**Fixed**
- The selected tab pill no longer overlaps the neighbouring tab at launch. A pending
  indicator animation kept writing a stale rectangle after the geometry had been snapped;
  the pill now always derives from live geometry, and restoring a session no longer
  animates once per tab.
- Changing the request method (POST → GET) now updates the method badge in the collection
  tree. The editor, the tab badge, the stored node and the saved file stay in sync.
- Switching method after a request no longer throws the response away. The previous result
  stays on screen with a slim "Request changed · showing the previous response" bar that
  offers a **Send again** action.
- Importing a Postman file could fail with "no importable requests": Apifox
  `apiCollection` payloads and Insomnia exports whose requests hang under a workspace were
  parsed as empty. Postman data dumps, Postman v1 collections, Hoppscotch v2 objects,
  files with a UTF-8 BOM and bare single-request files are now recognized too.

**Added**
- Import / export result page: a large check, the title, and a breakdown of what was
  brought in (collections, requests, folders, pre-request scripts, post-response scripts,
  auth, environment variables). Export results offer **Show in Folder**.
- The file page reports what was detected before importing (format plus counts), and the
  sidebar reveals and expands the newly imported collection.
- Environments travel with the collection: Postman dumps, Apifox and Insomnia environment
  resources are imported alongside the requests.
- Dialogs and the settings panel now blur and dim the main window behind them, and the
  modal is pinned in the centre of its parent instead of being draggable.

**Improved**
- The collection search field fills the width up to the import / export button.
- The export page states what will be written ("Exporting 1 collection, 5 requests") and
  disables the rows when there is nothing to export.

## v1.0.28 — 2026-11-18

**Added**
- A **Console** tab in the response panel: `console.log / warn / error` output and `test()`
  assertions from pre-request and post-response scripts, color-coded by level with Pre/Post
  badges, one-click copy, and inline output on the error page so a failing pre-request script
  is still visible when no response arrives. The console also records the outgoing request
  and the final status line.
- An **Import / Export** button next to the collection search field. A single dialog handles
  both directions with a back arrow: import from Ocelot JSON, Postman, Apifox, Hoppscotch,
  Insomnia, OpenAPI 3.x (JSON or YAML) and HAR, plus clipboard import; export as Ocelot JSON,
  Postman v2.1, OpenAPI 3.1 (JSON / YAML) or HAR. Files can be dropped onto the dialog, and
  the chosen file is parsed and summarized before importing.
- **Ocelot JSON** uses Postman v2.1 plus an `x-ocelot` block, so Postman / Apifox can import
  it directly while a round trip through Ocelot keeps scripts, auth and cookies.
- **Rename** in the tab context menu: updates the collection node, the tab title and the
  request itself, saves immediately, and pushes to the cloud when auto-sync is on.
- Clicking a tab now reveals the matching request in the sidebar: switches back to
  collections, expands the parents, clears a hiding filter and scrolls the row into view.

**Improved**
- Script engine hardened: `res.body` / `res.text` now return real text instead of a bound
  method, `req.setHeader` keeps existing rows disabled as before, and `res.json()`,
  `res.setHeader()`, `pw.env.has()`, `pw.env.toObject()` and `test()` were added. Syntax
  errors report the line number the user sees, and endless loops are stopped after 2 seconds
  by a deadline check injected into loop bodies (no background thread, so the process can
  never be aborted by a leftover thread at exit).
- Snippet buttons insert on a fresh line instead of mid-line; post-response scripts get
  response-reading and assertion snippets.
- Body badge no longer copies the whole body on every keystroke.

**Fixed**
- Editing a request and saving never wrote the changes back to the collection node, so
  reopening showed the old content. Tabs now sync into their node on every save.
- After an unclean exit, the next launch starts with animations temporarily disabled to
  avoid the macOS graphics-layer hard crash; focus is released before the window closes.
- All 429 self-tests pass.

## v1.0.27 — 2026-11-18

**Improved**
- The script run status now pairs a thin check/cross icon with the text. Success shows only
  "Ran successfully"; the line is left-aligned with the editor above and sits right beneath
  it, fades in when it appears, and uses the theme's success/danger colors. The icon uses a
  light stroke weight.
- Language switching now walks the widget tree once instead of twice; history group counts
  are computed in a single pass. Duplicate imports and redundant calls were consolidated.

**Added**
- A **Raw** body mode with a JSON / XML / HTML / Text language selector. The selected
  language drives syntax highlighting, formatting and `Content-Type`. All send paths and
  code generators now share one normalization helper.

**Fixed**
- History group titles are translated at paint time, so switching between Chinese and
  English updates them immediately instead of leaving the old language on screen.
- All 395 self-tests pass and repeated real GUI startups are crash-free.

## v1.0.26 — 2026-11-18

**Improved**
- Script **Run test** results now appear in a dedicated dialog. The status line shows only
  "Ran successfully", left-aligned with comfortable padding and a subtle fade-in when the
  text appears. The inline log panel at the bottom of the page is gone.

**Added**
- Params now has a **Bulk Edit** button, so you can edit all query parameters at once as
  `key: value` text.
- History is grouped into **Within the last hour / Today / Yesterday**, with each group's
  collapsed state remembered independently. Group headers now share the same subtle hover
  animation as the other buttons.

**Fixed**
- Fixed an intermittent startup `bus error` crash. The frameless translucent window now fades
  in using native window opacity instead of a graphics effect, and pages hosting native video
  views no longer get a `QGraphicsOpacityEffect` applied.
- All 395 self-tests pass.

## v1.0.25 — 2026-11-17

**Fixed**
- The run status on the script page is now a single line. `console.log()` output from both
  **Run test** and real requests is written to a read-only log panel directly below, so the
  "see logs below" message finally points at something real.
- Editing a pre-request or post-response script no longer wipes out the last response. Script
  changes update the request data and the dirty flag only; the response panel keeps showing
  what you were looking at.

**Improved**
- The auth type name **Inherit** is now always shown in English, matching Bearer, Basic,
  API Key and JWT.
- Params, Body, Headers, Cookies and Auth pages now each get a slim scrollbar. When their
  content is taller than the request pane they scroll on their own instead of being clipped.
- The collection runner uses the theme's subtle hover color for the current row instead of a
  bright gray bar. Clicking a finished row opens that request with its captured response, so
  you can inspect the result directly.
- All 395 self-tests pass.

## v1.0.24 — 2026-11-17

**Improved**
- The script editor is now split into two dedicated pages, **Pre-request Script** and
  **Post-response Script**; the redundant in-page tab switch is gone. The reference panel
  on the right scrolls independently with a slim scrollbar, so overflow no longer pushes
  the controls below out of place. `Run` becomes a clearer **Run test** button with a
  tooltip explaining that it runs the script locally without sending a request.
- History groups now use the same chevron as the collection tree. Click a group header to
  collapse or expand it, and the state is remembered across restarts.

**Added**
- **JWT auth** — auto-generate a signed token with HS256 / HS384 / HS512 or paste one
  manually. Payload and secret support environment variables, and the token is sent as
  `Authorization: Bearer <token>`. Generated tokens match the jwt.io standard exactly.
- **Inherit auth** — walk up the request's collection to find the nearest folder auth.
  Configure it from the folder's right-click **Configure auth…** menu. Both JWT and Inherit
  work on the direct and relay send paths.

**Optimized**
- All 395 self-tests pass.

## v1.0.23 — 2026-11-17

**Added**
- **Pre-request and post-response scripts** powered by Qt's built-in JavaScript engine
  (QJSEngine, zero extra dependencies). Modify the URL, headers and query params before
  sending; parse the response after it arrives. `pw.env.set()` writes variables into the
  active environment and persists them, `console.log()` output is visible, and a broken
  script never blocks the request.
- **Complete body type set** — none / form-data / x-www-form-urlencoded / JSON / XML /
  Text / Binary, with names aligned to mainstream API clients. XML is a new first-class
  type with syntax highlighting, validation, one-click formatting and automatic
  `application/xml` content type.

**Improved**
- Code editor now supports automatic bracket and quote pairing, smart indentation on
  Enter, Tab indentation and wrapping a selection in a pair. JSON and XML can be
  formatted in one click; JSONC line comments are handled.
- One unified syntax highlighting scheme across the whole app — JSON and Python /
  JavaScript / Go / Java and more share a single One Dark style token palette (declaration
  keywords in pink, functions in blue, strings in green, numbers in orange). Request
  bodies, responses, code examples and the script editor all use it.
- The response size card now counts header bytes including the status line, and adds a
  **Request Size** section with separate Header / Body figures. Card background is darker.
- History is grouped by date (Today / Yesterday / N days ago) with a count per group.

**Optimized**
- All 395 self-tests pass.

## v1.0.22 — 2026-11-17

**Fixed**
- **Switching the language in Settings left the right-hand page in Chinese**: the Settings
  window is a separate top-level window that the main window's translation pass could not
  reach. It now re-translates itself on switch, including the page title and nav width.
- **An extra divider line above the response area**: when the metrics bar was hidden, the
  divider below it stayed visible and overlapped the splitter handle. The divider now shows
  and hides together with the metrics bar, leaving a single line.
- **"New Mock Route" / "New Condition Rule" dialog titles were not translated** in English.
- **Timeline stats and "No Wrap" were not translated**: hit count / success rate / average /
  P95 / slowest, plus the raw view's wrap toggle, stayed in Chinese under English.

**Improved**
- Request panel tab order is now Params / Body / Headers / Cookies / Auth, with the most
  used Body tab moved to second place.
- Code examples in the API doc now share one fixed height: switching languages no longer
  makes the block jump between sizes; overflow scrolls inside.

**Optimized**
- All 395 self-tests pass.

## v1.0.21 — 2026-11-17

**Fixed**
- **The history list went blank in English**: the sidebar's segmented tabs did not recompute
  their widths after a language switch, clipping the `History` segment. Tabs now re-measure.
- **Command palette action names stayed in Chinese**: new request / send current request and
  others were untranslated, as were "Default" in the format menu and "Click to choose a
  file…" in file cells.
- **A chosen file in the request body could not be sent**: the code used the display text
  as the path, which becomes `No file chosen` in English and was treated as empty. The path
  is now stored separately from its display text.

**Improved**
- Settings header and footer hints wrap automatically, so long English text is no longer
  clipped at the window edge.
- English copy reviewed throughout; terminology keeps aligning with Postman.

**Optimized**
- All 395 self-tests pass.

## v1.0.20 — 2026-11-17

**Fixed**
- **Square window corners**: the rectangular content layer covered the window's own rounded
  corners. The content layer now has a rounded mask that follows the window, disabled when
  maximized.
- **Gray squares next to selected response-tree rows**: the indent cell got a system hover
  background. The highlight is now fully transparent while selected text stays highlighted.
- **Two rapid requests crossed streams**: an old request's `finished` signal treated the new
  request as done, leaving the spinner running or showing the wrong response. Results are
  now matched by signal source and stale ones are discarded.

**Improved**
- Settings / What's New footers no longer print `Ocelot x.y.z · Python + PyQt6`.
- The About page drops the runtime (Python / PyQt6) and "native macOS window" tags.
- Full English pass: toasts, placeholders, tooltips, Settings pages, Mock hub; terminology
  aligned with Postman (Send / Params / Headers / Cookies / Environments / Mock Server),
  with no source text lost when switching languages.

**Optimized**
- Large arrays only render the first 300 items with a "… {n} more" trailing row; even
  200,000 items open instantly.
- Added a crash log: hard crashes and uncaught exceptions are written to `crash.log` in the
  data directory.
- 395 self-tests.

## v1.0.19 — 2026-11-17

**Fixed**
- **Clicking "More → Mock data…" crashed**: the editor was missing the `mockRequested`
  signal and raised `AttributeError`; "Copy request" in the same menu had the same issue and
  was fixed too.
- Mock / Copy request in the More menu are now forwarded uniformly by the editor, with a
  single signal connection — one click no longer opens two windows.

**Improved**
- Response tree view: row height 16 → 21; the key column is sized to its content so
  `two_factor` is no longer truncated to `two_fa…`.
- The API doc footer now prefixes the status line with a "Status" label instead of showing
  a bare string of words.

## v1.0.18 — 2026-11-17

**Fixed**
- **Right-clicking inside an input crashed**: `QApplication` has no `cursor()` method and
  raised `AttributeError` when resolving the click position. The context menu now uses the
  screen coordinates carried by the event, falling back to the mouse position only if needed.
- **Mock showed "Stopped" but a browser refresh still worked**: stopping closed the listen
  port, but an existing HTTP keep-alive connection kept being served. Stopping now actively
  drops all live connections and responses no longer request connection reuse.
- Stopping now disconnects in-flight connections before closing the port, so no response can
  "arrive after stopping".

**Optimized**
- Self-tests expanded to 382 checks, including right-click positioning and the guarantee
  that stopped services return no data.

## v1.0.17 — 2026-11-17

**Added**
- **Mock conditional rules**: one route can return different results based on request
  header / query param / body / method — return VIP data with a `token`, 401 without it,
  covering both happy and error paths. Rules support equals / contains / exists / not
  exists, with their own status code, delay and response body.
- **Mock dynamic data**: write placeholders like `{{@id}}` `{{@uuid}}` `{{@name}}`
  `{{@cname}}` `{{@email}}` `{{@now}}` `{{@int(1,99)}}` `{{@pick(a,b)}}` in the response body;
  each request recomputes them. Editing a route offers "Preview random data".
- **Mock request log**: a new "Request Log" page shows each request's method, path, status,
  latency and matched route / rule in real time, with 2xx / 4xx / average-latency counters
  and a one-click clear.
- Route lists show a hit count per route.

**Improved**
- The start button now follows the real state: "Start Service" when stopped, "Stop Service"
  when running (previously hard-coded).
- The API doc table was rebuilt: a dedicated header bar, row dividers, a first column
  measured and clamped to 96–210, and word wrap for long content.
- Code examples: language labels align strictly with the code body; long lines are wrapped
  and sized by their real line count, with no half-cut lines or stray scrollbars.
- The Settings menu's "Settings…" is now a gear icon; "Switch Light / Dark" was removed
  (the theme is still under Settings → Appearance).
- The About page drops file names and class names for a user-facing capability list and a
  "what one request goes through" walkthrough.

**Fixed**
- Stopping could leave the port occupied (another instance or a leftover process): it now
  waits for the port to be truly released and reports honestly; if another Ocelot owns the
  port, it says so and switches automatically.
- Dynamic data containing Chinese characters broke the HTTP response when written into a
  header; it is now safely encoded.

**Optimized**
- Self-tests expanded to **374 checks**: menu entries, button states, placeholder randomness,
  rule matching, log latency, table column widths, code-block alignment and long-code scroll.

## v1.0.16 — 2026-11-17

**Added**
- **A real local Mock service**: an actual HTTP server on `127.0.0.1` whose routes, methods,
  status codes, delays and bodies you define. Supports prefix wildcards `/api/users/*`,
  echo mode (returns the request verbatim), CORS, and can be reached directly from a browser
  or script; "Try" builds a request in one click, and it can start with the app. If the port
  is taken it switches automatically.
- **Two Mock hub pages**: local Mock manages routes (create / edit / copy address / delete),
  while the public API catalog keeps 28 free endpoints (click a row to fill a request).
- **Shortcut settings**: all 16 actions are editable — click a keycap to record, clear in one
  click, restore defaults. Two actions competing for the same key make the older one step
  aside, and changes take effect immediately.
- **Fuller API docs**: overview (method / URL / status / latency / size / content type), auth
  notes, cookie table, response header table and status-code semantics; copying or saving
  produces a deliverable document.

**Improved**
- API doc window reflowed: a request card on top with status / latency / size metrics, a left
  outline that tracks scrolling, and cached code examples per language.
- Ten languages in code examples share syntax highlighting (CLI flags, URLs, strings and
  numbers each colored); code aligns strictly with the language label.
- Command palette entries are no longer clipped: a scrollable list with eased wheel input,
  keyboard selection auto-follow and cards clipped by whole rows.
- Mock public API list rebuilt as sub-widgets + layout: method / URL / description align
  strictly; search debounced at 120ms.
- The title bar's settings button is a real gear icon (previously a sun-like set of rays).
- Settings dialog widened to 940×700; About drops the shortcut table for four "Why Ocelot"
  advantages and a six-layer architecture note.

**Fixed**
- A query param already present in the URL was appended again in code generation and docs
  (`?a=1&a=1`); it now compares first, then appends.
- The Mock panel's status pill and button enable state were out of sync after start / stop.

**Optimized**
- Self-tests expanded to **351 checks**: a real local service for route / echo / 404,
  shortcut recording and conflict hand-off, command palette scroll, code-block alignment and
  highlighting, and the new doc sections.

## v1.0.15 — 2026-11-17

**Added**
- **API doc window**: "View API Doc" under "More →" at the top right of the response. Method /
  URL / param table / headers / body / response example on one page, a left outline to jump
  between sections, ten languages of code examples at the bottom with one-click switching,
  a toggle to mask tokens, and copy / save as `.md`.
- **Mock data panel**: 28 built-in free public APIs (httpbin / JSONPlaceholder / DummyJSON /
  ReqRes / random images…), searchable and grouped; a click fills a ready-made request.
- **Response timeline**: a new "Timeline" tab plots this URL's latency history as bars colored
  by status code, with hit count / success rate / average / P95 / slowest on top and hover
  details for each run.
- Command palette ⌘K gains Mock Data, API Doc, Copy Current Request and Close Tab.

**Improved**
- Param table headers align with data rows (checkbox placeholders are real controls, the
  "Type" header is centered).
- URL history completion is a custom-drawn overlay: rounded, clock icon, monospace URL,
  up/down to select.
- Settings reflowed: cloud sync address / token / button on one row, no longer squeezed;
  dialog widened to 900×672.
- About page rebuilt: a large title, version pill, three-column runtime info, two-column
  shortcuts and a copy-version action.

**Fixed**
- Right-click on selectable text in response headers and doc bodies still used the system
  menu (English, translucent); it is now taken over consistently.

**Optimized**
- Self-tests expanded to 312 checks.

## v1.0.14 — 2026-11-17

**Added**
- **One-click API docs**: "More →" in the response copies a full Markdown document (method,
  URL, query, headers, body, status code, latency, size, response example). A tab right-click
  offers "Copy API Doc (Markdown)" so each request can be exported without hand-writing docs.
- **Secret masking**: the same menu can "Copy response body (masked)" or export a doc with
  "secrets masked". `token` / `cookie` / `password` / `authorization` / JWT / `Bearer xxx`
  become `••••••` (long values keep the last four characters so you can confirm it is the
  same key). Safe to paste into chat, tickets or screenshots.

**Improved**
- Code generation (cURL / Python / JavaScript / HTTPie) now merges rows from the Cookies tab
  into the `Cookie` header; disabled rows are not exported, so generated code matches what
  "Send" actually does.

**Fixed**
- Runtime log prefixes still saying `Reqly` (save response / save config failures) are
  unified to `Ocelot`.

**Optimized**
- Self-tests expanded to 312 checks: every doc section, masking rules, long-value truncation,
  JSON structure comparison and cookies in generated code.

## v1.0.13 — 2026-11-17

**Renamed**
- Reqly → **Ocelot**. Title bar, About page, menus, User-Agent and data directory all changed;
  on first launch the old `~/Library/Application Support/Reqly` data is migrated so nothing
  is lost.

**Added**
- Requests gain a **Cookies** tab: table rows are merged into the `Cookie` header (coexisting
  with a hand-written one), and `Set-Cookie` in a response can be imported in one click so
  login sessions carry over.
- **Cloud sync (Turso)**: set a database URL and Auth Token in Settings; "Test Connection"
  runs a single `SELECT 1`; upload / restore from cloud (restoring backs up `state.json.bak`
  first), with an option to auto-upload on exit. Uses only Turso's HTTP pipeline, no new
  dependencies.
- URL bar completes from history: focusing it lists previously used URLs containing the
  current text, so a few keystrokes are enough.
- Command palette ⌘K can switch environments and jump straight to Appearance / Cloud Sync.

**Improved**
- The accent color now drives more than buttons: selection backgrounds, focus outlines,
  hover badges, tab titles and underlines, sidebar selection markers and Settings nav all
  follow it, with body text tinted slightly toward the accent — one coherent color temperature.
- Param type pills drop their outline; Auto gets its own warm-sand color at a larger size,
  clearly distinct from Null's gray and JSON's orange.

**Fixed**
- A black ring around checked checkboxes (the default pen also drew one) — the checked state
  is now a solid block only.
- The first accent swatch's selection ring was clipped by the card edge.
- Tab right-click "Copy as cURL" did nothing (`to_curl` was not imported, `NameError`).
- Qt's implicit cookie jar silently rewrote hand-written `Cookie` headers; it is now neither
  read nor written, and cookies are managed explicitly by the Cookies tab.

**Optimized**
- Removed two unreachable blocks in Settings, duplicate and unused imports in the main window;
  request counts and cookie hints merge into one refresh.

## v1.0.12 — 2026-11-17

**Added**
- Settings · Appearance gains an **Accent Color**: seven swatches (auto / ocean blue / pine /
  moss / terracotta / crimson / violet); buttons, switches, checkboxes and the send key follow
  immediately. "Auto" keeps the original black-and-white inversion.

**Improved**
- The param type menu's Auto now has its own color (warm sand), clearly distinct from Null's
  gray and JSON's orange.

**Fixed**
- Switching color scheme / accent rebuilt a destroyed hover detail card and crashed while
  painting — destroyed widgets are now skipped.
- Switching schemes only refreshes visible widgets; hidden ones repaint naturally when shown,
  making large windows much smoother.

**Self-tests**
- 228 checks: accent switching and persistence, swatch count and clicks, Auto vs Null contrast.

## v1.0.11 — 2026-11-16

**Fixed**
- After launch, tabs did not respond and content would not switch: the tab strip now emits
  its change signal unconditionally; the main window also self-heals a wrong editor request
  or a ghost tab, re-checking when the window regains focus.
- An error midway through `RequestEditor.load` left the loading flag stuck at True, so every
  later edit stopped writing back ("clicking does nothing") — a `finally` block now clears it.

**Optimized**
- Sidebar collapse / expand stutter: the splitter was clamped to the sidebar's minimum size
  (≈158), so the first two thirds of the animation did nothing and the last frame vanished.
  During animation the minimum size and size policy are relaxed, then restored — the slide is
  now truly frame-by-frame.
- Switching tabs and receiving responses no longer writes to disk synchronously (batched to
  one write per 700ms); the history list refreshes incrementally instead of rebuilding
  hundreds of widgets.
- Re-clicking the current tab no longer re-formats the whole response, making large JSON
  switches noticeably smoother.
- Large responses render on demand: the JSON tree and "Raw" tab are built only when opened —
  a 190KB response drops from 1 second to 60ms. Above 600KB only the first 600KB is previewed
  with a hint to "Save As" for the full text, and syntax highlighting is skipped above 180KB.

**Added**
- Extract results can be "Saved as Variable": one click writes into the current environment
  for later `{{name}}` references, so a login token no longer needs copying by hand.
- Middle-click a tab to close it; double-click the divider between request and response to
  restore a 50/50 split.
- Double-clicking an italic preview tab pins it (VSCode behavior); previously double-clicking
  a tab did nothing.

**Self-tests**
- 219 checks: tab self-healing, middle-click close, divider reset, save-as-variable,
  frame-by-frame sidebar animation and incremental history refresh.

## v1.0.10 — 2026-11-16

**Added**
- **Collection runner**: right-click a folder → "Run Collection" or ⌘⇧R to run every request
  in tree order, showing status / latency / size per request and a success / failure / total
  time summary; stop at any time, copy the whole result table (TSV pastes straight into a
  spreadsheet), and click a row to open that request.
- Param type gains File: pick a local file in a form row and upload it as real multipart, with
  code generation reflecting the file param.
- cURL import dialog: paste to parse with live preview, supporting `-X / -H / -d / -F / -u /
  -G / --data-urlencode` and merged short flags like `-sSL`.
- Request tab right-click: Close Others / Close All / Duplicate Tab / Copy as cURL.

**Improved**
- Code snippets expanded to 10 languages (adding Go / Java / PHP / C# / Kotlin /
  PowerShell), all syntax highlighted.
- Format / encoding / type dropdowns are custom-drawn, no more garbled native checkmarks;
  the method palette was reordered to match the reference image and "Custom" removed.

**Fixed**
- Pretty-printing squeezed HTML into one line, or into a staircase running right: it is now a
  token stream — inline tags stay on one line, `script` / `style` / `pre` content is preserved,
  CDATA is not split, and unclosed tags are tolerated.
- Detail card icons never lined up — root cause was `QPixmap.width()` returning device pixels
  (2× on Retina); the dpr is now factored in to center them correctly.
- Clicking a request tab's content did not switch pages and edits were lost — the tab strip
  now genuinely emits a change event.

**Self-tests**
- 196 checks: runner order and summary, file type, pretty-print structure, icon centering and
  tab switching.

## v1.0.9 — 2026-11-16

**Improved**
- Param types use capitalized English names (Auto / String / Number / Boolean / Null / JSON),
  each with a semantic color; String is green.
- HTTP method palette matches the reference: GET green / POST orange / PUT·HEAD·OPTIONS blue /
  DELETE red / PATCH pink / TRACE purple, with "Custom" removed.

**Added**
- Code snippets add Go / Java / PHP / C# / Kotlin / PowerShell, with multilingual highlighting.

**Fixed**
- Type / format / encoding dropdowns switched to custom-drawn menus, eliminating garbled
  macOS native checkmark glyphs.
- The "Expand All / Collapse All" buttons that appeared when selecting text are now fully
  hidden, leaving only format and encoding in the toolbar.
- Detail card icons misaligned and footer text overlapping the Body row: the title and metric
  row icons now share one size and x position, and all blocks accumulate sequentially.
- Clicking a request tab did not switch content and lost edits — TabStrip now emits
  currentChanged correctly.

**Self-tests**
- 186 checks: type colors, custom menus, detail-card alignment, code languages and tab
  switching.

## v1.0.8 — 2026-11-16

**Improved**
- Response Time / Size hover cards use a fixed anchor instead of following the mouse; the
  custom-drawn layout was rebuilt with segmented icons.
- Format / encoding buttons now use the same custom control, shown only on the "Pretty" tab.

**Added**
- The size card adds a Header / Body allocation bar; the time card adds an "estimated" note
  so each segment is not misread.

**Fixed**
- After changing the URL to time-tx, the previous image response was still shown — any
  request edit now invalidates the old response.
- After opening several request tabs their content merged together — responses, format,
  encoding and the current response sub-tab are now stored per tab.
- After dragging the sidebar width the URL bar disappeared and the description floated up —
  an interrupted animation now restores its paint state completely.

**Self-tests**
- 167 checks: fixed cards, button isolation, per-tab responses and animation-interrupt recovery.

## v1.0.7 — 2026-11-16

**Fixed**
- Sidebar collapse froze in two stages — the animation wrote to disk on every frame via
  `splitterMoved`. The signal is now disconnected during animation with a single write at
  the end.
- A new empty tab and an opened old request ended up with identical content — each tab is now
  an independent snapshot and collection tree changes only sync titles, not edits.
- The spinner never started on send, making the app look stuck — it now really spins with a
  skeleton shimmer.

**Added**
- Single-click a sidebar item enters VSCode-style preview (italic title, reused preview tab);
  double-click pins it.
- Param types use English names (auto / string / number / boolean / null / JSON).
- Settings → General adds a language switch (简体中文 / English), translated naturally and
  applied immediately across the whole UI.
- Node speed tests now cover every node (previously only 8), with controlled concurrency,
  a progress indicator, and a note that speed does not imply availability or overall latency.
- Response gains a format switch (Auto/JSON/XML/HTML/Text) and 11 encodings (UTF-8/GBK/Base64…).
- Hover detail cards over response time / size: segmented bar chart (DNS/TCP/SSL/TTFB/
  download) plus size breakdown.

**Self-tests**
- 155 checks: tab isolation, preview open, language switch, format / encoding, timing detail
  and spinner state.

## v1.0.6 — 2026-11-16

**Fixed**
- Only 22 nodes were listed — now the full 221 IPv4 / 130 IPv6 nodes are fetched, refreshable
  at any time.
- The gray bar in the method menu / command palette kept following the mouse after leaving —
  hover is now strictly bounds-checked.
- Sidebar collapse / expand stutter — the content repaint was frozen frame-by-frame during
  animation and the collection tree was no longer fully rebuilt at the end.
- Image / audio responses showed a row of question marks in Pretty / Raw — now a hint plus
  hex view, defaulting to Preview.
- After a title changed the pill width did not follow, swallowing the "+" into the pill; the
  collection tree showed left/right arrow cursors.
- A toast's underlying object was destroyed but still called, causing a crash.

**Added**
- Online nodes really work: the selected node forwards requests via a node server, with exit
  IP, region and latency annotated in the response metrics.
- The "Local" button moves to the right of Send; the node panel gains a refresh button and
  IPv4 / IPv6 counts.
- Preview gains "Save": images / audio / video / PDF / binary can all be saved locally.
- Settings gains an "About Ocelot" page and a "View What's New" entry; the changelog panel
  is color-coded by category.
- Param table gains a "Description (optional)" column used only as a note, never sent.

**Self-tests**
- 134 checks: indent gray block, menu reuse, zero-latency hover, toast sizing, three preview
  types, node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding
  and media container detection.

## v1.0.5 — 2026-11-16

**Fixed**
- Gray blocks to the left of selected collection-tree rows (the base class painted the indent
  area with the selection color) — the indent area is no longer painted and the selection
  background is transparent.
- Opening the method menu a second time crashed (`RuntimeError: MethodMenu has been deleted`)
  — the menu is now reused as a persistent object.
- The command palette's gray hover bar lagged behind the mouse — tweening was removed for
  zero-latency following, and the keyboard row uses a thin border instead of stealing focus.
- System toasts were large and empty — replaced with a custom-drawn toast sized to its text.
- Right-clicking an input opened the English system menu — replaced with a custom Chinese menu
  (Undo / Redo / Cut / Copy / Paste / Delete / Select All) with icons.
- gzip / deflate / br compressed bodies showed as gibberish or blank — they are now decompressed
  by `Content-Encoding` (with gzip-header sniffing as fallback).
- GBK / GB18030 pages showed garbled Chinese — when no charset is declared, UTF-8 then
  GB18030 are tried in order.

**Appearance**
- Unified base color: sidebar and workspace both use `#19191C`, removing the "half dark, half
  lighter" look and leaving a single 1px divider.
- Settings gains six color schemes: Graphite (default `#19191C`) / Slate / Warm Gray / Pine /
  Ink / Light; click a thumbnail to switch.
- Settings was rebuilt: section cards, scrollable content and a clearer information hierarchy.
- Sidebar is draggable 200–420 px and remembers its width; the title bar gains a collapse
  button (⌘B still works).
- The selected tab pill drops its outline.

**Added**
- "Preview" upgraded: image wheel zoom / drag pan / double-click fit / checkerboard transparency;
  embedded audio and video playback; PDF and binary get an "Open" and hex view; image / audio /
  video responses auto-switch to Preview.
- Media containers are detected by magic bytes (wav / mp3 / ogg / flac / m4a / webm / mov)
  instead of all being saved as unplayable `.bin`.
- "Nodes": the URL bar can select IPv4 / IPv6 nodes, searchable by region and ISP with one-click
  speed tests (TCP + DNS round trip), defaulting to "Direct". socks5 / http proxy nodes can be
  added and requests genuinely route through them, with metrics annotated.
- Network settings gain a default User-Agent; data settings gain a history limit.

**Self-tests**
- 108 checks: indent blocks, menu reuse, zero-latency hover, toast sizing, three preview types,
  node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding and
  media format detection.

## v1.0.4 — 2026-11-16

**Look & feel**
- Dark theme rebalanced around `#19191C`: five levels of gray for window / panel / card /
  overlay / selection; a content surface between sidebar and workspace so the boundary is no
  longer blurred.
- Method menu is custom-drawn: each method has a color, the current item shows a checkmark,
  row heights align and there are no native-menu rough edges.
- Removed all colored dots (collection tree, environments, tab strip) in favor of vector icons
  and status badges.
- Hover toasts use a rounded capsule style (smaller text, looser line height, no border burrs).
- Command palette hover uses a soft gray layer with 120ms easing, selected row gets a thin
  border instead of a hard cut.
- The tab strip's "×" and "+" were reflowed with ≥10px spacing.

**Params (rebuilt)**
- Add, remove, move up / down and copy / delete any row at any time.
- A new "Type" column: Auto / String / Number / Boolean / null / JSON, applied with the correct
  type when sent.
- Smart paste: `token=abc&debug=true`, `{"q":"x"}`, multi-line `k: v` or Tab-separated and `#`
  comment lines are split into rows in one paste, with comments auto-disabled.
- URL ↔ param table two-way sync: a URL with `?a=1&b=2` is split into the table and the URL
  keeps only the base; clearing params no longer leaves ghost params that break the request.

**Added**
- "Compare": auto line-by-line diff of this URL's response against the previous one, marking
  status code and latency changes, with a manual "Set as baseline".
- "Extract": use a JSON path like `a.b[0].c` or `*` to pull a field, with a hint listing valid
  top-level fields on error and one-click copy.

**Settings**
- Consolidated into a single page of six sections (General / Appearance / Network /
  Environments / Data / What's New) instead of nested dialogs.
- Code font size in three steps (Small / Standard / Large), applied to all open code areas
  immediately.
- The changelog panel was rebuilt: blocks per version, colored by category, word-wrapped,
  with a scroll that no longer stutters or overlaps.

**Self-tests**
- 80 assertions: param type inference, URL split, no ghost params, three paste formats, six
  Settings pages, diff stats and JSON path extraction.

## v1.0.3 — 2026-11-16

- Fixed a crash when the mouse moved over the collection tree (`RuntimeError: wrapped C/C++
  object of type QVariantAnimation has been deleted`) — the hover animation is now a
  persistent object instead of being destroyed at animation end.
- Added a "repeated hover" regression: sweep the collection tree three times, wait for each
  animation to finish and destroy before triggering again — 56 assertions.
- Sidebar-collapsed interaction tests now expand the sidebar first so no checks are skipped.

## v1.0.2 — 2026-11-16

- Fixed a crash when hovering the tab strip (`TypeError`: `QRectF.contains` only accepts
  `QPointF`, but got `QPoint`) that also killed the app when launched from the IDE.
- Startup self-check: on an old interpreter or missing PyQt6, print the interpreter path and
  a fix command instead of dumping a traceback.
- When launched from the run panel, bring the window to the front (`raise` + `activateWindow`).
- Added mouse-interaction regression: tab hover / click-to-switch / double-click blank to
  create, sidebar and segmented control sweeps — 53 assertions.
- Screenshot scripts now use a temporary state file instead of overwriting the real session
  (history, theme, open tabs).

## v1.0.1 — 2026-11-16

- Fixed: after switching from dark to light theme, JSON property names became nearly white
  and invisible on the light background (re-colored on theme switch).
- Fixed: the screenshot script overwrote real session data (now reads / writes a temp file).

## v1.0.0 — 2026-11-16

The first version: a pure-black, minimal API debugging tool with native macOS polish.

**Interface & motion**
- Borderless rounded window + traffic-light buttons (icons on hover), edge drag-resize,
  double-click title bar to zoom.
- Dark / light themes, pure-black layers, inverted solid primary buttons, no gradients or
  colored glows.
- All icons are 24×24 custom-drawn vector strokes, theme-colored and crisp on Retina.
- Animation: window fade-in, page cross-fade, response fade-in, segmented tab sliding underline,
  sliding selection pill, counting latency numbers, toast slide-up, sidebar collapse and
  loading skeleton shimmer.

**Request building**
- Method picker, URL input, query params and headers (enable switch / auto-append empty row /
  header autocomplete / bulk edit).
- Body: none / JSON / text / form (multipart with `@file` upload) / x-www-form-urlencoded /
  binary.
- Live JSON validation and format / minify.
- Auth: Bearer / Basic / API Key (Header or Query injection).
- Environment variables with `{{$timestamp}}` / `{{$uuid}}` / `{{$randomInt}}` dynamic variables.

**Send & response**
- Async cancellable send, timeout / follow-redirects / SSL-verify toggles, proxy (auto /
  system / direct), cookie persistence and parsing.
- Response metrics (status, latency, size, type, final URL).
- Six response views: Pretty / Tree / Raw / Headers / Cookies / Preview; in-response find and
  highlight.
- Copy response body, save to file, error-state hints.

**Organization & reuse**
- Collection tree (unlimited depth, drag sort, right-click menu, search filter, open-state dots).
- History (click to restore, hover to delete, clear).
- Multi-tab (drag reorder, sliding indicator, session restore).
- Environment variable management with active switching.
- Code generation: cURL / Python / JavaScript / HTTPie.
- cURL import, collection import / export (Postman v2.1 compatible).
- Command palette ⌘K, global shortcuts, Settings and What's New dialogs.
## v1.0.60 — 2026-11-19

**Changed**
- **The mark is now a solid silhouette**: a standing ocelot facing right, tail sweeping up behind into a fine arc. Built the way magpie's icon is built — one solid mass, with the background cut out to describe structure, instead of stroked line art.
- Only two negative spaces, both structural: an arch under the belly and a round eye. The head sits on the shoulder with no gap; round haunch, slim front leg, small round paws, low in front and high at the back.
- **Hover animation rebuilt for a solid mark**: the mark lifts 1% and scales 3.5%, the tail swings 4° around its root, and a point of light blooms inside the eye's cut-out — like the cat opening its eye. Everything eases back in 640ms on leave.
- Re-checked at small sizes: ears, legs and tail still read at 16px, and the 21px title bar no longer smears.
- The dock icon keeps the white rounded square, now with a near-black silhouette inside.
- Exported SVG assets are filled paths now (fill-rule: evenodd), so the asset and the app are the same shape.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.59 — 2026-11-19

**Changed**
- **The mark is redrawn thinner and sharper.** Stroke went from 5 to 4.3 units (~4.5% of the size) and the head is now one continuous curve — pointed ears, round cheeks, narrow chin — so it no longer smears into a blob at 21px in the title bar.
- **Hover animation is now "ink writing itself"**: a bright line leaves the chin, traces the whole contour, a small firefly rides the pen tip, and each spot blooms as the ink reaches it. The mark lifts, a faint light rises around it, and on leave the ink retracts along the same path in 620ms.
- Fixed why the old animation looked static: Qt measures dash length in pen widths, so the whole outline lit up at once instead of being drawn.
- The animation is no longer clipped by the widget bounds (6% inner margin, no more head tilt).
- At 40px and up the mark breathes — one 7-second cycle, so it is never quite still.

**Added**
- The dock icon is now a white rounded square with near-black line work, clean on any wallpaper.
- The response panel's "ready" empty state uses the brand mark and draws it once on open.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.58 — 2026-11-19

**Added**
- Line-art ocelot wordmark as the app logo: the welcome screen, the title bar (left of the title), the About card and the Dock icon now share one vector mark that follows the theme.
- Hover animation on the mark: the outline redraws itself from start to end, the whole mark lifts and scales slightly, and the two spots pop in with a spring. Leaving reverses the same curve. The About page plays it once on open.

**Changed**
- **Resource Manager trimmed down**: four metric tiles and six panels became three blocks — memory, storage, health — so there is nothing extra to interpret.
- The window shrank from 1080×800 to 656×452 and lost its scroll area.
- The maintenance strip went from four buttons to two: **Free memory** and **Clean up** (expired trash + backups older than 7 days + cached analyses), with a single combined report.
- Dropped the object-type scan (which walked tens of thousands of Python objects every refresh) and runtime widget counters; sampling is now every 3 seconds, so the dashboard costs less memory and CPU itself.
- Disk free space folded into the storage card as one line instead of its own card.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.57 — 2026-11-19

**Added**
- **Resource Manager** (settings menu, top-right): a real dashboard for memory, storage and runtime, fully bilingual and theme-aware.
- Memory: resident size read straight from libproc (no `ps` subprocess, works in restricted environments), peak, whole-machine pressure, and a 2-second sampler that draws the last three minutes with min / avg / max.
- Storage: app data split into state file / auto backups / logs / other, with proportion bars and per-group sizes, plus disk free space. The data folder path lives in a tooltip so it does not eat the layout.
- Runtime and assets: top 5 object types, threads, widgets, allocated blocks, and six counters for requests, collections, history, trash, environments and tabs.
- Maintenance strip: free memory (GC + icon / pixmap caches), clear analysis cache, purge expired trash, remove backups older than 7 days — each reports how much was released.
- Health score: weighted from system memory pressure, app data size, history volume and expired trash, with up to three actionable hints.

**Changed**
- AI analysis cache now expires after **8 minutes** instead of 30; the "Cached" tooltip follows the real value.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.56 — 2026-11-19

**Fixed**
- Trash folder detail: labels and values now share the same top alignment, so the three rows sit on one baseline instead of stepping down.
- English UI: AI status line, API-key hint, model heading, variables note, history count, about-page data path and settings title were built by string concatenation at runtime, so the generic translator could not match them as whole sentences. They are now rebuilt from templates on language change, in both directions.
- The conclusion block no longer has the text sitting above/below its side rule: the rule spans the full block and the text is vertically centred.

**Changed**
- Conclusion is now a theme-coloured quote block with a small theme-coloured dot before each section heading.
- Response panel's Auto / UTF-8 switches lost their pill border and fill, matching the rest of the toolbar.
- Hovering "Cached" shows the real expiry time (30 minutes) and a hint to re-analyse; translated in English too.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.55 — 2026-11-19

**Fixed**
- "Analyzing" no longer jitters: the status text stays put while only the spinner moves; streaming refreshes are throttled to 90ms.
- AI analysis layout rebuilt: the conclusion is a card with a side rule, evidence and recommendation lists use a separate bullet / 01-02 column so wrapped lines align with the text instead of snapping back to the left margin. Body text is brighter and larger, and bold fragments are highlighted.

**Added**
- Analysis cache: reopening an already analysed tab shows the saved result instantly instead of calling the AI again. Results are keyed by tab + request + response, shown as "Cached", capped at 8 entries, expired after 30 minutes, and cleared on close or data reload.
- "AI-generated · verify against the raw response" hint in the dialog footer.

**Changed**
- The analysis prompt is now a professional troubleshooting framework: HTTP status and business codes are strictly separated, findings are ranked (blocking / warning / note / normal), and every claim must cite a concrete field and value. All 11 tabs have their own focus; output budget raised to 1400 tokens, and a duplicated "focus:" prefix in the prompt was removed.
- Entry fade-in is 190ms; cache hits get a very light 160ms content softening without delaying the instant display.

**Verified**
- Targeted and full smoke checks pass.

## v1.0.54 — 2026-11-19

**Fixed**
- AI no longer calls a successful HTTP 200 response an "error code" just because the body contains `code: 1`. Business codes are interpreted from `msg` / `data` / `success`, not from the number alone.
- AI-renamed requests now update the collection node and matching history entries, so the sidebar shows the new name immediately.
- Global fix for IME composition: placeholder text is hidden while candidate words are being composed and restored afterwards, for every text input.

**Added**
- "AI response analysis" dialog: streaming Markdown output with fade-in animation and spinner, copy and re-analyze buttons, and an entry on the response tab row.
- Tab-aware analysis: pretty / tree / raw / headers / cookies / console / preview / diff / extract / timeline / network error each get their own evidence and focus points.
- Stale-response notice now has a close (x) button and "Never remind me" (persisted in settings).

**Changed**
- API docs code sample is collapsed by default; expand with the chevron.
- Removed AI script writing from pre/post script pages and removed DeepSeek from AI settings (GLM only).
- Rewrote all prompts for data generation, response analysis, docs and naming to be evidence-based and specific.

**Verified**
- 654 smoke checks plus 57 targeted checks pass.

## v1.0.53 — 2026-11-19

**Added**
- The code sample section in the API docs window now has a collapse arrow (the same chevron used in the collection tree): collapse it and the document takes the whole height.
- "AI content" switch in the docs window: hide or show the AI-written sections at any time; while off, copy and "Save .md" produce the purely generated document.

**Changed**
- Script AI is far less strict: it treats every request as a coding task and writes runnable JavaScript instead of refusing when the description is vague or off-topic. Only a plain prose answer (no code at all) is reported back.
- AI prompt dialog now sizes itself from its content, so the text box no longer runs under the buttons when the hint wraps or the font is larger.

**Removed**
- "New request from a sentence" is gone from the welcome screen, the command palette and the code behind it.

**Verified**
- 654 smoke checks plus 53 targeted checks pass.

## v1.0.52 — 2026-11-19

**Changed**
- Settings now has a single "Variables" page: environment variables and global variables sit behind one segmented switch, with the override rule (environment wins) stated right in the header. The old separate nav entries are gone.
- The AI settings page was rebuilt: switch → provider → key → models → advanced, with a single status line (ready / not configured / off) instead of colored decoration.

**Added**
- AI master switch: keep the key but turn AI off, and every AI entry point goes quiet; key and model choice are preserved.
- DeepSeek support next to Zhipu GLM (DeepSeek-V3 and R1 cards). Each provider keeps its own key and switching brings the right one back.
- "New request from a sentence" on the welcome screen and in the command palette: method, URL, headers, query params and body are filled in, with Content-Type added for JSON.
- "Save response field as variable" in the response more menu: pick a field, get a suggested name, store it globally or in the current environment.
- AI auto-naming with a switch: unnamed or URL-derived request names become human-readable after sending; hand-renamed requests are never touched, and each URL is only asked once.
- "AI script" as the first button on the pre-request and post-response script pages: describe the goal in a sentence and get JavaScript that only uses this sandbox's API; off-topic requests are refused and never written into the editor.
- "AI fill" in the API docs window: appends overview, field meanings and common errors to the generated document — included in copy and "Save .md", and the response sent to the model is redacted while the redact switch is on.

**Verified**
- 654 smoke checks plus 52 targeted checks (variable precedence, per-provider keys, AI switch, script refusal, doc append, one-sentence requests) all pass.

## v1.0.51 — 2026-11-19

**Fixed**
- Tab drag-and-drop is smooth again: reordering now reports once on mouse release instead of syncing `state.json` on every frame, tab widths/rects are cached, and the indicator snaps instead of restarting an animation mid-drag.

**Added**
- Global variables: available in every environment and request via `{{name}}`; a same-named environment variable overrides them. Manage them in Settings → Global variables.
- AI settings page: paste a Zhipu GLM API key and go. Four preset model cards (GLM-4-Flash 250414/latest, GLM-4.5, GLM-4.1V), one-click connection test, plus custom model ID and base URL for proxies or self-hosted gateways.
- AI body generation: in a JSON body, "AI generate" builds realistic data from the existing field names (or param keys), streams it into the editor and formats it when done.
- AI error explanation: available on the failure page and in the response "more" menu — returns the cause plus concrete fixes.

**Changed**
- Sidebar methods longer than 4 characters are abbreviated to 3 letters (PATCH → PAT, DELETE → DEL, OPTIONS → OPT) so names get more room.
- The Params tab of HTTP, WebSocket and Socket.IO no longer offers the File type (query params can't carry files); multipart form uploads keep it.

## v1.0.50 — 2026-11-19

**Changed**
- Request tabs now lift and follow the mouse while being dragged to reorder, leaving a translucent placeholder at the original spot — matching the sidebar's drag feel.
- WebSocket and Socket.IO "Params" pages now include "Paste" and "Bulk Edit", fully on par with HTTP params: bulk import from clipboard, key: value bulk editing, comment lines mark rows disabled, and the final-URL preview updates live.

## v1.0.49 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use three tabs: Chat / Params / Protocol (Auth). Added a real query-parameter table that is appended to the URL on connect, with bulk edit and a final-URL preview.
- Socket.IO Chat page first row is now "Event name" with matching English text; namespace moved into the Auth page; all rows share one left alignment with no functionality lost.
- Sidebar drops the duplicate "New Folder" button; the trash entry moves to the bottom action bar and the delete animation now flies to the new spot.
- Creating a folder now jumps focus to it with a highlight pulse and opens inline rename with a default name: confirm to keep it, type to replace.
- The search box now filters both Collections and History, keeps its text across tab switches, and hides empty history groups.
- Fixed the trash detail popup misalignment in English (truncated labels / uneven value column) with a language-aware label width; also reduced redundant history row rebuilds.

## v1.0.48 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now align their tabs, toolbar rows and inputs to the same left edge as the method badge; both protocols share one baseline.
- Protocol and Auth pages drop the full grey card background, keeping only group titles and thin dividers for a cleaner look.
- Removed leftover collapsed-card state, unused message counters and duplicate helpers to cut dead code.

## v1.0.47 — 2026-11-19

**Changed**
- WebSocket and Socket.IO request pages now use the same underline tab style as HTTP requests: WebSocket splits into Chat / Protocol, Socket.IO into Chat / Auth.
- The Chat page keeps only day-to-day sending: namespace, event name, payload, JSON/Text switch, format, save and send.
- Low-frequency settings moved to a second tab: connection parameters for WebSocket, handshake auth and ACK/reconnect options for Socket.IO.
- Socket.IO payload input gains a JSON/Text switch (controls highlighting and formatting), and its "More" menu now shows Socket.IO-specific actions: copy URL, export/clear event log.

## v1.0.46 — 2026-11-19

**Changed**
- Unified the layout of the WebSocket and Socket.IO pages into one skeleton: options row / composer row / editor / frequent chips — matching the HTTP request view while keeping only useful controls.
- The method badge on realtime pages now shrinks to a compact label, giving the room back to the URL field and removing the empty gap after the method name.
- Protocol fields (subprotocol, namespace, auth, event name) now stretch to fill the row and action buttons sit flush right for a cleaner look.
- Low-frequency switches are grouped on their own row and aligned with the handshake-headers button; both realtime pages now look identical, with no clipping in English or Chinese.

## v1.0.45 — 2026-11-18

**Added**
- Socket.IO requests with a dedicated "Events" page, creatable from the New Request menu and command palette.
- Lightweight Engine.IO v4 / Socket.IO v4 over websocket transport: handshake, namespaces, auth JSON, event emit/listen, ACK receipts, heartbeat and auto-reconnect — no extra dependency.
- Distinctive touches: auto-discovered events with one-click filtering, frequent events for one-click reload, double-click an event to load it back, JSON payload highlighting and formatting, clear-after-send.

**Fixed**
- Initialized the ACK registry to prevent a crash, and stopped treating ordinary integer data as an ACK id on server events that request a receipt.
- Auto-reconnect now keeps the namespace and auth; Socket.IO connections are fully closed on exit, leaving no orphans.
- Complete Chinese/English strings for namespace, auth, events, ACK and discovered events.

## v1.0.44 — 2026-11-18

**Changed**
- Trash time groups now use the same chevron as the collection tree, with the item count aligned right like history groups.
- Removed the redundant "Oldest deleted" strip above the trash list.
- Fixed hover cursors: collection tree and history rows now show the pointing-hand cursor again.
- Slightly widened the trash window and filter sidebar so English "Custom" and the date inputs are no longer clipped.
- Filled in missing English strings for the trash tooltip and WebSocket "Connecting to …" log line.
- Added a light dissolve animation for deleting a single history entry and clearing all history: sweep line, soft ring, fade-and-collapse.

## v1.0.43 — 2026-11-18

**Changed**
- Group trash items by deletion time (within 1 hour / today / yesterday / 7 days / 30 days / older), with collapsible headers and expand animations.
- Detail popup now fills with params / headers / body / cookies / auth / variables / sub-requests and scrolls.
- Unified method colors with the theme palette; WS / HEAD / OPTIONS are no longer grey.
- Fixed the transparent context menu by drawing an opaque rounded background; full CN/EN strings.
- Extended clear / restore / delete animations by ~0.5s for a calmer feel.
- Added a lightweight arc-to-trash-button fly animation when deleting from the sidebar.

## v1.0.42 — 2026-11-18

**Changed**
- Calendar weekday header switched to the theme's dark palette instead of the
  system light-grey strip.
- Removed the always-on trash detail panel so deleted records use the whole
  area; "Oldest deleted" moved above the list and aligned with the row icon.
- A small "Details" pill appears on row hover and opens a lightweight detail
  popup, keeping the layout clean.
- Added a 1px hairline separator between the filter sidebar and the list.
- Empty / restore / permanent-delete now play a light artistic animation
  (expanding ring + icon fade-in) with minimal resource use.

## v1.0.41 — 2026-11-18

**Changed**
- Trash stats bar items all aligned left again as before; search box now has a
  visible border so it reads clearly against the dark background.
- Refresh button icon spins one full turn on click for clear feedback.
- Widened the trash filter sidebar so the custom date range inputs are no
  longer clipped.
- Command palette gained "Open Trash" and "Trash auto-clean settings" actions.
- Trash detail simplified back to a short list (URL / contains / deleted at /
  original location) with type and method pills on the title row.

## v1.0.40 — 2026-11-18

**Changed**
- Trash window re-laid out: search moved into the top-right stats bar, the
  redundant activity timeline removed, and the detail panel made richer and
  scrollable (type / method / URL / params / headers / body / env vars /
  original location / exact delete time).
- Custom date range picker restyled to follow the pure-black theme — the
  system calendar's white background, red weekends and purple selection are
  gone.

**Added**
- "Trash auto-clean" switch (on by default) and retention period (7 / 30 / 90
  days) in Settings · Data. Expired items are permanently removed when saving
  settings and on launch.
- Cascade restore hints: selecting a folder also selects its independent child
  entries in the trash, and restoring prompts how many requests come back with
  it. Requests referencing `{{variables}}` get an undefined-variable warning.
- Saving a request now scrolls the left collection tree to the saved item;
  restoring from the trash refreshes the sidebar and reveals items at their
  original position. The Refresh button now re-reads state from disk.

**Verified**
- Self-test suite: 593 checks, 0 failures. Real launch with Trash window OK.

## v1.0.39 — 2026-11-18

**Added**
- Trash for deleted collections / folders / requests. Deletes now move items to
  the trash instead of erasing them, and restore puts the whole subtree back at
  its original position.
- A blurred, fixed Trash window with a distinctive three-part layout: filter
  rail on the left, item list on the right, detail panel at the bottom. Pure
  black minimal theme, no gradients or colored outlines.
- Full trash toolkit: restore, delete permanently, empty, detail view, search
  by name / URL / method, date-range filtering (today / 7d / 30d / custom),
  refresh, multi-select batch actions, an activity timeline and exact delete
  timestamps. Sidebar entry shows the item count.

**Fixed / Changed**
- HTML / XML code highlighting now uses the unified One Dark scheme (blue tags,
  amber attributes, green values, gray punctuation, colored inline script /
  style). `xml` was previously downgraded to the Python highlighter, leaving
  markup almost entirely gray.
- Sidebar delete is now "Move to Trash" with an accurate, reassuring prompt
  instead of an irreversible-delete warning.

**Verified**
- Self-test suite: 579 checks, 0 failures.

## v1.0.38 — 2026-11-18

**Fixed**
- Two expanded message cards could overlap. The list laid out rows using an
  80px estimate for a not-yet-created card, so once the real card turned out to
  be several hundred pixels tall the following rows were drawn right on top of
  it. Layout now creates and measures every expanded card first, then positions
  rows, and checks convergence against the row offsets themselves (not against
  whether card properties changed, which broke out of the loop too early).
- Scrolling to the bottom still hid the last message: the list height omitted
  the expanded card on the final row. Total height now includes that card in
  full, so the bottom edge is reachable.
- Resizing the window narrower reflows long text and changes card height; the
  whole list is now re-laid out on resize instead of only repositioning cards.

**Changed**
- Detail cards no longer show the "响应体" label; the Raw tab and the code box
  are aligned to the same left edge.

**Verified**
- Self-test suite: 554 checks, 0 failures.

## v1.0.37 — 2026-11-18

**Fixed**
- Scrolling over an expanded message card now scrolls the whole log again. The
  read-only code view was swallowing every wheel event (it still scrolled its
  own 1px), so the outer list never moved — the mouse sat on the card and
  nothing happened. Wheel events are now forwarded to the log scroll area.
- The scroll area no longer depends solely on its easing animation to move:
  it lands on the target value even when the animation cannot fire, so the
  wheel always works (including in safe mode).
- Tabs are chosen by **content** again: a plain-text frame shows only **Raw**,
  a real JSON payload shows **JSON / Raw**. Previously every text frame was
  given a JSON tab, so a plain "hello" message and even ERR system messages
  sported a meaningless JSON tab.
- Removed the collapse chevron from the top-left of detail cards; cards stay
  open with their full content visible.

**Changed**
- Code surface background moved closer to the window base (`#171717`-like),
  matching the response panel look the user compared against.

**Verified**
- Self-test suite: 549 checks, 0 failures.

## v1.0.36 — 2026-11-18

**Fixed**
- WebSocket detail code frames no longer render on a dead-black viewport: the
  background now follows the theme's code background (a shade close to the
  window base), so keys / strings / numbers keep the full syntax-highlight
  palette against a surface that matches the app.
- Plain-text frames whose payload is JSON now get the **JSON** tab and syntax
  highlighting too. Previously only frames tagged `json` at send time did,
  which left a JSON body showing a lone **Raw** tab with no colours.
- Expanding a log card no longer lets later frames cover it. The incremental
  append path now uses each open card's real height instead of a fixed 80px,
  and auto-scroll pauses while any card is open — so the expanded content
  stays in view and can be scrolled through.
- The "…" button in the response header now does something in a WebSocket
  session. It opens a WS-specific menu: connect / disconnect, copy URL, copy
  session stats, export the message log and clear it.

**Removed**
- The "Saved messages: store anything you send often…" empty-state hint in the
  WebSocket composer; the chips and their tooltips speak for themselves.

**Verified**
- Self-test suite extended to 550 checks.

## v1.0.35 — 2026-11-18

**Changed**
- WebSocket detail cards were rebuilt around content only: no repeated timestamp / preview
  from the row above. Tabs, copy button and a clean bordered code frame make the hierarchy
  clearer.
- Every expand arrow now uses the same chevron as the collection tree (right when collapsed,
  down when expanded) — both in log rows and in detail cards.
- The code frame can be collapsed. JSON keys and values no longer render in bold.
- The code frame has no scrollbars: it grows to fit all content and the outer log area
  handles scrolling.

**Fixed**
- Multi-line JSON in a log row used to overlap the rows below. Previews are now compacted
  to one horizontal line regardless of how the original was formatted.

**Verified**
- Self-test suite extended to 544 checks; startup-to-show ~547ms; clean exit with an open
  WebSocket connection.

## v1.0.34 — 2026-11-18

**Fixed**
- The URL-bar button still read **Connect** while a WebSocket was open (and after switching
  tabs); it now reads **Disconnect** and stays that way.
- Messages in progress were lost when switching tabs. Drafts and the text / JSON / binary
  choice are stored with the request.
- The input hint showed through Chinese IME preedit text (e.g. `ni'hao` overlaid the hint).
  The placeholder now hides while composing and returns afterwards.

**Changed**
- Log rows expand into inline detail cards: Raw / JSON / Hex tabs, line numbers and a copy
  button. Several rows can stay open at once (capped at 12, oldest closes first so the UI
  never accumulates thousands of text documents).
- JSON details keep their indented layout; row previews stay on a single elided line.
- Counters (received / sent / bytes, uptime / traffic) animate over 280ms instead of jumping.

**Improved**
- Appending frames is incremental and stats use cached counters: 4000 frames append in
  ~2ms, and painting remains limited to visible rows.
- Self-test suite extended to 539 checks.

## v1.0.33 — 2026-11-18

**Fixed**
- Occasional hard crash (`zsh: bus error`, `crash.log` showing `<no Python frame>`) when
  quitting. Shutdown now stops every animation, drops graphics effects, closes sockets and
  tears the window down explicitly instead of relying on Qt / Cocoa destruction order.
- The WebSocket log's empty hint was squeezed into a 1px line (the list is 8px tall when it
  has no rows). It now has its own centred page, with a different message when a filter
  matches nothing.
- **Settings → Appearance → Text size** did nothing: the dialog saved the value and closed,
  so the rebuild step saw "no change". It now zooms in place — the settings page stays open
  and the whole UI resizes as you click.

**Changed**
- WebSocket is a request *kind*, not a method: `WS` is gone from the method dropdown, and a
  WS request is created only from **New request → WebSocket request**.
- WS requests get a dedicated page with only what they need: message editor (text / JSON /
  binary), saved messages, subprotocol, heartbeat, auto-reconnect, clear-after-send, and a
  collapsible handshake-headers editor. The HTTP-only tabs are gone.
- "Export this folder" is now **Export collection**.
- The command palette is shorter — a floating panel rather than a full-height sheet.

**Improved**
- Welcome cards and empty states scale with the text-size setting, so 150% no longer
  overlaps lines.
- Self-test suite extended to 529 checks (WS page, handshake headers, live text scaling,
  palette height).

## v1.0.32 — 2026-11-18

**Added**
- **WebSocket requests.** Create one from **New request**, or switch any request's method to
  `WS`. Addresses accept `ws://` / `wss://`; pasted `http(s)` URLs are rewritten.
- Full WS feature set: text / JSON / binary messages, handshake headers + cookies + auth,
  subprotocols, ping heartbeat with real round-trip latency, exponential-backoff
  auto-reconnect, and live connection stats (uptime, frames and bytes in/out).
- A frame log with direction, type, time and size; filter by Received / Sent, search the
  contents, click a row for the full payload, copy, export to JSON or text, clear. Capped at
  4000 frames so long-running subscriptions stay light.
- Common messages: save recurring payloads as chips, click to load them back. They travel with
  the request in Ocelot / Postman export and come back intact.
- Double-click any received frame in the log to **replay** it: the payload is loaded back into
  the editor so you can tweak it and send again — no copy-paste.
- Settings → Appearance → **Text size** (100% / 110% / 125% / 150%). Scales the whole UI and
  the code area; applies instantly and returns you to the same settings page (unsaved tabs
  are carried over).
- Right-click a folder in the collection tree → **Export this folder** (Ocelot, Postman,
  OpenAPI, HAR). The default file name is the folder name and the exported file keeps the
  same folder structure.

**Fixed**
- Hovering "response time" after a failed request still showed a bogus `9 ms` card. Time,
  size and type are now hidden on failure, and the hover cards are gone.
- In English the `failed` pill was narrower than its label, so the text spilled out of the
  rounded background. Pills now size themselves from real glyph metrics.

**Improved**
- The command palette only paints the rows that are on screen; the rest render as you
  scroll, while search still matches every entry.
- Batch-running a collection skips WebSocket requests.
- Self-test suite extended to 519 checks, including a real local WebSocket server covering
  connect, echo, heartbeat, replay, disconnect and refused connections.

## v1.0.31 — 2026-11-18

**Fixed**
- The backdrop blur was not aligned with the window: it covered the whole window rect
  (including the 8 px shadow margin) and its corners stayed square. It now covers only the
  window card and is clipped to the same 12 px radius, so the arcs line up.
- The command palette had no blurred backdrop, and opening it made the card jump vertically.
  Layout is now fully computed before the palette is shown, and it fades in from 10 px
  above with a 120 ms animation.
- On the failed-request page the **Clear / Copy all** buttons were too loud. They are now
  compact and sit on the same line as the output summary, flush with the content edge.
- History mode showed two **Clear History** buttons (a text one and an icon one); the icon
  one is gone.
- Preview tabs stayed italic after double-clicking a collection item or sending the request.
  They are promoted to a normal tab now.
- The import source list had a large gap between **Import from URL** and **Export all
  collections**; the dialog height now follows the content.

**Added**
- Deleting a collection, folder or request (and clearing history) now asks for
  confirmation. Deleting a folder tells you how many requests go with it.

**Improved**
- The "Blur All Dialogs" description in Settings is a single short sentence.
- Self-test suite extended to 482 checks, all passing.

## v1.0.30 — 2026-11-18

**Fixed**
- The tab pill slide had disappeared: clicking a tab calls `set_current` twice (once from
  the click, once from the selection callback) and the second call snapped the animation
  that had just started. The pill now slides with a subtle velocity stretch, and the
  outgoing/incoming tab labels and method badges cross-fade.
- The modal backdrop was only blurred on the left-hand side. Replaced the Qt blur render
  with a two-stage downsample blur that is uniform across the whole window (about 3.5 ms
  for 1600×1000, a few hundred KB peak memory).
- The success check on the import result page sat left of centre: its icon was centred
  using device pixels, which is 2× off on Retina. It is now centred in logical pixels and
  gets a small expanding halo when it appears.
- Imported collections had the wrong name. The name now comes from the file
  (`info.name`, Apifox collection name, Insomnia workspace, OpenAPI title) or the file
  name, and the collection is created as a folder with that name — inner folders keep
  their hierarchy. A single-request JSON still imports as one request.

**Added**
- `Collections / History` segmented control: the selected pill slides between the two
  labels and the text colour cross-fades.
- Every dialog is centred on its parent window, including when a page change resizes it.
  Only Settings and Import/Export are blurred and immovable by default; other dialogs
  stay unblurred and can be dragged by their title bar.
- New setting **Appearance → Blur All Dialogs**: turn it on and every dialog becomes
  blurred and immovable.
- Command palette: the five most-used commands are pinned under a **Frequently used**
  heading (ordered by real usage, so the list adapts), followed by **All commands**. The
  card is centred and slides down as it fades in.
- **Import from URL**: paste a remote JSON / YAML link (8 MB limit); it downloads and runs
  through the same detection pipeline as a local file.

**Improved**
- Export file names default to the collection (folder) name instead of
  `ocelot-collection`.
- Removed a batch of unused imports and redundant work; the self-test suite now covers
  467 checks and passes.

## v1.0.29 — 2026-11-18

**Fixed**
- The selected tab pill no longer overlaps the neighbouring tab at launch. A pending
  indicator animation kept writing a stale rectangle after the geometry had been snapped;
  the pill now always derives from live geometry, and restoring a session no longer
  animates once per tab.
- Changing the request method (POST → GET) now updates the method badge in the collection
  tree. The editor, the tab badge, the stored node and the saved file stay in sync.
- Switching method after a request no longer throws the response away. The previous result
  stays on screen with a slim "Request changed · showing the previous response" bar that
  offers a **Send again** action.
- Importing a Postman file could fail with "no importable requests": Apifox
  `apiCollection` payloads and Insomnia exports whose requests hang under a workspace were
  parsed as empty. Postman data dumps, Postman v1 collections, Hoppscotch v2 objects,
  files with a UTF-8 BOM and bare single-request files are now recognized too.

**Added**
- Import / export result page: a large check, the title, and a breakdown of what was
  brought in (collections, requests, folders, pre-request scripts, post-response scripts,
  auth, environment variables). Export results offer **Show in Folder**.
- The file page reports what was detected before importing (format plus counts), and the
  sidebar reveals and expands the newly imported collection.
- Environments travel with the collection: Postman dumps, Apifox and Insomnia environment
  resources are imported alongside the requests.
- Dialogs and the settings panel now blur and dim the main window behind them, and the
  modal is pinned in the centre of its parent instead of being draggable.

**Improved**
- The collection search field fills the width up to the import / export button.
- The export page states what will be written ("Exporting 1 collection, 5 requests") and
  disables the rows when there is nothing to export.

## v1.0.28 — 2026-11-18

**Added**
- A **Console** tab in the response panel: `console.log / warn / error` output and `test()`
  assertions from pre-request and post-response scripts, color-coded by level with Pre/Post
  badges, one-click copy, and inline output on the error page so a failing pre-request script
  is still visible when no response arrives. The console also records the outgoing request
  and the final status line.
- An **Import / Export** button next to the collection search field. A single dialog handles
  both directions with a back arrow: import from Ocelot JSON, Postman, Apifox, Hoppscotch,
  Insomnia, OpenAPI 3.x (JSON or YAML) and HAR, plus clipboard import; export as Ocelot JSON,
  Postman v2.1, OpenAPI 3.1 (JSON / YAML) or HAR. Files can be dropped onto the dialog, and
  the chosen file is parsed and summarized before importing.
- **Ocelot JSON** uses Postman v2.1 plus an `x-ocelot` block, so Postman / Apifox can import
  it directly while a round trip through Ocelot keeps scripts, auth and cookies.
- **Rename** in the tab context menu: updates the collection node, the tab title and the
  request itself, saves immediately, and pushes to the cloud when auto-sync is on.
- Clicking a tab now reveals the matching request in the sidebar: switches back to
  collections, expands the parents, clears a hiding filter and scrolls the row into view.

**Improved**
- Script engine hardened: `res.body` / `res.text` now return real text instead of a bound
  method, `req.setHeader` keeps existing rows disabled as before, and `res.json()`,
  `res.setHeader()`, `pw.env.has()`, `pw.env.toObject()` and `test()` were added. Syntax
  errors report the line number the user sees, and endless loops are stopped after 2 seconds
  by a deadline check injected into loop bodies (no background thread, so the process can
  never be aborted by a leftover thread at exit).
- Snippet buttons insert on a fresh line instead of mid-line; post-response scripts get
  response-reading and assertion snippets.
- Body badge no longer copies the whole body on every keystroke.

**Fixed**
- Editing a request and saving never wrote the changes back to the collection node, so
  reopening showed the old content. Tabs now sync into their node on every save.
- After an unclean exit, the next launch starts with animations temporarily disabled to
  avoid the macOS graphics-layer hard crash; focus is released before the window closes.
- All 429 self-tests pass.

## v1.0.27 — 2026-11-18

**Improved**
- The script run status now pairs a thin check/cross icon with the text. Success shows only
  "Ran successfully"; the line is left-aligned with the editor above and sits right beneath
  it, fades in when it appears, and uses the theme's success/danger colors. The icon uses a
  light stroke weight.
- Language switching now walks the widget tree once instead of twice; history group counts
  are computed in a single pass. Duplicate imports and redundant calls were consolidated.

**Added**
- A **Raw** body mode with a JSON / XML / HTML / Text language selector. The selected
  language drives syntax highlighting, formatting and `Content-Type`. All send paths and
  code generators now share one normalization helper.

**Fixed**
- History group titles are translated at paint time, so switching between Chinese and
  English updates them immediately instead of leaving the old language on screen.
- All 395 self-tests pass and repeated real GUI startups are crash-free.

## v1.0.26 — 2026-11-18

**Improved**
- Script **Run test** results now appear in a dedicated dialog. The status line shows only
  "Ran successfully", left-aligned with comfortable padding and a subtle fade-in when the
  text appears. The inline log panel at the bottom of the page is gone.

**Added**
- Params now has a **Bulk Edit** button, so you can edit all query parameters at once as
  `key: value` text.
- History is grouped into **Within the last hour / Today / Yesterday**, with each group's
  collapsed state remembered independently. Group headers now share the same subtle hover
  animation as the other buttons.

**Fixed**
- Fixed an intermittent startup `bus error` crash. The frameless translucent window now fades
  in using native window opacity instead of a graphics effect, and pages hosting native video
  views no longer get a `QGraphicsOpacityEffect` applied.
- All 395 self-tests pass.

## v1.0.25 — 2026-11-17

**Fixed**
- The run status on the script page is now a single line. `console.log()` output from both
  **Run test** and real requests is written to a read-only log panel directly below, so the
  "see logs below" message finally points at something real.
- Editing a pre-request or post-response script no longer wipes out the last response. Script
  changes update the request data and the dirty flag only; the response panel keeps showing
  what you were looking at.

**Improved**
- The auth type name **Inherit** is now always shown in English, matching Bearer, Basic,
  API Key and JWT.
- Params, Body, Headers, Cookies and Auth pages now each get a slim scrollbar. When their
  content is taller than the request pane they scroll on their own instead of being clipped.
- The collection runner uses the theme's subtle hover color for the current row instead of a
  bright gray bar. Clicking a finished row opens that request with its captured response, so
  you can inspect the result directly.
- All 395 self-tests pass.

## v1.0.24 — 2026-11-17

**Improved**
- The script editor is now split into two dedicated pages, **Pre-request Script** and
  **Post-response Script**; the redundant in-page tab switch is gone. The reference panel
  on the right scrolls independently with a slim scrollbar, so overflow no longer pushes
  the controls below out of place. `Run` becomes a clearer **Run test** button with a
  tooltip explaining that it runs the script locally without sending a request.
- History groups now use the same chevron as the collection tree. Click a group header to
  collapse or expand it, and the state is remembered across restarts.

**Added**
- **JWT auth** — auto-generate a signed token with HS256 / HS384 / HS512 or paste one
  manually. Payload and secret support environment variables, and the token is sent as
  `Authorization: Bearer <token>`. Generated tokens match the jwt.io standard exactly.
- **Inherit auth** — walk up the request's collection to find the nearest folder auth.
  Configure it from the folder's right-click **Configure auth…** menu. Both JWT and Inherit
  work on the direct and relay send paths.

**Optimized**
- All 395 self-tests pass.

## v1.0.23 — 2026-11-17

**Added**
- **Pre-request and post-response scripts** powered by Qt's built-in JavaScript engine
  (QJSEngine, zero extra dependencies). Modify the URL, headers and query params before
  sending; parse the response after it arrives. `pw.env.set()` writes variables into the
  active environment and persists them, `console.log()` output is visible, and a broken
  script never blocks the request.
- **Complete body type set** — none / form-data / x-www-form-urlencoded / JSON / XML /
  Text / Binary, with names aligned to mainstream API clients. XML is a new first-class
  type with syntax highlighting, validation, one-click formatting and automatic
  `application/xml` content type.

**Improved**
- Code editor now supports automatic bracket and quote pairing, smart indentation on
  Enter, Tab indentation and wrapping a selection in a pair. JSON and XML can be
  formatted in one click; JSONC line comments are handled.
- One unified syntax highlighting scheme across the whole app — JSON and Python /
  JavaScript / Go / Java and more share a single One Dark style token palette (declaration
  keywords in pink, functions in blue, strings in green, numbers in orange). Request
  bodies, responses, code examples and the script editor all use it.
- The response size card now counts header bytes including the status line, and adds a
  **Request Size** section with separate Header / Body figures. Card background is darker.
- History is grouped by date (Today / Yesterday / N days ago) with a count per group.

**Optimized**
- All 395 self-tests pass.

## v1.0.22 — 2026-11-17

**Fixed**
- **Switching the language in Settings left the right-hand page in Chinese**: the Settings
  window is a separate top-level window that the main window's translation pass could not
  reach. It now re-translates itself on switch, including the page title and nav width.
- **An extra divider line above the response area**: when the metrics bar was hidden, the
  divider below it stayed visible and overlapped the splitter handle. The divider now shows
  and hides together with the metrics bar, leaving a single line.
- **"New Mock Route" / "New Condition Rule" dialog titles were not translated** in English.
- **Timeline stats and "No Wrap" were not translated**: hit count / success rate / average /
  P95 / slowest, plus the raw view's wrap toggle, stayed in Chinese under English.

**Improved**
- Request panel tab order is now Params / Body / Headers / Cookies / Auth, with the most
  used Body tab moved to second place.
- Code examples in the API doc now share one fixed height: switching languages no longer
  makes the block jump between sizes; overflow scrolls inside.

**Optimized**
- All 395 self-tests pass.

## v1.0.21 — 2026-11-17

**Fixed**
- **The history list went blank in English**: the sidebar's segmented tabs did not recompute
  their widths after a language switch, clipping the `History` segment. Tabs now re-measure.
- **Command palette action names stayed in Chinese**: new request / send current request and
  others were untranslated, as were "Default" in the format menu and "Click to choose a
  file…" in file cells.
- **A chosen file in the request body could not be sent**: the code used the display text
  as the path, which becomes `No file chosen` in English and was treated as empty. The path
  is now stored separately from its display text.

**Improved**
- Settings header and footer hints wrap automatically, so long English text is no longer
  clipped at the window edge.
- English copy reviewed throughout; terminology keeps aligning with Postman.

**Optimized**
- All 395 self-tests pass.

## v1.0.20 — 2026-11-17

**Fixed**
- **Square window corners**: the rectangular content layer covered the window's own rounded
  corners. The content layer now has a rounded mask that follows the window, disabled when
  maximized.
- **Gray squares next to selected response-tree rows**: the indent cell got a system hover
  background. The highlight is now fully transparent while selected text stays highlighted.
- **Two rapid requests crossed streams**: an old request's `finished` signal treated the new
  request as done, leaving the spinner running or showing the wrong response. Results are
  now matched by signal source and stale ones are discarded.

**Improved**
- Settings / What's New footers no longer print `Ocelot x.y.z · Python + PyQt6`.
- The About page drops the runtime (Python / PyQt6) and "native macOS window" tags.
- Full English pass: toasts, placeholders, tooltips, Settings pages, Mock hub; terminology
  aligned with Postman (Send / Params / Headers / Cookies / Environments / Mock Server),
  with no source text lost when switching languages.

**Optimized**
- Large arrays only render the first 300 items with a "… {n} more" trailing row; even
  200,000 items open instantly.
- Added a crash log: hard crashes and uncaught exceptions are written to `crash.log` in the
  data directory.
- 395 self-tests.

## v1.0.19 — 2026-11-17

**Fixed**
- **Clicking "More → Mock data…" crashed**: the editor was missing the `mockRequested`
  signal and raised `AttributeError`; "Copy request" in the same menu had the same issue and
  was fixed too.
- Mock / Copy request in the More menu are now forwarded uniformly by the editor, with a
  single signal connection — one click no longer opens two windows.

**Improved**
- Response tree view: row height 16 → 21; the key column is sized to its content so
  `two_factor` is no longer truncated to `two_fa…`.
- The API doc footer now prefixes the status line with a "Status" label instead of showing
  a bare string of words.

## v1.0.18 — 2026-11-17

**Fixed**
- **Right-clicking inside an input crashed**: `QApplication` has no `cursor()` method and
  raised `AttributeError` when resolving the click position. The context menu now uses the
  screen coordinates carried by the event, falling back to the mouse position only if needed.
- **Mock showed "Stopped" but a browser refresh still worked**: stopping closed the listen
  port, but an existing HTTP keep-alive connection kept being served. Stopping now actively
  drops all live connections and responses no longer request connection reuse.
- Stopping now disconnects in-flight connections before closing the port, so no response can
  "arrive after stopping".

**Optimized**
- Self-tests expanded to 382 checks, including right-click positioning and the guarantee
  that stopped services return no data.

## v1.0.17 — 2026-11-17

**Added**
- **Mock conditional rules**: one route can return different results based on request
  header / query param / body / method — return VIP data with a `token`, 401 without it,
  covering both happy and error paths. Rules support equals / contains / exists / not
  exists, with their own status code, delay and response body.
- **Mock dynamic data**: write placeholders like `{{@id}}` `{{@uuid}}` `{{@name}}`
  `{{@cname}}` `{{@email}}` `{{@now}}` `{{@int(1,99)}}` `{{@pick(a,b)}}` in the response body;
  each request recomputes them. Editing a route offers "Preview random data".
- **Mock request log**: a new "Request Log" page shows each request's method, path, status,
  latency and matched route / rule in real time, with 2xx / 4xx / average-latency counters
  and a one-click clear.
- Route lists show a hit count per route.

**Improved**
- The start button now follows the real state: "Start Service" when stopped, "Stop Service"
  when running (previously hard-coded).
- The API doc table was rebuilt: a dedicated header bar, row dividers, a first column
  measured and clamped to 96–210, and word wrap for long content.
- Code examples: language labels align strictly with the code body; long lines are wrapped
  and sized by their real line count, with no half-cut lines or stray scrollbars.
- The Settings menu's "Settings…" is now a gear icon; "Switch Light / Dark" was removed
  (the theme is still under Settings → Appearance).
- The About page drops file names and class names for a user-facing capability list and a
  "what one request goes through" walkthrough.

**Fixed**
- Stopping could leave the port occupied (another instance or a leftover process): it now
  waits for the port to be truly released and reports honestly; if another Ocelot owns the
  port, it says so and switches automatically.
- Dynamic data containing Chinese characters broke the HTTP response when written into a
  header; it is now safely encoded.

**Optimized**
- Self-tests expanded to **374 checks**: menu entries, button states, placeholder randomness,
  rule matching, log latency, table column widths, code-block alignment and long-code scroll.

## v1.0.16 — 2026-11-17

**Added**
- **A real local Mock service**: an actual HTTP server on `127.0.0.1` whose routes, methods,
  status codes, delays and bodies you define. Supports prefix wildcards `/api/users/*`,
  echo mode (returns the request verbatim), CORS, and can be reached directly from a browser
  or script; "Try" builds a request in one click, and it can start with the app. If the port
  is taken it switches automatically.
- **Two Mock hub pages**: local Mock manages routes (create / edit / copy address / delete),
  while the public API catalog keeps 28 free endpoints (click a row to fill a request).
- **Shortcut settings**: all 16 actions are editable — click a keycap to record, clear in one
  click, restore defaults. Two actions competing for the same key make the older one step
  aside, and changes take effect immediately.
- **Fuller API docs**: overview (method / URL / status / latency / size / content type), auth
  notes, cookie table, response header table and status-code semantics; copying or saving
  produces a deliverable document.

**Improved**
- API doc window reflowed: a request card on top with status / latency / size metrics, a left
  outline that tracks scrolling, and cached code examples per language.
- Ten languages in code examples share syntax highlighting (CLI flags, URLs, strings and
  numbers each colored); code aligns strictly with the language label.
- Command palette entries are no longer clipped: a scrollable list with eased wheel input,
  keyboard selection auto-follow and cards clipped by whole rows.
- Mock public API list rebuilt as sub-widgets + layout: method / URL / description align
  strictly; search debounced at 120ms.
- The title bar's settings button is a real gear icon (previously a sun-like set of rays).
- Settings dialog widened to 940×700; About drops the shortcut table for four "Why Ocelot"
  advantages and a six-layer architecture note.

**Fixed**
- A query param already present in the URL was appended again in code generation and docs
  (`?a=1&a=1`); it now compares first, then appends.
- The Mock panel's status pill and button enable state were out of sync after start / stop.

**Optimized**
- Self-tests expanded to **351 checks**: a real local service for route / echo / 404,
  shortcut recording and conflict hand-off, command palette scroll, code-block alignment and
  highlighting, and the new doc sections.

## v1.0.15 — 2026-11-17

**Added**
- **API doc window**: "View API Doc" under "More →" at the top right of the response. Method /
  URL / param table / headers / body / response example on one page, a left outline to jump
  between sections, ten languages of code examples at the bottom with one-click switching,
  a toggle to mask tokens, and copy / save as `.md`.
- **Mock data panel**: 28 built-in free public APIs (httpbin / JSONPlaceholder / DummyJSON /
  ReqRes / random images…), searchable and grouped; a click fills a ready-made request.
- **Response timeline**: a new "Timeline" tab plots this URL's latency history as bars colored
  by status code, with hit count / success rate / average / P95 / slowest on top and hover
  details for each run.
- Command palette ⌘K gains Mock Data, API Doc, Copy Current Request and Close Tab.

**Improved**
- Param table headers align with data rows (checkbox placeholders are real controls, the
  "Type" header is centered).
- URL history completion is a custom-drawn overlay: rounded, clock icon, monospace URL,
  up/down to select.
- Settings reflowed: cloud sync address / token / button on one row, no longer squeezed;
  dialog widened to 900×672.
- About page rebuilt: a large title, version pill, three-column runtime info, two-column
  shortcuts and a copy-version action.

**Fixed**
- Right-click on selectable text in response headers and doc bodies still used the system
  menu (English, translucent); it is now taken over consistently.

**Optimized**
- Self-tests expanded to 312 checks.

## v1.0.14 — 2026-11-17

**Added**
- **One-click API docs**: "More →" in the response copies a full Markdown document (method,
  URL, query, headers, body, status code, latency, size, response example). A tab right-click
  offers "Copy API Doc (Markdown)" so each request can be exported without hand-writing docs.
- **Secret masking**: the same menu can "Copy response body (masked)" or export a doc with
  "secrets masked". `token` / `cookie` / `password` / `authorization` / JWT / `Bearer xxx`
  become `••••••` (long values keep the last four characters so you can confirm it is the
  same key). Safe to paste into chat, tickets or screenshots.

**Improved**
- Code generation (cURL / Python / JavaScript / HTTPie) now merges rows from the Cookies tab
  into the `Cookie` header; disabled rows are not exported, so generated code matches what
  "Send" actually does.

**Fixed**
- Runtime log prefixes still saying `Reqly` (save response / save config failures) are
  unified to `Ocelot`.

**Optimized**
- Self-tests expanded to 312 checks: every doc section, masking rules, long-value truncation,
  JSON structure comparison and cookies in generated code.

## v1.0.13 — 2026-11-17

**Renamed**
- Reqly → **Ocelot**. Title bar, About page, menus, User-Agent and data directory all changed;
  on first launch the old `~/Library/Application Support/Reqly` data is migrated so nothing
  is lost.

**Added**
- Requests gain a **Cookies** tab: table rows are merged into the `Cookie` header (coexisting
  with a hand-written one), and `Set-Cookie` in a response can be imported in one click so
  login sessions carry over.
- **Cloud sync (Turso)**: set a database URL and Auth Token in Settings; "Test Connection"
  runs a single `SELECT 1`; upload / restore from cloud (restoring backs up `state.json.bak`
  first), with an option to auto-upload on exit. Uses only Turso's HTTP pipeline, no new
  dependencies.
- URL bar completes from history: focusing it lists previously used URLs containing the
  current text, so a few keystrokes are enough.
- Command palette ⌘K can switch environments and jump straight to Appearance / Cloud Sync.

**Improved**
- The accent color now drives more than buttons: selection backgrounds, focus outlines,
  hover badges, tab titles and underlines, sidebar selection markers and Settings nav all
  follow it, with body text tinted slightly toward the accent — one coherent color temperature.
- Param type pills drop their outline; Auto gets its own warm-sand color at a larger size,
  clearly distinct from Null's gray and JSON's orange.

**Fixed**
- A black ring around checked checkboxes (the default pen also drew one) — the checked state
  is now a solid block only.
- The first accent swatch's selection ring was clipped by the card edge.
- Tab right-click "Copy as cURL" did nothing (`to_curl` was not imported, `NameError`).
- Qt's implicit cookie jar silently rewrote hand-written `Cookie` headers; it is now neither
  read nor written, and cookies are managed explicitly by the Cookies tab.

**Optimized**
- Removed two unreachable blocks in Settings, duplicate and unused imports in the main window;
  request counts and cookie hints merge into one refresh.

## v1.0.12 — 2026-11-17

**Added**
- Settings · Appearance gains an **Accent Color**: seven swatches (auto / ocean blue / pine /
  moss / terracotta / crimson / violet); buttons, switches, checkboxes and the send key follow
  immediately. "Auto" keeps the original black-and-white inversion.

**Improved**
- The param type menu's Auto now has its own color (warm sand), clearly distinct from Null's
  gray and JSON's orange.

**Fixed**
- Switching color scheme / accent rebuilt a destroyed hover detail card and crashed while
  painting — destroyed widgets are now skipped.
- Switching schemes only refreshes visible widgets; hidden ones repaint naturally when shown,
  making large windows much smoother.

**Self-tests**
- 228 checks: accent switching and persistence, swatch count and clicks, Auto vs Null contrast.

## v1.0.11 — 2026-11-16

**Fixed**
- After launch, tabs did not respond and content would not switch: the tab strip now emits
  its change signal unconditionally; the main window also self-heals a wrong editor request
  or a ghost tab, re-checking when the window regains focus.
- An error midway through `RequestEditor.load` left the loading flag stuck at True, so every
  later edit stopped writing back ("clicking does nothing") — a `finally` block now clears it.

**Optimized**
- Sidebar collapse / expand stutter: the splitter was clamped to the sidebar's minimum size
  (≈158), so the first two thirds of the animation did nothing and the last frame vanished.
  During animation the minimum size and size policy are relaxed, then restored — the slide is
  now truly frame-by-frame.
- Switching tabs and receiving responses no longer writes to disk synchronously (batched to
  one write per 700ms); the history list refreshes incrementally instead of rebuilding
  hundreds of widgets.
- Re-clicking the current tab no longer re-formats the whole response, making large JSON
  switches noticeably smoother.
- Large responses render on demand: the JSON tree and "Raw" tab are built only when opened —
  a 190KB response drops from 1 second to 60ms. Above 600KB only the first 600KB is previewed
  with a hint to "Save As" for the full text, and syntax highlighting is skipped above 180KB.

**Added**
- Extract results can be "Saved as Variable": one click writes into the current environment
  for later `{{name}}` references, so a login token no longer needs copying by hand.
- Middle-click a tab to close it; double-click the divider between request and response to
  restore a 50/50 split.
- Double-clicking an italic preview tab pins it (VSCode behavior); previously double-clicking
  a tab did nothing.

**Self-tests**
- 219 checks: tab self-healing, middle-click close, divider reset, save-as-variable,
  frame-by-frame sidebar animation and incremental history refresh.

## v1.0.10 — 2026-11-16

**Added**
- **Collection runner**: right-click a folder → "Run Collection" or ⌘⇧R to run every request
  in tree order, showing status / latency / size per request and a success / failure / total
  time summary; stop at any time, copy the whole result table (TSV pastes straight into a
  spreadsheet), and click a row to open that request.
- Param type gains File: pick a local file in a form row and upload it as real multipart, with
  code generation reflecting the file param.
- cURL import dialog: paste to parse with live preview, supporting `-X / -H / -d / -F / -u /
  -G / --data-urlencode` and merged short flags like `-sSL`.
- Request tab right-click: Close Others / Close All / Duplicate Tab / Copy as cURL.

**Improved**
- Code snippets expanded to 10 languages (adding Go / Java / PHP / C# / Kotlin /
  PowerShell), all syntax highlighted.
- Format / encoding / type dropdowns are custom-drawn, no more garbled native checkmarks;
  the method palette was reordered to match the reference image and "Custom" removed.

**Fixed**
- Pretty-printing squeezed HTML into one line, or into a staircase running right: it is now a
  token stream — inline tags stay on one line, `script` / `style` / `pre` content is preserved,
  CDATA is not split, and unclosed tags are tolerated.
- Detail card icons never lined up — root cause was `QPixmap.width()` returning device pixels
  (2× on Retina); the dpr is now factored in to center them correctly.
- Clicking a request tab's content did not switch pages and edits were lost — the tab strip
  now genuinely emits a change event.

**Self-tests**
- 196 checks: runner order and summary, file type, pretty-print structure, icon centering and
  tab switching.

## v1.0.9 — 2026-11-16

**Improved**
- Param types use capitalized English names (Auto / String / Number / Boolean / Null / JSON),
  each with a semantic color; String is green.
- HTTP method palette matches the reference: GET green / POST orange / PUT·HEAD·OPTIONS blue /
  DELETE red / PATCH pink / TRACE purple, with "Custom" removed.

**Added**
- Code snippets add Go / Java / PHP / C# / Kotlin / PowerShell, with multilingual highlighting.

**Fixed**
- Type / format / encoding dropdowns switched to custom-drawn menus, eliminating garbled
  macOS native checkmark glyphs.
- The "Expand All / Collapse All" buttons that appeared when selecting text are now fully
  hidden, leaving only format and encoding in the toolbar.
- Detail card icons misaligned and footer text overlapping the Body row: the title and metric
  row icons now share one size and x position, and all blocks accumulate sequentially.
- Clicking a request tab did not switch content and lost edits — TabStrip now emits
  currentChanged correctly.

**Self-tests**
- 186 checks: type colors, custom menus, detail-card alignment, code languages and tab
  switching.

## v1.0.8 — 2026-11-16

**Improved**
- Response Time / Size hover cards use a fixed anchor instead of following the mouse; the
  custom-drawn layout was rebuilt with segmented icons.
- Format / encoding buttons now use the same custom control, shown only on the "Pretty" tab.

**Added**
- The size card adds a Header / Body allocation bar; the time card adds an "estimated" note
  so each segment is not misread.

**Fixed**
- After changing the URL to time-tx, the previous image response was still shown — any
  request edit now invalidates the old response.
- After opening several request tabs their content merged together — responses, format,
  encoding and the current response sub-tab are now stored per tab.
- After dragging the sidebar width the URL bar disappeared and the description floated up —
  an interrupted animation now restores its paint state completely.

**Self-tests**
- 167 checks: fixed cards, button isolation, per-tab responses and animation-interrupt recovery.

## v1.0.7 — 2026-11-16

**Fixed**
- Sidebar collapse froze in two stages — the animation wrote to disk on every frame via
  `splitterMoved`. The signal is now disconnected during animation with a single write at
  the end.
- A new empty tab and an opened old request ended up with identical content — each tab is now
  an independent snapshot and collection tree changes only sync titles, not edits.
- The spinner never started on send, making the app look stuck — it now really spins with a
  skeleton shimmer.

**Added**
- Single-click a sidebar item enters VSCode-style preview (italic title, reused preview tab);
  double-click pins it.
- Param types use English names (auto / string / number / boolean / null / JSON).
- Settings → General adds a language switch (简体中文 / English), translated naturally and
  applied immediately across the whole UI.
- Node speed tests now cover every node (previously only 8), with controlled concurrency,
  a progress indicator, and a note that speed does not imply availability or overall latency.
- Response gains a format switch (Auto/JSON/XML/HTML/Text) and 11 encodings (UTF-8/GBK/Base64…).
- Hover detail cards over response time / size: segmented bar chart (DNS/TCP/SSL/TTFB/
  download) plus size breakdown.

**Self-tests**
- 155 checks: tab isolation, preview open, language switch, format / encoding, timing detail
  and spinner state.

## v1.0.6 — 2026-11-16

**Fixed**
- Only 22 nodes were listed — now the full 221 IPv4 / 130 IPv6 nodes are fetched, refreshable
  at any time.
- The gray bar in the method menu / command palette kept following the mouse after leaving —
  hover is now strictly bounds-checked.
- Sidebar collapse / expand stutter — the content repaint was frozen frame-by-frame during
  animation and the collection tree was no longer fully rebuilt at the end.
- Image / audio responses showed a row of question marks in Pretty / Raw — now a hint plus
  hex view, defaulting to Preview.
- After a title changed the pill width did not follow, swallowing the "+" into the pill; the
  collection tree showed left/right arrow cursors.
- A toast's underlying object was destroyed but still called, causing a crash.

**Added**
- Online nodes really work: the selected node forwards requests via a node server, with exit
  IP, region and latency annotated in the response metrics.
- The "Local" button moves to the right of Send; the node panel gains a refresh button and
  IPv4 / IPv6 counts.
- Preview gains "Save": images / audio / video / PDF / binary can all be saved locally.
- Settings gains an "About Ocelot" page and a "View What's New" entry; the changelog panel
  is color-coded by category.
- Param table gains a "Description (optional)" column used only as a note, never sent.

**Self-tests**
- 134 checks: indent gray block, menu reuse, zero-latency hover, toast sizing, three preview
  types, node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding
  and media container detection.

## v1.0.5 — 2026-11-16

**Fixed**
- Gray blocks to the left of selected collection-tree rows (the base class painted the indent
  area with the selection color) — the indent area is no longer painted and the selection
  background is transparent.
- Opening the method menu a second time crashed (`RuntimeError: MethodMenu has been deleted`)
  — the menu is now reused as a persistent object.
- The command palette's gray hover bar lagged behind the mouse — tweening was removed for
  zero-latency following, and the keyboard row uses a thin border instead of stealing focus.
- System toasts were large and empty — replaced with a custom-drawn toast sized to its text.
- Right-clicking an input opened the English system menu — replaced with a custom Chinese menu
  (Undo / Redo / Cut / Copy / Paste / Delete / Select All) with icons.
- gzip / deflate / br compressed bodies showed as gibberish or blank — they are now decompressed
  by `Content-Encoding` (with gzip-header sniffing as fallback).
- GBK / GB18030 pages showed garbled Chinese — when no charset is declared, UTF-8 then
  GB18030 are tried in order.

**Appearance**
- Unified base color: sidebar and workspace both use `#19191C`, removing the "half dark, half
  lighter" look and leaving a single 1px divider.
- Settings gains six color schemes: Graphite (default `#19191C`) / Slate / Warm Gray / Pine /
  Ink / Light; click a thumbnail to switch.
- Settings was rebuilt: section cards, scrollable content and a clearer information hierarchy.
- Sidebar is draggable 200–420 px and remembers its width; the title bar gains a collapse
  button (⌘B still works).
- The selected tab pill drops its outline.

**Added**
- "Preview" upgraded: image wheel zoom / drag pan / double-click fit / checkerboard transparency;
  embedded audio and video playback; PDF and binary get an "Open" and hex view; image / audio /
  video responses auto-switch to Preview.
- Media containers are detected by magic bytes (wav / mp3 / ogg / flac / m4a / webm / mov)
  instead of all being saved as unplayable `.bin`.
- "Nodes": the URL bar can select IPv4 / IPv6 nodes, searchable by region and ISP with one-click
  speed tests (TCP + DNS round trip), defaulting to "Direct". socks5 / http proxy nodes can be
  added and requests genuinely route through them, with metrics annotated.
- Network settings gain a default User-Agent; data settings gain a history limit.

**Self-tests**
- 108 checks: indent blocks, menu reuse, zero-latency hover, toast sizing, three preview types,
  node parsing and probing, Chinese right-click menu, gzip decompression, GBK decoding and
  media format detection.

## v1.0.4 — 2026-11-16

**Look & feel**
- Dark theme rebalanced around `#19191C`: five levels of gray for window / panel / card /
  overlay / selection; a content surface between sidebar and workspace so the boundary is no
  longer blurred.
- Method menu is custom-drawn: each method has a color, the current item shows a checkmark,
  row heights align and there are no native-menu rough edges.
- Removed all colored dots (collection tree, environments, tab strip) in favor of vector icons
  and status badges.
- Hover toasts use a rounded capsule style (smaller text, looser line height, no border burrs).
- Command palette hover uses a soft gray layer with 120ms easing, selected row gets a thin
  border instead of a hard cut.
- The tab strip's "×" and "+" were reflowed with ≥10px spacing.

**Params (rebuilt)**
- Add, remove, move up / down and copy / delete any row at any time.
- A new "Type" column: Auto / String / Number / Boolean / null / JSON, applied with the correct
  type when sent.
- Smart paste: `token=abc&debug=true`, `{"q":"x"}`, multi-line `k: v` or Tab-separated and `#`
  comment lines are split into rows in one paste, with comments auto-disabled.
- URL ↔ param table two-way sync: a URL with `?a=1&b=2` is split into the table and the URL
  keeps only the base; clearing params no longer leaves ghost params that break the request.

**Added**
- "Compare": auto line-by-line diff of this URL's response against the previous one, marking
  status code and latency changes, with a manual "Set as baseline".
- "Extract": use a JSON path like `a.b[0].c` or `*` to pull a field, with a hint listing valid
  top-level fields on error and one-click copy.

**Settings**
- Consolidated into a single page of six sections (General / Appearance / Network /
  Environments / Data / What's New) instead of nested dialogs.
- Code font size in three steps (Small / Standard / Large), applied to all open code areas
  immediately.
- The changelog panel was rebuilt: blocks per version, colored by category, word-wrapped,
  with a scroll that no longer stutters or overlaps.

**Self-tests**
- 80 assertions: param type inference, URL split, no ghost params, three paste formats, six
  Settings pages, diff stats and JSON path extraction.

## v1.0.3 — 2026-11-16

- Fixed a crash when the mouse moved over the collection tree (`RuntimeError: wrapped C/C++
  object of type QVariantAnimation has been deleted`) — the hover animation is now a
  persistent object instead of being destroyed at animation end.
- Added a "repeated hover" regression: sweep the collection tree three times, wait for each
  animation to finish and destroy before triggering again — 56 assertions.
- Sidebar-collapsed interaction tests now expand the sidebar first so no checks are skipped.

## v1.0.2 — 2026-11-16

- Fixed a crash when hovering the tab strip (`TypeError`: `QRectF.contains` only accepts
  `QPointF`, but got `QPoint`) that also killed the app when launched from the IDE.
- Startup self-check: on an old interpreter or missing PyQt6, print the interpreter path and
  a fix command instead of dumping a traceback.
- When launched from the run panel, bring the window to the front (`raise` + `activateWindow`).
- Added mouse-interaction regression: tab hover / click-to-switch / double-click blank to
  create, sidebar and segmented control sweeps — 53 assertions.
- Screenshot scripts now use a temporary state file instead of overwriting the real session
  (history, theme, open tabs).

## v1.0.1 — 2026-11-16

- Fixed: after switching from dark to light theme, JSON property names became nearly white
  and invisible on the light background (re-colored on theme switch).
- Fixed: the screenshot script overwrote real session data (now reads / writes a temp file).

## v1.0.0 — 2026-11-16

The first version: a pure-black, minimal API debugging tool with native macOS polish.

**Interface & motion**
- Borderless rounded window + traffic-light buttons (icons on hover), edge drag-resize,
  double-click title bar to zoom.
- Dark / light themes, pure-black layers, inverted solid primary buttons, no gradients or
  colored glows.
- All icons are 24×24 custom-drawn vector strokes, theme-colored and crisp on Retina.
- Animation: window fade-in, page cross-fade, response fade-in, segmented tab sliding underline,
  sliding selection pill, counting latency numbers, toast slide-up, sidebar collapse and
  loading skeleton shimmer.

**Request building**
- Method picker, URL input, query params and headers (enable switch / auto-append empty row /
  header autocomplete / bulk edit).
- Body: none / JSON / text / form (multipart with `@file` upload) / x-www-form-urlencoded /
  binary.
- Live JSON validation and format / minify.
- Auth: Bearer / Basic / API Key (Header or Query injection).
- Environment variables with `{{$timestamp}}` / `{{$uuid}}` / `{{$randomInt}}` dynamic variables.

**Send & response**
- Async cancellable send, timeout / follow-redirects / SSL-verify toggles, proxy (auto /
  system / direct), cookie persistence and parsing.
- Response metrics (status, latency, size, type, final URL).
- Six response views: Pretty / Tree / Raw / Headers / Cookies / Preview; in-response find and
  highlight.
- Copy response body, save to file, error-state hints.

**Organization & reuse**
- Collection tree (unlimited depth, drag sort, right-click menu, search filter, open-state dots).
- History (click to restore, hover to delete, clear).
- Multi-tab (drag reorder, sliding indicator, session restore).
- Environment variable management with active switching.
- Code generation: cURL / Python / JavaScript / HTTPie.
- cURL import, collection import / export (Postman v2.1 compatible).
- Command palette ⌘K, global shortcuts, Settings and What's New dialogs.
