"""Joystick kalibrasyonu için CLI tabanlı yapı.

Bu modül, joystick eksenini ve min/center/max
noktalarını kaydedip config'e yazılabilir hale getirir.
"""

import time
from typing import Dict
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live

try:
    import msvcrt
except ImportError:
    msvcrt = None

console = Console()

CONTROL_ACTIONS = [
    ("forward", "İleri / Geri"),
    ("vertical", "Yukarı / Aşağı"),
    ("strafe", "Yanal Sağ / Sol"),
    ("yaw", "Dönüş Sağ / Sol"),
]


def _wait_button_release(manager, timeout: float = 3.0) -> None:
    """Onay butonu hâlâ basılıysa bir sonraki adımı yanlışlıkla onaylamasın."""
    end = time.time() + timeout
    while time.time() < end:
        if not manager.get_state().buttons.get(0, False):
            return
        time.sleep(0.05)


def _get_axes_table(state) -> Table:
    table = Table(
        title="[bold cyan]🎮 Mevcut Eksen Durumları[/bold cyan]",
        show_header=True,
        header_style="bold magenta",
        border_style="dim cyan"
    )
    table.add_column("Eksen Kodu", style="bold yellow", justify="center")
    table.add_column("Etiket", style="cyan", justify="center")
    table.add_column("Canlı Değer", style="green", justify="right")

    for axis_index, label in state.axis_labels.items():
        value = state.axes.get(axis_index, 0.0)
        table.add_row(f"A{axis_index}", label, f"{value:+.2f}")

    return table


def _prompt_axis_index(manager, state, action_name: str) -> int:
    console.clear()
    console.print(
        Panel(
            f"[bold yellow] Eksen Seçimi: {action_name}[/bold yellow]\n\n"
            f"[dim]Aşağıdaki listeden ilgili hareket için kullanmak istediğiniz eksen numarasını tuşlayıp [bold white]ENTER[/bold white]'a veya Gamepad [bold green]X (A)[/bold green] butonuna basın.[/dim]",
            border_style="yellow"
        )
    )

    if msvcrt is None:
        console.print(_get_axes_table(state))
        while True:
            raw = input("\nEksen numarası (ör: 0, 1): ").strip()
            if raw.isdigit():
                axis_index = int(raw)
                if axis_index in state.axes:
                    return axis_index
            console.print("[red]❌ Geçersiz eksen numarası! Tekrar deneyin.[/red]")

    _wait_button_release(manager)
    buffer = ""
    with Live(console=console, refresh_per_second=10, screen=False) as live:
        while True:
            live_state = manager.get_state()

            grid = Table.grid(padding=1)
            grid.add_row(_get_axes_table(live_state))
            grid.add_row(
                Panel(
                    f"[bold cyan]Girdiğiniz Eksen No:[/bold cyan] [bold bright_green]{buffer}[/bold bright_green] █\n"
                    f"[dim]Numarayı girdikten sonra Onaylamak için: [bold white]ENTER[/bold white] veya Gamepad [bold green]X / A[/bold green] Butonu[/dim]",
                    border_style="blue"
                )
            )

            live.update(grid)

            if live_state.buttons.get(0, False):
                if buffer.isdigit():
                    axis_index = int(buffer)
                    if axis_index in live_state.axes:
                        time.sleep(0.3)
                        return axis_index
                buffer = ""
                time.sleep(0.3)

            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in {"\r", "\n"}:
                    if buffer.isdigit():
                        axis_index = int(buffer)
                        if axis_index in live_state.axes:
                            return axis_index
                    buffer = ""
                elif key in {"\b", "\x7f"}:
                    buffer = buffer[:-1]
                elif key.isdigit():
                    buffer += key
                elif key == "\x03":
                    raise KeyboardInterrupt

            time.sleep(0.05)


