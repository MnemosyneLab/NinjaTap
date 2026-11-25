"""HTTPS client that pins the phone's certificate."""

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from urllib3 import HTTPSConnectionPool, HTTPResponse
from urllib3.exceptions import HTTPError, SSLError

from ninjatap.protocol import Display, Status, Step, sequence_body


def _raise_unless_ok(payload: dict, fallback: str = "clipboard failed") -> None:
    status = payload.get("status")
    if status != "ok":
        detail = payload.get("detail") or status or fallback
        raise PhoneError(str(detail))


class PhoneError(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class Phone:
    def __init__(self, base_url: str, secret: str, fingerprint: str):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "NINJATAP_URL must be the phone HTTPS origin, for example https://192.0.2.10:8787"
            )
        fingerprint = fingerprint.strip().replace(":", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
            raise ValueError(
                "NINJATAP_TLS_FINGERPRINT must be the phone's full SHA-256 fingerprint (64 hex digits)"
            )
        self.secret = secret
        # For this connection the pinned certificate is the trust anchor.
        self._pool = HTTPSConnectionPool(
            parsed.hostname, parsed.port, cert_reqs="CERT_NONE", assert_fingerprint=fingerprint
        )

    def screencap(self, timeout: float | None = None) -> bytes:
        return self.capture(timeout)[0]

    def capture(self, timeout: float | None = None) -> tuple[bytes, Display]:
        response = self._send("GET", "/screencap", timeout=timeout)
        body = response.data
        # Older players return screen readiness errors as HTTP 200 JSON.
        if not body.startswith(b"\x89PNG"):
            try:
                status = json.loads(body)["status"]
            except (ValueError, KeyError, TypeError):
                status = None
            if isinstance(status, str) and status != "ok":
                raise PhoneError(status)
        rotation = response.headers.get("x-ninjatap-rotation", "0")
        if rotation not in ("0", "1", "2", "3"):
            raise PhoneError("invalid screenshot rotation")
        return body, Display(int(rotation))

    def display(self, timeout: float | None = None) -> Display:
        try:
            body = self._open("/screen", timeout=timeout)
        except PhoneError as error:
            if error.status == "not found":
                # Older players only accept upright portrait touches.
                return Display()
            raise
        payload = json.loads(body)
        _raise_unless_ok(payload, "could not read the phone display")
        rotation = payload.get("rotation")
        if type(rotation) is not int or rotation not in range(4):
            raise PhoneError("invalid display rotation")
        return Display(rotation)

    def inject(self, steps: list[Step], timeout: float | None = None, *, rotation: int = 0) -> Status:
        body = json.dumps(sequence_body(steps, rotation)).encode()
        payload = json.loads(self._open("/inject", body, timeout=timeout).decode())
        return payload["status"]

    def press_key(self, key: str, timeout: float | None = None) -> str:
        payload = json.loads(self._open("/key", json.dumps({"key": key}).encode(), timeout))
        _raise_unless_ok(payload, "navigation failed")
        return "ok"

    def set_screen_locked(self, locked: bool, timeout: float | None = None) -> str:
        operation = "lock" if locked else "unlock"
        payload = json.loads(self._open(f"/screen/{operation}", b"", timeout))
        _raise_unless_ok(payload, f"screen {operation} failed")
        return "ok"

    def read_clipboard(self, timeout: float | None = None) -> str:
        payload = json.loads(self._open("/clipboard", timeout=timeout).decode())
        _raise_unless_ok(payload)
        return payload.get("text") or ""

    def write_clipboard(self, text: str, timeout: float | None = None) -> str:
        body = json.dumps({"text": text}).encode()
        payload = json.loads(self._open("/clipboard", body, timeout=timeout).decode())
        _raise_unless_ok(payload)
        return "ok"

    def pull(self, remote_path: str, target: Path) -> int:
        path = "/files?" + urlencode({"path": remote_path})
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"destination already exists: {target}")
        response = self._send("GET", path, timeout=30, preload_content=False)
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent) as pending:
                size = 0
                for chunk in response.stream(128 * 1024, decode_content=False):
                    pending.write(chunk)
                    size += len(chunk)
                if response.headers.get("Content-Length") != str(size):
                    raise PhoneError("incomplete file download")
                pending.flush()
                os.link(pending.name, target)
                return size
        except HTTPError as error:
            raise PhoneError(f"file download interrupted: {error}") from error
        finally:
            response.close()
            response.release_conn()

    def push(self, source: Path, remote_path: str) -> int:
        path = "/files?" + urlencode({"path": remote_path})
        if not source.is_file():
            raise OSError(f"not a local file: {source}")
        with source.open("rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise OSError(f"not a local file: {source}")

            def chunks():
                remaining = info.st_size
                while remaining:
                    chunk = file.read(min(128 * 1024, remaining))
                    if not chunk:
                        raise OSError("local file changed during upload")
                    remaining -= len(chunk)
                    yield chunk

            self._send("PUT", path, body=chunks(), timeout=30, headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(info.st_size),
            })
            return info.st_size

    def _open(self, path: str, body: bytes | None = None, timeout: float | None = None) -> bytes:
        return self._send("POST" if body is not None else "GET", path, body=body, timeout=timeout).data

    def _send(
        self, method: str, path: str, *, body=None, timeout=None, headers=None, preload_content=True
    ) -> HTTPResponse:
        request_headers = {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        try:
            response = self._pool.urlopen(
                method,
                path,
                body=body,
                headers=request_headers,
                timeout=timeout,
                retries=False,
                redirect=False,
                preload_content=preload_content,
            )
        except SSLError as error:
            raise PhoneError(f"phone TLS verification failed: {error}") from error
        except (HTTPError, OSError) as error:
            raise PhoneError(f"phone unreachable: {error}") from error
        if not 200 <= response.status < 300:
            try:
                detail = (response.data[:4096] if preload_content else response.read(4096)).decode(errors="replace")
            finally:
                response.close()
                response.release_conn()
            try:
                status = json.loads(detail)["status"]
            except (json.JSONDecodeError, KeyError, TypeError):
                status = detail.strip() or str(response.status)
            raise PhoneError(status)
        return response
