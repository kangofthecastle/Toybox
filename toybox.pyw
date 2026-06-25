import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement (pythonw-at-login safety)

import subprocess
import appicon
import winkit.tray as tray

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "toybox.log")
ICON_PATH = os.path.join(HERE, "toybox.ico")

# toy key -> (window title, script filename)
TOYS = (
    ("hud", "HUD", "hud.pyw"),
    ("clipboard", "Clipboard", "clipboard.pyw"),
    ("pet", "Pet", "pet.pyw"),
)


def _pythonw():
    """The pythonw.exe next to the running interpreter (no console window), else
    fall back to the running interpreter itself."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def main():
    if not os.environ.get("TOYBOX_SMOKE") and not startup.acquire_single_instance("Toybox_launcher"):
        return  # another launcher is already running
    procs = {key: None for key, _title, _script in TOYS}
    script_for = {key: script for key, _title, script in TOYS}

    def is_running(key):
        # Detect ANY running instance (single-instance mutex), not just ones we
        # spawned, so the checkmarks are accurate and we never double-spawn.
        return startup.is_instance_running("Toybox_" + key)

    def start(key):
        if is_running(key):
            return
        try:
            proc = subprocess.Popen([_pythonw(), os.path.join(HERE, script_for[key])])
            procs[key] = proc
        except Exception:
            procs[key] = None

    def stop(key):
        proc = procs.get(key)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        procs[key] = None

    def make_toggle(key):
        def toggle():
            if is_running(key):
                stop(key)
            else:
                start(key)
        return toggle

    def make_toggle_startup(key):
        name = "Toybox_" + key
        script = os.path.join(HERE, script_for[key])

        def toggle_startup():
            try:
                enabled = startup.is_run_at_startup(name)
                startup.set_run_at_startup(name, script, not enabled)
            except Exception:
                pass
        return toggle_startup

    def quit_all():
        for key in list(procs):
            stop(key)
        the_tray.request_quit()

    def menu_provider():
        items = []
        for key, title, _script in TOYS:
            items.append({
                "label": "Show " + title,
                "checked": is_running(key),
                "callback": make_toggle(key),
            })
        items.append({"separator": True})
        for key, title, _script in TOYS:
            try:
                enabled = startup.is_run_at_startup("Toybox_" + key)
            except Exception:
                enabled = False
            items.append({
                "label": "Start " + title + " at login",
                "checked": enabled,
                "callback": make_toggle_startup(key),
            })
        items.append({"separator": True})
        items.append({"label": "Quit Toybox", "callback": quit_all})
        return items

    appicon.ensure_ico(ICON_PATH)  # generate the cute toolbox icon
    the_tray = tray.TrayIcon("Toybox", menu_provider, icon_path=ICON_PATH)
    the_tray.run()  # blocks; owns the Win32 message loop and TOYBOX_SMOKE auto-quit


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise
