"""Tests for the lazy ChromaDB accessor + its double-checked locking.

The real PersistentClient is faked so nothing touches disk; we only verify the
singleton contract: repeated calls return the SAME instance, and concurrent
first-callers do not each build a client (the lock collapses the race to one
construction).
"""
import importlib
import sys
import threading
import time
import types


def _install_fake_chromadb(monkeypatch, build_delay=0.0):
    """Install a fake `chromadb` module whose PersistentClient counts builds.

    ``build_delay`` widens the construction window so that, without a lock,
    multiple racing first-callers would each enter the build and bump the
    counter. With double-checked locking the count stays 1.
    """
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, path=None):
            calls["n"] += 1
            if build_delay:
                time.sleep(build_delay)
            self.path = path

    fake = types.ModuleType("chromadb")
    fake.PersistentClient = _FakeClient
    monkeypatch.setitem(sys.modules, "chromadb", fake)
    return calls


def _fresh_chroma(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma_db"))
    import ocd_core.config as c
    importlib.reload(c)
    import ocd_core.chroma as ch
    importlib.reload(ch)
    return ch


def test_get_chroma_returns_same_instance(monkeypatch, tmp_path):
    calls = _install_fake_chromadb(monkeypatch)
    ch = _fresh_chroma(monkeypatch, tmp_path)
    a = ch._get_chroma()
    b = ch._get_chroma()
    assert a is b
    assert calls["n"] == 1


def test_concurrent_first_callers_share_one_client(monkeypatch, tmp_path):
    # A non-trivial build window guarantees a real race: a lockless _get_chroma
    # would let several threads past the `is None` check and build duplicates.
    calls = _install_fake_chromadb(monkeypatch, build_delay=0.05)
    ch = _fresh_chroma(monkeypatch, tmp_path)

    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # maximize the chance of a real race on first build
        results.append(ch._get_chroma())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert all(r is results[0] for r in results)
    # Double-checked locking must collapse the race to a single construction.
    assert calls["n"] == 1
