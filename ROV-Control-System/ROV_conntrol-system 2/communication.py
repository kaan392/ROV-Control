"""UDP bağlantısı ve kontrol paketleri için modül."""
import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class ControlPacket:
    forward: int
    strafe: int
    vertical: int
    yaw: int
    emergency_stop: bool = False
    sequence: int = 0  # UDPConnection.send() doldurur; Arduino ACK'inde geri döner
    reverse_mask: int = 0  # bit 0..5: M1..M6 için Python reverse ayarı

    def format(self) -> str:
        e_val = 1 if self.emergency_stop else 0
        reverse_mask = max(0, min(63, int(self.reverse_mask)))
        return (
            f"F:{self.forward},S:{self.strafe},Y:{self.yaw},V:{self.vertical},"
            f"E:{e_val},N:{self.sequence},R:{reverse_mask}"
        )


@dataclass
class LinkStats:
    """Arduino'dan dönen ACK paketlerinden hesaplanan bağlantı bilgisi."""
    state: str                      # SIM / WAITING / OK / NO REPLY
    rtt_ms: Optional[float]         # son gidiş-dönüş süresi
    rtt_avg_ms: Optional[float]     # yumuşatılmış ortalama
    loss_pct: Optional[float]       # son ~100 paketteki kayıp yüzdesi
    ack_age_ms: Optional[int]       # son ACK'ten bu yana geçen süre
    held: bool = False              # Arduino motorları "kumandayı nötre al" kilidinde tutuyor


class UDPConnection:
    ACK_TIMEOUT_S = 1.0   # bu süre içinde ACK gelmeyen paket kayıp sayılır
    ACK_STALE_S = 0.5     # bu süredir ACK yoksa "NO REPLY"

    def __init__(
        self,
        target_ip: str,
        target_port: int,
        use_simulation: bool = True,
        local_port: Optional[int] = None,
    ):
        self.target_ip = target_ip
        self.target_port = target_port
        self.use_simulation = use_simulation
        self.local_port = local_port
        self.socket: Optional[socket.socket] = None

        self._lock = threading.Lock()
        self._seq = 0
        self._pending = {}                 # sequence -> gönderim zamanı
        self._history = deque(maxlen=100)  # True = ACK geldi, False = kayıp
        self._rtt = None
        self._rtt_avg = None
        self._last_ack = None
        self._held = False

    def connect(self):
        if self.use_simulation:
            logging.info(
                "UDP bağlantısı simülasyon modunda. Hedef: %s:%d",
                self.target_ip,
                self.target_port,
            )
            return

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if self.local_port is not None:
                self.socket.bind(("0.0.0.0", self.local_port))
            self.socket.settimeout(0.2)
            threading.Thread(
                target=self._rx_loop, args=(self.socket,), daemon=True
            ).start()
            logging.info(
                "UDP bağlantısı hazırlanıyor: %s:%d",
                self.target_ip,
                self.target_port,
            )
        except Exception as exc:
            logging.error("UDP soket oluşturulamadı: %s", exc)
            if self.socket is not None:
                try:
                    self.socket.close()
                except Exception:
                    pass
            self.socket = None

    def _rx_loop(self, sock: socket.socket):
        """Arduino'dan gelen 'A:<seq>' ACK paketlerini dinler (RTT ölçümü için)."""
        while self.socket is sock:
            try:
                data, addr = sock.recvfrom(64)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Windows: hedef kapalıyken ICMP "port unreachable" bir kez hata verir.
                time.sleep(0.01)
                continue
            except OSError:
                break

            arrival = time.monotonic()
            if addr[0] != self.target_ip:
                continue
            text = data.decode("ascii", errors="ignore").strip()
            if not text.startswith("A:"):
                continue
            fields = text[2:].split(",")
            try:
                seq = int(fields[0])
            except ValueError:
                continue

            with self._lock:
                sent_at = self._pending.pop(seq, None)
                if sent_at is None:
                    continue
                rtt = (arrival - sent_at) * 1000.0
                self._rtt = rtt
                self._rtt_avg = rtt if self._rtt_avg is None else self._rtt_avg * 0.9 + rtt * 0.1
                self._last_ack = arrival
                self._held = "H:1" in fields[1:]
                self._history.append(True)

    def get_stats(self) -> LinkStats:
        if self.use_simulation:
            return LinkStats("SIM", None, None, None, None)

        now = time.monotonic()
        with self._lock:
            cutoff = now - self.ACK_TIMEOUT_S
            for seq in [s for s, t in self._pending.items() if t < cutoff]:
                del self._pending[seq]
                self._history.append(False)

            loss = None
            if self._history:
                loss = 100.0 * self._history.count(False) / len(self._history)

            ack_age = None if self._last_ack is None else int((now - self._last_ack) * 1000)
            if ack_age is None:
                state = "WAITING"
            elif ack_age > self.ACK_STALE_S * 1000:
                state = "NO REPLY"
            else:
                state = "OK"

            return LinkStats(state, self._rtt, self._rtt_avg, loss, ack_age, self._held)

    def send(self, packet: ControlPacket) -> bool:
        """Paketi gönderir. Başarılıysa True, hata olursa (istisna fırlatmadan) False döner."""
        packet.sequence = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        message = packet.format().encode("ascii")

        if self.use_simulation:
            logging.info("Gönderilen UDP paket: %s", message.decode("ascii"))
            return True

        if self.socket is None:
            self.connect()
        if self.socket is None:
            return False

        try:
            with self._lock:
                self._pending[packet.sequence] = time.monotonic()
            self.socket.sendto(message, (self.target_ip, self.target_port))
            return True
        except OSError as exc:
            logging.warning("UDP gönderilemedi: %s", exc)
            return False

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

