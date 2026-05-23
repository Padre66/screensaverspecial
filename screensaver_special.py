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

try:
    import serial
    import serial.tools.list_ports
except Exception:
    serial = None

APP_TITLE = "ScreenSaver Special"
CONFIG_FILE = Path("config.json")


@dataclass
class AppConfig:
    monitor_mode: str = "window"  # window vagy serial
    cashier_window_title_part: str = "Juta"
    screensaver_image: str = "C:/LaciABC/laci_abc_sotet_hatter.png"
    target_monitor_index: int = 0
    idle_seconds: float = 60.0
    check_interval: float = 0.5
    change_threshold: float = 0.03
    visible_after_change_seconds: float = 2.0
    start_minimized: bool = False
    auto_start_monitoring: bool = False
    use_visible_screen_fallback: bool = True
    serial_port: str = "COM1"
    serial_baudrate: int = 9600
    serial_bytesize: int = 8
    serial_parity: str = "N"
    serial_stopbits: float = 1.0


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cfg = AppConfig()
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    CONFIG_FILE.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


def list_windows() -> List[Tuple[int, str]]:
    result: List[Tuple[int, str]] = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if title and title not in {APP_TITLE, "Program Manager"}:
            result.append((hwnd, title))

    win32gui.EnumWindows(callback, None)
    result.sort(key=lambda item: item[1].lower())
    return result


def find_window_by_title_part(title_part: str) -> Optional[int]:
    title_part = title_part.lower().strip()
    if not title_part:
        return None
    for hwnd, title in list_windows():
        if title_part in title.lower():
            return hwnd
    return None


def capture_printwindow(hwnd: int) -> Optional[Image.Image]:
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
        ok = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
        if not ok:
            ok = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 0)
        if not ok:
            return None
        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        return Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1)
    except Exception:
        return None
    finally:
        for cleanup in (
            lambda: win32gui.DeleteObject(bitmap.GetHandle()) if bitmap is not None else None,
            lambda: save_dc.DeleteDC() if save_dc is not None else None,
            lambda: mfc_dc.DeleteDC() if mfc_dc is not None else None,
            lambda: win32gui.ReleaseDC(hwnd, hwnd_dc) if hwnd_dc is not None else None,
        ):
            try:
                cleanup()
            except Exception:
                pass


def capture_visible(hwnd: int) -> Optional[Image.Image]:
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right <= left or bottom <= top:
            return None
        return ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
    except Exception:
        return None


def capture_window(hwnd: int, visible_first: bool, overlay_visible: bool) -> Tuple[Optional[Image.Image], str]:
    if overlay_visible:
        img = capture_printwindow(hwnd)
        return img, "printwindow-behind-logo"
    if visible_first:
        img = capture_visible(hwnd)
        if img is not None:
            return img, "visible-screen"
        img = capture_printwindow(hwnd)
        return img, "printwindow-fallback"
    img = capture_printwindow(hwnd)
    if img is not None:
        return img, "printwindow"
    img = capture_visible(hwnd)
    return img, "visible-fallback"


