"""Ayarlar penceresi (motor reverse) ve köşe log paneli."""
import json
import logging
import os
import queue
import time

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
MOTOR_NAMES = (
    "M1  Arka Sol", "M2  Arka Sağ", "M3  Ön Sol",
    "M4  Ön Sağ", "M5  Sol Dikey", "M6  Sağ Dikey",
)

# ---------------------------------------------------------------- log
_log_queue = queue.Queue()

def log_event(level: str, message: str) -> None:
    _log_queue.put((time.strftime("%H:%M:%S"), level.upper(), message))

class _QueueLogHandler(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if record.exc_info:
            msg += f" ({record.exc_info[1]})"
        log_event(record.levelname, msg)

_handler_installed = False

def install_log_handler() -> None:
    """logging.info/warning/error çağrılarını log paneline düşürür."""
    global _handler_installed
    if _handler_installed:
        return
    # Seviyeyi INFO yapıyoruz ki tüm loglar panele düşsün
    handler = _QueueLogHandler(level=logging.INFO)
    logging.getLogger().addHandler(handler)
    _handler_installed = True

class LogPanel:
    COLORS = {"INFO": "#8ba0ae", "WARNING": "#ffae64", "ERROR": "#ff6b6b", "CRITICAL": "#ff6b6b"}

    def __init__(self, parent, tk):
        self.tk = tk
        self._last = {}  # mesaj -> [son zaman, bastırılan tekrar sayısı]

        bar = tk.Frame(parent, bg="#111d29")
        bar.pack(fill="x", padx=6, pady=(2, 0))
        for text, cmd in (("Temizle", self.clear), ("Kopyala", self.copy)):
            tk.Button(
                bar, text=text, command=cmd, bg="#1b2f40", fg="#9eb4c1",
                activebackground="#274258", activeforeground="#e5f2f8",
                relief="flat", font=("Segoe UI", 7, "bold"), padx=6, pady=0, bd=0,
            ).pack(side="right", padx=(4, 0))

        self.text = tk.Text(
            parent, height=6, bg="#0c1822", fg="#8ba0ae", font=("Consolas", 8),
            relief="flat", wrap="word", state="disabled", highlightthickness=0,
        )
        scroll = tk.Scrollbar(parent, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=3)
        self.text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=3)
        for level, color in self.COLORS.items():
            self.text.tag_configure(level, foreground=color)

    def start(self, root):
        self._root = root
        self._poll()

    def _poll(self):
        try:
            while True:
                stamp, level, msg = _log_queue.get_nowait()
                self._add(stamp, level, msg)
        except queue.Empty:
            pass
        self._root.after(200, self._poll)

    def _add(self, stamp, level, msg):
        now = time.monotonic()
        rec = self._last.get(msg)
        if rec and now - rec[0] < 3.0:  # aynı mesaj spam yapmasın
            rec[1] += 1
            return
        suffix = f"  (+{rec[1]} tekrar)" if rec and rec[1] else ""
        self._last[msg] = [now, 0]

        self.text.configure(state="normal")
        self.text.insert("end", f"{stamp} {msg}{suffix}\n", level if level in self.COLORS else "INFO")
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 200:
            self.text.delete("1.0", f"{lines - 200}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def copy(self):
        self.text.clipboard_clear()
        self.text.clipboard_append(self.text.get("1.0", "end").strip())


# ----------------------------------------------------- motor reverse ayarı
def load_reverse_flags() -> list:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        flags = [bool(x) for x in cfg.get("motors", {}).get("reverse", [])]
    except Exception:
        flags = []
    return (flags + [False] * 6)[:6]


def save_reverse_flags(flags) -> bool:
    try:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            cfg = {}
        cfg.setdefault("motors", {})["reverse"] = [bool(x) for x in flags]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as exc:
        log_event("ERROR", f"Config kaydedilemedi: {exc}")
        return False


def flags_to_mask(flags) -> int:
    return sum(1 << i for i, f in enumerate(flags) if f)


def open_config_window(root, tk, udp_connection):
    existing = getattr(root, "_config_win", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return

    win = tk.Toplevel(root)
    root._config_win = win
    win.title("OBLIVION | AYARLAR")
    win.configure(bg="#0a1420")
    win.resizable(False, False)
    win.transient(root)

    tk.Label(win, text="MOTOR YÖNLERİ", bg="#0a1420", fg="#5bd8e8",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
    tk.Label(win, text="İşaretli motor ters döner. Değişiklik anında Arduino'ya gider ve kaydedilir.",
             bg="#0a1420", fg="#8196a8", font=("Segoe UI", 8)).pack(anchor="w", padx=16)

    flags = load_reverse_flags()
    variables = [tk.BooleanVar(value=f) for f in flags]

    def apply(changed=None):
        current = [v.get() for v in variables]
        udp_connection.reverse_mask = flags_to_mask(current)
        if save_reverse_flags(current):
            names = [MOTOR_NAMES[i].split()[0] for i, f in enumerate(current) if f]
            log_event("INFO", "Ters motorlar: " + (", ".join(names) if names else "yok"))

    box = tk.Frame(win, bg="#111d29", highlightthickness=1, highlightbackground="#273d4f")
    box.pack(fill="x", padx=16, pady=10)
    for i, name in enumerate(MOTOR_NAMES):
        tk.Checkbutton(
            box, text=f"{name}  —  TERS", variable=variables[i], command=apply,
            bg="#111d29", fg="#e5f2f8", selectcolor="#1b2f40",
            activebackground="#111d29", activeforeground="#ffffff",
            font=("Segoe UI", 10), anchor="w",
        ).grid(row=i // 2, column=i % 2, sticky="w", padx=14, pady=6)

    def set_all(value):
        for v in variables:
            v.set(value)
        apply()

    buttons = tk.Frame(win, bg="#0a1420")
    buttons.pack(fill="x", padx=16, pady=(0, 6))
    for text, value in (("Hepsini ters çevir", True), ("Hepsini normale döndür", False)):
        tk.Button(buttons, text=text, command=lambda v=value: set_all(v),
                  bg="#1b2f40", fg="#e5f2f8", activebackground="#274258",
                  activeforeground="#ffffff", relief="flat",
                  font=("Segoe UI", 9, "bold"), padx=10, pady=5).pack(side="left", padx=(0, 8))

    tk.Label(win, text="Güvenlik: yön değişince motorlar durur, kumandayı nötre getirince devam eder.",
             bg="#0a1420", fg="#ffae64", font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(4, 14))