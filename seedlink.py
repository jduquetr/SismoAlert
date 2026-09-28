"""Cliente SeedLink 3.1 mínimo (el de ObsPy falla con servidores RingServer 4)."""
import io
import logging
import socket
import time

from obspy import read

log = logging.getLogger("sismos")


class SeedLinkClient:
    RECORD = 512
    HEADER = 8  # "SL" + número de secuencia en hexadecimal

    def __init__(self, server, streams, on_trace, timeout=120):
        host, port = server.split(":")
        self.addr = (host, int(port))
        self.streams = streams  # [(red, estación, selector)]
        self.on_trace = on_trace
        self.timeout = timeout
        self.sock = None

    def _cmd(self, text, expect_ok=True):
        self.sock.sendall(text.encode("ascii") + b"\r\n")
        if not expect_ok:
            return None
        resp = self._readline()
        if resp not in ("OK",):
            raise ConnectionError(f"'{text}' -> {resp}")
        return resp

    def _readline(self):
        buf = b""
        while not buf.endswith(b"\r\n"):
            c = self.sock.recv(1)
            if not c:
                raise ConnectionError("conexión cerrada")
            buf += c
        return buf.decode("ascii", "replace").strip()

    def _recv_exact(self, n):
        data = bytearray()
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("conexión cerrada por el servidor")
            data.extend(chunk)
        return bytes(data)

    def run(self):
        self.sock = socket.create_connection(self.addr, timeout=30)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.sendall(b"HELLO\r\n")
            banner = [self._readline(), self._readline()]
            log.info("SeedLink: %s", " / ".join(banner))
            for net, sta, sel in self.streams:
                self._cmd(f"STATION {sta} {net}")
                self._cmd(f"SELECT {sel}.D")
                self._cmd("DATA")
            self._cmd("END", expect_ok=False)
            while True:
                head = self._recv_exact(self.HEADER)
                if head[:2] != b"SL":
                    raise ConnectionError(f"encabezado inesperado {head!r}")
                rec = self._recv_exact(self.RECORD)
                if head[2:6] == b"INFO":
                    continue
                try:
                    st = read(io.BytesIO(rec), format="MSEED")
                except Exception as e:
                    log.debug("registro no legible: %s", e)
                    continue
                for tr in st:
                    self.on_trace(tr)
        finally:
            try:
                self.sock.sendall(b"BYE\r\n")
            except OSError:
                pass
            self.sock.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    t0 = time.time()
    n = {}

    def show(tr):
        n[tr.stats.station] = n.get(tr.stats.station, 0) + 1
        print(tr.id, tr.stats.endtime, f"{tr.stats.npts} muestras")
        if time.time() - t0 > 20:
            raise SystemExit(f"paquetes por estación: {n}")

    SeedLinkClient("rtserve.iris.washington.edu:18000",
                   [("CM", "HEL", "00HHZ"), ("CM", "RUS", "00HHZ")], show).run()
