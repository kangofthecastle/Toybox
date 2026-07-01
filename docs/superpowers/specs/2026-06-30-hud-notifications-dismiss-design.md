# HUD Notifications — Dismiss (Mark-as-Read) Design

**Status:** Approved (brainstorming complete) — ready for implementation plan.

**Builds on:** `docs/superpowers/specs/2026-06-30-hud-notifications-tile-design.md`
(the notifications tile). This adds the ability to *act* on a notification —
mark one thread, or all threads, as read on GitHub — directly from the HUD.

**Branch:** continues on `hud-notifications-tile` (dismiss extends the tile's
model/parser/render/worker; the combined branch finishes as one feature).

---

## 1. Goal

From the notifications tile, let the user:
- **Dismiss one** unread notification (a per-item `✕`), and
- **Mark all** unread notifications read (a header `✓`),

by calling GitHub's notifications API. The tile updates instantly
(optimistically) and reconciles with GitHub on the next fetch. Clicking an
item still opens its thread in the browser — dismiss is an *additional*
action, not a replacement.

**Non-goals (YAGNI):** no undo UI, no unsubscribe, no per-item read↔unread
toggle, no "mark read across a single repo" scoping (the tile is already
all-repos), no marking read up to a timestamp. Just dismiss-one and
dismiss-all.

---

## 2. UX

```
Notifications  🔔 8              ✓     ← header: ✓ at the right edge = mark ALL read
⇄ app #34 · review     2h ✕      ← per-item ✕ (right edge of line 1) = mark THIS thread read
   Fix the flaky timeout test     ← click anywhere else on either line = open thread (unchanged)
```

- **Per-item `✕`** — the rightmost ~14 px of an item's **line 1**. Marks that
  one thread read. **No confirmation** (single item; reversible — you can mark
  it unread again on github.com).
- **Header `✓`** — the rightmost ~14 px of the tile **header line**. Marks
  **all** unread threads read. **Confirms first** (a yes/no dialog): GitHub has
  no bulk "mark unread," so mark-all is effectively irreversible; an accidental
  click must not clear the whole inbox.
- **Optimistic feedback** — the targeted item(s) disappear and the `🔔` count
  drops the instant the user clicks, before the network call returns. The
  worker's subsequent refetch is the source of truth; on failure the item(s)
  reappear with a transient `! dismiss failed` line.
- An item whose `thread_url` is empty (rare/malformed) renders **without** a
  `✕` and is not individually dismissable (mark-all still covers it).

---

## 3. Data model — `feedkit/model.py`, `feedkit/parse.py`

- `NotifItem` gains a trailing field **`thread_url`** = the notification's
  top-level `url` (`https://api.github.com/notifications/threads/{id}`). New
  field order:
  `(glyph, repo, number, reason_label, urgency, updated_at, title, url, thread_url)`.
- The parser sets `thread_url = n.get("url") or ""` (null-safe; empty when
  missing).
- **Security invariant (critical):** `thread_url` is an **api.github.com** URL
  used **only** by the authenticated API client for the mutation. It is
  **never** passed to `webbrowser.open` / the `is_web_url` open-path. The only
  URL that ever reaches the browser is the existing `url` (`https://github.com/…`).
  The two URLs remain strictly separate; `_register_hit`/`_open_at` keep their
  `is_web_url` gate unchanged and only ever receive `url`.

---

## 4. Network — write path — `feedkit/fetch.py`

Add a sibling to `fetch()` (the GET path is untouched):

```
send(url, method, headers) -> SendResult
```

- Issues a `urllib.request.Request(url, method=method, headers=headers)` with an
  empty body, over the **default verifying TLS context** (TLS is never
  weakened; no custom SSL context). `method` is `"PATCH"` (one thread) or
  `"PUT"` (all).
