"""Opaque-box E2E test harness: subprocess CLI runner, HTTPS MockScholarlyServer,
test-only sitecustomize HTTPS router, PdfFactory (fitz + PIL), and WorkspaceFactory.
"""
from __future__ import annotations

import csv
import hashlib
import http.server
import io
import json
import os
import shutil
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import fitz
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "research-scientist"
SCRIPTS_DIR = SKILL_DIR / "scripts"
MODULES_DIR = SKILL_DIR / "modules"
REFS_DIR = SKILL_DIR / "references"
EVAL_FIXTURES_DIR = REPO_ROOT / "evaluation" / "fixtures"
T123_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "t123"
RADAR_SCRIPT = MODULES_DIR / "researchradar" / "problem-statement-finder" / "scripts" / "radar.py"


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    json_out: Any
    command: list[str]


def _try_parse_json(text: str) -> Any:
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        return None


def run_cli(
    script_path: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    stdin_text: str | None = None,
    timeout: int = 30,
) -> CliResult:
    """Execute a skill/module Python CLI script in a fresh subprocess."""
    merged_env = os.environ.copy()
    merged_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        merged_env.update(env)
    cmd = [sys.executable, str(script_path), *[str(a) for a in args]]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=merged_env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CliResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        json_out=_try_parse_json(proc.stdout),
        command=cmd,
    )


_SITECUSTOMIZE_CODE = '''"""Test-only HTTPS/HTTP router redirecting external hosts to MockScholarlyServer and blocking unmocked outbound sockets."""
import os
from urllib.parse import urlparse

_MOCK_ORIGIN = os.environ.get("E2E_MOCK_ORIGIN", "").rstrip("/")
_BLOCK_UNMOCKED = os.environ.get("RS_MOCK_BLOCK_UNMOCKED", "1" if _MOCK_ORIGIN else "0") == "1"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _normalize_host(host):
    s = (host or "").strip()
    if s.startswith("["):
        end = s.find("]")
        if end != -1:
            s = s[1:end]
    elif s.count(":") == 1:
        s = s.split(":", 1)[0]
    return s.lower()


def _check_host_allowed(host):
    clean = _normalize_host(host)
    if not clean or clean in _LOCAL_HOSTS:
        return
    if _BLOCK_UNMOCKED:
        raise OSError(f"offline_mode_blocked_unmocked_host: {clean}")


def _rewrite_url(url):
    if not _MOCK_ORIGIN or not isinstance(url, str):
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return url
    host = (parsed.hostname or "").lower()
    if not host or host in _LOCAL_HOSTS:
        return url
    if parsed.path.startswith("/__host__/"):
        return url
    rest = parsed.path or "/"
    if parsed.query:
        rest = f"{rest}?{parsed.query}"
    return f"{_MOCK_ORIGIN}/__host__/{host}{rest}"


if _MOCK_ORIGIN or _BLOCK_UNMOCKED:
    import http.client
    import socket

    _orig_http_connect = http.client.HTTPConnection.connect
    _orig_https_connect = http.client.HTTPSConnection.connect
    _orig_socket_create_connection = socket.create_connection
    _orig_socket_connect = socket.socket.connect
    _orig_socket_connect_ex = socket.socket.connect_ex

    def _check_socket_address(address):
        if isinstance(address, tuple) and address:
            host = address[0]
            if isinstance(host, bytes):
                host = host.decode("ascii", "ignore")
            if isinstance(host, str):
                _check_host_allowed(host)

    def _patched_http_connect(self):
        _check_host_allowed(getattr(self, "host", ""))
        return _orig_http_connect(self)

    def _patched_https_connect(self):
        _check_host_allowed(getattr(self, "host", ""))
        return _orig_https_connect(self)

    def _patched_create_connection(address, *args, **kwargs):
        host = address[0] if isinstance(address, (tuple, list)) and address else ""
        _check_host_allowed(host)
        return _orig_socket_create_connection(address, *args, **kwargs)

    def _patched_socket_connect(self, address):
        _check_socket_address(address)
        return _orig_socket_connect(self, address)

    def _patched_socket_connect_ex(self, address):
        _check_socket_address(address)
        return _orig_socket_connect_ex(self, address)

    http.client.HTTPConnection.connect = _patched_http_connect
    http.client.HTTPSConnection.connect = _patched_https_connect
    socket.create_connection = _patched_create_connection
    socket.socket.connect = _patched_socket_connect
    socket.socket.connect_ex = _patched_socket_connect_ex

    try:
        import urllib3.util.connection

        _orig_urllib3_create_connection = urllib3.util.connection.create_connection

        def _patched_urllib3_create_connection(address, *args, **kwargs):
            host = address[0] if isinstance(address, (tuple, list)) and address else ""
            _check_host_allowed(host)
            return _orig_urllib3_create_connection(address, *args, **kwargs)

        urllib3.util.connection.create_connection = _patched_urllib3_create_connection
    except Exception:
        pass


if _MOCK_ORIGIN:
    import urllib.request

    _orig_open = urllib.request.OpenerDirector.open

    def _patched_open(self, fullurl, data=None, timeout=None):
        if isinstance(fullurl, str):
            fullurl = _rewrite_url(fullurl)
        elif isinstance(fullurl, urllib.request.Request):
            orig_url = fullurl.full_url
            new_url = _rewrite_url(orig_url)
            if new_url != orig_url:
                headers = dict(fullurl.header_items())
                cloned = urllib.request.Request(
                    new_url,
                    data=fullurl.data,
                    headers=headers,
                    origin_req_host=fullurl.origin_req_host,
                    unverifiable=fullurl.unverifiable,
                    method=fullurl.get_method(),
                )
                for k, v in fullurl.unredirected_hdrs.items():
                    cloned.add_unredirected_header(k, v)
                fullurl = cloned
        if timeout is None:
            return _orig_open(self, fullurl, data)
        return _orig_open(self, fullurl, data, timeout)

    urllib.request.OpenerDirector.open = _patched_open

    try:
        import requests.adapters

        _orig_send = requests.adapters.HTTPAdapter.send

        def _patched_send(self, request, *args, **kwargs):
            if getattr(request, "url", None):
                request.url = _rewrite_url(request.url)
            return _orig_send(self, request, *args, **kwargs)

        requests.adapters.HTTPAdapter.send = _patched_send
    except Exception:
        pass
'''


