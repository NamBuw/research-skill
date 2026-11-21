"""Opaque-box E2E tests for Feature F20: Token-Frugal / Context-Efficiency Architecture.

Covers:
- Tier 1 (`T1-J1`..`T1-J5`, 5 tests):
  - `T1-J1`: `SKILL.md` YAML frontmatter word/token budget check.
  - `T1-J2`: `SKILL.md` 3-layer progressive disclosure & lean body budget check.
  - `T1-J3`: Core retrieval/extraction scripts (`search_papers.py`,
    `search_campaign.py`, `extract_pdf_blocks.py`, `local_evidence.py`,
    `capture_venue_sources.py`) support `--compact` with bounded stdout + disk pointer.
  - `T1-J4`: Analysis/gate scripts (`gap_pipeline.py`, `storm_explorer.py`,
    `humanizer_lint.py`, `check_engineering_diagnostics.py`, `report_latex_pdf.py`)
    support `--compact` / bounded structured JSON output with zero filler.
  - `T1-J5`: `claim_audit.py` verifies progressive disclosure references and
    `--compact` flags exist consistently without drift.
- Tier 2 (`T2-J1`..`T2-J3`, 3 boundary/corner tests):
  - `T2-J1`: Large PDF (>=20 pages) and large corpus (>=50 passages) under
    `--compact` keep stdout strictly `< 4096` bytes while full output lives on disk.
  - `T2-J2`: Multi-source search payload under `--compact` preserves exact verdict,
    counts, seed check status, disk artifact path, and failed/rate-limited sources.
  - `T2-J3`: `SKILL.md` does NOT inline multi-hundred-line schemas, JSON examples,
    or the Humanizer 26-pattern full catalog (kept in `references/` / `modules/`).
- Tier 3 (`T3-15`, 1 cross-feature chain):
  - `T3-15`: `extract_pdf_blocks.py --out ... --compact` ->
    `local_evidence.py --inputs <artifact_path> --compact` ->
    `report_latex_pdf.py --strict --json`.

Completely self-contained by design (no imports from `helpers.py` or `real_cases_runner.py`).
"""
from __future__ import annotations

import csv
import http.server
import json
import os
import re
import shutil
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import fitz

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "research-scientist"
SCRIPTS_DIR = SKILL_DIR / "scripts"
REFS_DIR = SKILL_DIR / "references"
MODULES_DIR = SKILL_DIR / "modules"

MAX_COMPACT_STDOUT_BYTES = 4096

CONVERSATIONAL_FILLER_PHRASES = (
    "i hope this helps",
    "here is your",
    "here's your",
    "certainly!",
    "sure thing",
    "great job",
    "happy to help",
    "as an ai language model",
    "let me know if you need",
)

_SITECUSTOMIZE_CODE = '''"""Self-contained test-only HTTP/HTTPS router redirecting mocked hosts and failing closed on unmocked hosts."""
import http.client
import os
import socket

_MOCK_PORT = int(os.environ.get("F20_MOCK_PORT", "0") or "0")
_MOCK_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("F20_MOCK_HOSTS", "").split(",")
    if h.strip()
}
_BLOCK_UNMOCKED = os.environ.get("F20_BLOCK_UNMOCKED", "1") == "1"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _normalize_host(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
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


if _MOCK_PORT or _BLOCK_UNMOCKED:
    _orig_https_connect = http.client.HTTPSConnection.connect
    _orig_http_connect = http.client.HTTPConnection.connect
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

    def _patched_https_connect(self):
        host = _normalize_host(getattr(self, "host", ""))
        if host in _LOCAL_HOSTS:
            return _orig_https_connect(self)
        if _MOCK_PORT and host in _MOCK_HOSTS:
            self.sock = _orig_socket_create_connection(
                ("127.0.0.1", _MOCK_PORT), self.timeout, self.source_address
            )
            self.sock = self._context.wrap_socket(self.sock, server_hostname="127.0.0.1")
            return
        raise OSError(f"offline_mode_blocked_unmocked_host: {host}")

    def _patched_http_connect(self):
        _check_host_allowed(getattr(self, "host", ""))
        return _orig_http_connect(self)

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

    http.client.HTTPSConnection.connect = _patched_https_connect
    http.client.HTTPConnection.connect = _patched_http_connect
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
'''


class _ThreadingHTTPSServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _LocalMockServer:
    """Self-contained ephemeral TLS-enabled local HTTP server."""

    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="f20_mock_https_")
        self.tmp_path = Path(self._tmpdir.name)
        self.cert_path = self.tmp_path / "cert.pem"
        self.key_path = self.tmp_path / "key.pem"
        self.sitecustomize_dir = self.tmp_path / "sitecustomize_pkg"
        self.sitecustomize_dir.mkdir(parents=True, exist_ok=True)
        (self.sitecustomize_dir / "sitecustomize.py").write_text(
            _SITECUSTOMIZE_CODE, encoding="utf-8"
        )
        self._routes: list[tuple[str | None, str, tuple[int, str, str | bytes, dict[str, str]]]] = []
        self._lock = threading.Lock()
        self._httpd: _ThreadingHTTPSServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    def __enter__(self) -> "_LocalMockServer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()

    def add_route(
        self,
        path_prefix: str,
        status: int,
        ctype: str,
        body: str | bytes,
        *,
        host: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._routes.append(
            (host.lower() if host else None, path_prefix, (status, ctype, body, headers or {}))
        )

    def _dispatch(self, host: str | None, path: str) -> tuple[int, str, bytes, dict[str, str]]:
        best: tuple[int, tuple[int, str, str | bytes, dict[str, str]]] | None = None
        for route_host, prefix, resp in self._routes:
            if route_host is not None and route_host != (host or "").lower():
                continue
            if path == prefix or path.startswith(prefix):
                score = len(prefix) + (1000 if route_host is not None else 0)
                if best is None or score > best[0]:
                    best = (score, resp)
        if best is None:
            return 404, "application/json", b'{"error":"not_found"}', {}
        status, ctype, body, hdrs = best[1]
        raw = body.encode("utf-8") if isinstance(body, str) else body
        return status, ctype, raw, hdrs

    def start(self) -> None:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(self.key_path),
                "-out", str(self.cert_path),
                "-days", "1", "-subj", "/CN=127.0.0.1",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        server_ref = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _handle(self) -> None:
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                host_key: str | None = None
                if path.startswith("/__host__/"):
                    rest = path[len("/__host__/") :]
                    if "/" in rest:
                        host_key, sub = rest.split("/", 1)
                        path = "/" + sub
                    else:
                        host_key = rest
                        path = "/"
                else:
                    host_hdr = self.headers.get("Host", "")
                    host_key = host_hdr.split(":", 1)[0].lower() if host_hdr else None
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length > 0:
                    self.rfile.read(length)
                status, ctype, raw, extra = server_ref._dispatch(host_key, path)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                for k, v in extra.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                self._handle()

            def do_POST(self) -> None:  # noqa: N802
                self._handle()

        httpd = _ThreadingHTTPSServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(self.cert_path), keyfile=str(self.key_path))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._tmpdir.cleanup()

    def url(self, path: str = "/") -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"https://127.0.0.1:{self.port}{path}"

    def env(self, *, use_sitecustomize: bool = True) -> dict[str, str]:
        env_map: dict[str, str] = {
            "SSL_CERT_FILE": str(self.cert_path),
            "REQUESTS_CA_BUNDLE": str(self.cert_path),
        }
        if use_sitecustomize:
            mock_hosts = sorted({h for h, _, _ in self._routes if h})
            env_map["F20_MOCK_PORT"] = str(self.port)
            env_map["F20_MOCK_HOSTS"] = ",".join(mock_hosts)
            env_map["F20_BLOCK_UNMOCKED"] = "1"
            prev = os.environ.get("PYTHONPATH", "")
            env_map["PYTHONPATH"] = (
                f"{self.sitecustomize_dir}{os.pathsep}{prev}"
                if prev
                else str(self.sitecustomize_dir)
            )
        return env_map