def diff_score(a: Image.Image, b: Image.Image) -> float:
    a = a.resize((320, 180)).convert("L")
    b = b.resize((320, 180)).convert("L")
    aa = np.asarray(a, dtype=np.int16)
    bb = np.asarray(b, dtype=np.int16)
    return float(np.mean(np.abs(aa - bb)))


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
            raise RuntimeError("Nincs ilyen monitor index.")
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
        image = self.fit_image(image, monitor.width, monitor.height)
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
    def fit_image(img: Image.Image, w: int, h: int) -> Image.Image:
        img_ratio = img.width / img.height
        target_ratio = w / h
        if img_ratio > target_ratio:
            nw = w
            nh = int(w / img_ratio)
        else:
            nh = h
            nw = int(h * img_ratio)
        resized = img.resize((nw, nh), Image.LANCZOS)
        bg = Image.new("RGB", (w, h), "black")
        bg.paste(resized, ((w - nw) // 2, (h - nh) // 2))
        return bg


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x780")
        self.root.minsize(860, 720)
        self.config = load_config()
        self.overlay = Overlay(root, self.on_overlay_manual_hide)
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.monitoring = False
        self.test_overlay_active = False
        self.window_items: List[Tuple[int, str]] = []
        self.monitor_items = []
        self.status_var = tk.StringVar(value="Kész")
        self.build_ui()
        self.refresh_monitors()
        self.refresh_windows()
        self.refresh_serial_ports()
        self.load_values_to_ui()
        if self.config.start_minimized:
            self.root.iconify()
        if self.config.auto_start_monitoring:
            self.root.after(500, self.start_monitoring)

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="ScreenSaver Special - kassza kijelzővédő", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 10))

        mode_frame = ttk.LabelFrame(main, text="Figyelési mód", padding=10)
        mode_frame.pack(fill="x")
        self.mode_var = tk.StringVar()
        ttk.Radiobutton(mode_frame, text="Ablakkép figyelése", variable=self.mode_var, value="window").pack(side="left", padx=(0, 20))
        ttk.Radiobutton(mode_frame, text="Soros port aktivitás figyelése", variable=self.mode_var, value="serial").pack(side="left")

        settings = ttk.LabelFrame(main, text="Ablakkép beállítások", padding=10)
        settings.pack(fill="x", pady=(10, 0))
        ttk.Label(settings, text="Kasszaprogram ablaka:").grid(row=0, column=0, sticky="w", pady=4)
        self.window_combo = ttk.Combobox(settings, state="readonly", width=70)
        self.window_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(settings, text="Frissítés", command=self.refresh_windows).grid(row=0, column=2, padx=4)
        ttk.Button(settings, text="Cím átvétele", command=self.use_selected_window_title).grid(row=0, column=3, padx=4)
        ttk.Label(settings, text="Ablakcím részlete:").grid(row=1, column=0, sticky="w", pady=4)
        self.title_part_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.title_part_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=6, pady=4)
        self.fallback_var = tk.BooleanVar()
        ttk.Checkbutton(settings, text="Látható képernyőrész figyelése elsődlegesen, amíg a logó nem látszik", variable=self.fallback_var).grid(row=2, column=1, columnspan=3, sticky="w", padx=6, pady=4)
        settings.columnconfigure(1, weight=1)

        serial_frame = ttk.LabelFrame(main, text="Soros port beállítások", padding=10)
        serial_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(serial_frame, text="COM port:").grid(row=0, column=0, sticky="w", pady=4)
        self.serial_port_var = tk.StringVar()
        self.serial_port_combo = ttk.Combobox(serial_frame, textvariable=self.serial_port_var, width=20)
        self.serial_port_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(serial_frame, text="Portok frissítése", command=self.refresh_serial_ports).grid(row=0, column=2, padx=4)
        ttk.Label(serial_frame, text="Szabadon írható, pl. COM1, COM3, COM12").grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(serial_frame, text="Baud rate:").grid(row=1, column=0, sticky="w", pady=4)
        self.serial_baud_var = tk.StringVar()
        ttk.Combobox(serial_frame, textvariable=self.serial_baud_var, values=["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"], width=18).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(serial_frame, text="Adatbit:").grid(row=1, column=2, sticky="e", pady=4)
        self.serial_bytesize_var = tk.StringVar()
        ttk.Combobox(serial_frame, textvariable=self.serial_bytesize_var, values=["5", "6", "7", "8"], width=8).grid(row=1, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(serial_frame, text="Paritás:").grid(row=2, column=0, sticky="w", pady=4)
        self.serial_parity_var = tk.StringVar()
        ttk.Combobox(serial_frame, textvariable=self.serial_parity_var, values=["N", "E", "O", "M", "S"], width=8).grid(row=2, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(serial_frame, text="Stopbit:").grid(row=2, column=2, sticky="e", pady=4)
        self.serial_stopbits_var = tk.StringVar()
        ttk.Combobox(serial_frame, textvariable=self.serial_stopbits_var, values=["1", "1.5", "2"], width=8).grid(row=2, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(serial_frame, text="Megjegyzés: Windows alatt egy COM portot általában csak egy program tud egyszerre megnyitni.").grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        image_frame = ttk.LabelFrame(main, text="Kép és monitor", padding=10)
        image_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(image_frame, text="Kijelzővédő kép:").grid(row=0, column=0, sticky="w", pady=4)
        self.image_var = tk.StringVar()
        ttk.Entry(image_frame, textvariable=self.image_var).grid(row=0, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        ttk.Button(image_frame, text="Tallózás", command=self.browse_image).grid(row=0, column=3, padx=4)
        ttk.Label(image_frame, text="Cél monitor:").grid(row=1, column=0, sticky="w", pady=4)
        self.monitor_combo = ttk.Combobox(image_frame, state="readonly", width=70)
        self.monitor_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        ttk.Button(image_frame, text="Frissítés", command=self.refresh_monitors).grid(row=1, column=3, padx=4)
        image_frame.columnconfigure(1, weight=1)

        numeric = ttk.LabelFrame(main, text="Időzítés és érzékenység", padding=10)
        numeric.pack(fill="x", pady=(10, 0))
        self.idle_var = tk.StringVar()
        self.interval_var = tk.StringVar()
        self.threshold_var = tk.StringVar()
        self.visible_after_var = tk.StringVar()
        self.add_number_row(numeric, 0, "Tétlenségi idő (mp):", self.idle_var, "Ennyi ideig nincs változás/adat, utána logó.")
        self.add_number_row(numeric, 1, "Ellenőrzés gyakorisága (mp):", self.interval_var, "Soros portnál 0.1-0.5 ajánlott.")
        self.add_number_row(numeric, 2, "Változásérzékenység:", self.threshold_var, "Csak ablakkép módban számít.")
        self.add_number_row(numeric, 3, "Változás után látható idő (mp):", self.visible_after_var, "Változás/adat után legalább ennyi ideig látszik a kassza.")

        options = ttk.LabelFrame(main, text="Indítás", padding=10)
        options.pack(fill="x", pady=(10, 0))
        self.start_minimized_var = tk.BooleanVar()
        self.auto_start_var = tk.BooleanVar()
        ttk.Checkbutton(options, text="Indításkor kis méretben induljon", variable=self.start_minimized_var).pack(anchor="w")
        ttk.Checkbutton(options, text="Program indításakor automatikusan induljon a figyelés", variable=self.auto_start_var).pack(anchor="w")

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=12)
        ttk.Button(buttons, text="Mentés", command=self.save_from_ui).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Teszt kép mutatása", command=self.test_show_overlay).pack(side="left", padx=6)
        ttk.Button(buttons, text="Teszt kép elrejtése", command=self.hide_test_overlay).pack(side="left", padx=6)
        ttk.Button(buttons, text="Capture teszt", command=self.capture_test).pack(side="left", padx=6)
        ttk.Button(buttons, text="Soros port teszt", command=self.serial_test).pack(side="left", padx=6)
        ttk.Button(buttons, text="Start monitorozás", command=self.start_monitoring).pack(side="right", padx=6)
        ttk.Button(buttons, text="Stop", command=self.stop_monitoring).pack(side="right", padx=6)

        log_box = ttk.LabelFrame(main, text="Állapot", padding=10)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=10, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=6).pack(side="bottom", fill="x")

    def add_number_row(self, parent, row: int, label: str, var: tk.StringVar, hint: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var, width=12).grid(row=row, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(parent, text=hint).grid(row=row, column=2, sticky="w", padx=6, pady=4)

    def log_message(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status_var.set(message)

    def load_values_to_ui(self) -> None:
        self.mode_var.set(self.config.monitor_mode)
        self.title_part_var.set(self.config.cashier_window_title_part)
        self.image_var.set(self.config.screensaver_image)
        self.idle_var.set(str(self.config.idle_seconds))
        self.interval_var.set(str(self.config.check_interval))
        self.threshold_var.set(str(self.config.change_threshold))
        self.visible_after_var.set(str(self.config.visible_after_change_seconds))
        self.start_minimized_var.set(self.config.start_minimized)
        self.auto_start_var.set(self.config.auto_start_monitoring)
        self.fallback_var.set(self.config.use_visible_screen_fallback)
        self.serial_port_var.set(self.config.serial_port)
        self.serial_baud_var.set(str(self.config.serial_baudrate))
        self.serial_bytesize_var.set(str(self.config.serial_bytesize))
        self.serial_parity_var.set(self.config.serial_parity)
        self.serial_stopbits_var.set(str(self.config.serial_stopbits))
        if self.monitor_items:
            self.monitor_combo.current(min(max(self.config.target_monitor_index, 0), len(self.monitor_items) - 1))

    def refresh_windows(self) -> None:
        self.window_items = list_windows()
        self.window_combo["values"] = [f"{title}  (HWND: {hwnd})" for hwnd, title in self.window_items]
        if self.window_items:
            self.window_combo.current(0)
        self.log_message(f"Ablaklista frissítve: {len(self.window_items)} ablak")

    def refresh_monitors(self) -> None:
        self.monitor_items = get_monitors()
        self.monitor_combo["values"] = [f"{i}: {m.width}x{m.height} pozíció: {m.x},{m.y}" for i, m in enumerate(self.monitor_items)]
        if self.monitor_items:
            self.monitor_combo.current(min(max(int(self.config.target_monitor_index), 0), len(self.monitor_items) - 1))
        self.log_message(f"Monitorlista frissítve: {len(self.monitor_items)} monitor")

    def refresh_serial_ports(self) -> None:
        if serial is None:
            self.log_message("pyserial nem elérhető")
            return
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if hasattr(self, "serial_port_combo"):
            self.serial_port_combo["values"] = ports
        self.log_message(f"Soros port lista frissítve: {len(ports)} port")

    def use_selected_window_title(self) -> None:
        idx = self.window_combo.current()
        if 0 <= idx < len(self.window_items):
            self.title_part_var.set(self.window_items[idx][1])

    def browse_image(self) -> None:
        filename = filedialog.askopenfilename(title="Kijelzővédő kép kiválasztása", filetypes=[("Képfájlok", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("Minden fájl", "*.*")])
        if filename:
            self.image_var.set(filename)

    def config_from_ui(self) -> AppConfig:
        monitor_index = self.monitor_combo.current()
        if monitor_index < 0:
            monitor_index = 0
        return AppConfig(
            monitor_mode=self.mode_var.get().strip() or "window",
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
            serial_port=self.serial_port_var.get().strip().upper(),
            serial_baudrate=int(float(self.serial_baud_var.get())),
            serial_bytesize=int(float(self.serial_bytesize_var.get())),
            serial_parity=self.serial_parity_var.get().strip().upper() or "N",
            serial_stopbits=float(self.serial_stopbits_var.get()),
        )

    def save_from_ui(self) -> bool:
        try:
            cfg = self.config_from_ui()
            if not Path(cfg.screensaver_image).exists():
                raise ValueError("A kiválasztott kép nem található.")
            if cfg.monitor_mode == "window" and not cfg.cashier_window_title_part:
                raise ValueError("Ablakkép módban az ablakcím részlete nem lehet üres.")
            if cfg.monitor_mode == "serial" and not cfg.serial_port:
                raise ValueError("Soros port módban a COM port nem lehet üres.")
            if cfg.idle_seconds < 1:
                raise ValueError("A tétlenségi idő legyen legalább 1 másodperc.")
            if cfg.check_interval < 0.05:
                raise ValueError("Az ellenőrzési gyakoriság legyen legalább 0.05 másodperc.")
            self.config = cfg
            save_config(cfg)
            self.log_message("Beállítások mentve config.json fájlba")
            return True
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return False

    def selected_hwnd(self) -> Optional[int]:
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
        hwnd = self.selected_hwnd()
        if hwnd is None:
            self.log_message("Capture teszt: nincs kiválasztott/megtalált ablak")
            return
        img, mode = capture_window(hwnd, self.config.use_visible_screen_fallback, self.overlay.visible)
        if img is None:
            self.log_message("Capture teszt sikertelen: az ablak képe nem olvasható")
        else:
            self.log_message(f"Capture teszt sikeres: {img.width}x{img.height}, mód: {mode}")

    def serial_test(self) -> None:
        if not self.save_from_ui():
            return
        if serial is None:
            self.log_message("Soros port teszt sikertelen: pyserial nincs telepítve")
            return
        try:
            with serial.Serial(
                port=self.config.serial_port,
                baudrate=self.config.serial_baudrate,
                bytesize=self.config.serial_bytesize,
                parity=self.config.serial_parity,
                stopbits=self.config.serial_stopbits,
                timeout=0.2,
            ):
                self.log_message(f"Soros port teszt sikeres: {self.config.serial_port}")
        except Exception as exc:
            self.log_message(f"Soros port teszt sikertelen: {exc}")

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
        self.stop_event.clear()
        self.monitoring = True
        self.test_overlay_active = False
        target = self.serial_loop if self.config.monitor_mode == "serial" else self.window_loop
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()
        self.log_message(f"Monitorozás elindítva, mód: {self.config.monitor_mode}")

    def stop_monitoring(self) -> None:
        self.stop_event.set()
        self.monitoring = False
        self.test_overlay_active = False
        self.overlay.hide()
        self.log_message("Monitorozás leállítva")

    def show_overlay(self) -> None:
        self.overlay.show(self.config.screensaver_image, self.config.target_monitor_index)

    def window_loop(self) -> None:
        hwnd: Optional[int] = None
        previous_img: Optional[Image.Image] = None
        last_change_time = time.time()
        last_missing_log = 0.0
        last_capture_fail_log = 0.0
        last_wait_log = 0.0
        last_score_log = 0.0
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
                        time.sleep(1)
                        continue
                    self.root.after(0, self.log_message, f"Figyelt ablak: {win32gui.GetWindowText(hwnd)}")

                current_img, mode = capture_window(hwnd, self.config.use_visible_screen_fallback, self.overlay.visible)
                if current_img is None:
                    if time.time() - last_capture_fail_log > 5:
                        self.root.after(0, self.log_message, "Capture sikertelen: nincs olvasható ablak-kép")
                        last_capture_fail_log = time.time()
                    time.sleep(1)
                    continue
                if previous_img is None:
                    previous_img = current_img
                    last_change_time = time.time()
                    self.root.after(0, self.log_message, f"Első képminta rögzítve, mód: {mode}")
                    time.sleep(self.config.check_interval)
                    continue

                score = diff_score(previous_img, current_img)
                if time.time() - last_score_log > 5:
                    self.root.after(0, self.log_message, f"Aktuális eltérés: {score:.2f}, küszöb: {self.config.change_threshold:.2f}, mód: {mode}")
                    last_score_log = time.time()

                if score > self.config.change_threshold:
                    previous_img = current_img
                    last_change_time = time.time()
                    overlay_logged = False
                    self.root.after(0, self.overlay.hide)
                else:
                    idle_time = time.time() - last_change_time
                    if not self.overlay.visible and time.time() - last_wait_log > 10 and idle_time < self.config.idle_seconds:
                        self.root.after(0, self.log_message, f"Tétlen: {idle_time:.0f}/{self.config.idle_seconds:.0f} mp")
                        last_wait_log = time.time()
                    if idle_time >= self.config.idle_seconds and not self.overlay.visible:
                        self.root.after(0, self.show_overlay)
                        if not overlay_logged:
                            self.root.after(0, self.log_message, "Tétlenségi idő letelt, kép megjelenítése")
                            overlay_logged = True
                time.sleep(self.config.check_interval)
            except Exception as exc:
                self.root.after(0, self.log_message, f"Hiba: {exc}")
                time.sleep(2)
        self.monitoring = False
        self.root.after(0, self.overlay.hide)

    def serial_loop(self) -> None:
        if serial is None:
            self.root.after(0, self.log_message, "Soros port mód nem használható: pyserial nincs telepítve")
            self.monitoring = False
            return

        port = None
        last_activity = time.time()
        last_idle_log = 0.0
        overlay_logged = False
        reconnect_log = 0.0

        while not self.stop_event.is_set():
            try:
                if port is None or not port.is_open:
                    try:
                        port = serial.Serial(
                            port=self.config.serial_port,
                            baudrate=self.config.serial_baudrate,
                            bytesize=self.config.serial_bytesize,
                            parity=self.config.serial_parity,
                            stopbits=self.config.serial_stopbits,
                            timeout=0,
                        )
                        self.root.after(0, self.log_message, f"Soros port megnyitva: {self.config.serial_port}")
                        last_activity = time.time()
                    except Exception as exc:
                        if time.time() - reconnect_log > 5:
                            self.root.after(0, self.log_message, f"Soros port nem nyitható: {exc}")
                            reconnect_log = time.time()
                        time.sleep(1)
                        continue

                count = port.in_waiting
                if count > 0:
                    data = port.read(count)
                    last_activity = time.time()
                    overlay_logged = False
                    self.root.after(0, self.overlay.hide)
                    self.root.after(0, self.log_message, f"Soros adat érkezett: {len(data)} byte")
                else:
                    idle_time = time.time() - last_activity
                    if not self.overlay.visible and time.time() - last_idle_log > 10 and idle_time < self.config.idle_seconds:
                        self.root.after(0, self.log_message, f"Soros port tétlen: {idle_time:.0f}/{self.config.idle_seconds:.0f} mp")
                        last_idle_log = time.time()
                    if idle_time >= self.config.idle_seconds and not self.overlay.visible:
                        self.root.after(0, self.show_overlay)
                        if not overlay_logged:
                            self.root.after(0, self.log_message, "Soros port tétlenségi idő letelt, kép megjelenítése")
                            overlay_logged = True
                time.sleep(self.config.check_interval)
            except Exception as exc:
                self.root.after(0, self.log_message, f"Soros port hiba: {exc}")
                try:
                    if port is not None:
                        port.close()
                except Exception:
                    pass
                port = None
                time.sleep(1)

        try:
            if port is not None:
                port.close()
        except Exception:
            pass
        self.monitoring = False
        self.root.after(0, self.overlay.hide)


def main() -> None:
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_monitoring(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