class _ThreadingHTTPSServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MockScholarlyServer:
    """Ephemeral TLS-enabled local HTTP server with programmable routes."""

    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="e2e_mock_https_")
        self.tmp_path = Path(self._tmpdir.name)
        self.cert_path = self.tmp_path / "cert.pem"
        self.key_path = self.tmp_path / "key.pem"
        self.sitecustomize_dir = self.tmp_path / "sitecustomize_pkg"
        self.sitecustomize_dir.mkdir(parents=True, exist_ok=True)
        (self.sitecustomize_dir / "sitecustomize.py").write_text(_SITECUSTOMIZE_CODE, encoding="utf-8")

        self._routes: list[tuple[str | None, str, Callable[[dict[str, Any]], tuple[int, str, bytes | str, dict[str, str]]]]] = []
        self._sequences: dict[tuple[str | None, str], list[tuple[int, str, bytes | str, dict[str, str]]]] = {}
        self._seq_counts: dict[tuple[str | None, str], int] = {}
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._httpd: _ThreadingHTTPSServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def _generate_cert(self) -> None:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(self.key_path),
                "-out",
                str(self.cert_path),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def start(self) -> None:
        self._generate_cert()
        server_ref = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _handle(self, method: str) -> None:
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                host_key: str | None = None
                if path.startswith("/__host__/"):
                    remainder = path[len("/__host__/") :]
                    if "/" in remainder:
                        host_key, sub_path = remainder.split("/", 1)
                        path = "/" + sub_path
                    else:
                        host_key = remainder
                        path = "/"
                else:
                    host_header = self.headers.get("Host", "")
                    host_key = host_header.split(":", 1)[0].lower() if host_header else None

                length = int(self.headers.get("Content-Length", "0") or "0")
                raw_body = self.rfile.read(length) if length > 0 else b""
                req_ctx = {
                    "method": method,
                    "host": host_key,
                    "path": path,
                    "query": parsed.query,
                    "params": parse_qs(parsed.query),
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": raw_body,
                }
                status, ctype, resp_body, extra_headers = server_ref._dispatch(req_ctx)
                body_bytes = resp_body.encode("utf-8") if isinstance(resp_body, str) else resp_body
                self.send_response(status)
                if ctype:
                    self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header("Connection", "close")
                for hk, hv in (extra_headers or {}).items():
                    self.send_header(hk, hv)
                self.end_headers()
                if method != "HEAD" and body_bytes:
                    self.wfile.write(body_bytes)

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def do_HEAD(self) -> None:
                self._handle("HEAD")

        httpd = _ThreadingHTTPSServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(self.cert_path), keyfile=str(self.key_path))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._tmpdir.cleanup()

    def reset(self) -> None:
        with self._lock:
            self._routes.clear()
            self._sequences.clear()
            self._seq_counts.clear()
            self.requests.clear()

    def url(self, path: str = "/", host: str = "localhost") -> str:
        clean_path = path if path.startswith("/") else "/" + path
        return f"https://{host}:{self.port}{clean_path}"

    def add_route(
        self,
        path_prefix: str,
        responder: tuple[int, str, bytes | str] | tuple[int, str, bytes | str, dict[str, str]] | Callable[[dict[str, Any]], Any],
        *,
        host: str | None = None,
    ) -> None:
        def _wrap(ctx: dict[str, Any]) -> tuple[int, str, bytes | str, dict[str, str]]:
            out = responder(ctx) if callable(responder) else responder
            if len(out) == 3:
                st, ct, bd = out
                return int(st), ct, bd, {}
            st, ct, bd, hd = out
            return int(st), ct, bd, dict(hd)

        with self._lock:
            self._routes.append((host.lower() if host else None, path_prefix, _wrap))

    def add_json(self, path_prefix: str, payload: Any, *, status: int = 200, host: str | None = None, headers: dict[str, str] | None = None) -> None:
        self.add_route(path_prefix, (status, "application/json; charset=utf-8", json.dumps(payload), headers or {}), host=host)

    def add_sequence(
        self,
        path_prefix: str,
        responses: list[tuple[int, str, bytes | str] | tuple[int, str, bytes | str, dict[str, str]]],
        *,
        host: str | None = None,
    ) -> None:
        key = (host.lower() if host else None, path_prefix)
        normed: list[tuple[int, str, bytes | str, dict[str, str]]] = []
        for item in responses:
            if len(item) == 3:
                normed.append((int(item[0]), item[1], item[2], {}))
            else:
                normed.append((int(item[0]), item[1], item[2], dict(item[3])))
        with self._lock:
            self._sequences[key] = normed
            self._seq_counts[key] = 0

    def _dispatch(self, req_ctx: dict[str, Any]) -> tuple[int, str, bytes | str, dict[str, str]]:
        with self._lock:
            self.requests.append(req_ctx)
            host = (req_ctx.get("host") or "").lower()
            path = req_ctx["path"]

            # Exact or prefix match in sequences first (most specific path first)
            for (seq_host, seq_prefix), seq_list in sorted(
                self._sequences.items(), key=lambda kv: (kv[0][0] is not None, len(kv[0][1])), reverse=True
            ):
                if seq_host is not None and seq_host != host:
                    continue
                if path == seq_prefix or path.startswith(seq_prefix):
                    idx = self._seq_counts[(seq_host, seq_prefix)]
                    self._seq_counts[(seq_host, seq_prefix)] = idx + 1
                    chosen = seq_list[min(idx, len(seq_list) - 1)]
                    return chosen

            # Route match (most specific host + longest prefix first)
            for r_host, r_prefix, fn in sorted(
                self._routes, key=lambda item: (item[0] is not None, len(item[1])), reverse=True
            ):
                if r_host is not None and r_host != host:
                    continue
                if path == r_prefix or path.startswith(r_prefix):
                    return fn(req_ctx)

        return 404, "application/json", json.dumps({"error": "not_found", "host": host, "path": path}), {}

    def env(self, *, use_sitecustomize: bool = True, extra: dict[str, str] | None = None) -> dict[str, str]:
        out = {
            "SSL_CERT_FILE": str(self.cert_path),
            "REQUESTS_CA_BUNDLE": str(self.cert_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if use_sitecustomize:
            out["E2E_MOCK_ORIGIN"] = f"https://127.0.0.1:{self.port}"
            out["RS_MOCK_BLOCK_UNMOCKED"] = "1"
            prev_pp = os.environ.get("PYTHONPATH", "")
            out["PYTHONPATH"] = (
                f"{self.sitecustomize_dir}{os.pathsep}{prev_pp}" if prev_pp else str(self.sitecustomize_dir)
            )
        if extra:
            out.update(extra)
        return out


class PdfFactory:
    """Synthetic PDF builder using PyMuPDF (fitz) and Pillow."""

    @staticmethod
    def make_clean_paper_pdf(
        dest: Path,
        *,
        title: str = "Renormalized Graph Convolution Study",
        quote_p1: str = "We introduce a renormalized adjacency operator that stabilizes multi-layer propagation.",
        quote_p2: str = "Across Cora and Citeseer, two-layer propagation yields 81.5 percent accuracy without depth collapse.",
        equation: str = "H^(l+1) = sigma(D^-0.5 A_tilde D^-0.5 H^(l) W^(l))  (Equation 8)",
    ) -> Path:
        doc = fitz.open()
        p1 = doc.new_page(width=612, height=792)
        p1.insert_text((72, 72), title, fontsize=15)
        p1.insert_text((72, 110), "Section 1. Introduction", fontsize=12)
        p1.insert_text((72, 135), quote_p1, fontsize=10)
        p1.insert_text((72, 165), "Section 3.1 Layer Propagation", fontsize=12)
        p1.insert_text((72, 190), equation, fontsize=10)

        p2 = doc.new_page(width=612, height=792)
        p2.insert_text((72, 72), "Section 4. Experimental Results", fontsize=12)
        p2.insert_text((72, 100), quote_p2, fontsize=10)
        p2.insert_text((72, 130), "Limitations: We did not evaluate heterophilous graphs or graphs above 10M nodes.", fontsize=10)
        doc.save(str(dest))
        doc.close()
        return dest

    @staticmethod
    def make_table_pdf(
        dest: Path,
        headers: list[str] | None = None,
        rows: list[list[str]] | None = None,
    ) -> Path:
        headers = headers or ["Method", "Cora", "Citeseer"]
        rows = rows or [
            ["GCN", "81.5", "70.3"],
            ["MLP", "55.1", "46.5"],
        ]
        all_rows = [headers] + rows
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "Table 1: Node classification accuracy across benchmark datasets.", fontsize=11)

        x0, y0 = 72, 100
        col_w, row_h = 130, 28
        ncols = len(headers)
        nrows = len(all_rows)
        for r_idx, row in enumerate(all_rows):
            for c_idx, cell in enumerate(row):
                rx0 = x0 + c_idx * col_w
                ry0 = y0 + r_idx * row_h
                rect = fitz.Rect(rx0, ry0, rx0 + col_w, ry0 + row_h)
                page.draw_rect(rect, color=(0, 0, 0), width=1.0)
                page.insert_text((rx0 + 8, ry0 + 18), str(cell), fontsize=10)
        # Ensure outer border is crisp for pdfplumber line detection
        page.draw_rect(fitz.Rect(x0, y0, x0 + ncols * col_w, y0 + nrows * row_h), color=(0, 0, 0), width=1.2)
        doc.save(str(dest))
        doc.close()
        return dest

    @staticmethod
    def make_scanned_image_pdf(
        dest: Path,
        text_lines: list[str] | None = None,
    ) -> Path:
        text_lines = text_lines or [
            "Renormalized adjacency reduces degree variance.",
            "Validation accuracy reaches 81.5 percent on Cora.",
        ]
        img = Image.new("RGB", (2000, 700), color="white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(size=42)
        except TypeError:
            font = ImageFont.load_default()
        y = 100
        for line in text_lines:
            draw.text((80, y), line, fill="black", font=font)
            y += 110
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(40, 80, 572, 280), stream=buf.getvalue())
        doc.save(str(dest))
        doc.close()
        return dest

    @staticmethod
    def make_garbled_low_entropy_pdf(dest: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        junk = "aaa   \x01\x01\x01   aaa   \x02\x02\x02   " * 20
        y = 72
        for i in range(0, len(junk), 80):
            page.insert_text((50, y), junk[i : i + 80], fontsize=9)
            y += 14
        doc.save(str(dest))
        doc.close()
        return dest

    @staticmethod
    def make_encrypted_pdf(dest: Path, user_pw: str = "secret", owner_pw: str = "owner") -> Path:
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "Confidential restricted manuscript text.", fontsize=12)
        doc.save(
            str(dest),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=user_pw,
            owner_pw=owner_pw,
        )
        doc.close()
        return dest


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso_utc(days_offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_offset)).isoformat()