def _run_cli(
    script_path: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    assert script_path.is_file(), f"Missing expected script: {script_path}"
    merged = os.environ.copy()
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        merged.update(env)
    cmd = [sys.executable, str(script_path), *[str(a) for a in args]]
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        env=merged,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_stdout_json(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    raw = (proc.stdout or "").strip()
    assert raw, f"Expected JSON stdout, got empty stdout (stderr={proc.stderr!r})"
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise AssertionError(
            f"Stdout is not valid JSON: {exc}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        ) from exc
    assert isinstance(parsed, dict), f"Expected JSON dict on stdout, got {type(parsed).__name__}"
    return parsed


def _iter_strings(obj: Any) -> list[str]:
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(_iter_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_iter_strings(v))
    return found


def _assert_artifact_pointer(summary_json: dict[str, Any], expected_path: Path | None = None) -> Path:
    """Verify compact JSON points to an existing full-payload artifact on disk."""
    strings = _iter_strings(summary_json)
    if expected_path is not None:
        resolved = expected_path.resolve()
        assert expected_path.is_file(), f"Expected disk artifact missing at {expected_path}"
        assert any(
            (s == str(expected_path) or s == str(resolved) or expected_path.name in s)
            for s in strings
        ), f"Compact stdout JSON missing artifact path pointer to {expected_path}: {summary_json}"
        return expected_path

    for s in strings:
        if "/" in s or s.endswith(".json"):
            candidate = Path(s)
            if candidate.is_file():
                return candidate
    raise AssertionError(
        f"Compact stdout JSON did not report an existing disk artifact path: {summary_json}"
    )


def _assert_no_filler(text: str) -> None:
    lowered = text.lower()
    for phrase in CONVERSATIONAL_FILLER_PHRASES:
        assert phrase not in lowered, f"Conversational filler {phrase!r} leaked into stdout: {text!r}"


def _split_frontmatter(skill_text: str) -> tuple[str, str]:
    lines = skill_text.splitlines()
    assert lines and lines[0].strip() == "---", "SKILL.md must open with YAML frontmatter '---'"
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    assert end_idx != -1, "SKILL.md YAML frontmatter missing closing '---'"
    fm = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    return fm, body


def _make_multipage_pdf(path: Path, page_texts: list[str]) -> Path:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 545, 780), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _abstract_inverted_index(text: str) -> dict[str, list[int]]:
    inv: dict[str, list[int]] = {}
    for idx, tok in enumerate(text.split()):
        inv.setdefault(tok, []).append(idx)
    return inv


def _make_openalex_work(
    work_id: str,
    title: str,
    abstract_text: str,
    *,
    doi: str | None = None,
    year: int = 2024,
) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/{work_id}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "display_name": title,
        "title": title,
        "publication_year": year,
        "authorships": [{"author": {"display_name": "Author A"}}],
        "abstract_inverted_index": _abstract_inverted_index(abstract_text),
        "primary_location": {"source": {"display_name": "ICML", "type": "conference"}},
    }


def _copy_skill_tree(dst: Path) -> Path:
    shutil.copytree(
        SKILL_DIR,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return dst


# ---------------------------------------------------------------------------
# Tier 1: Core Category-Partition E2E Tests (T1-J1 .. T1-J5)
# ---------------------------------------------------------------------------


def test_t1_j1_skill_md_frontmatter_token_budget() -> None:
    """T1-J1 (F20): SKILL.md YAML frontmatter stays <= 150 words (~120 tokens) without inline prose walls."""
    skill_md = SKILL_DIR / "SKILL.md"
    assert skill_md.is_file(), f"Missing {skill_md}"
    raw = skill_md.read_text(encoding="utf-8")
    fm, _ = _split_frontmatter(raw)

    name_match = re.search(r"^name\s*:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?\s*$", fm, re.M)
    assert name_match is not None and name_match.group(1) == "research-scientist", (
        "Frontmatter must keep canonical name: research-scientist"
    )
    assert re.search(r"^description\s*:\s*\S+", fm, re.M), "Frontmatter missing 'description:' field"
    assert "```" not in fm, "Frontmatter must not contain inline code fences/examples"
    assert len(fm.splitlines()) <= 25, f"Frontmatter too tall ({len(fm.splitlines())} lines)"

    words = re.findall(r"\S+", fm)
    assert len(words) <= 150, (
        f"SKILL.md YAML frontmatter exceeds <= 150 word budget: {len(words)} words"
    )

    fm_lines = fm.splitlines()
    desc_text = ""
    for idx, ln in enumerate(fm_lines):
        m = re.match(r"^description\s*:\s*(.*)$", ln)
        if m:
            val = m.group(1).strip()
            if val in {">", "|", ">-", "|-"} or not val:
                parts = []
                for sub in fm_lines[idx + 1 :]:
                    if sub and not sub[0].isspace():
                        break
                    if sub.strip():
                        parts.append(sub.strip())
                desc_text = " ".join(parts)
            else:
                desc_text = val
            break
    desc_words = re.findall(r"\S+", desc_text)
    assert 8 <= len(desc_words) <= 120, (
        f"Frontmatter description out of tight trigger budget: {len(desc_words)} words"
    )


def test_t1_j2_skill_md_progressive_disclosure_and_lean_body() -> None:
    """T1-J2 (F20): SKILL.md <= 180 lines / <= 1500 words and routes on-demand to existing references/*.md / sub-skills."""
    skill_md = SKILL_DIR / "SKILL.md"
    raw = skill_md.read_text(encoding="utf-8")
    _, body = _split_frontmatter(raw)

    total_lines = len(raw.splitlines())
    total_words = len(re.findall(r"\S+", raw))
    assert total_lines <= 180, f"SKILL.md exceeds 180-line core budget: {total_lines} lines"
    assert total_words <= 1500, f"SKILL.md exceeds 1500-word core budget: {total_words} words"

    # Verify progressive disclosure routing table / selective execution rule
    body_lower = body.lower()
    assert any(
        tok in body_lower
        for tok in (
            "only the stages needed",
            "on-demand",
            "on demand",
            "select the decision path",
            "route",
            "sub-skill",
            "delegate",
        )
    ), "SKILL.md lacks selective/on-demand stage routing instruction"

    ref_matches = re.findall(r"references/([A-Za-z0-9_.-]+\.md)", body)
    distinct_refs = sorted(set(ref_matches))
    for ref_name in distinct_refs:
        ref_path = REFS_DIR / ref_name
        assert ref_path.is_file(), f"SKILL.md references missing file: {ref_path}"

    # F21 hub-and-spoke compatibility: verify any sibling sub-skill routes if referenced
    sibling_links = sorted(set(re.findall(r"\.\./(research-[a-z0-9-]+)/SKILL\.md", body)))
    for sib in sibling_links:
        sib_skill = REPO_ROOT / sib / "SKILL.md"
        assert sib_skill.is_file(), f"SKILL.md references missing sibling sub-skill: {sib_skill}"

    known_f21_siblings = (
        "research-precedent-corpus",
        "research-gap-rq-audit",
        "research-experiment-coding",
        "research-novelty-venue",
        "research-paper-writing",
        "research-user-report",
    )
    mentioned_siblings = [s for s in known_f21_siblings if s in body_lower]
    for sib in mentioned_siblings:
        assert (REPO_ROOT / sib / "SKILL.md").is_file(), (
            f"SKILL.md routes to sibling sub-skill {sib} but {REPO_ROOT / sib / 'SKILL.md'} is missing"
        )

    routed_targets = len(distinct_refs) + len(set(sibling_links) | set(mentioned_siblings))
    assert routed_targets >= 5, (
        f"Expected SKILL.md to route deep workflows to >=5 references/*.md or sibling sub-skills, found {routed_targets}"
    )

    script_matches = re.findall(r"scripts/([A-Za-z0-9_.-]+\.py)", body)
    for script_name in sorted(set(script_matches)):
        assert (SCRIPTS_DIR / script_name).is_file(), (
            f"SKILL.md references missing script: {SCRIPTS_DIR / script_name}"
        )


def test_t1_j3_retrieval_extraction_scripts_support_compact(tmp_path: Path) -> None:
    """T1-J3 (F20): search_papers, search_campaign, extract_pdf_blocks, local_evidence, capture_venue_sources support --compact."""
    target_scripts = (
        "search_papers.py",
        "search_campaign.py",
        "extract_pdf_blocks.py",
        "local_evidence.py",
        "capture_venue_sources.py",
    )
    help_outputs: dict[str, str] = {}
    for name in target_scripts:
        help_proc = _run_cli(SCRIPTS_DIR / name, ["--help"], timeout=15)
        assert help_proc.returncode == 0, f"{name} --help failed: {help_proc.stderr}"
        help_text = help_proc.stdout + help_proc.stderr
        assert "--compact" in help_text, f"{name} missing --compact flag in --help"
        help_outputs[name] = help_text

    # 1. extract_pdf_blocks.py --out ... --compact
    pdf_path = _make_multipage_pdf(
        tmp_path / "sample.pdf",
        [
            "Page 1: Graph Convolutional Networks apply symmetric normalized adjacency propagation.",
            "Page 2: Across Cora, two-layer propagation yields 81.5% accuracy over 10 random seeds.",
        ],
    )
    blocks_out = tmp_path / "blocks.json"
    res_pdf = _run_cli(
        SCRIPTS_DIR / "extract_pdf_blocks.py",
        [str(pdf_path), "--out", str(blocks_out), "--compact"],
    )
    assert res_pdf.returncode == 0, f"extract_pdf_blocks failed: {res_pdf.stderr}"
    assert len(res_pdf.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    pdf_summary = _parse_stdout_json(res_pdf)
    _assert_no_filler(res_pdf.stdout)
    assert "pages" not in pdf_summary, "Compact stdout must not dump raw 'pages' blocks"
    _assert_artifact_pointer(pdf_summary, blocks_out)

    # 2. local_evidence.py --out ... --compact
    study_b = tmp_path / "study_b.json"
    study_b.write_text(
        json.dumps([
            {"type": "paragraph", "page_idx": 0, "bbox": [0, 0, 100, 20],
             "text": "Symmetric normalization prevents activation explosion in two-layer graph models with 81.5% accuracy."}
        ]),
        encoding="utf-8",
    )
    qa_out = tmp_path / "qa.json"
    res_qa = _run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(blocks_out), str(study_b),
            "--question", "What accuracy does two-layer symmetric normalization achieve?",
            "--min-studies", "2", "--min-evidence", "2",
            "--out", str(qa_out), "--compact",
        ],
    )
    assert res_qa.returncode == 0, f"local_evidence failed: {res_qa.stderr}"
    assert len(res_qa.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    qa_summary = _parse_stdout_json(res_qa)
    _assert_no_filler(res_qa.stdout)
    assert qa_summary.get("gate_status") == "ANSWERABLE"
    assert "context_packed" not in qa_summary, "Compact stdout must not dump raw context_packed"
    _assert_artifact_pointer(qa_summary, qa_out)

    # 3-5. search_papers.py, search_campaign.py, capture_venue_sources.py with local HTTPS mock
    long_abstract = " ".join(["Normalized adjacency propagation stabilizes deep graph networks."] * 35)
    oa_payload = {
        "meta": {"count": 1},
        "results": [
            _make_openalex_work(
                "W2519887557",
                "Semi-Supervised Classification with Graph Convolutional Networks",
                long_abstract,
                doi="10.48550/arxiv.1609.02907",
                year=2016,
            )
        ],
    }
    with _LocalMockServer() as srv:
        srv.add_route("/works", 200, "application/json", json.dumps(oa_payload), host="api.openalex.org")
        cfp_url = srv.url("/icml2027/cfp")
        fee_url = srv.url("/icml2027/fees")
        srv.add_route(
            "/icml2027/cfp", 200, "text/html",
            "<html><body><h1>ICML 2027</h1><p>Main Conference Track. Full paper deadline February 4, 2027 AoE.</p>"
            + ("<p>Detailed submission formatting policy paragraph.</p>" * 40)
            + "</body></html>",
        )
        srv.add_route(
            "/icml2027/fees", 200, "text/html",
            "<html><body><p>Author registration fee USD 400.</p></body></html>",
        )

        # 3. search_papers.py --out ... --compact
        sp_out = tmp_path / "search_papers.json"
        res_sp = _run_cli(
            SCRIPTS_DIR / "search_papers.py",
            [
                "graph convolution",
                "--source", "openalex",
                "--known-doi", "10.48550/arxiv.1609.02907",
                "--out", str(sp_out),
                "--compact",
            ],
            env=srv.env(),
        )
        assert res_sp.returncode == 0, f"search_papers failed: {res_sp.stderr}"
        assert len(res_sp.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
        assert long_abstract not in res_sp.stdout, "Compact stdout must not dump full abstract text"
        assert long_abstract[250:400] not in res_sp.stdout, (
            "Compact stdout must not dump abstract tail beyond 200-char preview"
        )
        sp_summary = _parse_stdout_json(res_sp)
        for item in sp_summary.get("top_results", []):
            prev = item.get("abstract_preview")
            if prev is not None:
                assert len(prev) <= 200, f"abstract_preview exceeded 200 chars: {len(prev)}"
        _assert_no_filler(res_sp.stdout)
        _assert_artifact_pointer(sp_summary, sp_out)
        assert long_abstract in sp_out.read_text(encoding="utf-8"), (
            "Full abstract missing from disk artifact"
        )

        # 4. search_campaign.py --out ... --compact
        plan_path = tmp_path / "campaign_plan.json"
        plan_path.write_text(
            json.dumps({
                "question": "Has normalized adjacency GCN been published?",
                "known_seeds": [{"doi": "10.48550/arxiv.1609.02907"}],
                "queries": [
                    {"id": "q1", "family": "direct_problem", "query": "graph convolution", "sources": ["openalex"], "size": 5, "pages": 1}
                ],
            }),
            encoding="utf-8",
        )
        sc_out = tmp_path / "campaign.json"
        res_sc = _run_cli(
            SCRIPTS_DIR / "search_campaign.py",
            [str(plan_path), "--out", str(sc_out), "--compact"],
            env=srv.env(),
        )
        assert res_sc.returncode == 0, f"search_campaign failed: {res_sc.stderr}"
        assert len(res_sc.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
        assert long_abstract not in res_sc.stdout, "Compact stdout must not dump full campaign abstract"
        assert long_abstract[250:400] not in res_sc.stdout, (
            "Compact stdout must not dump campaign abstract tail beyond 200-char preview"
        )
        sc_summary = _parse_stdout_json(res_sc)
        for item in sc_summary.get("top_results", []):
            prev = item.get("abstract_preview")
            if prev is not None:
                assert len(prev) <= 200, f"campaign abstract_preview exceeded 200 chars: {len(prev)}"
        _assert_no_filler(res_sc.stdout)
        _assert_artifact_pointer(sc_summary, sc_out)
        assert long_abstract in sc_out.read_text(encoding="utf-8"), (
            "Full abstract missing from campaign disk artifact"
        )

        # 5. capture_venue_sources.py --compact (with --out if supported)
        now_iso = datetime.now(timezone.utc).isoformat()
        dossier_path = tmp_path / "dossier.json"
        dossier_path.write_text(
            json.dumps({
                "venue": "ICML",
                "edition": "2027",
                "track": "Main Conference Track",
                "official_cfp_url": cfp_url,
                "checked_at": now_iso,
                "user_timezone": "UTC",
                "milestones": {"abstract_registration": None, "full_paper": "2027-02-04T23:59:00 AoE"},
                "currency": "USD",
                "budget_currency": "USD",
                "budget": 500,
                "presentation_mode": "online",
                "evidence_claims": [
                    {"field": "venue", "source_url": cfp_url, "quote": "ICML 2027"},
                    {"field": "fees.author_registration", "source_url": fee_url, "quote": "Author registration fee USD 400"},
                ],
                "fees": [
                    {"category": "author_registration", "name": "Author registration", "mandatory": True, "amount": 400, "source_url": fee_url, "checked_at": now_iso}
                ],
            }),
            encoding="utf-8",
        )
        cap_out = tmp_path / "venue_capture.json"
        cap_args = [str(dossier_path), "--compact"]
        expected_cap: Path | None = None
        if "--out" in help_outputs["capture_venue_sources.py"]:
            cap_args = [str(dossier_path), "--out", str(cap_out), "--compact"]
            expected_cap = cap_out
        res_cap = _run_cli(
            SCRIPTS_DIR / "capture_venue_sources.py",
            cap_args,
            env=srv.env(),
        )
        assert res_cap.returncode == 0, f"capture_venue_sources failed: {res_cap.stderr}"
        assert len(res_cap.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
        assert "Detailed submission formatting policy paragraph." not in res_cap.stdout, (
            "Compact stdout must not dump bulky raw HTML text"
        )
        cap_summary = _parse_stdout_json(res_cap)
        _assert_no_filler(res_cap.stdout)
        artifact_file = _assert_artifact_pointer(cap_summary, expected_cap)
        artifact_data = json.loads(artifact_file.read_text(encoding="utf-8"))
        assert "Detailed submission formatting policy paragraph." in json.dumps(artifact_data)


def test_t1_j4_analysis_gate_scripts_support_compact_and_zero_filler(tmp_path: Path) -> None:
    """T1-J4 (F20): gap_pipeline, storm_explorer, humanizer_lint, check_engineering_diagnostics, report_latex_pdf support --compact."""
    target_scripts = (
        "gap_pipeline.py",
        "storm_explorer.py",
        "humanizer_lint.py",
        "check_engineering_diagnostics.py",
        "report_latex_pdf.py",
    )
    for name in target_scripts:
        script_path = SCRIPTS_DIR / name
        assert script_path.is_file(), f"Missing analysis/gate script: {script_path}"
        help_proc = _run_cli(script_path, ["--help"], timeout=15)
        assert help_proc.returncode == 0, f"{name} --help failed: {help_proc.stderr}"
        assert "--compact" in (help_proc.stdout + help_proc.stderr), (
            f"{name} missing --compact flag in --help"
        )

    # 1. humanizer_lint.py --strict --json --compact
    clean_md = tmp_path / "clean.md"
    clean_md.write_text(
        "# Evaluation\n\nTwo-layer GCN achieves 81.5% accuracy on Cora across 10 seeds.\n",
        encoding="utf-8",
    )
    res_hum = _run_cli(
        SCRIPTS_DIR / "humanizer_lint.py",
        [str(clean_md), "--strict", "--json", "--compact"],
    )
    assert res_hum.returncode == 0, f"humanizer_lint failed: {res_hum.stderr}"
    assert len(res_hum.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    hum_json = _parse_stdout_json(res_hum)
    _assert_no_filler(res_hum.stdout)
    assert hum_json.get("risk_count") == 0

    # 2. report_latex_pdf.py --strict --json --compact
    rep_in = tmp_path / "report_in.json"
    rep_in.write_text(
        json.dumps({
            "schema": "research_scientist_executive_report_v1",
            "report_type": "gap_audit",
            "lang": "en",
            "title": "Split Leakage Audit",
            "verdict": {
                "status": "rejected",
                "summary": "REJECT GAP: Moving scaling inside the training fold drops test NDCG@10 from 0.418 to 0.311 [run_logs/audit.json].",
                "evidence_refs": ["K1"],
            },
            "key_evidence": [
                {
                    "id": "K1",
                    "claim": "Clean split NDCG@10 is 0.311 vs 0.418 leaky.",
                    "value": "0.311",
                    "status": "verified",
                    "locator": "run_logs/audit.json",
                }
            ],
            "flaws_and_risks": [
                {
                    "id": "R1",
                    "severity": "high",
                    "summary": "StandardScaler fit runs before train-test split.",
                    "locator": "run_logs/audit.json",
                }
            ],
            "next_steps": [
                {"step": 1, "action": "Move scaling inside the training fold.", "target": "train_eval.py", "locator": "run_logs/audit.json"}
            ],
            "sources": [{"id": "S1", "title": "Split audit log", "locator": "run_logs/audit.json"}],
        }),
        encoding="utf-8",
    )
    rep_pdf = tmp_path / "report_out.pdf"
    res_rep = _run_cli(
        SCRIPTS_DIR / "report_latex_pdf.py",
        ["--input", str(rep_in), "--out", str(rep_pdf), "--lang", "en", "--strict", "--json", "--compact"],
        timeout=120,
    )
    assert res_rep.returncode == 0, f"report_latex_pdf failed: {res_rep.stderr}\n{res_rep.stdout}"
    assert len(res_rep.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    rep_json = _parse_stdout_json(res_rep)
    _assert_no_filler(res_rep.stdout)
    assert rep_json.get("status") == "ok" and rep_pdf.is_file()

    # 3. storm_explorer.py --compact
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps([
            {"id": "P1", "source": "openalex", "family": "same_problem", "year": 2024, "title": "Rank Fusion Latency", "text": "RRF has low latency in-domain.", "abstract": "Measures latency.", "access": "full_text"},
            {"id": "P2", "source": "arxiv", "family": "cross_setting_analogy", "year": 2025, "title": "OOD Calibration", "text": "Learned fusion miscalibrates under OOD shift.", "abstract": "Measures calibration.", "access": "full_text"},
        ]),
        encoding="utf-8",
    )
    storm_out = tmp_path / "storm.json"
    res_storm = _run_cli(
        SCRIPTS_DIR / "storm_explorer.py",
        ["--topic", "RRF OOD calibration", "--corpus", str(corpus_path), "--out", str(storm_out), "--compact"],
    )
    assert res_storm.returncode == 0, f"storm_explorer failed: {res_storm.stderr}"
    assert len(res_storm.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    storm_summary = _parse_stdout_json(res_storm)
    _assert_no_filler(res_storm.stdout)
    _assert_artifact_pointer(storm_summary, storm_out)

    # 4. gap_pipeline.py --compact
    digests_path = tmp_path / "digests.json"
    digests_path.write_text(
        json.dumps({
            "P1": {"source_id": "P1", "access": "full_text", "digest": "In-domain latency only."},
            "P2": {"source_id": "P2", "access": "full_text", "digest": "Calibration under shift."},
        }),
        encoding="utf-8",
    )
    cands_path = tmp_path / "candidates.json"
    cands_path.write_text(
        json.dumps([
            {
                "id": "G1",
                "claim": "RRF variance under OOD query shift remains uncharacterized.",
                "trigger": "literature_synthesis",
                "cited_ids": ["P1", "P2"],
                "support_ids": ["P1", "P2"],
                "cutoff_year": 2026,
                "sgha_critics_passed": True,
                "engineering_checked": True,
            }
        ]),
        encoding="utf-8",
    )
    gap_out = tmp_path / "gap_out.json"
    res_gap = _run_cli(
        SCRIPTS_DIR / "gap_pipeline.py",
        [
            "--topic", "RRF OOD calibration",
            "--corpus", str(corpus_path),
            "--digests", str(digests_path),
            "--candidates", str(cands_path),
            "--out", str(gap_out),
            "--compact",
        ],
    )
    assert res_gap.returncode == 0, f"gap_pipeline failed: {res_gap.stderr}"
    assert len(res_gap.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    gap_summary = _parse_stdout_json(res_gap)
    _assert_no_filler(res_gap.stdout)
    _assert_artifact_pointer(gap_summary, gap_out)

    # 5. check_engineering_diagnostics.py --compact
    code_dir = tmp_path / "ml_repo"
    code_dir.mkdir()
    (code_dir / "train.py").write_text(
        "from sklearn.model_selection import train_test_split\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "def run(X, y):\n"
        "    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)\n"
        "    sc = StandardScaler()\n"
        "    X_tr = sc.fit_transform(X_tr)\n"
        "    X_te = sc.transform(X_te)\n"
        "    return X_tr, X_te\n",
        encoding="utf-8",
    )
    splits_csv = tmp_path / "splits.csv"
    with splits_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerows([["sample_id", "split"], ["S1", "train"], ["S2", "train"], ["S3", "val"], ["S4", "test"]])
    metrics_json = tmp_path / "metrics.json"
    metrics_json.write_text(
        json.dumps({
            "baseline": {"name": "ItemKNN", "ndcg10": 0.314, "seeds": [1, 2, 3]},
            "sanity_controls": {"shuffled_label_ndcg10": 0.041, "constant_baseline_ndcg10": 0.050},
            "candidate": {"name": "Linear", "ndcg10": 0.319, "seeds": [1, 2, 3]},
        }),
        encoding="utf-8",
    )
    res_eng = _run_cli(
        SCRIPTS_DIR / "check_engineering_diagnostics.py",
        ["--code-dir", str(code_dir), "--splits", str(splits_csv), "--metrics", str(metrics_json), "--compact"],
    )
    assert res_eng.returncode == 0, f"check_engineering_diagnostics failed: {res_eng.stderr}"
    assert len(res_eng.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    eng_summary = _parse_stdout_json(res_eng)
    _assert_no_filler(res_eng.stdout)
    assert eng_summary.get("verdict") == "PASS"


def test_t1_j5_claim_audit_verifies_progressive_disclosure_and_compact_flags(tmp_path: Path) -> None:
    """T1-J5 (F20): claim_audit.py verifies SKILL.md progressive disclosure refs and --compact flags without drift."""
    claim_audit_script = SCRIPTS_DIR / "claim_audit.py"
    res_ok = _run_cli(claim_audit_script, ["--root", str(SKILL_DIR), "--json"])
    assert res_ok.returncode == 0, f"claim_audit failed on live skill tree:\n{res_ok.stdout}\n{res_ok.stderr}"
    ok_report = _parse_stdout_json(res_ok)
    assert ok_report["status"] == "passed"
    assert ok_report["finding_count"] == 0

    # Docs (SKILL.md or references/*.md) should document --compact for F20 audit coverage
    docs_blob = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8") + "\n" + "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(REFS_DIR.glob("*.md"))
    )
    assert "--compact" in docs_blob, "Neither SKILL.md nor references/*.md documents --compact flag"

    # Negative drift 1: broken progressive disclosure reference in SKILL.md copy
    copy_broken_ref = _copy_skill_tree(tmp_path / "skill_broken_ref")
    skill_ref = copy_broken_ref / "SKILL.md"
    skill_ref.write_text(
        skill_ref.read_text(encoding="utf-8")
        + "\nSee [ghost workflow](references/nonexistent_progressive_disclosure_guide.md).\n",
        encoding="utf-8",
    )
    res_bad_ref = _run_cli(claim_audit_script, ["--root", str(copy_broken_ref), "--json"])
    assert res_bad_ref.returncode == 1, (
        "claim_audit.py failed to catch broken progressive disclosure references/*.md link in SKILL.md"
    )
    assert "nonexistent_progressive_disclosure_guide.md" in (res_bad_ref.stdout + res_bad_ref.stderr)

    # Negative drift 2: documented --compact flag missing from target script AST
    copy_broken_flag = _copy_skill_tree(tmp_path / "skill_broken_flag")
    skill_flag = copy_broken_flag / "SKILL.md"
    skill_flag.write_text(
        skill_flag.read_text(encoding="utf-8")
        + "\nRun `python3 scripts/extract_pdf_blocks.py paper.pdf --out blocks.json --compact`.\n",
        encoding="utf-8",
    )
    extractor_copy = copy_broken_flag / "scripts" / "extract_pdf_blocks.py"
    extractor_src = extractor_copy.read_text(encoding="utf-8")
    extractor_copy.write_text(extractor_src.replace("--compact", "--disabled-opt"), encoding="utf-8")

    res_bad_flag = _run_cli(claim_audit_script, ["--root", str(copy_broken_flag), "--json"])
    assert res_bad_flag.returncode == 1, (
        "claim_audit.py failed to catch --compact flag drift between docs and script AST"
    )
    assert "--compact" in (res_bad_flag.stdout + res_bad_flag.stderr)


# ---------------------------------------------------------------------------
# Tier 2: Boundary & Negative Corner Tests (T2-J1 .. T2-J3)
# ---------------------------------------------------------------------------


def test_t2_j1_large_pdf_and_corpus_compact_bounded_stdout(tmp_path: Path) -> None:
    """T2-J1 (F20): >=20-page PDF & >=50-passage corpus stay < 4096 bytes on stdout while full output lives on disk."""
    pages_text = []
    for idx in range(1, 25):
        body = (
            f"Page {idx} Evaluation Section.\n"
            f"Paragraph A on page {idx}: Iterative graph propagation stabilizes training across 10 seeds.\n"
            f"Paragraph B on page {idx}: Experimental batch {idx} logs memory footprint and convergence curve.\n"
        )
        if idx == 18:
            body += "Anchor finding: Clean split ItemKNN achieves NDCG@10 = 0.412 across 5 folds.\n"
        if idx == 22:
            body += "Latency finding: Sparse baseline latency measures 14.3 ms per batch.\n"
        pages_text.append(body)

    large_pdf = _make_multipage_pdf(tmp_path / "large_24p.pdf", pages_text)
    blocks_out = tmp_path / "large_blocks.json"
    res_ext = _run_cli(
        SCRIPTS_DIR / "extract_pdf_blocks.py",
        [str(large_pdf), "--out", str(blocks_out), "--compact"],
    )
    assert res_ext.returncode == 0, f"extract_pdf_blocks failed: {res_ext.stderr}"
    ext_stdout_bytes = len(res_ext.stdout.encode("utf-8"))
    assert ext_stdout_bytes < MAX_COMPACT_STDOUT_BYTES, (
        f"extract_pdf_blocks --compact stdout exceeded 4096 bytes: {ext_stdout_bytes}"
    )
    ext_summary = _parse_stdout_json(res_ext)
    _assert_artifact_pointer(ext_summary, blocks_out)
    assert "pages" not in ext_summary
    disk_blocks_size = blocks_out.stat().st_size
    assert disk_blocks_size > ext_stdout_bytes * 2, "Full disk MinerU V2 artifact unexpectedly small"
    blocks_payload = json.loads(blocks_out.read_text(encoding="utf-8"))
    pages_list = blocks_payload["pages"] if isinstance(blocks_payload, dict) else blocks_payload
    assert len(pages_list) == 24

    # Large corpus >= 60 passages across 2 studies
    study_1 = tmp_path / "study_large_1.json"
    study_2 = tmp_path / "study_large_2.json"
    study_1_blocks = [
        {
            "type": "paragraph",
            "page_idx": i // 3,
            "bbox": [0, 0, 100, 20],
            "text": (
                f"Study 1 passage {i}: Clean split ItemKNN achieves NDCG@10 = 0.412 with baseline latency 14.3 ms."
                if i == 15
                else f"Study 1 passage {i}: Supplementary ablation run {i} evaluates regularizer decay schedules."
            ),
        }
        for i in range(32)
    ]
    study_2_blocks = [
        {
            "type": "paragraph",
            "page_idx": i // 3,
            "bbox": [0, 0, 100, 20],
            "text": (
                f"Study 2 passage {i}: Independent replication confirms NDCG@10 = 0.412 and 14.3 ms latency on clean folds."
                if i == 20
                else f"Study 2 passage {i}: Auxiliary hyperparameter sweep trial {i} records validation variance."
            ),
        }
        for i in range(30)
    ]
    study_1.write_text(json.dumps(study_1_blocks), encoding="utf-8")
    study_2.write_text(json.dumps(study_2_blocks), encoding="utf-8")

    qa_out = tmp_path / "large_qa.json"
    res_qa = _run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(study_1), str(study_2),
            "--question", "What are the clean split NDCG@10 and baseline latency?",
            "--limit", "25",
            "--min-studies", "2",
            "--min-evidence", "2",
            "--out", str(qa_out),
            "--compact",
        ],
    )
    assert res_qa.returncode == 0, f"local_evidence failed: {res_qa.stderr}"
    qa_stdout_bytes = len(res_qa.stdout.encode("utf-8"))
    assert qa_stdout_bytes < MAX_COMPACT_STDOUT_BYTES, (
        f"local_evidence --compact stdout exceeded 4096 bytes: {qa_stdout_bytes}"
    )
    qa_summary = _parse_stdout_json(res_qa)
    _assert_artifact_pointer(qa_summary, qa_out)
    assert qa_summary.get("gate_status") == "ANSWERABLE"
    assert qa_summary.get("distinct_studies", 0) >= 2
    assert "context_packed" not in qa_summary
    qa_disk = json.loads(qa_out.read_text(encoding="utf-8"))
    assert len(qa_disk["ranked_passages"]) >= 2
    assert qa_out.stat().st_size > qa_stdout_bytes


def test_t2_j2_multi_source_compact_preserves_verdicts_counts_seeds_and_failures(tmp_path: Path) -> None:
    """T2-J2 (F20): Multi-source --compact keeps exact verdict, counts, seed check status, artifact path, and failed/429 sources."""
    long_abs_1 = " ".join(["Renormalized adjacency graph convolution achieves 81.5% on Cora."] * 30)
    long_abs_2 = " ".join(["We compare calibrated rank fusion against dense retrieval baselines."] * 30)
    long_abs_3 = " ".join(["Ablation over temperature scaling reduces calibration error by 4.1%."] * 30)
    oa_payload = {
        "meta": {"count": 3},
        "results": [
            _make_openalex_work("W2519887557", "Graph Convolutional Networks", long_abs_1, doi="10.48550/arxiv.1609.02907", year=2016),
            _make_openalex_work("W3000000002", "Calibrated Rank Fusion", long_abs_2, doi="10.1000/crf-2024", year=2024),
            _make_openalex_work("W3000000003", "Temperature Scaling Ablation", long_abs_3, doi="10.1000/tsa-2025", year=2025),
        ],
    }

    with _LocalMockServer() as srv:
        srv.add_route("/works", 200, "application/json", json.dumps(oa_payload), host="api.openalex.org")
        srv.add_route(
            "/graph/v1/paper/search",
            429,
            "application/json",
            '{"message":"Too Many Requests"}',
            host="api.semanticscholar.org",
            headers={"Retry-After": "0"},
        )
        srv.add_route(
            "/works",
            500,
            "application/json",
            '{"error":"internal_server_error"}',
            host="api.crossref.org",
        )

        out_path = tmp_path / "multi_search.json"
        res = _run_cli(
            SCRIPTS_DIR / "search_papers.py",
            [
                "graph convolution",
                "--source", "openalex",
                "--source", "s2",
                "--source", "crossref",
                "--known-doi", "10.48550/arxiv.1609.02907",
                "--out", str(out_path),
                "--compact",
            ],
            env=srv.env(),
        )
        assert res.returncode == 0, f"search_papers failed: {res.stderr}"
        stdout_bytes = len(res.stdout.encode("utf-8"))
        assert stdout_bytes < MAX_COMPACT_STDOUT_BYTES, (
            f"Multi-source --compact stdout exceeded 4096 bytes: {stdout_bytes}"
        )
        summary = _parse_stdout_json(res)
        _assert_artifact_pointer(summary, out_path)
        assert long_abs_1 not in res.stdout, "Compact stdout leaked full abstract text"
        assert long_abs_1[250:400] not in res.stdout, (
            "Compact stdout leaked abstract text beyond 200-char preview"
        )
        for item in summary.get("top_results", []):
            prev = item.get("abstract_preview")
            if prev is not None:
                assert len(prev) <= 200, f"abstract_preview exceeded 200 chars: {len(prev)}"

        # Verify failed & rate-limited source statuses are NOT silently dropped
        raw_sources = summary.get("source_statuses") or summary.get("sources") or {}

        def _src_status(val: Any) -> str:
            return val if isinstance(val, str) else str((val or {}).get("status", ""))

        assert "openalex" in raw_sources and _src_status(raw_sources["openalex"]) == "complete"
        assert "s2" in raw_sources and _src_status(raw_sources["s2"]) in {
            "rate_limited", "http_429", "partial_http_429"
        }
        assert "crossref" in raw_sources and _src_status(raw_sources["crossref"]) in {
            "source_failed", "http_500"
        }

        # Verify known seed check status preserved
        seed_checks = summary.get("known_seed_checks", [])
        assert seed_checks and any(chk.get("status") == "retrieved" for chk in seed_checks), (
            f"Compact summary dropped known_seed_checks status: {summary}"
        )

        # Verify structured counts match full disk artifact
        disk_payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert len(disk_payload["results"]) == 3
        assert long_abs_1 in out_path.read_text(encoding="utf-8")
        assert out_path.stat().st_size > stdout_bytes
        result_count = summary.get("total_results", summary.get("result_count"))
        if result_count is None and isinstance(summary.get("results"), list):
            result_count = len(summary["results"])
        assert result_count == 3, f"Compact summary missing structured count == 3: {summary}"


def test_t2_j3_skill_md_no_inlined_schemas_examples_or_humanizer_catalog() -> None:
    """T2-J3 (F20): SKILL.md does not inline multi-hundred-line schemas, JSON examples, or Humanizer 26-pattern catalog."""
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    _, body = _split_frontmatter(skill_text)

    # 1. No large fenced code blocks or JSON schema dumps inlined in SKILL.md
    fenced_blocks = re.findall(r"```[^\n]*\n(.*?)```", body, flags=re.S)
    total_fenced_lines = sum(len(b.splitlines()) for b in fenced_blocks)
    assert total_fenced_lines <= 25, (
        f"SKILL.md inlines too many code/example lines ({total_fenced_lines}); move to references/"
    )
    for block in fenced_blocks:
        assert len(block.splitlines()) < 15, "SKILL.md contains a bloated fenced block (>=15 lines)"

    assert not re.search(r'"(?:schema|properties|additionalProperties)"\s*:', body), (
        "SKILL.md must not inline JSON schemas (keep in references/*.schema-example.json)"
    )

    # 2. Humanizer 26-pattern catalog stays in references/ / modules/, not inlined in SKILL.md
    section_markers = re.findall(r"§\s*\d+", body)
    assert len(section_markers) <= 2, (
        f"SKILL.md inlines Humanizer pattern catalog markers ({section_markers}); keep in references/modules"
    )
    for catalog_token in (
        "negative parallelism",
        "synonym cycling",
        "em-dash overuse",
        "chatbot residue",
        "trailing participle",
    ):
        assert catalog_token not in body.lower(), (
            f"Humanizer catalog rule {catalog_token!r} should live in references/modules, not SKILL.md"
        )

    # Verify externalized schemas and Humanizer catalog actually exist on disk
    schema_examples = list(REFS_DIR.glob("*.schema-example.json"))
    assert len(schema_examples) >= 5, "Expected externalized *.schema-example.json files in references/"
    assert (REFS_DIR / "humanizer-paper-writing.md").is_file()
    assert (MODULES_DIR / "humanizer" / "UPSTREAM_SKILL.md").is_file()


# ---------------------------------------------------------------------------
# Tier 3: Cross-Feature Chain (T3-15)
# ---------------------------------------------------------------------------


def test_t3_15_chain_extract_compact_local_evidence_compact_to_report_pdf(tmp_path: Path) -> None:
    """T3-15 (F20): extract_pdf_blocks --out --compact -> local_evidence --compact -> report_latex_pdf --strict --json."""
    filler_alpha = " ".join(
        [f"Background protocol note {i}: fixed random seed 42 and identical vocabulary splits." for i in range(12)]
    )
    pages_alpha = [f"Study Alpha Page {p}.\n{filler_alpha}" for p in range(1, 13)]
    pages_alpha[6] = (
        "Study Alpha Page 7.\n"
        "Empirical result: On Cora benchmark, two-layer GCN with symmetric normalization "
        "achieves 81.5% accuracy across 10 seeds (arXiv:1609.02907)."
    )

    filler_beta = " ".join(
        [f"Baseline tuning note {i}: grid search over neighborhood k on validation split." for i in range(12)]
    )
    pages_beta = [f"Study Beta Page {p}.\n{filler_beta}" for p in range(1, 13)]
    pages_beta[9] = (
        "Study Beta Page 10.\n"
        "Independent ablation confirms tuned ItemKNN reaches 0.314 NDCG@10 on clean splits "
        "without preprocessing leakage (arXiv:1907.06902)."
    )

    pdf_alpha = _make_multipage_pdf(tmp_path / "study_alpha.pdf", pages_alpha)
    pdf_beta = _make_multipage_pdf(tmp_path / "study_beta.pdf", pages_beta)
    blocks_alpha = tmp_path / "blocks_alpha.json"
    blocks_beta = tmp_path / "blocks_beta.json"

    # Stage 1: extract_pdf_blocks.py --out ... --compact
    for pdf_p, out_p in ((pdf_alpha, blocks_alpha), (pdf_beta, blocks_beta)):
        res_ext = _run_cli(
            SCRIPTS_DIR / "extract_pdf_blocks.py",
            [str(pdf_p), "--out", str(out_p), "--compact"],
        )
        assert res_ext.returncode == 0, f"extract_pdf_blocks failed: {res_ext.stderr}"
        assert len(res_ext.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
        ext_summary = _parse_stdout_json(res_ext)
        assert "pages" not in ext_summary
        _assert_artifact_pointer(ext_summary, out_p)
        assert out_p.stat().st_size > len(res_ext.stdout.encode("utf-8"))

    # Stage 2: local_evidence.py --inputs <artifacts> --out <qa.json> --compact
    qa_out = tmp_path / "qa_chain.json"
    res_qa = _run_cli(
        SCRIPTS_DIR / "local_evidence.py",
        [
            "--inputs", str(blocks_alpha), str(blocks_beta),
            "--question", "What accuracy and NDCG@10 do GCN and tuned ItemKNN achieve?",
            "--min-studies", "2",
            "--min-evidence", "2",
            "--out", str(qa_out),
            "--compact",
        ],
    )
    assert res_qa.returncode == 0, f"local_evidence failed: {res_qa.stderr}"
    assert len(res_qa.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    qa_summary = _parse_stdout_json(res_qa)
    assert qa_summary.get("gate_status") == "ANSWERABLE"
    assert qa_summary.get("distinct_studies") == 2
    assert "context_packed" not in qa_summary
    _assert_artifact_pointer(qa_summary, qa_out)

    qa_full = json.loads(qa_out.read_text(encoding="utf-8"))
    assert len(qa_full["ranked_passages"]) >= 2

    # Stage 3: Build concise grounded report from disk QA artifact -> report_latex_pdf.py --strict --json
    report_in = tmp_path / "chain_report.json"
    report_in.write_text(
        json.dumps({
            "schema": "research_scientist_executive_report_v1",
            "report_type": "gap_audit",
            "lang": "en",
            "title": "Evidence Audit for GCN and ItemKNN",
            "verdict": {
                "status": "rejected",
                "summary": "REJECT GAP: Tuned ItemKNN reaches 0.314 NDCG@10 on clean splits across 24 PDF pages [arXiv:1907.06902].",
                "evidence_refs": ["K1", "K2"],
            },
            "key_evidence": [
                {
                    "id": "K1",
                    "claim": "Two-layer GCN reaches 81.5% accuracy across 10 seeds on Cora.",
                    "value": "81.5%",
                    "status": "verified",
                    "locator": "arXiv:1609.02907, Page 7",
                },
                {
                    "id": "K2",
                    "claim": "Tuned ItemKNN reaches 0.314 NDCG@10 on clean splits.",
                    "value": "0.314",
                    "status": "verified",
                    "locator": "arXiv:1907.06902, Page 10",
                },
            ],
            "flaws_and_risks": [
                {
                    "id": "R1",
                    "severity": "high",
                    "summary": "Untuned baselines inflate apparent neural gains.",
                    "locator": "arXiv:1907.06902, Page 10",
                }
            ],
            "next_steps": [
                {
                    "step": 1,
                    "action": "Compare against tuned ItemKNN across 10 fixed seeds.",
                    "target": "arXiv:1907.06902",
                    "locator": "arXiv:1907.06902",
                }
            ],
            "sources": [
                {"id": "S1", "title": "Kipf & Welling (2016)", "locator": "arXiv:1609.02907"},
                {"id": "S2", "title": "Dacrema et al. (2019)", "locator": "arXiv:1907.06902"},
            ],
        }),
        encoding="utf-8",
    )
    out_pdf = tmp_path / "chain_report.pdf"
    out_tex = tmp_path / "chain_report.tex"
    res_pdf = _run_cli(
        SCRIPTS_DIR / "report_latex_pdf.py",
        [
            "--input", str(report_in),
            "--out", str(out_pdf),
            "--tex-out", str(out_tex),
            "--lang", "en",
            "--strict",
            "--json",
        ],
        timeout=120,
    )
    assert res_pdf.returncode == 0, f"report_latex_pdf failed:\nstdout={res_pdf.stdout}\nstderr={res_pdf.stderr}"
    assert len(res_pdf.stdout.encode("utf-8")) < MAX_COMPACT_STDOUT_BYTES
    receipt = _parse_stdout_json(res_pdf)
    assert receipt["status"] == "ok"
    assert receipt["lint_findings"] == []
    assert out_pdf.is_file() and out_pdf.stat().st_size > 256

    with fitz.open(str(out_pdf)) as doc:
        assert len(doc) >= 1
        pdf_text = unicodedata.normalize("NFC", "\n".join(p.get_text("text") for p in doc))
    for token in ("REJECT GAP", "81.5%", "0.314", "10 seeds", "arXiv:1609.02907", "arXiv:1907.06902"):
        assert token in pdf_text, f"Expected token {token!r} missing from compiled PDF"
