"""Oblivion - ROV Ground Control Station Main Module"""
import copy
import json
import os
import subprocess
import sys
import time
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

from calibration import run_calibration
from communication import UDPConnection
from controller import JoystickController
from gui import run_live_display, console, get_logo_text
from joystick import JoystickError, JoystickManager
from rich.panel import Panel

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
        "reverse": {
            "M1": False,
            "M2": False,
            "M3": False,
            "M4": False,
            "M5": False,
            "M6": False
        }
    }
}


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

    joystick_manager = None
    while joystick_manager is None:
        try:
            joystick_manager = JoystickManager()
        except JoystickError:
            console.clear()
            console.print(Panel("[bold yellow]⏳ Joystick bekleniyor... Lütfen bir gamepad bağlayın.[/bold yellow]", border_style="yellow"))
            time.sleep(1.5)

    state = joystick_manager.get_state()
    config = load_config()
    joystick_settings = config.get("joystick") or copy.deepcopy(DEFAULT_CONFIG["joystick"])
    calibration_data = joystick_settings.get("calibration", {})

    console.clear()
    console.print(get_logo_text())
    console.print(f"[bold cyan]Algılanan Cihaz:[/bold cyan] [bright_green]{state.name}[/bright_green]\n")

    if calibration_data:
        console.print("[green]Mevcut kalibrasyon verisi yüklendi.[/green]")
    else:
        console.print("[yellow]Henüz yapılmış bir kalibrasyon bulunamadı.[/yellow]")

    try:
        answer = input("\nYeniden kalibrasyon yapmak istiyor musunuz? (e/h): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        answer = "h"

    if answer in ["e", "evet", "y", "yes"]:
        calibration_data = run_calibration(joystick_manager, state)
        joystick_settings["calibration"] = calibration_data
        joystick_settings["axis_mapping"] = configure_axis_mapping(calibration_data, joystick_settings.get("axis_mapping", {}))
        config["joystick"] = joystick_settings
        save_config(config)

    controller = JoystickController(
        deadzone=joystick_settings.get("deadzone", 0.08),
        sensitivity=joystick_settings.get("sensitivity", 1.0),
        axis_mapping=configure_axis_mapping(calibration_data, joystick_settings.get("axis_mapping", {})),
        calibration=calibration_data,
        invert=joystick_settings.get("invert"),
    )

    # Reverse ayarları mevcut motor yönlerine EK tersleme uygular.
    # False varsayılanı, mevcut Arduino INVERT_M1..M6 davranışını aynen korur.
    motor_settings = config.setdefault("motors", {})
    reverse_settings = motor_settings.setdefault("reverse", {})
    motor_reverse = {
        f"M{i}": bool(reverse_settings.get(f"M{i}", False))
        for i in range(1, 7)
    }
    reverse_settings.update(motor_reverse)
    config["motors"] = motor_settings
    save_config(config)

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