class WorkspaceFactory:
    """Builders for isolated temp workspaces used by Tiers 1–3 tests."""

    @staticmethod
    def copy_skill_tree(dest_root: Path) -> Path:
        target = dest_root / "research-scientist"
        shutil.copytree(SKILL_DIR, target)
        return target

    @staticmethod
    def make_ml_repo(
        dest: Path,
        *,
        leaky_preprocessing: bool = False,
        overlapping_splits: bool = False,
        missing_baseline: bool = False,
        cherry_picked_seeds: bool = False,
        metric_direction_bug: bool = False,
        hpo_mismatch: bool = False,
    ) -> dict[str, Path]:
        dest.mkdir(parents=True, exist_ok=True)
        train_py = dest / "train.py"
        if leaky_preprocessing:
            train_py.write_text(
                "from sklearn.preprocessing import StandardScaler\n"
                "from sklearn.model_selection import train_test_split\n"
                "def run(X, y):\n"
                "    scaler = StandardScaler()\n"
                "    X_scaled = scaler.fit_transform(X)\n"
                "    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)\n"
                "    return X_train, X_test\n",
                encoding="utf-8",
            )
        elif metric_direction_bug:
            train_py.write_text(
                "def evaluate_loss(y_true, y_pred):\n"
                "    # Bug: higher loss treated as better under accuracy metric\n"
                "    return sum(abs(a - b) for a, b in zip(y_true, y_pred)) / len(y_true)\n",
                encoding="utf-8",
            )
        elif hpo_mismatch:
            train_py.write_text(
                "def run_benchmark(X_train, y_train, X_test, y_test):\n"
                "    baseline_cfg = {'lr': 0.01}  # default untuned, 0 HPO trials\n"
                "    for trial in range(50):\n"
                "        candidate_score = tune_on_split(X_test, y_test, trial)\n"
                "    return baseline_cfg, candidate_score\n",
                encoding="utf-8",
            )
        else:
            train_py.write_text(
                "from sklearn.preprocessing import StandardScaler\n"
                "from sklearn.model_selection import train_test_split\n"
                "def run(X, y):\n"
                "    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)\n"
                "    scaler = StandardScaler()\n"
                "    X_train_s = scaler.fit_transform(X_train)\n"
                "    X_test_s = scaler.transform(X_test)\n"
                "    return X_train_s, X_test_s\n",
                encoding="utf-8",
            )

        splits_csv = dest / "splits.csv"
        rows = [
            ["sample_id", "split"],
            ["S001", "train"],
            ["S002", "train"],
            ["S003", "val"],
            ["S004", "test"],
        ]
        if overlapping_splits:
            rows.append(["S001", "test"])
        with splits_csv.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)

        metrics_json = dest / "metrics.json"
        if missing_baseline:
            metrics_payload = {
                "metric_id": "accuracy",
                "metric_direction": "higher",
                "runs": [
                    {"model": "candidate", "seed": 42, "status": "ok", "value": 0.85},
                ],
            }
        elif cherry_picked_seeds:
            metrics_payload = {
                "metric_id": "accuracy",
                "metric_direction": "higher",
                "runs": [
                    {"model": "baseline", "seed": 1, "status": "ok", "value": 0.78},
                    {"model": "baseline", "seed": 2, "status": "ok", "value": 0.79},
                    {"model": "baseline", "seed": 3, "status": "ok", "value": 0.77},
                    {"model": "baseline", "seed": 4, "status": "ok", "value": 0.78},
                    {"model": "baseline", "seed": 5, "status": "ok", "value": 0.79},
                    {"model": "candidate", "seed": 42, "status": "ok", "value": 0.83},
                    {"model": "candidate", "seed": 43, "status": "failed", "exit_code": 1, "excluded": True},
                    {"model": "candidate", "seed": 44, "status": "failed", "exit_code": 1, "excluded": True},
                ],
            }
        elif metric_direction_bug:
            metrics_payload = {
                "metric_id": "cross_entropy_loss",
                "metric_direction": "higher",
                "averaging_mismatch": {"baseline": "micro", "candidate": "macro"},
                "runs": [
                    {"model": "baseline", "seed": 1, "status": "ok", "value": 0.41},
                    {"model": "candidate", "seed": 1, "status": "ok", "value": 0.55},
                ],
            }
        elif hpo_mismatch:
            metrics_payload = {
                "metric_id": "accuracy",
                "metric_direction": "higher",
                "hpo_trials": {"baseline": 0, "candidate": 50},
                "tuning_split": {"baseline": "none", "candidate": "test"},
                "runs": [
                    {"model": "baseline", "seed": 1, "status": "ok", "value": 0.70},
                    {"model": "candidate", "seed": 1, "status": "ok", "value": 0.84},
                ],
            }
        else:
            metrics_payload = {
                "metric_id": "accuracy",
                "metric_direction": "higher",
                "hpo_trials": {"baseline": 10, "candidate": 10},
                "sanity_controls": ["dummy_majority", "shuffled_label"],
                "runs": [
                    {"model": "dummy_majority", "seed": 1, "status": "ok", "value": 0.50},
                    {"model": "shuffled_label", "seed": 1, "status": "ok", "value": 0.49},
                    {"model": "baseline", "seed": 1, "status": "ok", "value": 0.78},
                    {"model": "baseline", "seed": 2, "status": "ok", "value": 0.79},
                    {"model": "baseline", "seed": 3, "status": "ok", "value": 0.78},
                    {"model": "candidate", "seed": 1, "status": "ok", "value": 0.82},
                    {"model": "candidate", "seed": 2, "status": "ok", "value": 0.83},
                    {"model": "candidate", "seed": 3, "status": "ok", "value": 0.82},
                ],
            }
        metrics_json.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")
        return {
            "code_dir": dest,
            "train_py": train_py,
            "splits_csv": splits_csv,
            "metrics_json": metrics_json,
        }

    @staticmethod
    def make_verified_experiment_workspace(
        dest: Path,
        *,
        tamper_result_value: bool = False,
        tamper_artifact_bytes: bool = False,
        backdated_protocol: bool = False,
        missing_artifact_file: bool = False,
    ) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        split_file = dest / "split_manifest.json"
        split_file.write_text(json.dumps({"train": ["S1", "S2"], "test": ["S3", "S4"]}), encoding="utf-8")
        metric_file = dest / "eval_metric.py"
        metric_file.write_text("def accuracy(y, p): return sum(a==b for a,b in zip(y,p))/len(y)\n", encoding="utf-8")
        base_out = dest / "baseline_run.json"
        base_out.write_text(json.dumps({"accuracy": 0.5}), encoding="utf-8")
        cand_out = dest / "candidate_run.json"
        cand_out.write_text(json.dumps({"accuracy": 0.6}), encoding="utf-8")
        base_log = dest / "baseline_run.log"
        base_log.write_text("INFO run=baseline-1 exit_code=0 accuracy=0.5\n", encoding="utf-8")
        cand_log = dest / "candidate_run.log"
        cand_log.write_text("INFO run=candidate-1 exit_code=0 accuracy=0.6\n", encoding="utf-8")

        split_sha = sha256_file(split_file)
        metric_sha = sha256_file(metric_file)
        base_sha = sha256_file(base_out)
        cand_sha = sha256_file(cand_out)

        if tamper_artifact_bytes:
            cand_out.write_text(json.dumps({"accuracy": 0.6, "tampered": True}), encoding="utf-8")

        if missing_artifact_file:
            cand_artifact_path = "results/nonexistent.json"
        else:
            cand_artifact_path = "candidate_run.json"

        frozen_ts = "2026-01-02T00:00:00Z" if backdated_protocol else "2026-01-01T00:00:00Z"
        base_start = "2026-01-01T12:00:00Z" if backdated_protocol else "2026-01-02T00:00:00Z"

        manifest = {
            "question_id": "RQ-E2E-1",
            "protocol_version": "v1",
            "protocol_frozen_at_utc": frozen_ts,
            "runs": [
                {
                    "run_id": "baseline-1",
                    "role": "baseline",
                    "protocol_version": "v1",
                    "code_commit": "abc1234",
                    "data_version": "v1",
                    "split_manifest_path": "split_manifest.json",
                    "split_manifest_sha256": split_sha,
                    "metric_id": "accuracy",
                    "metric_script_path": "eval_metric.py",
                    "metric_script_sha256": metric_sha,
                    "command": "python3 train.py --role baseline",
                    "started_at_utc": base_start,
                    "ended_at_utc": "2026-01-02T01:00:00Z",
                    "exit_code": 0,
                    "log_path": "baseline_run.log",
                    "result_artifact_path": "baseline_run.json",
                    "result_artifact_sha256": base_sha,
                    "result_value": 0.5,
                    "deviations": [],
                    "decision_timing": "prespecified",
                },
                {
                    "run_id": "candidate-1",
                    "role": "candidate",
                    "protocol_version": "v1",
                    "code_commit": "def5678",
                    "data_version": "v1",
                    "split_manifest_path": "split_manifest.json",
                    "split_manifest_sha256": split_sha,
                    "metric_id": "accuracy",
                    "metric_script_path": "eval_metric.py",
                    "metric_script_sha256": metric_sha,
                    "command": "python3 train.py --role candidate",
                    "started_at_utc": "2026-01-02T02:00:00Z",
                    "ended_at_utc": "2026-01-02T03:00:00Z",
                    "exit_code": 0,
                    "log_path": "candidate_run.log",
                    "result_artifact_path": cand_artifact_path,
                    "result_artifact_sha256": cand_sha,
                    "result_value": 0.72 if tamper_result_value else 0.6,
                    "deviations": [],
                    "decision_timing": "prespecified",
                },
            ],
        }
        manifest_path = dest / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path
