# What's Changed

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