def _capture_position(manager, axis_index: int, instruction: str) -> float:
    console.clear()

    if msvcrt is None:
        console.print(Panel(f"[bold cyan]📍 {instruction}[/bold cyan]\n\nHareketi tamamlayınca [bold white]ENTER[/bold white] tuşuna basın.", border_style="cyan"))
        input()
        state = manager.get_state()
        return float(state.axes.get(axis_index, 0.0))

    _wait_button_release(manager)
    with Live(console=console, refresh_per_second=10, screen=False) as live:
        while True:
            live_state = manager.get_state()
            raw_value = float(live_state.axes.get(axis_index, 0.0))

            pos = int(round((raw_value + 1.0) * 10))
            pos = max(0, min(20, pos))
            if pos < 10:
                bar = "░" * pos + "█" * (10 - pos) + "│" + "░" * 10
            elif pos > 10:
                bar = "░" * 10 + "│" + "█" * (pos - 10) + "░" * (20 - pos)
            else:
                bar = "░" * 10 + "│" + "░" * 10

            info_panel = Panel(
                f"[bold yellow]📍 {instruction}[/bold yellow]\n\n"
                f"Eksen (A{axis_index}) Değeri: [bold bright_green]{raw_value:+.2f}[/bold bright_green]\n"
                f"Konum: [{bar}]\n\n"
                f"[dim cyan]Konumu kaydetmek için Gamepad [bold green]X (Cross)[/bold green] Butonuna veya Klavyeden [bold white]ENTER / SPACE[/bold white]'e basın.[/dim cyan]",
                title="[bold]~ KALİBRASYON NOKTASI CAPTURE ~[/bold]",
                border_style="magenta",
                padding=(1, 2)
            )
            live.update(info_panel)

            if live_state.buttons.get(0, False):
                time.sleep(0.3)
                return float(live_state.axes.get(axis_index, 0.0))

            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in {"\r", "\n", " "}:
                    return float(live_state.axes.get(axis_index, 0.0))
                if key == "\x03":
                    raise KeyboardInterrupt

            time.sleep(0.05)


def run_calibration(manager, state) -> Dict[str, Dict[str, float]]:
    console.clear()
    console.print(Panel("[bold bright_magenta]⚙️  JOYSTICK KALİBRASYON MODU ⚙️[/bold bright_magenta]\n[dim]Tüm hareket yönlerini sırayla kalibre edeceğiz.[/dim]", border_style="magenta", expand=False))
    time.sleep(1.5)

    calibration_data = {}
    used_axes = {}

    for action_key, action_label in CONTROL_ACTIONS:
        while True:
            axis_index = _prompt_axis_index(manager, state, action_label)
            if axis_index in used_axes:
                console.print(f"[red]❌ A{axis_index} zaten '{used_axes[axis_index]}' için seçildi. Başka bir eksen seçin.[/red]")
                time.sleep(1.5)
                continue
            break

        used_axes[axis_index] = action_label
        axis_label = state.axis_labels.get(axis_index, f"A{axis_index}")

        center = _capture_position(manager, axis_index, f"[{action_label}] için {axis_label} eksenini MERKEZDE (Bırakılmış) tutun")
        min_value = _capture_position(manager, axis_index, f"[{action_label}] için {axis_label} eksenini değeri -1'e yakın olan uca getirin")
        max_value = _capture_position(manager, axis_index, f"[{action_label}] için {axis_label} eksenini değeri +1'e yakın olan uca getirin")

        if min_value > max_value:
            min_value, max_value = max_value, min_value

        calibration_data[action_key] = {
            "axis": axis_index,
            "label": axis_label,
            "center": center,
            "min": min_value,
            "max": max_value,
        }

        console.clear()
        console.print(Panel(f"[bold green]✅ {action_label} kalibrasyonu başarıyla kaydedildi![/bold green]", border_style="green"))
        time.sleep(1)

    console.clear()
    console.print(Panel("[bold bright_green]🎉 TÜM KALİBRASYON İŞLEMLERİ TAMAMLANDI![/bold bright_green]", border_style="green"))
    time.sleep(1.5)

    return calibration_data

