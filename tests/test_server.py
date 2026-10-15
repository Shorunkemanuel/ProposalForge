import json
import socket
import threading
import unittest
import urllib.error
import urllib.request

from app.proposal import InvalidModelOutput
from app.providers import ProviderTimeout, ProviderUnavailable
from app.server import (
    create_server,
    process_readiness_request,
    process_request,
    resolve_allowed_hosts,
)


def valid_payload(**overrides):
    payload = {
        "client_name": "Acme Corp",
        "brief": "Acme needs a marketing website for a spring launch.",
        "scope": "Design and build a five-page responsive marketing site.",
        "timeline": "Six weeks starting in November.",
        "hourly_rate": "85.00",
        "estimated_hours": "40",
        "expenses": "250.00",
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


def valid_draft():
    return {
        "introduction": "Hello",
        "project_understanding": "A site.",
        "proposed_approach": "Plan and build.",
        "timeline": "Six weeks.",
        "relevant_experience": "As supplied.",
        "pricing_explanation": "As calculated.",
        "closing": "Thank you.",
        "missing_information": [],
    }


def expect_http_error(case, expected_code, call, msg=None):
    """Assert that ``call()`` raises ``HTTPError`` with ``expected_code``.

    ``HTTPError`` is a file-like response whose underlying temporary file must
    be closed explicitly, otherwise garbage collection later emits a
    ``ResourceWarning``. The error response is closed here on both the success
    and assertion-failure paths; if ``call`` unexpectedly succeeds, that
    response is closed too before failing.
    """
    try:
        response = call()
    except urllib.error.HTTPError as exc:
        with exc:
            case.assertEqual(exc.code, expected_code, msg)
            return exc.read()
    response.close()
    case.fail(f"expected HTTPError {expected_code}" + (f": {msg}" if msg else ""))


class StubProvider:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error

    def generate(self, system_prompt, user_prompt):
        if self.error:
            raise self.error
        return self.content


class ProcessRequestTests(unittest.TestCase):
    def test_success_returns_200(self):
        provider = StubProvider(content=json.dumps(valid_draft()))
        status, body = process_request(valid_payload(), provider)
        self.assertEqual(status, 200)
        self.assertEqual(body["pricing"]["total"], "3650.00")

    def test_validation_error_returns_400(self):
        status, body = process_request(valid_payload(hourly_rate="-1"), StubProvider())
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "validation_error")
        self.assertIn("hourly_rate", body["fields"])

    def test_invalid_model_output_returns_502(self):
        provider = StubProvider(content="not json")
        status, body = process_request(valid_payload(), provider)
        self.assertEqual(status, 502)
        self.assertEqual(body["error"], "invalid_model_output")

    def test_provider_timeout_returns_504(self):
        provider = StubProvider(error=ProviderTimeout("slow"))
        status, body = process_request(valid_payload(), provider)
        self.assertEqual(status, 504)
        self.assertEqual(body["error"], "provider_timeout")

    def test_provider_unavailable_returns_502(self):
        provider = StubProvider(error=ProviderUnavailable("down"))
        status, body = process_request(valid_payload(), provider)
        self.assertEqual(status, 502)
        self.assertEqual(body["error"], "provider_unavailable")

    def test_unexpected_error_returns_generic_500(self):
        provider = StubProvider(error=RuntimeError("secret stack detail"))
        status, body = process_request(valid_payload(), provider)
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "internal_error")
        self.assertNotIn("secret", json.dumps(body))

    def test_invalid_model_output_exception_from_provider_handled(self):
        provider = StubProvider(error=InvalidModelOutput("bad"))
        status, body = process_request(valid_payload(), provider)
        self.assertEqual(status, 502)
        self.assertEqual(body["error"], "invalid_model_output")


class ProcessReadinessRequestTests(unittest.TestCase):
    def test_valid_payload_is_ready(self):
        status, body = process_readiness_request(valid_payload())
        self.assertEqual(status, 200)
        self.assertTrue(body["ready"])
        self.assertEqual(body["total_sections"], 4)

    def test_incomplete_payload_reports_missing_sections(self):
        status, body = process_readiness_request({"client_name": "Acme"})
        self.assertEqual(status, 200)
        self.assertFalse(body["ready"])
        self.assertEqual(body["complete_sections"], 0)

    def test_non_dict_payload_is_handled(self):
        status, body = process_readiness_request("not a dict")
        self.assertEqual(status, 200)
        self.assertFalse(body["ready"])

    def test_missing_pricing_numbers_are_reported(self):
        payload = valid_payload()
        del payload["hourly_rate"]
        status, body = process_readiness_request(payload)
        self.assertEqual(status, 200)
        self.assertFalse(body["ready"])
        pricing = next(s for s in body["sections"] if s["id"] == "pricing")
        self.assertFalse(pricing["complete"])


class HttpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        provider = StubProvider(content=json.dumps(valid_draft()))
        cls.server = create_server(provider=provider, host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_get_index(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn(b"ProposalForge", response.read())

    def test_get_static_asset(self):
        with urllib.request.urlopen(self.url("/static/app.js"), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.headers["Content-Type"])

    def test_get_unknown_returns_404(self):
        expect_http_error(
            self, 404, lambda: urllib.request.urlopen(self.url("/nope"), timeout=5)
        )

    def test_post_proposal_success(self):
        request = urllib.request.Request(
            self.url("/api/proposals"),
            data=json.dumps(valid_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertEqual(body["pricing"]["total"], "3650.00")

    def test_post_negative_expenses_rejected(self):
        body = expect_http_error(
            self,
            400,
            lambda: self._post(
                json.dumps(valid_payload(expenses="-5")).encode("utf-8"),
                {"Content-Type": "application/json"},
            ),
        )
        payload = json.loads(body)
        self.assertEqual(payload["error"], "validation_error")
        self.assertIn("expenses", payload["fields"])

    def test_post_readiness_ready(self):
        request = urllib.request.Request(
            self.url("/api/readiness"),
            data=json.dumps(valid_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            body = json.loads(response.read())
            self.assertTrue(body["ready"])
            self.assertEqual(len(body["sections"]), 4)

    def test_post_readiness_incomplete(self):
        request = urllib.request.Request(
            self.url("/api/readiness"),
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertFalse(json.loads(response.read())["ready"])

    def test_post_readiness_foreign_host_rejected(self):
        data = self._raw_post(f"evil.example:{self.port}", path="/api/readiness")
        self.assertIn(b" 403 ", self._status_line(data))

    def test_post_readiness_without_json_content_type_returns_415(self):
        body = expect_http_error(
            self,
            415,
            lambda: self._post(b"{}", {"Content-Type": "text/plain"}, path="/api/readiness"),
        )
        self.assertEqual(json.loads(body)["error"], "unsupported_media_type")

    def test_post_invalid_json_returns_400(self):
        request = urllib.request.Request(
            self.url("/api/proposals"),
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        body = expect_http_error(
            self, 400, lambda: urllib.request.urlopen(request, timeout=5)
        )
        self.assertEqual(json.loads(body)["error"], "invalid_json")

    def test_post_unknown_path_returns_404(self):
        request = urllib.request.Request(
            self.url("/api/other"),
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        expect_http_error(
            self, 404, lambda: urllib.request.urlopen(request, timeout=5)
        )

    def _post(self, body, headers, path="/api/proposals"):
        request = urllib.request.Request(
            self.url(path), data=body, headers=headers, method="POST"
        )
        return urllib.request.urlopen(request, timeout=5)

    def _body(self):
        return json.dumps(valid_payload()).encode("utf-8")

    def _raw_post(self, host_header, body=None, include_host=True, path="/api/proposals"):
        """POST with an explicit Host header (urllib cannot spoof Host).

        Returns the raw response bytes. The socket is closed by the ``with``
        block so no ``ResourceWarning`` is emitted under ``-W error``.
        """
        body = self._body() if body is None else body
        lines = [f"POST {path} HTTP/1.1"]
        if include_host:
            lines.append(f"Host: {host_header}")
        lines.append("Content-Type: application/json")
        lines.append(f"Content-Length: {len(body)}")
        lines.append("Connection: close")
        request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(request)
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        return data

    def _status_line(self, data):
        return data.split(b"\r\n", 1)[0]

    def test_post_host_ipv4_loopback_allowed(self):
        data = self._raw_post(f"127.0.0.1:{self.port}")
        self.assertIn(b" 200 ", self._status_line(data))

    def test_post_host_localhost_allowed(self):
        data = self._raw_post(f"localhost:{self.port}")
        self.assertIn(b" 200 ", self._status_line(data))

    def test_post_host_localhost_case_insensitive_allowed(self):
        data = self._raw_post(f"LOCALHOST:{self.port}")
        self.assertIn(b" 200 ", self._status_line(data))

    def test_post_host_ipv6_loopback_allowed(self):
        data = self._raw_post(f"[::1]:{self.port}")
        self.assertIn(b" 200 ", self._status_line(data))

    def test_post_host_without_port_allowed(self):
        data = self._raw_post("127.0.0.1")
        self.assertIn(b" 200 ", self._status_line(data))

    def test_post_foreign_host_rejected(self):
        data = self._raw_post(f"evil.example:{self.port}")
        self.assertIn(b" 403 ", self._status_line(data))
        self.assertIn(b"forbidden", data)

    def test_post_foreign_host_without_port_rejected(self):
        data = self._raw_post("evil.example")
        self.assertIn(b" 403 ", self._status_line(data))

    def test_post_host_suffix_spoof_rejected(self):
        data = self._raw_post(f"127.0.0.1.evil.example:{self.port}")
        self.assertIn(b" 403 ", self._status_line(data))

    def test_post_missing_host_rejected(self):
        data = self._raw_post(None, include_host=False)
        self.assertIn(b" 403 ", self._status_line(data))

    def test_post_bad_host_rejected_before_body_read(self):
        # A valid JSON body must still be refused when Host is untrusted,
        # proving the Host check runs before the body is processed.
        data = self._raw_post(f"evil.example:{self.port}", body=self._body())
        self.assertIn(b" 403 ", self._status_line(data))
        self.assertNotIn(b"3650.00", data)

    def test_security_headers_on_html(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as response:
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            csp = response.headers["Content-Security-Policy"]
            self.assertIn("default-src 'none'", csp)
            self.assertIn("frame-ancestors 'none'", csp)

    def test_security_headers_on_api_response(self):
        resp = self._post(
            json.dumps(valid_payload()).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        with resp:
            self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("Content-Security-Policy", resp.headers)
            self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_post_without_json_content_type_returns_415(self):
        body = expect_http_error(
            self, 415, lambda: self._post(b"{}", {"Content-Type": "text/plain"})
        )
        self.assertEqual(json.loads(body)["error"], "unsupported_media_type")

    def test_post_cross_origin_rejected(self):
        body = expect_http_error(
            self,
            403,
            lambda: self._post(
                json.dumps(valid_payload()).encode("utf-8"),
                {
                    "Content-Type": "application/json",
                    "Origin": "http://evil.example",
                },
            ),
        )
        self.assertEqual(json.loads(body)["error"], "forbidden")

    def test_post_same_origin_allowed(self):
        payload = json.dumps(valid_payload()).encode("utf-8")
        resp = self._post(
            payload,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Origin": self.url(""),
            },
        )
        with resp:
            self.assertEqual(resp.status, 200)

    def test_oversized_body_returns_413(self):
        # Send only the headers with an oversized Content-Length. The server
        # rejects on the declared size before reading the body, so actually
        # streaming 200 KB would race with the connection closing and could
        # raise BrokenPipeError instead of surfacing the 413 response.
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            headers = (
                "POST /api/proposals HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {200_000}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            sock.sendall(headers.encode("ascii"))
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        self.assertIn(b" 413 ", data.split(b"\r\n", 1)[0])
        self.assertIn(b"payload_too_large", data)

    def test_static_path_traversal_returns_404(self):
        for path in (
            "/static/%2e%2e/%2e%2e/app/server.py",
            "/static/%2e%2e/server.py",
            "/static/..%2f..%2fapp%2fserver.py",
        ):
            expect_http_error(
                self,
                404,
                lambda path=path: urllib.request.urlopen(self.url(path), timeout=5),
                msg=path,
            )

    def test_server_header_does_not_leak_runtime(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as response:
            server = response.headers.get("Server", "")
            self.assertNotIn("Python", server)
            self.assertNotIn("BaseHTTP", server)


class BindAddressTests(unittest.TestCase):
    def test_loopback_binds_accepted(self):
        for host in ("127.0.0.1", "localhost", "LOCALHOST", "127.0.0.2", "::1", "[::1]"):
            with self.subTest(host=host):
                allowed = resolve_allowed_hosts(host)
                self.assertIn("127.0.0.1", allowed)
                self.assertIn("localhost", allowed)
                self.assertIn("::1", allowed)

    def test_unsupported_binds_rejected(self):
        for host in (
            "0.0.0.0",
            "::",
            "0:0:0:0:0:0:0:0",
            "",
            "192.168.1.10",
            "example.com",
        ):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    resolve_allowed_hosts(host)

    def test_create_server_rejects_wildcard_bind(self):
        for host in ("0.0.0.0", "::"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    create_server(provider=StubProvider(), host=host, port=0)


class UnconfiguredProviderServerTests(unittest.TestCase):
    """The UI must load and return a clear error when no model is configured."""

    @classmethod
    def setUpClass(cls):
        from app.providers import OllamaProvider, ProviderConfig

        provider = OllamaProvider(ProviderConfig(base_url="http://127.0.0.1:1", model=""))
        cls.server = create_server(provider=provider, host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_ui_loads_without_model(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_readiness_works_without_model(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/readiness",
            data=json.dumps(valid_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertTrue(json.loads(r.read())["ready"])

    def test_generate_returns_clear_provider_error(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/proposals",
            data=json.dumps(valid_payload()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        body = json.loads(
            expect_http_error(
                self, 502, lambda: urllib.request.urlopen(request, timeout=5)
            )
        )
        self.assertEqual(body["error"], "provider_unavailable")
        self.assertIn("model", body["message"].lower())


if __name__ == "__main__":
    unittest.main()
