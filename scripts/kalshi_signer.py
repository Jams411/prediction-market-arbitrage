"""Reusable Kalshi request signer — RSA-PSS over SHA-256, via ``openssl``.

The shipped ``livebook`` package deliberately holds **no** cryptography
dependency: its :class:`livebook.Signer` protocol
(``sign(message: bytes) -> bytes``) says implementations "live in the caller's
code". This module is that caller-side implementation, kept in ``scripts/`` (not
in ``src/``) so the package's zero-runtime-crypto posture is unchanged. It
shells out to ``openssl`` exactly as ``scripts/observe_kalshi_demo.py`` already
does for the demo REST probes — one signing path for REST **and** WebSocket.

Signing (verified against the official Kalshi docs 2026-09-09 —
``docs/API_SOURCES.md`` K-WS-AUTH-03 / K-TR-03, sources WS-A-S1 / WS-A-S2):

    signature = base64( RSA-PSS( SHA-256(message),
                                 mgf   = MGF1(SHA-256),
                                 salt_len = digest length (PSS.DIGEST_LENGTH) ) )

The signed *message* is built by :mod:`livebook.ws_auth`
(``timestamp_ms + "GET" + "/trade-api/ws/v2"`` for the market-data WS); this
module only turns bytes into a raw signature. It has no notion of endpoint,
HTTP method, or "read" vs "trade" — the same RSA key signs every request the
same way, so read-only behaviour is a property of *which* requests the caller
sends, never of the signer.

Key-material rules (enforced here): the private key is only ever read from a
file path; it is never accepted on the command line, never taken from an
environment variable, never logged, and never returned. ``repr`` shows only the
path, not the contents.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SignerError", "OpensslRsaPssSigner", "read_keychain_password"]


class SignerError(RuntimeError):
    """Signing could not be performed (missing key file, ``openssl`` failure)."""


@dataclass(frozen=True)
class OpensslRsaPssSigner:
    """RSA-PSS/SHA-256 signer backed by ``openssl dgst``.

    Structurally satisfies :class:`livebook.Signer`: ``sign`` takes the message
    bytes and returns the **raw** signature bytes (``livebook.ws_auth`` base64-
    encodes them for the ``KALSHI-ACCESS-SIGNATURE`` header).
    """

    pem_path: Path
    openssl: str = "openssl"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"OpensslRsaPssSigner(pem_path={str(self.pem_path)!r})"

    def sign(self, message: bytes) -> bytes:
        if not isinstance(message, bytes):  # pragma: no cover - defensive
            raise SignerError("message to sign must be bytes")
        path = self.pem_path
        if not path.is_file():
            raise SignerError(f"private key file not found: {path}")
        try:
            proc = subprocess.run(
                [
                    self.openssl,
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(path),
                    "-sigopt",
                    "rsa_padding_mode:pss",
                    "-sigopt",
                    "rsa_pss_saltlen:digest",
                    "-binary",
                ],
                input=message,
                capture_output=True,
                check=True,
            )
        except FileNotFoundError as exc:  # openssl not on PATH
            raise SignerError(f"openssl executable not found: {self.openssl!r}") from exc
        except subprocess.CalledProcessError as exc:
            # stderr may name the key path but never contains key material.
            detail = exc.stderr.decode("utf-8", "replace").strip() or f"exit {exc.returncode}"
            raise SignerError(f"openssl signing failed: {detail}") from None
        signature = proc.stdout
        if not signature:
            raise SignerError("openssl produced an empty signature")
        return signature


def read_keychain_password(service: str, account: str | None = None) -> str:
    """Return a generic-password secret from the macOS Keychain.

    Mirrors ``scripts/observe_kalshi_demo.py``: the **API key id** (not secret
    key material — the key id is a non-secret identifier, but Keychain keeps it
    off disk and out of the shell history) is stored as a generic password under
    ``service``. ``account`` defaults to the current user (``whoami``).
    """
    if account is None:
        account = subprocess.run(
            ["whoami"], capture_output=True, text=True, check=True
        ).stdout.strip()
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - non-macOS
        raise SignerError("`security` (macOS Keychain CLI) not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or f"exit {exc.returncode}"
        raise SignerError(f"no Keychain entry for service {service!r}: {detail}") from None
    value = out.stdout.strip()
    if not value:
        raise SignerError(f"empty Keychain entry for service {service!r}")
    return value