- `SendResult` is a small namedtuple `(status, code, error)`:
  - `status="ok"` for any 2xx (GitHub returns 205 for a thread PATCH, 202 for
    `PUT /notifications`),
  - `status="error"` with an `error` word for `HTTPError` / `URLError` /
    `TimeoutError` (same error taxonomy/order as `fetch`).
- No response body is read beyond the status line (these endpoints return
  empty/!json bodies). Reuses the existing default User-Agent and auth headers
  via `model.github_headers(token)`.

**Endpoints (canonical):**
- Mark one read: `PATCH {thread_url}` (i.e. `…/notifications/threads/{id}`).
- Mark all read: `PUT https://api.github.com/notifications` (no body).

---

## 5. Worker — action queue — `feedkit/manager.py`

The manager already runs a single daemon worker that is the **only** code that
touches the network (snapshot-under-lock, fetch-unlocked, results via
`queue.Queue`). Mutations reuse that thread via a new **action queue** so the
UI thread never blocks on network I/O.

- New `self._actions` (a `queue.Queue`). Public, thread-safe enqueue methods
  called from the HUD (main thread):
  - `mark_read(idx, thread_url)` → enqueues `("one", idx, thread_url)`,
  - `mark_all_read(idx)` → enqueues `("all", idx, None)`.
- At the **top of `_run_once`** (before the due-feeds loop), the worker drains
  `self._actions` and, for each, calls `_do_action(...)` which:
  1. reads `token` under the lock,
  2. runs `fetch.send(target, method, github_headers(token))` **unlocked**
     (`target`/`method` = the thread_url+PATCH, or the global url+PUT),
  3. **on success:** invalidates that feed's cache so it refetches immediately
     and reconciles with GitHub — under the lock, drop `self._cache[idx]`'s
     `etag`/`lm` (force a 200, not a 304) and set `self._last[idx]` stale so the
     feed is **due** this same tick. The normal fetch path then returns the
     real post-mutation list + badge.
  4. **on failure:** enqueue onto the result `queue` a `FeedResult` that
     **restores** the cached pre-mutation `items`/`badge` with
     `state="stale"`, `error="dismiss failed"`, so the optimistic removal is
     rolled back on the next drain.
- `set_feeds` also clears `self._actions` (drains/replaces) so actions never
  target a stale index after a Settings save.
- Concurrency invariant preserved: the lock is **never** held across
  `fetch.send`; actions are drained and run exactly like a fetch — snapshot
  under lock, network unlocked, write-back under lock, results via the queue.

---

## 6. HUD — hit-testing, optimism, confirm — `hud.pyw`

**6a. x-aware hit regions.** Today a feed line registers a whole-row horizontal
*band* → one URL (`_register_hit(y, url)`), and `_open_at(x, y)` ignores `x`.
For notifications:
- The item's **line 1** reserves its rightmost ~14 px as a **dismiss zone**;
  the rest of line 1 (and all of line 2) remains the **open-thread zone**.
- The **header line** reserves its rightmost ~14 px as a **mark-all zone**; the
  rest opens `github.com/notifications`.
- This needs an action-aware hit record: extend the hit list so a region can
  carry either an *open URL* (existing behavior, `is_web_url`-gated) or a
  *dismiss action* (`("one", idx, thread_url)` / `("all", idx)`), keyed by
  `x`-range as well as `y`. Non-notifications feeds keep the existing
  whole-band, URL-only behavior byte-for-byte.
- **Isolation (resolves the §3/§7 "gate unchanged" requirement):** dismiss /
  mark-all hit records carry an **action**, not a URL, and on click are
  dispatched straight to `manager.mark_read` / `mark_all_read` — they NEVER
  pass through `_open_at` / `webbrowser.open`. The open-thread hit records and
  their `is_web_url` gate are untouched, so the browser open-path can still
  only ever receive an `https://github.com/…` URL. A click resolves to *at
  most one* zone (dismiss/mark-all takes precedence in its narrow right-edge
  x-range; everything else opens the thread).
- The `✕`/`✓` glyphs are drawn as their own canvas items at the right edge
  (dim, like the age), so the dismiss zone is visually obvious.

