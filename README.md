# 🧸 Toybox

Three lightweight Windows desktop toys, plus a tray launcher to run them.
**Pure Python 3.12 standard library — `tkinter` + `ctypes` + `winreg`. Zero installs.**

| Toy | What it is |
|-----|------------|
| 🖥️ **System Monitor HUD** (`hud.pyw`) | A small, draggable, translucent always-on-top overlay showing live **CPU %**, **RAM %**, and a clock, each with a scrolling sparkline. |
| 📋 **Clipboard History** (`clipboard.pyw`) | Runs quietly and remembers your last copied text snippets. Press **Ctrl+Shift+V** for a picker — pick one to re-copy it. In-memory only (never written to disk). |
| 🎵 **Music-Reactive Pet** (`pet.pyw`) | A little click-through blob that lives near the bottom of your screen and **dances to whatever audio is playing** — it bobs with loudness and hops on the beat. |
| 🚀 **Tray Launcher** (`toybox.pyw`) | A system-tray icon to show/hide each toy and toggle "start at login". |

Everything is designed to be **featherweight**: the HUD updates once a second, the pet drops to a slow idle frame-rate when there's no sound, and the clipboard watcher is just a couple of cheap polls. No network, no telemetry, no background services.

## Quick start

You already have Python 3.12 (the `py` launcher). From this folder:

```sh
# Run a single toy (pythonw = no console window):
pythonw hud.pyw
pythonw clipboard.pyw
pythonw pet.pyw

# Or run the launcher and control everything from the tray:
pythonw toybox.pyw
```

Tip: because `.pyw` files are associated with `pythonw.exe`, you can also just **double-click `toybox.pyw`** in Explorer. Right-click the tray icon for the menu.

To debug a toy and see errors, run it with the console build instead: `py hud.pyw`.

## Using each toy

**System Monitor HUD** — drag it anywhere (it remembers where). Right-click for opacity presets (100% / 85% / 60%) and Close. Position and opacity persist in `config.json`.

**Monitor partitions (SPLIT row on the HUD)** — treat one monitor as two. Each attached monitor gets a glyph: click it to cycle **off → vertical (left/right) → horizontal (top/bottom)**. While a split is on, **just drag any window** — a translucent overlay shows the two zones; drop into one and the window snaps to fill it (DWM-border-exact). **Hold Shift while dragging to opt out** and place the window freely. **Right-click the glyph** to drag the divider anywhere (release to set, Esc cancels); windows you've snapped this session re-fit to the new ratio. Layout + ratio persist per monitor in `config.json`.

**Clipboard History** — copy text as usual; it's captured automatically. Press **Ctrl+Shift+V** to open the picker: type to filter, ↑/↓ to move, **Enter** or double-click to re-copy the highlighted entry, **Esc** to dismiss. Holds the most recent 20 entries (configurable), in memory only — nothing is saved to disk, so copied passwords don't linger.

**Music-Reactive Pet** — just play music or any audio. The pet grows and bounces with the loudness and reacts on beats (hops, wiggles, blinks); when it's quiet it idles and breathes. It's fully click-through, so it never gets in your way.

**Tray Launcher** — right-click the tray icon:
- **Show HUD / Clipboard / Pet** — toggles each toy on/off (checkmark = running).
- **Start … at login** — toggles whether that toy auto-launches when you log in (writes an `HKEY_CURRENT_USER\…\Run` entry).
- **Quit Toybox** — closes the launcher and any toys it started.

## Run at startup

Either use the launcher's "Start … at login" menu items, or enable a toy directly — each writes a per-user (`HKCU`) Run entry pointing at `pythonw.exe "<toy>.pyw"`. No admin rights needed. Disabling removes the entry.

## Configuration

`config.json` is created in this folder on first run and is safe to hand-edit (missing/invalid keys fall back to defaults):

```jsonc
{
  "hud":       { "x": 40, "y": 40, "alpha": 0.85, "locked": false },
  "clipboard": { "max_items": 20, "hotkey": ["ctrl", "shift", "V"] },
  "pet":       { "x": null, "y": null,            // null = auto-place bottom-center
                 "sensitivity": 1.6,              // higher = harder to trigger a "beat"
                 "floor": 0.02,                   // ignore audio quieter than this
                 "smoothing": 0.4,                // envelope responsiveness (0–1)
                 "idle_fps": 8, "active_fps": 30 },
  "startup":   { "hud": false, "clipboard": false, "pet": false }
}
```

## How it works (the lightweight bits)

- **Audio reactivity** taps the Windows audio peak meter (`IAudioMeterInformation::GetPeakValue` via WASAPI) — the same level the volume mixer shows. It's just a float read, so there's no audio capture or FFT. A small onset detector turns that envelope into "beats".
- **Translucent / click-through windows** use tkinter plus a few native extended window styles (`WS_EX_LAYERED` / `WS_EX_TRANSPARENT`) applied through `ctypes`.
- **The hotkey** is detected by polling `GetAsyncKeyState` (high bit, edge-detected) — no global hook.
- **The tray icon** is a real `Shell_NotifyIcon` with its own Win32 message loop, all in `ctypes`.
- The native glue lives in one place, the `winkit/` package; the rest is plain tkinter and small pure-logic modules.

## Project layout

```
hud.pyw  clipboard.pyw  pet.pyw  toybox.pyw   # the toys + launcher
winkit/        # native helpers: window, monitors, metrics, input, audio, startup, tray
zonekit/       # monitor partitions: zone math, drag tracker, snap/divider overlays
clip_history.py  beat_detector.py  sysmetrics.py  config.py   # pure logic
tests/         # unit tests + real-system integration + smoke launches
docs/superpowers/   # design spec, plan, and the native-code research notes
```

## Tests

```sh
py -m unittest discover -s tests -t .
```

Runs the pure-logic unit tests, real-system integration checks (metrics, clipboard, audio meter, registry round-trip, tray create/destroy), and a smoke launch of each toy (a window briefly appears and auto-closes).

## Credits

- `assets/meow.wav` — a single meow extracted and trimmed from the **CatMeows** dataset by L. Cavallini, S. Ntalampiras, et al. (Zenodo record [4008297](https://zenodo.org/records/4008297)), licensed **[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)**.
