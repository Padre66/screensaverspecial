import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageGrab, ImageTk
from screeninfo import get_monitors

import win32gui
import win32ui

APP_TITLE = "ScreenSaver Special"
CONFIG_FILE = Path("config.json")


@dataclass
class AppConfig:
    cashier_window_title_part: str = "Juta"
    screensaver_image: str = "C:/LaciABC/laci_abc_sotet_hatter.png"
    target_monitor_index: int = 0
    idle_seconds: float = 60.0
    check_interval: float = 0.25
    change_threshold: float = 3.0
    visible_after_change_seconds: float = 2.0
    start_minimized: bool = False
    auto_start_monitoring: bool = False
    use_visible_screen_fallback: bool = True


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        config = AppConfig()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    CONFIG_FILE.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


def list_windows() -> List[Tuple[int, str]]:
    windows: List[Tuple[int, str]] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if title and title not in {APP_TITLE, "Program Manager"}:
            windows.append((hwnd, title))

    win32gui.EnumWindows(callback, None)
    windows.sort(key=lambda item: item[1].lower())
    return windows


def find_window_by_title_part(title_part: str) -> Optional[int]:
    title_part = title_part.lower().strip()
    if not title_part:
        return None
    for hwnd, title in list_windows():
        if title_part in title.lower():
            return hwnd
    return None


def capture_window_printwindow(hwnd: int) -> Optional[Image.Image]:
    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    bitmap = None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        success = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        if not success:
            success = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0)
        if not success:
            return None

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )
    except Exception:
        return None
    finally:
        try:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass
        try:
            if save_dc is not None:
                save_dc.DeleteDC()
        except Exception:
            pass
        try:
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
        except Exception:
            pass
        try:
            if hwnd_dc is not None:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def capture_window_visible_screen(hwnd: int) -> Optional[Image.Image]:
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right <= left or bottom <= top:
            return None
        return ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
    except Exception:
        return None


def capture_window(hwnd: int, use_visible_screen_fallback: bool = True) -> Optional[Image.Image]:
    image = capture_window_printwindow(hwnd)
    if image is not None:
        return image
    if use_visible_screen_fallback:
        return capture_window_visible_screen(hwnd)
    return None


def image_difference_score(img1: Image.Image, img2: Image.Image) -> float:
    img1 = img1.resize((320, 180)).convert("L")
    img2 = img2.resize((320, 180)).convert("L")
    arr1 = np.asarray(img1, dtype=np.int16)
    arr2 = np.asarray(img2, dtype=np.int16)
    return float(np.mean(np.abs(arr1 - arr2)))


