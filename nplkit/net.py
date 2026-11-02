# CardOS HTTPS client that streams, so big uploads/downloads never sit in RAM.
#
#   from nplkit import net
#   r = net.request("POST", "example.com", "/api", {"Content-Type": "application/json"},
#                   body=[b'{"a":', b'1}'])          # body: bytes or a list/generator of chunks
#   print(r.status); data = r.read()                 # or r.readinto(buf) piece by piece
#   r.close()
#
# Body chunks are sent as they come; when the total length isn't given it is
# measured first (chunks must then be a list). Chunked responses are decoded.
import gc
import socket
import ssl

# ---- TLS memory reserve
# A TLS connection needs ~30 KB of contiguous system RAM, but MicroPython grows
# its heap by grabbing the largest free block and never gives it back. Apps that
# use the network (NET = True) get a placeholder block held for them while they
# run; each request releases it just before connecting and takes it back after.
_reserve = None
RESERVE_W, RESERVE_H = 240, 60      # same size as the launcher's canvas (~28 KB)


def largest_free():
    """Largest contiguous block of system RAM, in bytes."""
    import esp32
    return max(i[2] for i in esp32.idf_heap_info(esp32.HEAP_DATA))


def new_canvas(w, h):
    """Lcd.newCanvas, but returns None instead of crashing when RAM is short."""
    if largest_free() < w * h * 2 + 4096:
        return None
    try:
        from M5 import Lcd
        return Lcd.newCanvas(w, h, 16, False)
    except Exception:
        return None


def hold_reserve(block=None):
    """Hold a block of RAM for TLS. `block` adopts an existing canvas instead."""
    global _reserve
    if _reserve is None:
        _reserve = block or new_canvas(RESERVE_W, RESERVE_H)
        if _reserve is None:
            print("net: no RAM for the TLS reserve")


def drop_reserve():
    """Release the reserve. Returns True if one was held."""
    global _reserve
    if _reserve is None:
        return False
    try:
        _reserve.delete()
    except Exception:
        pass
    _reserve = None
    return True


class Response:
    def __init__(self, sock, rehold=False):
        self._rehold = rehold
        self._s = sock
        self.status = 0
        self.headers = {}
        self._chunked = False
        self._left = -1          # bytes left in the body (or the current chunk), -1 = unknown
        self._done = False
        self._read_head()

    def _line(self):
        line = self._s.readline()
        if not line:
            raise OSError("connection closed")
        return line

    def _read_head(self):
        parts = self._line().split(None, 2)
        self.status = int(parts[1])
        while True:
            line = self._line()
            if line in (b"\r\n", b"\n"):
                break
            k, _, v = line.decode().partition(":")
            self.headers[k.strip().lower()] = v.strip()
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            self._chunked = True
            self._left = 0
        elif "content-length" in self.headers:
            self._left = int(self.headers["content-length"])

    def _next_chunk(self):
        size = int(self._line().split(b";")[0].strip(), 16)
        if size == 0:
            self._line()  # trailing CRLF
            self._done = True
        self._left = size

    def readinto(self, buf):
        """Fill `buf` with body bytes; returns how many (0 at the end)."""
        if self._done:
            return 0
        if self._chunked and self._left == 0:
            self._next_chunk()
            if self._done:
                return 0
        want = len(buf)
        if self._left >= 0:
            want = min(want, self._left)
        n = self._s.readinto(memoryview(buf)[:want])
        if not n:
            self._done = True
            return 0
        if self._left >= 0:
            self._left -= n
            if self._chunked and self._left == 0:
                self._line()  # CRLF after each chunk
            elif not self._chunked and self._left == 0:
                self._done = True
        return n

    def read(self, limit=16384):
        """Read the whole (small) body as bytes."""
        out = bytearray()
        buf = bytearray(1024)
        while len(out) < limit:
            n = self.readinto(buf)
            if not n:
                break
            out += buf[:n]
        return bytes(out)

    def close(self):
        try:
            self._s.close()
        except Exception:
            pass
        if self._rehold:
            self._rehold = False
            hold_reserve()


def request(method, host, path, headers=None, body=None, length=None, timeout=30, tls=True):
    """tls=False talks plain HTTP on port 80: no ~30 KB TLS cost, but only use
    it for public data (nothing secret, like API keys, may be sent)."""
    if isinstance(body, (bytes, bytearray)):
        body = [body]
    if body is not None and length is None:
        length = sum(len(c) for c in body)
    gc.collect()
    had_reserve = drop_reserve() if tls else False   # hand the held block to TLS
    try:
        addr = socket.getaddrinfo(host, 443 if tls else 80)[0][-1]
        raw = socket.socket()
        raw.settimeout(timeout)
        try:
            raw.connect(addr)
            s = ssl.wrap_socket(raw, server_hostname=host) if tls else raw
        except Exception:
            raw.close()
            raise
    except Exception:
        if had_reserve:
            hold_reserve()
        raise
    try:
        head = "%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n" % (method, path, host)
        for k, v in (headers or {}).items():
            head += "%s: %s\r\n" % (k, v)
        if body is not None:
            head += "Content-Length: %d\r\n" % length
        s.write(head.encode() + b"\r\n")
        if body is not None:
            for chunk in body:
                if chunk:
                    s.write(chunk)
        return Response(s, rehold=had_reserve)
    except Exception:
        s.close()
        if had_reserve:
            hold_reserve()
        raise
