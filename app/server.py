"""Standard-library HTTP server and JSON API for ProposalForge.

Endpoints:
    GET  /                  serve the browser application
    GET  /static/<path>     serve static assets
    POST /api/proposals     validate, price, generate, return a draft

The server binds to localhost by default and is not intended to be exposed
publicly. Error responses never include stack traces, secrets, or raw
provider payloads.
"""

import ipaddress
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from .proposal import InvalidModelOutput, build_proposal
from .providers import ProviderError, ProviderTimeout, ProviderUnavailable, get_provider
from .readiness import evaluate_readiness
from .validation import ValidationError

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY_BYTES = 100_000

# Milestone 2 binds to loopback only. The Host header is checked against this
# set so a DNS-rebinding page (whose Host stays attacker-controlled even after
# its name resolves to 127.0.0.1) cannot drive the local API.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNSUPPORTED_BIND_MESSAGE = (
    "ProposalForge Milestone 2 only binds to loopback addresses "
    "(127.0.0.1, localhost, ::1). Network/LAN access is not supported. "
    "Use the default --host 127.0.0.1."
)


def _normalize_host(host):
    host = (host or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.endswith("."):
        host = host[:-1]
    return host


def resolve_allowed_hosts(host):
    """Return the allowed Host-header values for a bind address.

    Only loopback bind addresses are supported in Milestone 2. Wildcard
    (``0.0.0.0``/``::``), empty, LAN, and other non-loopback addresses raise
    ``ValueError`` so the server refuses to start rather than silently
    exposing the API.
    """
    normalized = _normalize_host(host)
    if normalized == "localhost":
        is_loopback = True
    else:
        try:
            is_loopback = ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        raise ValueError(UNSUPPORTED_BIND_MESSAGE)
    return LOOPBACK_HOSTS | {normalized}


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".ico": "image/x-icon",
}

# Locked down for a local, first-party tool: no inline script/style, no
# external origins, no framing. The UI and API are same-origin only.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
}


def process_readiness_request(payload):
    """Pure readiness handler: return (status_code, response_dict).

    Readiness is deterministic application logic with no provider involved,
    so this always returns 200 with a checklist report.
    """
    return 200, evaluate_readiness(payload)


def process_request(payload, provider):
    """Pure request handler: return (status_code, response_dict).

    Kept free of socket concerns so it can be unit-tested directly.
    """
    try:
        result = build_proposal(payload, provider)
    except ValidationError as exc:
        return 400, {"error": "validation_error", "fields": exc.errors}
    except InvalidModelOutput as exc:
        return 502, {"error": "invalid_model_output", "message": str(exc)}
    except ProviderTimeout as exc:
        return 504, {"error": "provider_timeout", "message": str(exc)}
    except ProviderUnavailable as exc:
        return 502, {"error": "provider_unavailable", "message": str(exc)}
    except ProviderError:
        return 502, {
            "error": "provider_error",
            "message": "The AI provider failed. Please try again.",
        }
    except Exception:
        return 500, {
            "error": "internal_error",
            "message": "An unexpected server error occurred.",
        }
    return 200, result


class ProposalForgeHandler(BaseHTTPRequestHandler):
    server_version = "ProposalForge"
    sys_version = ""
    provider = None
    static_dir = STATIC_DIR
    allowed_hosts = LOOPBACK_HOSTS

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):
        return

    def _send_security_headers(self):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, relative_path):
        safe_path = os.path.normpath("/" + relative_path).lstrip("/")
        if safe_path.startswith("..") or os.path.isabs(safe_path):
            self._send_json(404, {"error": "not_found"})
            return
        static_root = os.path.realpath(self.static_dir)
        full_path = os.path.realpath(os.path.join(static_root, safe_path))
        if full_path != static_root and not full_path.startswith(static_root + os.sep):
            self._send_json(404, {"error": "not_found"})
            return
        if not os.path.isfile(full_path):
            self._send_json(404, {"error": "not_found"})
            return
        ext = os.path.splitext(full_path)[1].lower()
        with open(full_path, "rb") as handle:
            body = handle.read()
        self._send_bytes(200, body, CONTENT_TYPES.get(ext, "application/octet-stream"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_static("index.html")
            return
        if path.startswith("/static/"):
            self._serve_static(unquote(path[len("/static/"):]))
            return
        self._send_json(404, {"error": "not_found"})

    def _host_allowed(self) -> bool:
        """True only when the Host header names an allowed loopback host.

        The port is ignored and the comparison is case-insensitive. A missing
        or malformed Host is refused. This is the primary DNS-rebinding
        defense: after a name is rebound to 127.0.0.1 the Host header is still
        the attacker's name and fails this check.
        """
        raw_host = self.headers.get("Host")
        if not raw_host:
            return False
        try:
            hostname = urlparse("//" + raw_host).hostname
        except ValueError:
            return False
        if not hostname:
            return False
        return hostname.lower() in self.allowed_hosts

    def _same_origin(self) -> bool:
        """True unless a browser cross-origin Origin header is present.

        The UI always posts same-origin, so a cross-origin Origin indicates a
        local-browser (CSRF/DNS-rebinding) request and is refused. Non-browser
        clients that omit Origin are allowed, and JSON content-type is still
        required separately.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host")
        if not host:
            return False
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https"):
            return False
        return parsed.netloc == host

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/proposals", "/api/readiness"):
            self._send_json(404, {"error": "not_found"})
            return

        if not self._host_allowed():
            self._send_json(
                403, {"error": "forbidden", "message": "Request host is not allowed."}
            )
            return

        if not self._same_origin():
            self._send_json(403, {"error": "forbidden"})
            return

        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            self._send_json(415, {"error": "unsupported_media_type"})
            return

        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header) if length_header is not None else 0
        except ValueError:
            self._send_json(400, {"error": "invalid_request"})
            return
        if length <= 0:
            self._send_json(400, {"error": "invalid_request", "message": "Empty body."})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "payload_too_large"})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid_json"})
            return

        if path == "/api/readiness":
            status, response = process_readiness_request(payload)
        else:
            status, response = process_request(payload, self.provider)
        self._send_json(status, response)


def create_server(provider=None, host="127.0.0.1", port=8000, static_dir=None):
    allowed_hosts = resolve_allowed_hosts(host)
    provider = provider or get_provider()
    handler = type(
        "BoundProposalForgeHandler",
        (ProposalForgeHandler,),
        {
            "provider": provider,
            "static_dir": static_dir or STATIC_DIR,
            "allowed_hosts": allowed_hosts,
        },
    )
    return ThreadingHTTPServer((host, port), handler)