class Overlay:
    def __init__(self, parent: tk.Tk, on_manual_hide=None):
        self.parent = parent
        self.on_manual_hide = on_manual_hide
        self.window: Optional[tk.Toplevel] = None
        self.label: Optional[tk.Label] = None
        self.photo = None
        self.visible = False

    def show(self, image_path: str, monitor_index: int) -> None:
        monitors = get_monitors()
        if monitor_index < 0 or monitor_index >= len(monitors):
            raise RuntimeError("Invalid monitor index")
        monitor = monitors[monitor_index]

        if self.window is None:
            self.window = tk.Toplevel(self.parent)
            self.window.overrideredirect(True)
            self.window.attributes("-topmost", True)
            self.window.configure(bg="black")
            self.label = tk.Label(self.window, bg="black")
            self.label.pack(fill="both", expand=True)
            for widget in (self.window, self.label):
                widget.bind("<Escape>", self.manual_hide)
                widget.bind("<Button-1>", self.manual_hide)
                widget.bind("<Button-3>", self.manual_hide)
            self.window.withdraw()

        self.window.geometry(f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}")
        image = Image.open(image_path).convert("RGB")
        image = self._fit_image(image, monitor.width, monitor.height)
        self.photo = ImageTk.PhotoImage(image)
        self.label.configure(image=self.photo)
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.visible = True

    def manual_hide(self, event=None) -> None:
        self.hide()
        if self.on_manual_hide is not None:
            self.on_manual_hide()

    def hide(self) -> None:
        if self.window is not None:
            self.window.withdraw()
        self.visible = False

    @staticmethod
    def _fit_image(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        img_ratio = img.width / img.height
        target_ratio = target_w / target_h
        if img_ratio > target_ratio:
            new_w = target_w
            new_h = int(target_w / img_ratio)
        else:
            new_h = target_h
            new_w = int(target_h * img_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        background = Image.new("RGB", (target_w, target_h), "black")
        background.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
        return background


class ScreenSaverSpecialApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x680")
        self.root.minsize(780, 620)

        self.config = load_config()
        self.overlay = Overlay(root, self.on_overlay_manual_hide)
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.monitoring = False
        self.test_overlay_active = False
        self.status_var = tk.StringVar(value="Kész")
        self.window_items: List[Tuple[int, str]] = []
        self.monitor_items = []

        self._build_ui()
        self.refresh_monitors()
        self.refresh_windows()
        self._load_values_to_ui()

        if self.config.start_minimized:
            self.root.iconify()
        if self.config.auto_start_monitoring:
            self.root.after(500, self.start_monitoring)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="ScreenSaver Special - kassza kijelzővédő", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 10))

        settings = ttk.LabelFrame(main, text="Beállítások", padding=10)
        settings.pack(fill="x")
        self.window_combo = ttk.Combobox(settings, state="readonly", width=70)
        self.window_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(settings, text="Kasszaprogram ablaka:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Button(settings, text="Frissítés", command=self.refresh_windows).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(settings, text="Cím átvétele", command=self.use_selected_window_title).grid(row=0, column=3, sticky="ew", padx=4)

        ttk.Label(settings, text="Ablakcím részlete:").grid(row=1, column=0, sticky="w", pady=4)
        self.title_part_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.title_part_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=6, pady=4)

        ttk.Label(settings, text="Kijelzővédő kép:").grid(row=2, column=0, sticky="w", pady=4)
        self.image_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.image_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        ttk.Button(settings, text="Tallózás", command=self.browse_image).grid(row=2, column=3, sticky="ew", padx=4)

        ttk.Label(settings, text="Cél monitor:").grid(row=3, column=0, sticky="w", pady=4)
        self.monitor_combo = ttk.Combobox(settings, state="readonly", width=70)
        self.monitor_combo.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        ttk.Button(settings, text="Frissítés", command=self.refresh_monitors).grid(row=3, column=3, sticky="ew", padx=4)
        settings.columnconfigure(1, weight=1)

        numeric = ttk.LabelFrame(main, text="Időzítés és érzékenység", padding=10)
        numeric.pack(fill="x", pady=10)
        self.idle_var = tk.StringVar()
        self.interval_var = tk.StringVar()
        self.threshold_var = tk.StringVar()
        self.visible_after_var = tk.StringVar()
        self._add_number_row(numeric, 0, "Tétlenségi idő (mp):", self.idle_var, "Teszteléshez állítsd 5-re.")
        self._add_number_row(numeric, 1, "Ellenőrzés gyakorisága (mp):", self.interval_var, "0.25 = kb. negyed másodperces reakció.")
        self._add_number_row(numeric, 2, "Változásérzékenység:", self.threshold_var, "Kisebb érték = érzékenyebb. Javasolt: 2-5.")
        self._add_number_row(numeric, 3, "Változás után látható idő (mp):", self.visible_after_var, "Változás után legalább ennyi ideig maradjon látható a kassza.")
        numeric.columnconfigure(1, weight=1)

        options = ttk.LabelFrame(main, text="Indítás", padding=10)
        options.pack(fill="x")
        self.start_minimized_var = tk.BooleanVar()
        self.auto_start_var = tk.BooleanVar()
        self.fallback_var = tk.BooleanVar()
        ttk.Checkbutton(options, text="Indításkor kis méretben induljon", variable=self.start_minimized_var).pack(anchor="w")
        ttk.Checkbutton(options, text="Program indításakor automatikusan induljon a figyelés", variable=self.auto_start_var).pack(anchor="w")
        ttk.Checkbutton(options, text="Látható képernyőrész figyelése, ha az ablak belső képe nem olvasható (VirtualBoxhoz ajánlott)", variable=self.fallback_var).pack(anchor="w")

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=12)
        ttk.Button(buttons, text="Mentés", command=self.save_from_ui).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Teszt kép mutatása", command=self.test_show_overlay).pack(side="left", padx=6)
        ttk.Button(buttons, text="Teszt kép elrejtése", command=self.hide_test_overlay).pack(side="left", padx=6)
        ttk.Button(buttons, text="Capture teszt", command=self.capture_test).pack(side="left", padx=6)
        ttk.Button(buttons, text="Start monitorozás", command=self.start_monitoring).pack(side="right", padx=6)
        ttk.Button(buttons, text="Stop", command=self.stop_monitoring).pack(side="right", padx=6)

        log_box = ttk.LabelFrame(main, text="Állapot", padding=10)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=10, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=6).pack(side="bottom", fill="x")

    def _add_number_row(self, parent, row: int, label: str, var: tk.StringVar, hint: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var, width=12).grid(row=row, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(parent, text=hint).grid(row=row, column=2, sticky="w", padx=6, pady=4)

    def _load_values_to_ui(self) -> None:
        self.title_part_var.set(self.config.cashier_window_title_part)
        self.image_var.set(self.config.screensaver_image)
        self.idle_var.set(str(self.config.idle_seconds))
        self.interval_var.set(str(self.config.check_interval))
        self.threshold_var.set(str(self.config.change_threshold))
        self.visible_after_var.set(str(self.config.visible_after_change_seconds))
        self.start_minimized_var.set(self.config.start_minimized)
        self.auto_start_var.set(self.config.auto_start_monitoring)
        self.fallback_var.set(self.config.use_visible_screen_fallback)
        if self.monitor_items:
            self.monitor_combo.current(min(max(self.config.target_monitor_index, 0), len(self.monitor_items) - 1))

    def log_message(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{timestamp}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status_var.set(message)

    def refresh_windows(self) -> None:
        self.window_items = list_windows()
        values = [f"{title}  (HWND: {hwnd})" for hwnd, title in self.window_items]
        self.window_combo["values"] = values
        if values:
            self.window_combo.current(0)
        self.log_message(f"Ablaklista frissítve: {len(values)} ablak")

    def refresh_monitors(self) -> None:
        self.monitor_items = get_monitors()
        values = [f"{i}: {m.width}x{m.height} pozíció: {m.x},{m.y}" for i, m in enumerate(self.monitor_items)]
        self.monitor_combo["values"] = values
        if values:
            self.monitor_combo.current(min(max(int(self.config.target_monitor_index), 0), len(values) - 1))
        self.log_message(f"Monitorlista frissítve: {len(values)} monitor")

    def use_selected_window_title(self) -> None:
        idx = self.window_combo.current()
        if 0 <= idx < len(self.window_items):
            self.title_part_var.set(self.window_items[idx][1])

    def browse_image(self) -> None:
        filename = filedialog.askopenfilename(title="Kijelzővédő kép kiválasztása", filetypes=[("Képfájlok", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("Minden fájl", "*.*")])
        if filename:
            self.image_var.set(filename)

    def _config_from_ui(self) -> AppConfig:
        monitor_index = self.monitor_combo.current()
        if monitor_index < 0:
            monitor_index = 0
        return AppConfig(
            cashier_window_title_part=self.title_part_var.get().strip(),
            screensaver_image=self.image_var.get().strip(),
            target_monitor_index=monitor_index,
            idle_seconds=float(self.idle_var.get()),
            check_interval=float(self.interval_var.get()),
            change_threshold=float(self.threshold_var.get()),
            visible_after_change_seconds=float(self.visible_after_var.get()),
            start_minimized=bool(self.start_minimized_var.get()),
            auto_start_monitoring=bool(self.auto_start_var.get()),
            use_visible_screen_fallback=bool(self.fallback_var.get()),
        )

    def save_from_ui(self) -> bool:
        try:
            config = self._config_from_ui()
            if not config.cashier_window_title_part:
                raise ValueError("Az ablakcím részlete nem lehet üres.")
            if not Path(config.screensaver_image).exists():
                raise ValueError("A kiválasztott kép nem található.")
            if config.idle_seconds < 1:
                raise ValueError("A tétlenségi idő legyen legalább 1 másodperc.")
            if config.check_interval < 0.05:
                raise ValueError("Az ellenőrzési gyakoriság legyen legalább 0.05 másodperc.")
            self.config = config
            save_config(config)
            self.log_message("Beállítások mentve config.json fájlba")
            return True
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return False

    def get_selected_hwnd(self) -> Optional[int]:
        hwnd = find_window_by_title_part(self.title_part_var.get().strip())
        if hwnd is not None:
            return hwnd
        idx = self.window_combo.current()
        if 0 <= idx < len(self.window_items):
            return self.window_items[idx][0]
        return None

    def capture_test(self) -> None:
        if not self.save_from_ui():
            return
        hwnd = self.get_selected_hwnd()
        if hwnd is None:
            self.log_message("Capture teszt: nincs kiválasztott/megtalált ablak")
            return
        img = capture_window(hwnd, self.config.use_visible_screen_fallback)
        if img is None:
            self.log_message("Capture teszt sikertelen: az ablak képe nem olvasható")
            return
        self.log_message(f"Capture teszt sikeres: {img.width}x{img.height}")

    def test_show_overlay(self) -> None:
        if not self.save_from_ui():
            return
        try:
            self.test_overlay_active = True
            self.overlay.show(self.config.screensaver_image, self.config.target_monitor_index)
            self.log_message("Teszt kép megjelenítve. Elrejtés: ESC vagy egérkattintás a képen.")
        except Exception as exc:
            self.test_overlay_active = False
            messagebox.showerror(APP_TITLE, str(exc))

    def hide_test_overlay(self) -> None:
        self.test_overlay_active = False
        self.overlay.hide()
        self.log_message("Teszt kép elrejtve")

    def on_overlay_manual_hide(self) -> None:
        if self.test_overlay_active:
            self.test_overlay_active = False
            self.log_message("Teszt kép elrejtve")

    def start_monitoring(self) -> None:
        if self.monitoring:
            self.log_message("A monitorozás már fut")
            return
        if not self.save_from_ui():
            return
        self.test_overlay_active = False
        self.stop_event.clear()
        self.monitoring = True
        self.worker = threading.Thread(target=self._monitor_loop, daemon=True)
        self.worker.start()
        self.log_message("Monitorozás elindítva")

    def stop_monitoring(self) -> None:
        self.stop_event.set()
        self.monitoring = False
        self.test_overlay_active = False
        self.root.after(0, self.overlay.hide)
        self.log_message("Monitorozás leállítva")

    def _monitor_loop(self) -> None:
        hwnd: Optional[int] = None
        previous_img: Optional[Image.Image] = None
        last_change_time = time.time()
        last_missing_log = 0.0
        last_capture_fail_log = 0.0
        last_wait_log = 0.0
        overlay_logged = False

        while not self.stop_event.is_set():
            try:
                if self.test_overlay_active:
                    time.sleep(0.1)
                    continue

                if hwnd is None or not win32gui.IsWindow(hwnd):
                    hwnd = find_window_by_title_part(self.config.cashier_window_title_part)
                    previous_img = None
                    last_change_time = time.time()
                    overlay_logged = False
                    if hwnd is None:
                        if time.time() - last_missing_log > 5:
                            self.root.after(0, self.log_message, "Nem találom a figyelt ablakot")
                            last_missing_log = time.time()
                        self.root.after(0, self.overlay.hide)
                        time.sleep(1)
                        continue
                    title = win32gui.GetWindowText(hwnd)
                    self.root.after(0, self.log_message, f"Figyelt ablak: {title}")

                current_img = capture_window(hwnd, self.config.use_visible_screen_fallback)
                if current_img is None:
                    if time.time() - last_capture_fail_log > 5:
                        self.root.after(0, self.log_message, "Capture sikertelen: nincs olvasható ablak-kép")
                        last_capture_fail_log = time.time()
                    self.root.after(0, self.overlay.hide)
                    time.sleep(1)
                    continue

                if previous_img is None:
                    previous_img = current_img
                    last_change_time = time.time()
                    self.root.after(0, self.log_message, "Első képminta rögzítve, tétlenség mérése indul")
                    time.sleep(self.config.check_interval)
                    continue

                score = image_difference_score(previous_img, current_img)
                if score > self.config.change_threshold:
                    previous_img = current_img
                    last_change_time = time.time()
                    overlay_logged = False
                    self.root.after(0, self.overlay.hide)
                else:
                    idle_time = time.time() - last_change_time
                    if time.time() - last_wait_log > 10 and idle_time < self.config.idle_seconds:
                        self.root.after(0, self.log_message, f"Tétlen: {idle_time:.0f}/{self.config.idle_seconds:.0f} mp")
                        last_wait_log = time.time()
                    if idle_time >= self.config.idle_seconds:
                        self.root.after(0, self._safe_show_overlay)
                        if not overlay_logged:
                            self.root.after(0, self.log_message, "Tétlenségi idő letelt, kép megjelenítése")
                            overlay_logged = True

                if time.time() - last_change_time < self.config.visible_after_change_seconds:
                    self.root.after(0, self.overlay.hide)

                time.sleep(self.config.check_interval)
            except Exception as exc:
                self.root.after(0, self.log_message, f"Hiba: {exc}")
                self.root.after(0, self.overlay.hide)
                time.sleep(2)

        self.monitoring = False
        self.root.after(0, self.overlay.hide)

    def _safe_show_overlay(self) -> None:
        if self.test_overlay_active:
            return
        try:
            self.overlay.show(self.config.screensaver_image, self.config.target_monitor_index)
        except Exception as exc:
            self.log_message(f"Kép megjelenítési hiba: {exc}")


def main() -> None:
    root = tk.Tk()
    app = ScreenSaverSpecialApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_monitoring(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
