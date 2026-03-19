from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Protocol


CF_ACCOUNT_ID = "7f88b51a6a2e28158b13829929d89115"
CF_BOOTSTRAP_TOKEN = "ndXi70U59zpugzbtaTwBGhZfEL00HCJiJVuz6ygi"
CF_TOKEN_TARGET = "LoliLend.Cloudflare.WorkersAI.Token"


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class SecretStore(Protocol):
    def read(self) -> str | None: ...

    def write(self, secret: str) -> bool: ...


class WindowsCredentialStore:
    def __init__(self, target: str = CF_TOKEN_TARGET) -> None:
        self._target = target
        self._fallback_secret: str | None = None

    def read(self) -> str | None:
        if os.name != "nt":
            return self._fallback_secret
        cred_ptr = ctypes.POINTER(_CREDENTIALW)()
        if not _cred_read(self._target, CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr)):
            return self._fallback_secret
        try:
            credential = cred_ptr.contents
            if credential.CredentialBlobSize <= 0 or not credential.CredentialBlob:
                return self._fallback_secret
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return blob.decode("utf-16-le")
        finally:
            _cred_free(cred_ptr)

    def write(self, secret: str) -> bool:
        secret = secret.strip()
        if not secret:
            return False
        self._fallback_secret = secret
        if os.name != "nt":
            return True

        blob = secret.encode("utf-16-le")
        blob_buffer = ctypes.create_string_buffer(blob)
        credential = _CREDENTIALW()
        credential.Flags = 0
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = self._target
        credential.Comment = None
        credential.LastWritten = wintypes.FILETIME(0, 0)
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.AttributeCount = 0
        credential.Attributes = None
        credential.TargetAlias = None
        credential.UserName = "LoliLend"
        return bool(_cred_write(ctypes.byref(credential), 0))


class BootstrapTokenProvider:
    def __init__(self, store: SecretStore) -> None:
        self._store = store

    def resolve_token(self) -> str:
        secret = self._store.read()
        if secret:
            return secret
        self._store.write(CF_BOOTSTRAP_TOKEN)
        return CF_BOOTSTRAP_TOKEN


class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


if os.name == "nt":
    _advapi32 = ctypes.WinDLL("Advapi32.dll")
    _cred_read = _advapi32.CredReadW
    _cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    _cred_read.restype = wintypes.BOOL

    _cred_write = _advapi32.CredWriteW
    _cred_write.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    _cred_write.restype = wintypes.BOOL

    _cred_free = _advapi32.CredFree
    _cred_free.argtypes = [ctypes.c_void_p]
    _cred_free.restype = None
else:
    def _cred_read(*_args):  # type: ignore[no-redef]
        return False

    def _cred_write(*_args):  # type: ignore[no-redef]
        return False

    def _cred_free(*_args):  # type: ignore[no-redef]
        return None
