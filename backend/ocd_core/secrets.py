"""Secret storage — OS keychain first, encrypted-file fallback (review finding C3).

Secrets (connector auth headers today; BYO-key provider API keys in Phase 1) must
never be written as plaintext into tracked/on-disk config. This module provides a
small ``SecretStore`` port with three adapters:

* ``KeyringStore``   — the OS credential vault via ``keyring`` (macOS Keychain,
  Windows Credential Manager, Freedesktop Secret Service). Default when available.
* ``EncryptedFileStore`` — a Fernet-encrypted JSON blob under the data dir, used on
  headless/Linux-server installs with no usable keyring. The Fernet key comes from
  ``OCD_SECRET_KEY`` (a urlsafe-base64 Fernet key) or a generated ``secret.key`` file
  written with ``0600`` perms.
* ``MemoryStore``    — in-process only; used by tests and as a last-resort fallback.

``get_secret_store()`` picks the best available backend once per process. The choice
is overridable with ``OCD_SECRET_BACKEND=keyring|file|memory`` for deployment control
and tests.
"""
from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from . import config

SERVICE = "open-claude-desktop"


class SecretStore(ABC):
    """A minimal key -> secret string store."""

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class MemoryStore(SecretStore):
    """Ephemeral in-process store (tests / last-resort fallback)."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._d[key] = value

    def get(self, key: str) -> str | None:
        return self._d.get(key)

    def delete(self, key: str) -> None:
        self._d.pop(key, None)


class KeyringStore(SecretStore):
    """OS credential vault via the ``keyring`` library."""

    def __init__(self, service: str = SERVICE) -> None:
        import keyring  # imported lazily so the module loads without the dep
        self._keyring = keyring
        self._service = service

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(self._service, key, value)

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(self._service, key)

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(self._service, key)
        except Exception:
            pass  # already absent — deletion is idempotent


class EncryptedFileStore(SecretStore):
    """Fernet-encrypted JSON blob for headless installs with no OS keyring."""

    def __init__(self, path: Path | None = None, key: bytes | None = None) -> None:
        from cryptography.fernet import Fernet
        self._path = Path(path) if path else (config.REPO_ROOT / "runtime" / "secrets.enc")
        self._fernet = Fernet(key or self._resolve_key())
        self._lock = threading.Lock()

    def _resolve_key(self) -> bytes:
        from cryptography.fernet import Fernet
        env = os.getenv("OCD_SECRET_KEY")
        if env:
            return env.encode()
        key_file = self._path.parent / "secret.key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            return key_file.read_bytes()
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass  # best effort (e.g. Windows)
        return key

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._fernet.decrypt(self._path.read_bytes()).decode())
        except Exception:
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        blob = self._fernet.encrypt(json.dumps(data).encode())
        self._path.write_bytes(blob)
        try:
            os.chmod(self._path, 0o600)
        except Exception:
            pass

    def set(self, key: str, value: str) -> None:
        with self._lock:
            data = self._load()
            data[key] = value
            self._save(data)

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._load().get(key)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(key, None) is not None:
                self._save(data)


class _WorkspaceScopedStore(SecretStore):
    """Transparently namespaces keys by the current workspace so two tenants can't read
    each other's secrets (provider API keys, connector auth, OAuth tokens).

    A thin delegating wrapper — the backend (keyring / encrypted file) is unchanged. The
    namespace is read at each call (not construction), so one process-wide backend serves
    every workspace and a held reference re-scopes correctly per request. `local` and the
    flag-off desktop map to `namespace() is None` → keys pass through UNPREFIXED, so
    pre-tenancy secrets keep resolving under their historical names."""

    def __init__(self, inner: SecretStore) -> None:
        self._inner = inner

    def _k(self, key: str) -> str:
        from . import tenancy
        ns = tenancy.namespace()
        return f"ws::{ns}::{key}" if ns else key

    def set(self, key: str, value: str) -> None:
        self._inner.set(self._k(key), value)

    def get(self, key: str) -> str | None:
        return self._inner.get(self._k(key))

    def delete(self, key: str) -> None:
        self._inner.delete(self._k(key))


def _keyring_usable() -> bool:
    """True iff a real, writable keyring backend is available."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring
        backend = keyring.get_keyring()
        if isinstance(backend, FailKeyring):
            return False
        # Some environments expose a chainer with no usable backend; probe gently.
        keyring.get_password(SERVICE, "__probe__")
        return True
    except Exception:
        return False


_store: SecretStore | None = None
_store_lock = threading.Lock()


def _backend_store() -> SecretStore:
    """Return the process-wide secret backend, choosing the best one once.

    Override with ``OCD_SECRET_BACKEND=keyring|file|memory``.
    """
    global _store
    with _store_lock:
        if _store is not None:
            return _store
        backend = os.getenv("OCD_SECRET_BACKEND", "").strip().lower()
        if backend == "memory":
            _store = MemoryStore()
        elif backend == "file":
            _store = EncryptedFileStore()
        elif backend == "keyring":
            _store = KeyringStore()
        elif _keyring_usable():
            _store = KeyringStore()
        else:
            try:
                _store = EncryptedFileStore()
            except Exception:
                _store = MemoryStore()
        return _store


def get_secret_store() -> SecretStore:
    """The secret store callers use. Under multi-tenancy it's a per-workspace-scoped view
    of the backend; locally (flag off) it's the raw backend, byte-for-byte as before — so
    existing single-user secrets and the backend-selection contract are untouched."""
    raw = _backend_store()
    from . import tenancy
    return _WorkspaceScopedStore(raw) if tenancy.enforcing() else raw


def reset_store() -> None:
    """Drop the cached store (tests)."""
    global _store
    with _store_lock:
        _store = None
