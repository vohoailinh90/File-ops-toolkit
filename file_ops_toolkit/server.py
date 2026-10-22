"""The local web server: a JSON API plus the built UI, bound to this machine only.

The API can write files wherever the user's account can, so it is guarded three ways: it listens on
127.0.0.1 only, every `/api/` call needs the per-launch token the served page carries, and the Host
header must name the loopback address (which stops a DNS-rebinding page from reaching it).
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import string
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .excel import ExcelError, JobRow, read_jobs
from .i18n import Translator
from .report import report_csv
from .runner import LAYOUTS, JobRun, Options, default_destination

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
LOCALES_DIR = Path(__file__).resolve().parent / "locales"
MAX_UPLOAD = 25 * 1024 * 1024
TOKEN_HEADER = "X-Token"


class AppState:
    """What the one local user has loaded and started."""

    def __init__(self, token: str, web_dist: Path = WEB_DIST):
        self.token = token
        self.web_dist = web_dist
        self.file_name = ""
        self.rows: list[JobRow] = []
        self.run: JobRun | None = None
        self.lock = threading.Lock()


def make_server(host: str = "127.0.0.1", port: int = 0, web_dist: Path = WEB_DIST) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the server only binds to this machine")
    state = AppState(os.environ.get("FOT_DEV_TOKEN") or secrets.token_urlsafe(24), web_dist)
    handler = type("Handler", (_Handler,), {"state": state})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.app_state = state  # type: ignore[attr-defined]
    return server


def serve(port: int = 8765, open_browser: bool = True) -> None:
    try:
        server = make_server(port=port)
    except OSError:
        server = make_server(port=0)  # the port is taken: let the OS pick one
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(url, flush=True)
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class _Handler(BaseHTTPRequestHandler):
    state: AppState
    server_version = "FileOpsToolkit"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - signature fixed by the base class
        pass

    # ------------------------------------------------------------ plumbing
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, code: str, **extra: object) -> None:
        self._json({"error": code, **extra}, status)

    def _authorised(self) -> bool:
        return secrets.compare_digest(self.headers.get(TOKEN_HEADER, ""), self.state.token)

    def _body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > limit:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too_large")
            return None
        return self.rfile.read(length)

    # ------------------------------------------------------------ routing
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "bad_host")
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self._static(url.path)
        if not self._authorised():
            return self._error(HTTPStatus.UNAUTHORIZED, "bad_token")
        query = parse_qs(url.query)
        if url.path == "/api/status":
            return self._status(int(query.get("since", ["0"])[0] or 0))
        if url.path == "/api/fs":
            return self._fs(query.get("path", [""])[0])
        if url.path == "/api/report.csv":
            return self._report(query.get("lang", ["en"])[0])
        if url.path == "/api/defaults":
            return self._json({"dest": default_destination()})
        self._error(HTTPStatus.NOT_FOUND, "not_found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "bad_host")
        if not self._authorised():
            return self._error(HTTPStatus.UNAUTHORIZED, "bad_token")
        path = urlparse(self.path).path
        if path == "/api/upload":
            return self._upload()
        if path == "/api/run":
            return self._start()
        if path == "/api/cancel":
            with self.state.lock:
                run = self.state.run
            if run is not None:
                run.cancel()
            return self._json({"ok": True})
        self._error(HTTPStatus.NOT_FOUND, "not_found")

    # ------------------------------------------------------------ static UI
    def _static(self, request_path: str) -> None:
        root = self.state.web_dist.resolve()
        relative = request_path.lstrip("/") or "index.html"
        target = (root / relative).resolve()
        if root not in target.parents and target != root:
            return self._error(HTTPStatus.FORBIDDEN, "forbidden")
        if not target.is_file():
            target = root / "index.html"  # the single page owns every other path
        if not target.is_file():
            return self._send(HTTPStatus.SERVICE_UNAVAILABLE, b"UI not built: run `npm run build` in web/.",
                              "text/plain; charset=utf-8")
        body = target.read_bytes()
        if target.name == "index.html":
            meta = f'<meta name="fot-token" content="{self.state.token}">'
            body = body.replace(b"</head>", meta.encode("ascii") + b"</head>", 1)
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, body, mime if not mime.startswith("text/") else mime + "; charset=utf-8")

    # ------------------------------------------------------------ API
    def _upload(self) -> None:
        body = self._body(MAX_UPLOAD)
        if body is None:
            return
        import io
        try:
            rows = read_jobs(io.BytesIO(body))
        except ExcelError as exc:
            return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code)
        name = os.path.basename(unquote(self.headers.get("X-File-Name", "")).replace("\\", "/")) or "list.xlsx"
        with self.state.lock:
            if self.state.run is not None and self.state.run.state == "running":
                return self._error(HTTPStatus.CONFLICT, "run_in_progress")
            self.state.file_name, self.state.rows, self.state.run = name, rows, None
        self._json({"file": name, "rows": [row.__dict__ for row in rows],
                    "invalid": sum(1 for row in rows if row.error),
                    "folders": len({row.address.casefold() for row in rows if not row.error})})

    def _start(self) -> None:
        body = self._body(64 * 1024)
        if body is None:
            return
        try:
            request = json.loads(body or b"{}")
            dest = str(request["dest"]).strip()
            options = Options(recursive=bool(request.get("recursive", True)), layout=str(request.get("layout", "flat")))
        except (ValueError, KeyError, TypeError):
            return self._error(HTTPStatus.BAD_REQUEST, "bad_request")
        if not dest or options.layout not in LAYOUTS:
            return self._error(HTTPStatus.BAD_REQUEST, "bad_request")
        with self.state.lock:
            if not self.state.rows:
                return self._error(HTTPStatus.CONFLICT, "no_list")
            if self.state.run is not None and self.state.run.state == "running":
                return self._error(HTTPStatus.CONFLICT, "run_in_progress")
            run = JobRun(self.state.rows, dest, options)
            self.state.run = run
        run.start()
        self._json({"ok": True})

    def _status(self, since: int) -> None:
        with self.state.lock:
            run, loaded = self.state.run, bool(self.state.rows)
        if run is None:
            return self._json({"state": "idle", "loaded": loaded, "total": len(self.state.rows), "done": 0,
                               "counts": {}, "copied_files": 0, "next": 0, "results": [], "error": "", "elapsed": 0})
        self._json({**run.snapshot(max(since, 0)), "loaded": loaded})

    def _fs(self, path: str) -> None:
        """Folders only, for the destination picker. Lists the drives when no path is given."""
        if not path:
            return self._json({"path": "", "parent": None, "entries": [{"name": d, "path": d} for d in _roots()]})
        folder = Path(path)
        try:
            entries = sorted((e for e in os.scandir(folder) if _is_dir(e)), key=lambda e: e.name.casefold())
        except OSError:
            return self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "folder_unreadable")
        parent = str(folder.parent) if folder.parent != folder else ""
        return self._json({"path": str(folder), "parent": parent,
                           "entries": [{"name": e.name, "path": e.path} for e in entries
                                       if not e.name.startswith(".")]})

    def _report(self, lang: str) -> None:
        with self.state.lock:
            run = self.state.run
        if run is None:
            return self._error(HTTPStatus.CONFLICT, "no_results")
        tr = Translator.from_dir(LOCALES_DIR, locale=lang if lang in ("ja", "en") else "en")
        self._send(200, report_csv(run.results(), tr), "text/csv; charset=utf-8",
                   {"Content-Disposition": 'attachment; filename="fetch-report.csv"'})


def _is_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def _roots() -> list[str]:
    if os.name == "nt":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
    return ["/", str(Path.home())]