**6b. Optimistic update (main thread).** On a `✕` click, the HUD rebuilds
`feed_state[idx]` as a new `FeedResult` with that item removed and
`badge = max(0, badge-1)`, redraws, then calls `manager.mark_read(idx,
thread_url)`. On a confirmed `✓`, it sets `feed_state[idx]` to an empty
`ok`/badge-0 result, redraws, then calls `manager.mark_all_read(idx)`. The
worker's next queued result (reconciled on success, restored on failure)
overwrites this optimistic state on the next 250 ms drain.

**6c. Confirm dialog.** Mark-all pops `tkinter.messagebox.askyesno("Mark all
notifications read?", …)` parented to the HUD root. Yes → optimistic clear +
enqueue; No/closed → no-op, no redraw. (Per-item `✕` never confirms.)

**6d. Error surfacing.** A failed mutation arrives as the restored
`state="stale", error="dismiss failed"` result; the existing tile error-line
path renders `! dismiss failed` above the (restored) items until the next
successful fetch clears it.

---

## 7. Security & safety

- **Outward-facing action.** Both actions mutate GitHub server state. Per-item
  is low-stakes and reversible (re-mark unread on github.com), so it fires
  immediately. Mark-all is gated behind an explicit yes/no confirm because it
  is effectively irreversible in bulk.
- **URL isolation.** The browser open-path only ever receives the
  `https://github.com/…` `url`; the `api.github.com` `thread_url` and the
  `PUT /notifications` endpoint never reach `webbrowser.open`. `is_web_url`
  gating at `_register_hit`/`_open_at` is unchanged.
- **TLS** is never weakened; `send` uses the default verifying context, like
  `fetch`.
- **Token** is the same classic PAT (`notifications` scope already grants
  write); it stays in gitignored `config.json`/env, masked, never logged.

---

## 8. Testing plan

- **model/parse:** `NotifItem.thread_url` carried from `n["url"]`; null/missing
  → `""`; field order asserted; backward-compat of existing positional
  constructions (trailing field).
- **fetch:** `send()` issues PATCH/PUT (verified via the test `HTTPServer`'s
  `do_PATCH`/`do_PUT`); 2xx → `ok`; HTTPError/URLError/TimeoutError → `error`
  with the right word and reduction order; TLS context never weakened.
- **manager:** `mark_read`/`mark_all_read` enqueue; `_run_once` drains the
  action queue and calls `send`; on success the feed's cache etag is dropped and
  it refetches (assert a 200 reconcile via injected `fetch_fn`); on failure a
  restoring `stale`/`dismiss failed` `FeedResult` is queued; lock never held
  across `send`; `set_feeds` clears pending actions.
- **hud (smoke, Windows-only real Tk):** clicking the line-1 dismiss zone
  removes the item, decrements the badge, and enqueues `("one", idx,
  thread_url)`; clicking the open zone still registers the web URL; the header
  `✓` confirm (patched to return True) enqueues `("all", idx)` and clears the
  tile; an item with empty `thread_url` shows no `✕`; a restored failure result
  re-shows the item with `! dismiss failed`.
- **full suite** green, including the subprocess HUD smoke (exit 0, empty
  stderr).

---

## 9. File-change summary

| File | Change |
|---|---|
| `feedkit/model.py` | `NotifItem` gains trailing `thread_url` |
| `feedkit/parse.py` | parser sets `thread_url = n.get("url") or ""` |
| `feedkit/fetch.py` | new `send(url, method, headers)` + `SendResult` |
| `feedkit/manager.py` | action queue, `mark_read`/`mark_all_read`, `_do_action`, drain + force-refetch/restore |
| `hud.pyw` | x-aware dismiss/mark-all hit regions, `✕`/`✓` glyphs, optimistic update, confirm dialog, error line |
| tests | model/parse/fetch/manager unit tests + hud smoke tests |
