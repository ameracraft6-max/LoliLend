from __future__ import annotations

from PySide6.QtCore import QByteArray


def encode_qbytearray(value: QByteArray) -> str:
    if value.isEmpty():
        return ""
    return bytes(value.toBase64()).decode("ascii")


def decode_qbytearray(value: str) -> QByteArray:
    raw = str(value).strip()
    if not raw:
        return QByteArray()
    return QByteArray.fromBase64(raw.encode("ascii"))
