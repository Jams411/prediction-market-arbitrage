"""Deterministic, offline tests for ``scripts/kalshi_signer.py``.

The signer *is* ``openssl``, so these tests generate a throwaway RSA key with
``openssl`` in ``tmp_path``, sign a message, and verify the signature with the
matching public key using the same RSA-PSS parameters. No network, no committed
key, no real credential. Skipped if ``openssl`` is unavailable.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from kalshi_signer import OpensslRsaPssSigner, SignerError, read_keychain_password

from prediction_market_arbitrage.livebook import KalshiCredentials, kalshi_ws_handshake

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")

MESSAGE = b"1700000000000GET/trade-api/ws/v2"


@pytest.fixture
def rsa_key(tmp_path: Path) -> Path:
    key_path = tmp_path / "test-key.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
         "-out", str(key_path)],
        check=True,
        capture_output=True,
    )
    return key_path


def _verify(pub_pem: Path, message: bytes, signature: bytes, tmp_path: Path) -> bool:
    msg_file = tmp_path / "msg.bin"
    sig_file = tmp_path / "sig.bin"
    msg_file.write_bytes(message)
    sig_file.write_bytes(signature)
    proc = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub_pem),
         "-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:digest",
         "-signature", str(sig_file), str(msg_file)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and "Verified OK" in proc.stdout


@pytest.fixture
def pub_key(rsa_key: Path, tmp_path: Path) -> Path:
    pub_path = tmp_path / "test-key.pub.pem"
    subprocess.run(
        ["openssl", "pkey", "-in", str(rsa_key), "-pubout", "-out", str(pub_path)],
        check=True,
        capture_output=True,
    )
    return pub_path


def test_sign_returns_raw_2048_bit_signature(rsa_key: Path) -> None:
    signature = OpensslRsaPssSigner(rsa_key).sign(MESSAGE)
    assert isinstance(signature, bytes)
    assert len(signature) == 256  # 2048-bit key -> 256-byte signature


def test_signature_verifies_with_matching_public_key(
    rsa_key: Path, pub_key: Path, tmp_path: Path
) -> None:
    signature = OpensslRsaPssSigner(rsa_key).sign(MESSAGE)
    assert _verify(pub_key, MESSAGE, signature, tmp_path)


def test_signature_does_not_verify_for_a_different_message(
    rsa_key: Path, pub_key: Path, tmp_path: Path
) -> None:
    signature = OpensslRsaPssSigner(rsa_key).sign(MESSAGE)
    assert not _verify(pub_key, b"1700000000000GET/trade-api/ws/v2/tampered", signature, tmp_path)


def test_pss_is_randomised_same_message_two_signatures_differ(rsa_key: Path) -> None:
    signer = OpensslRsaPssSigner(rsa_key)
    assert signer.sign(MESSAGE) != signer.sign(MESSAGE)


def test_missing_key_file_raises_signer_error_naming_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope.pem"
    with pytest.raises(SignerError, match=str(missing)):
        OpensslRsaPssSigner(missing).sign(MESSAGE)


def test_repr_shows_path_not_contents(rsa_key: Path) -> None:
    assert "test-key.pem" in repr(OpensslRsaPssSigner(rsa_key))
    assert "BEGIN" not in repr(OpensslRsaPssSigner(rsa_key))


def test_integrates_with_kalshi_ws_handshake(
    rsa_key: Path, pub_key: Path, tmp_path: Path
) -> None:
    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
    now_ms = str(int(now.timestamp() * 1000))
    handshake = kalshi_ws_handshake(
        KalshiCredentials(api_key_id="k-prod-id", private_key_pem=rsa_key.read_text()),
        OpensslRsaPssSigner(rsa_key),
        now=now,
    )
    assert handshake.url == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    assert handshake.headers["KALSHI-ACCESS-KEY"] == "k-prod-id"
    assert handshake.headers["KALSHI-ACCESS-TIMESTAMP"] == now_ms
    signature = base64.b64decode(handshake.headers["KALSHI-ACCESS-SIGNATURE"])
    assert _verify(pub_key, f"{now_ms}GET/trade-api/ws/v2".encode(), signature, tmp_path)


# --------------------------------------------------------------------------- #
# read_keychain_password — subprocess stubbed, never hits the real Keychain
# --------------------------------------------------------------------------- #


def test_read_keychain_password_builds_expected_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        stdout = "me\n" if cmd[:1] == ["whoami"] else "prod-key-id-value\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    value = read_keychain_password("pma-kalshi-prod-api-key-id", account="me")
    assert value == "prod-key-id-value"
    assert seen["cmd"][:3] == ["security", "find-generic-password", "-a"]
    assert "-w" in seen["cmd"] and "pma-kalshi-prod-api-key-id" in seen["cmd"]


def test_read_keychain_password_empty_entry_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="   \n", stderr=""),
    )
    with pytest.raises(SignerError, match="empty Keychain entry"):
        read_keychain_password("pma-kalshi-prod-api-key-id", account="me")
