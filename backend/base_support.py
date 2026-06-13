import traceback
from tkinter import messagebox, filedialog, simpledialog
import tkinter as tk
from PIL import Image, ImageTk
from datetime import datetime, timedelta, timezone
import ttkbootstrap as ttk
import logging
import shutil, glob
import atexit
import difflib
import itertools
import zipfile, subprocess, tempfile
try:
    import keyboard as kb
except Exception:
    kb = None
import json, requests, time, os, threading, re, webbrowser, random, pyautogui, psutil, \
    queue, sys, hashlib, asyncio, traceback

import platform

import queue
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional


import queue
import threading
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional
try:
    from pynput import mouse as _pynput_mouse
except Exception:
    _pynput_mouse = None


import queue
import threading
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional


class CalibrationManager:
    """Manages calibration overlays and temporary displays in a dedicated tkinter thread."""

    def __init__(self):
        self._disabled = False
        self._use_background_thread = platform.system() != "Darwin"
        self._queue = queue.Queue()
        self._root: Optional[tk.Tk] = None
        self._ready = threading.Event()
        self._save_fn: Optional[Callable] = None
        self._emit_fn: Optional[Callable] = None

        if self._use_background_thread:
            # Start the background tkinter thread on non-macOS platforms.
            self._thread = threading.Thread(target=self._tk_loop, daemon=True)
            self._thread.start()
            self._ready.wait()  # wait until the tkinter loop is alive
        else:
            self._ready.set()

    # ----------------------------------------------------------------------
    # Public API (original interface preserved)
    # ----------------------------------------------------------------------
    def set_refs(self, window: Any, tracker: Any, save_fn: Callable, emit_fn: Callable) -> None:
        """Store callbacks. 'window' and 'tracker' are ignored (kept for compatibility)."""
        if self._disabled:
            return
        self._save_fn = save_fn
        self._emit_fn = emit_fn

    def start(self, config_key: str = "calibration_point") -> None:
        """
        Show a full‑screen calibration overlay, capture a click, and save the coordinates.
        This method can be called directly or via request_calibration().
        """
        if self._disabled:
            return
        self.request_calibration(config_key, "point")

    def request_calibration(self, config_key: str, window_type: str = "point") -> None:
        """Request a calibration for the given configuration key."""
        if self._disabled:
            return
        if self._use_background_thread:
            self._queue.put({"action": "calibrate", "key": config_key, "type": window_type})
        else:
            # On macOS avoid creating Tk windows from non-main threads; prefer pynput-based capture
            if _pynput_mouse is not None:
                try:
                    self._run_calibration_pynput(config_key, window_type)
                    return
                except Exception:
                    pass
            # If pynput is not available, fail loudly with instructions rather than attempting Tk from a worker thread
            raise RuntimeError(
                "Calibration on macOS requires the 'pynput' package; install it (pip install pynput) "
                "and grant Accessibility permissions."
            )

    def _run_calibration_pynput(self, config_key: str, window_type: str) -> None:
        """Capture click or drag coordinates using pynput (safe on macOS)."""
        if not self._save_fn:
            return

        captured = {"x": None, "y": None, "x2": None, "y2": None}
        finished = threading.Event()

        def on_click(x, y, button, pressed):
            try:
                if window_type == "point":
                    if pressed:
                        captured["x"] = int(x)
                        captured["y"] = int(y)
                        finished.set()
                        return False
                else:
                    # for region: first press stores start, release stores end
                    if pressed:
                        captured["x"] = int(x)
                        captured["y"] = int(y)
                    else:
                        captured["x2"] = int(x)
                        captured["y2"] = int(y)
                        finished.set()
                        return False
            except Exception:
                finished.set()
                return False

        listener = _pynput_mouse.Listener(on_click=on_click)
        listener.start()
        # Wait until user clicks (or times out after 120s)
        finished.wait(120)
        try:
            listener.stop()
        except Exception:
            pass

        if window_type == "point":
            if captured["x"] is not None and captured["y"] is not None:
                try:
                    self._save_fn({config_key: [captured["x"], captured["y"]]})
                    if self._emit_fn:
                        self._emit_fn({"key": config_key, "x": captured["x"], "y": captured["y"]})
                except Exception:
                    pass
        else:
            if captured["x"] is not None and captured["y"] is not None and captured["x2"] is not None and captured["y2"] is not None:
                x0 = min(captured["x"], captured["x2"])
                y0 = min(captured["y"], captured["y2"])
                w = max(abs(captured["x2"] - captured["x"]), 1)
                h = max(abs(captured["y2"] - captured["y"]), 1)
                try:
                    self._save_fn({config_key: [x0, y0, w, h]})
                    if self._emit_fn:
                        self._emit_fn({"key": config_key, "x": x0, "y": y0, "w": w, "h": h})
                except Exception:
                    pass

    def request_display(self, config_key: str, label: Optional[str] = None, duration_ms: int = 2500) -> None:
        """Request a temporary message overlay."""
        if self._disabled:
            return
        if self._use_background_thread:
            self._queue.put({
                "action": "display",
                "key": config_key,
                "label": label or str(config_key),
                "duration_ms": int(duration_ms)
            })
        else:
            self._run_display_sync(config_key, label or str(config_key), int(duration_ms))

    def request_display_many(self, items: List[Dict], duration_ms: int = 2500) -> None:
        """Request multiple temporary messages displayed in sequence."""
        if self._disabled:
            return
        if self._use_background_thread:
            self._queue.put({
                "action": "display_many",
                "items": items,
                "duration_ms": int(duration_ms)
            })
        else:
            self._run_display_many_sync(items, int(duration_ms))

    def close(self, event=None) -> None:
        """Shut down the internal tkinter root window (optional)."""
        if self._root:
            self._root.quit()
            self._root.destroy()

    # ----------------------------------------------------------------------
    # Internal tkinter thread and queue processing
    # ----------------------------------------------------------------------
    def _tk_loop(self) -> None:
        """Run tkinter event loop in a background thread."""
        try:
            # Environment setup for frozen apps (bundled executables)
            import os
            import sys
            if getattr(sys, 'frozen', False) or getattr(sys, '__compiled__', False):
                try:
                    _base = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
                    for _sub in os.listdir(_base):
                        _full = os.path.join(_base, _sub)
                        if os.path.isdir(_full):
                            _low = _sub.lower()
                            if _low.startswith("tcl") and "TCL_LIBRARY" not in os.environ:
                                os.environ["TCL_LIBRARY"] = _full
                            elif _low.startswith("tk") and "TK_LIBRARY" not in os.environ:
                                os.environ["TK_LIBRARY"] = _full
                except Exception:
                    pass

            self._root = tk.Tk()
            self._root.withdraw()          # hide the main tkinter window
            self._ready.set()              # signal that we are ready
            self._process_queue()          # start processing requests
            self._root.mainloop()
        except Exception as e:
            print(f"[CalibrationManager] FATAL: {e}")
            import traceback
            traceback.print_exc()
            self._ready.set()   # avoid deadlock on error

    def _process_queue(self) -> None:
        """Periodically process pending requests (called via 'after')."""
        try:
            while True:
                req = self._queue.get_nowait()
                self._execute_request(req)
        except queue.Empty:
            pass
        finally:
            if self._root:
                self._root.after(100, self._process_queue)

    def _execute_request(self, req: Dict) -> None:
        """Execute a single request inside the tkinter thread."""
        action = req.get("action")
        if action == "calibrate":
            self._run_calibration(req["key"], req["type"])
        elif action == "display":
            self._run_display(req["key"], req["label"], req["duration_ms"])
        elif action == "display_many":
            self._run_display_many(req["items"], req["duration_ms"])

    def _run_calibration_sync(self, config_key: str, window_type: str) -> None:
        """Run a calibration overlay synchronously for macOS."""
        if not self._save_fn:
            return

        root = tk.Tk()
        root.withdraw()

        overlay = tk.Toplevel(root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.25)
        except Exception:
            pass
        overlay.configure(bg="black", cursor="crosshair")

        sw = overlay.winfo_screenwidth()
        sh = overlay.winfo_screenheight()
        overlay.geometry(f"{sw}x{sh}+0+0")

        result: Dict[str, int] = {}
        start: Dict[str, Optional[int]] = {"x": None, "y": None}
        rect_id: Optional[int] = None

        canvas = tk.Canvas(overlay, bg="", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        label_text = (
            "Click to calibrate a single point. Press Escape to cancel."
            if window_type == "point"
            else "Click and drag to select a region. Release to confirm. Press Escape to cancel."
        )
        tk.Label(
            canvas,
            text=label_text,
            fg="white",
            bg="black",
            font=("Helvetica", 18, "bold"),
            padx=20,
            pady=10,
        ).place(relx=0.5, rely=0.02, anchor="n")

        def finish(payload: Optional[Dict[str, int]]) -> None:
            if payload is None:
                overlay.destroy()
                return

            if window_type == "point":
                self._save_fn({config_key: [payload["x"], payload["y"]]})
                event_data = {"key": config_key, "x": payload["x"], "y": payload["y"]}
            else:
                self._save_fn({config_key: [payload["x"], payload["y"], payload["w"], payload["h"]]})
                event_data = {
                    "key": config_key,
                    "x": payload["x"],
                    "y": payload["y"],
                    "w": payload["w"],
                    "h": payload["h"],
                }

            if self._emit_fn:
                self._emit_fn(event_data)
            overlay.destroy()

        def on_press(event: tk.Event) -> None:
            x = overlay.winfo_pointerx()
            y = overlay.winfo_pointery()
            start["x"] = x
            start["y"] = y
            nonlocal rect_id
            if window_type == "region":
                if rect_id is not None:
                    canvas.delete(rect_id)
                rect_id = canvas.create_rectangle(x, y, x, y, outline="white", width=2, dash=(4, 4))

        def on_move(event: tk.Event) -> None:
            if window_type != "region" or start["x"] is None or start["y"] is None:
                return
            x = overlay.winfo_pointerx()
            y = overlay.winfo_pointery()
            if rect_id is not None:
                canvas.coords(rect_id, start["x"], start["y"], x, y)

        def on_release(event: tk.Event) -> None:
            x = overlay.winfo_pointerx()
            y = overlay.winfo_pointery()
            if window_type == "point":
                finish({"x": x, "y": y})
                return

            if start["x"] is None or start["y"] is None:
                finish(None)
                return

            x0 = min(start["x"], x)
            y0 = min(start["y"], y)
            w = max(abs(x - start["x"]), 1)
            h = max(abs(y - start["y"]), 1)
            finish({"x": x0, "y": y0, "w": w, "h": h})

        def on_escape(event: tk.Event = None) -> None:
            finish(None)

        overlay.bind("<ButtonPress-1>", on_press)
        overlay.bind("<B1-Motion>", on_move)
        overlay.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)
        overlay.focus_force()

        root.wait_window(overlay)
        try:
            root.destroy()
        except Exception:
            pass

    # ----------------------------------------------------------------------
    # Calibration overlay
    # ----------------------------------------------------------------------
    def _run_calibration(self, config_key: str, window_type: str) -> None:
        """Show a full‑screen overlay, capture click coordinates, and call save_fn."""
        if not self._root or not self._save_fn:
            return
        overlay = tk.Toplevel(self._root)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.1)
        overlay.configure(bg="#111111", cursor="crosshair")
        overlay.attributes("-topmost", True)

        result: Dict[str, Optional[int]] = {"x": None, "y": None, "w": None, "h": None}
        start: Dict[str, Optional[int]] = {"x": None, "y": None}
        rect_id: Optional[int] = None

        canvas = tk.Canvas(overlay, bg="", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        label_text = (
            "Click to calibrate a single point. Press Escape to cancel."
            if window_type == "point"
            else "Click and drag to select a region. Release to confirm. Press Escape to cancel."
        )
        tk.Label(
            canvas,
            text=label_text,
            fg="white",
            bg="black",
            font=("Helvetica", 18, "bold"),
            padx=20,
            pady=10,
        ).place(relx=0.5, rely=0.02, anchor="n")

        def finish_point(x: int, y: int) -> None:
            result["x"] = x
            result["y"] = y
            overlay.destroy()

        def finish_region(x: int, y: int, w: int, h: int) -> None:
            result["x"] = x
            result["y"] = y
            result["w"] = w
            result["h"] = h
            overlay.destroy()

        def on_press(event: tk.Event) -> None:
            start["x"] = overlay.winfo_pointerx()
            start["y"] = overlay.winfo_pointery()
            nonlocal rect_id
            if window_type == "region":
                if rect_id is not None:
                    canvas.delete(rect_id)
                rect_id = canvas.create_rectangle(start["x"], start["y"], start["x"], start["y"], outline="white", width=2, dash=(4, 4))

        def on_move(event: tk.Event) -> None:
            if window_type != "region" or start["x"] is None or start["y"] is None:
                return
            x = overlay.winfo_pointerx()
            y = overlay.winfo_pointery()
            if rect_id is not None:
                canvas.coords(rect_id, start["x"], start["y"], x, y)

        def on_release(event: tk.Event) -> None:
            x = overlay.winfo_pointerx()
            y = overlay.winfo_pointery()
            if window_type == "point":
                finish_point(x, y)
                return

            if start["x"] is None or start["y"] is None:
                overlay.destroy()
                return

            x0 = min(start["x"], x)
            y0 = min(start["y"], y)
            w = max(abs(x - start["x"]), 1)
            h = max(abs(y - start["y"]), 1)
            finish_region(x0, y0, w, h)

        def on_escape(event: tk.Event = None) -> None:
            overlay.destroy()

        overlay.bind("<ButtonPress-1>", on_press)
        overlay.bind("<B1-Motion>", on_move)
        overlay.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)

        self._root.wait_window(overlay)

        if result["x"] is not None and result["y"] is not None:
            if window_type == "point":
                self._save_fn({config_key: [result["x"], result["y"]]})
                payload = {"key": config_key, "x": result["x"], "y": result["y"]}
            else:
                self._save_fn({config_key: [result["x"], result["y"], result["w"], result["h"]]})
                payload = {
                    "key": config_key,
                    "x": result["x"],
                    "y": result["y"],
                    "w": result["w"],
                    "h": result["h"],
                }
            if self._emit_fn:
                self._emit_fn(payload)

    def _run_display_sync(self, config_key: str, label: str, duration_ms: int) -> None:
        """Show a centered overlay on macOS and wait until it disappears."""
        root = tk.Tk()
        root.withdraw()

        overlay = tk.Toplevel(root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.85)
        except Exception:
            pass
        overlay.configure(bg="black")

        lbl = tk.Label(
            overlay, text=label, fg="white", bg="black",
            font=("Helvetica", 24, "bold"), padx=20, pady=10
        )
        lbl.pack(expand=True, fill="both")

        overlay.update_idletasks()
        w = overlay.winfo_width()
        h = overlay.winfo_height()
        sw = overlay.winfo_screenwidth()
        sh = overlay.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        overlay.geometry(f"+{x}+{y}")

        overlay.after(duration_ms, root.quit)
        overlay.focus_force()
        try:
            root.mainloop()
        except Exception:
            pass
        try:
            overlay.destroy()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    def _run_display_many_sync(self, items: List[Dict], duration_ms: int) -> None:
        """Show multiple displays sequentially in macOS sync mode."""
        for item in items:
            self._run_display_sync(item.get("key", ""), item.get("label", str(item)), duration_ms)

    # ----------------------------------------------------------------------
    # Temporary display overlays
    # ----------------------------------------------------------------------
    def _run_display(self, config_key: str, label: str, duration_ms: int) -> None:
        """Show a centered label that disappears after duration_ms."""
        if not self._root:
            return

        overlay = tk.Toplevel(self._root)
        overlay.overrideredirect(True)          # no window decorations
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.85)
        overlay.configure(bg="black")

        lbl = tk.Label(
            overlay, text=label, fg="white", bg="black",
            font=("Helvetica", 24, "bold"), padx=20, pady=10
        )
        lbl.pack(expand=True, fill="both")

        # Center the window on the screen
        overlay.update_idletasks()
        w = overlay.winfo_width()
        h = overlay.winfo_height()
        sw = overlay.winfo_screenwidth()
        sh = overlay.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        overlay.geometry(f"+{x}+{y}")

        overlay.after(duration_ms, overlay.destroy)

    def _run_display_many(self, items: List[Dict], duration_ms: int) -> None:
        """Show multiple displays sequentially."""
        if not items:
            return
        item = items[0]
        self._run_display(item.get("key", ""), item.get("label", str(item)), duration_ms)
        if len(items) > 1:
            self._root.after(duration_ms + 50, lambda: self._run_display_many(items[1:], duration_ms))
    