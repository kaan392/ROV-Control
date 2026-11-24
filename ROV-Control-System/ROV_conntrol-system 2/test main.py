"""Oblivion - ROV Ground Control Station (Klavye Simülasyonlu Test Modu)

Klavye, gerçek bir gamepad gibi davranır: çubuk ileri/yukarı = eksen -1.
Controller bu işareti çevirip komutta ileri/yukarı'yı yapar.
"""
import copy
import json
import os
import subprocess
import sys
import traceback

if __name__ == "__main__" and sys.platform == "win32":
    if not os.environ.get("ROV_CONSOLE_SPAWNED"):
        env = os.environ.copy()
        env["ROV_CONSOLE_SPAWNED"] = "1"
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            env=env,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        sys.exit(0)

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

from communication import UDPConnection
from controller import JoystickController
from gui import run_live_display, console, get_logo_text

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DEFAULT_CONFIG = {
    "joystick": {
        "deadzone": 0.08,
        "sensitivity": 1.0,
        "axis_mapping": {
            "forward": 1,
            "strafe": 0,
            "vertical": 3,
            "yaw": 2
        },
        "invert": {
            "forward": True,
            "strafe": False,
            "vertical": True,
            "yaw": False
        },
        "calibration": {}
    },
    "network": {
        "target_ip": "192.168.1.100",
        "target_port": 5032,
        "use_simulation": False,
        "local_port": None
    },
    "motors": {
        "reverse": {f"M{i}": False for i in range(1, 7)}
    }
}


class KeyboardSimulatedState:
    def __init__(self):
        self.name = "Klavye Simülatör Joystick (Test)"
        self.axes = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
        self.buttons = {i: False for i in range(16)}
        self.hats = {0: (0, 0)}

        self.axis_labels = {
            0: "Strafe (X)",
            1: "Forward (Y)",
            2: "Yaw (RX)",
            3: "Vertical (RY)",
            4: "Axis 4",
            5: "Axis 5"
        }
        self.button_labels = {i: f"Btn {i}" for i in range(16)}

    def get_axis(self, axis_index: int) -> float:
        return self.axes.get(axis_index, 0.0)

    def get_button(self, button_index: int) -> bool:
        return self.buttons.get(button_index, False)


class KeyboardJoystickManager:
    def __init__(self):
        self.state = KeyboardSimulatedState()
        self.is_connected = True

        if PYNPUT_AVAILABLE:
            self.listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self.listener.daemon = True
            self.listener.start()

    def _on_press(self, key):
        try:
            ch = key.char.lower() if hasattr(key, 'char') and key.char else None
            # Gamepad ile aynı işaret: çubuk ileri/yukarı = -1
            if ch == 'w':
                self.state.axes[1] = -1.0   # ileri
            elif ch == 's':
                self.state.axes[1] = 1.0    # geri
            elif ch == 'a':
                self.state.axes[0] = -1.0   # sol
            elif ch == 'd':
                self.state.axes[0] = 1.0    # sağ
            elif ch == 'r':
                self.state.axes[3] = -1.0   # yukarı
            elif ch == 'f':
                self.state.axes[3] = 1.0    # aşağı
            elif ch == 'q':
                self.state.axes[2] = -1.0   # sola dön
            elif ch == 'e':
                self.state.axes[2] = 1.0    # sağa dön
        except Exception:
            pass

        if key == keyboard.Key.space:
            self.state.buttons[0] = True

    def _on_release(self, key):
        try:
            ch = key.char.lower() if hasattr(key, 'char') and key.char else None
            if ch in ['w', 's']:
                self.state.axes[1] = 0.0
            elif ch in ['a', 'd']:
                self.state.axes[0] = 0.0
            elif ch in ['r', 'f']:
                self.state.axes[3] = 0.0
            elif ch in ['q', 'e']:
                self.state.axes[2] = 0.0
        except Exception:
            pass

        if key == keyboard.Key.space:
            self.state.buttons[0] = False

    def get_state(self):
        return self.state

    def update(self):
        return self.state

    def poll(self):
        return self.state

    def close(self):
        pass

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        config = copy.deepcopy(DEFAULT_CONFIG)
        save_config(config)
        return config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        console.print(f"[red]Config kaydedilemedi: {e}[/red]")


def configure_axis_mapping(calibration_data: dict, default_mapping: dict) -> dict:
    mapping = dict(default_mapping)
    if calibration_data:
        for action, data in calibration_data.items():
            if isinstance(data, dict) and "axis" in data:
                mapping[action] = data["axis"]
    return mapping


def main():
    console.clear()

    joystick_manager = KeyboardJoystickManager()
    state = joystick_manager.get_state()

    config = load_config()
    joystick_settings = config.get("joystick") or copy.deepcopy(DEFAULT_CONFIG["joystick"])
    calibration_data = joystick_settings.get("calibration", {})

    console.clear()
    console.print(get_logo_text())
    console.print(f"[bold cyan]Algılanan Cihaz:[/bold cyan] [bright_green]{state.name}[/bright_green]")
    if not PYNPUT_AVAILABLE:
        console.print("[bold red]Not: 'pynput' kütüphanesi bulunamadı. Klavyeden canlı veri testi için 'pip install pynput' yapabilirsiniz.[/bold red]\n")
    else:
        console.print("[bold yellow]Klavye Kontrolleri Aktif:[/bold yellow] W/S (İleri/Geri), A/D (Sol/Sağ), R/F (Yukarı/Aşağı), Q/E (Dönüş), Space (Acil Durdurma - arayüz penceresinde)\n")

    controller = JoystickController(
        deadzone=joystick_settings.get("deadzone", 0.08),
        sensitivity=joystick_settings.get("sensitivity", 1.0),
        axis_mapping=configure_axis_mapping(calibration_data, joystick_settings.get("axis_mapping", {})),
        calibration=calibration_data,
        invert=joystick_settings.get("invert"),
    )

    motor_settings = config.setdefault("motors", {})
    reverse_settings = motor_settings.setdefault("reverse", {})
    motor_reverse = {
        f"M{i}": bool(reverse_settings.get(f"M{i}", False))
        for i in range(1, 7)
    }
    reverse_settings.update(motor_reverse)

    def save_motor_reverse(updated_reverse):
        motor_settings["reverse"] = {
            f"M{i}": bool(updated_reverse.get(f"M{i}", False))
            for i in range(1, 7)
        }
        config["motors"] = motor_settings
        save_config(config)

    network_settings = config.get("network") or DEFAULT_CONFIG["network"]
    udp_connection = UDPConnection(
        target_ip=network_settings.get("target_ip", "192.168.1.100"),
        target_port=network_settings.get("target_port", 5032),
        use_simulation=network_settings.get("use_simulation", False),
        local_port=network_settings.get("local_port"),
    )
    udp_connection.connect()

    run_live_display(
        joystick_manager,
        controller,
        calibration_data,
        udp_connection,
        motor_reverse=motor_reverse,
        save_motor_reverse=save_motor_reverse,
    )

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        try:
            input("\nUygulama hatası. Hata mesajını kopyalamak için Enter'a basın...")
        except (EOFError, KeyboardInterrupt):
            pass

