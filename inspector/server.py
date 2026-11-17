"""Loopback-only read-only API and range-capable video streaming."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).parent / "static"
STATIC_FILES = {"/": "index.html", "/app.js": "app.js", "/core.mjs": "core.mjs", "/styles.css": "styles.css"}


def byte_range(header, size):
    if not header:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()) or size == 0:
        raise ValueError("Unsatisfiable range")
    first, last = match.groups()
    if not first:
        length = int(last)
        if length <= 0:
            raise ValueError("Unsatisfiable range")
        return max(0, size - length), size - 1, True
    start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable range")
    return start, end, True


def make_server(dataset, port=8765):
    manifest = json.dumps(dataset.manifest(), allow_nan=False, separators=(",", ":")).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # No asset paths, frames, or dataset values in request logs.

        def send_headers(self, status, content_type, length, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                             "style-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
                             "connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()

        def payload(self, status, data):
            body = json.dumps(data, allow_nan=False).encode()
            self.send_headers(status, "application/json", len(body))
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            try:
                self.route()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser cancelled a seek / chunk request.

        def route(self):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                self.payload(403, {"error": "This viewer is available on localhost only"})
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in hosts}:
                self.payload(403, {"error": "Cross-origin requests are not supported"})
                return
            url = urlsplit(self.path)
            if url.path == "/api/manifest":
                self.send_headers(200, "application/json", len(manifest))
                if self.command != "HEAD":
                    self.wfile.write(manifest)
            elif url.path == "/api/frames":
                try:
                    query = parse_qs(url.query)
                    start = int(query.get("start", ["0"])[0])
                    count = int(query.get("count", ["125"])[0])
                    if not 0 <= start < dataset.n_frames or not 1 <= count <= 250:
                        raise ValueError()
                except ValueError:
                    self.payload(400, {"error": "Use an in-range start and count between 1 and 250"})
                    return
                self.payload(200, {"frames": dataset.frames(start, count)})
            elif url.path == "/video" and dataset.video:
                self.file(dataset.video, video=True)
            elif url.path in STATIC_FILES:
                self.file(STATIC / STATIC_FILES[url.path])
            else:
                self.payload(404, {"error": "Not found"})

        def file(self, path, video=False):
            size = path.stat().st_size
            try:
                start, end, partial = byte_range(self.headers.get("Range") if video else None, size)
            except ValueError:
                self.send_headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            length = max(0, end - start + 1)
            extra = {"Accept-Ranges": "bytes"} if video else {}
            if partial:
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            mime = "text/javascript" if path.suffix in (".js", ".mjs") else mimetypes.guess_type(path.name)[0]
            self.send_headers(206 if partial else 200, mime or "application/octet-stream", length, extra)
            if self.command != "HEAD":
                with path.open("rb") as handle:
                    handle.seek(start)
                    while length:
                        chunk = handle.read(min(length, 512 * 1024))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        length -= len(chunk)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
