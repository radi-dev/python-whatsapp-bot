"""Tests for the context storage backends.

Every backend must behave identically through the ``ContextStorage``
interface, so the same test-suite is run against each of them.

* MemoryStorage / SQLiteStorage - always run (stdlib only).
* SQLAlchemyStorage (sync Engine + AsyncEngine) - run if ``sqlalchemy``
  (and ``aiosqlite`` for the async engine) is installed.
* RedisStorage - run against ``fakeredis`` if installed, or against a real
  server when the ``WHATSAPP_TEST_REDIS_URL`` environment variable is set.
"""

import asyncio
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from python_whatsapp_bot.context_storage import (
    ContextLock,
    ContextLockNotSupportedError,
    ContextLockTimeoutError,
    ContextSerializationError,
    ContextStorage,
    ContextStorageError,
    MemoryStorage,
    RedisStorage,
    SQLAlchemyStorage,
    SQLiteStorage,
    Serializer,
    _redact_url,
)

try:
    import sqlalchemy  # noqa: F401

    HAS_SQLALCHEMY = True
except ImportError:  # pragma: no cover
    HAS_SQLALCHEMY = False

try:
    import aiosqlite  # noqa: F401
    import greenlet  # noqa: F401  (needed by sqlalchemy.ext.asyncio)

    HAS_AIOSQLITE = True
except ImportError:  # pragma: no cover
    HAS_AIOSQLITE = False

try:
    import fakeredis
    import lupa  # noqa: F401  (fakeredis[lua]: redis-py locks release via Lua scripts)

    HAS_FAKEREDIS = True
except ImportError:  # pragma: no cover
    HAS_FAKEREDIS = False

REAL_REDIS_URL = os.environ.get("WHATSAPP_TEST_REDIS_URL")


# --------------------------------------------------------------------------- #
# Backend factories
# --------------------------------------------------------------------------- #


def _memory(tmp_path, **kw):
    return MemoryStorage(warn=False, **kw)


def _sqlite(tmp_path, **kw):
    return SQLiteStorage(str(tmp_path / "ctx.db"), **kw)


def _sqlalchemy_sync(tmp_path, **kw):
    return SQLAlchemyStorage("sqlite:///{}".format(tmp_path / "sa.db"), **kw)


def _sqlalchemy_async(tmp_path, **kw):
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///{}".format(tmp_path / "sa_async.db"))
    return SQLAlchemyStorage(engine=engine, **kw)


def _redis(tmp_path, **kw):
    kw.pop("purge_interval", None)  # Redis expires keys itself; no sweep to configure
    if REAL_REDIS_URL:
        storage = RedisStorage(REAL_REDIS_URL, key_prefix="test:whatsapp:", **kw)
        storage.client.flushdb()
        return storage
    server = fakeredis.FakeServer()
    return RedisStorage(
        client=fakeredis.FakeRedis(server=server),
        async_client=fakeredis.FakeAsyncRedis(server=server),
        key_prefix="test:whatsapp:",
        **kw
    )


def _ttl_for(factory):
    """Redis TTLs are whole seconds; the others can use a fraction to keep tests fast."""
    return 1 if factory is _redis else 0.4


def _raw_count(storage):
    """Number of physical rows/keys, bypassing TTL filtering (None if not inspectable)."""
    if isinstance(storage, MemoryStorage):
        return len(storage._data)
    if isinstance(storage, SQLiteStorage):
        import sqlite3

        conn = sqlite3.connect(storage.path)
        try:
            return conn.execute("SELECT count(*) FROM {}".format(storage.table_name)).fetchone()[0]
        finally:
            conn.close()
    if isinstance(storage, SQLAlchemyStorage) and not storage._is_async:
        with storage.engine.connect() as conn:
            return conn.execute(sqlalchemy.select(sqlalchemy.func.count()).select_from(storage.table)).scalar()
    return None


BACKENDS = [
    pytest.param(_memory, id="memory"),
    pytest.param(_sqlite, id="sqlite"),
    pytest.param(
        _sqlalchemy_sync,
        id="sqlalchemy-sync",
        marks=pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed"),
    ),
    pytest.param(
        _redis,
        id="redis",
        marks=pytest.mark.skipif(
            not (HAS_FAKEREDIS or REAL_REDIS_URL), reason="fakeredis[lua] not installed"
        ),
    ),
]

ASYNC_BACKENDS = BACKENDS + [
    pytest.param(
        _sqlalchemy_async,
        id="sqlalchemy-async",
        marks=pytest.mark.skipif(
            not (HAS_SQLALCHEMY and HAS_AIOSQLITE), reason="sqlalchemy/aiosqlite not installed"
        ),
    ),
]


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    s = request.param(tmp_path)
    yield s
    s.close()


@pytest.fixture(params=BACKENDS)
def ttl_storage(request, tmp_path):
    """(storage, ttl): a storage whose records expire quickly, with auto-purge disabled."""
    ttl = _ttl_for(request.param)
    s = request.param(tmp_path, ttl=ttl, purge_interval=None)
    yield s, ttl
    s.close()


@pytest.fixture(params=ASYNC_BACKENDS)
def async_ttl_storage(request, tmp_path):
    ttl = _ttl_for(request.param)
    return request.param(tmp_path, ttl=ttl, purge_interval=None), ttl


@pytest.fixture(params=ASYNC_BACKENDS)
def async_storage(request, tmp_path):
    return request.param(tmp_path)


# --------------------------------------------------------------------------- #
# Shared behaviour - sync
# --------------------------------------------------------------------------- #


class TestStorageContract:
    def test_missing_key_returns_none(self, storage):
        assert storage.get("nobody") is None
        assert storage.exists("nobody") is False

    def test_set_get_roundtrip(self, storage):
        data = {"name": "Ada", "age": 36, "tags": ["a", "b"], "nested": {"x": 1.5, "ok": True, "n": None}}
        storage.set("123", data)
        assert storage.get("123") == data
        assert storage.exists("123") is True

    def test_overwrite(self, storage):
        storage.set("123", {"step": 1})
        storage.set("123", {"step": 2})
        assert storage.get("123") == {"step": 2}

    def test_delete(self, storage):
        storage.set("123", {"a": 1})
        storage.delete("123")
        assert storage.get("123") is None
        storage.delete("123")  # deleting a missing key must not raise

    def test_keys_are_isolated(self, storage):
        storage.set("1", {"who": "one"})
        storage.set("2", {"who": "two"})
        assert storage.get("1") == {"who": "one"}
        assert storage.get("2") == {"who": "two"}

    def test_returns_copies_not_shared_references(self, storage):
        storage.set("1", {"list": [1]})
        first = storage.get("1")
        first["list"].append(2)
        assert storage.get("1") == {"list": [1]}

    def test_unicode(self, storage):
        storage.set("1", {"msg": "héllo wörld 🚀 ✅"})
        assert storage.get("1") == {"msg": "héllo wörld 🚀 ✅"}

    def test_empty_dict(self, storage):
        storage.set("1", {})
        assert storage.get("1") == {}
        assert storage.exists("1") is True

    def test_non_serializable_value_raises(self, storage):
        with pytest.raises(ContextSerializationError):
            storage.set("1", {"obj": object()})
        assert storage.get("1") is None

    def test_ping(self, storage):
        storage.ping()

    def test_thread_safety(self, storage):
        errors = []

        def worker(n):
            try:
                for i in range(20):
                    storage.set("user{}".format(n), {"i": i, "n": n})
                    assert storage.get("user{}".format(n))["n"] == n
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        for n in range(8):
            assert storage.get("user{}".format(n)) == {"i": 19, "n": n}


# --------------------------------------------------------------------------- #
# Shared behaviour - async
# --------------------------------------------------------------------------- #


class TestStorageContractAsync:
    async def test_async_roundtrip(self, async_storage):
        assert await async_storage.aget("1") is None
        assert await async_storage.aexists("1") is False
        await async_storage.aset("1", {"a": [1, 2, {"b": "c"}]})
        assert await async_storage.aget("1") == {"a": [1, 2, {"b": "c"}]}
        assert await async_storage.aexists("1") is True
        await async_storage.aset("1", {"a": 2})
        assert await async_storage.aget("1") == {"a": 2}
        await async_storage.adelete("1")
        assert await async_storage.aget("1") is None
        await async_storage.adelete("1")
        await async_storage.aping()
        await async_storage.aclose()

    async def test_async_concurrent_writes(self, async_storage):
        async def worker(n):
            for i in range(10):
                await async_storage.aset("u{}".format(n), {"i": i, "n": n})

        await asyncio.gather(*(worker(n) for n in range(5)))
        for n in range(5):
            assert await async_storage.aget("u{}".format(n)) == {"i": 9, "n": n}
        await async_storage.aclose()


# --------------------------------------------------------------------------- #
# TTL / expiry
# --------------------------------------------------------------------------- #


class TestTTLContract:
    def test_expired_record_is_invisible(self, ttl_storage):
        storage, ttl = ttl_storage
        storage.set("u", {"a": 1})
        assert storage.get("u") == {"a": 1}
        assert storage.exists("u") is True
        time.sleep(ttl * 1.3)
        assert storage.get("u") is None
        assert storage.exists("u") is False

    def test_write_refreshes_expiry(self, ttl_storage):
        storage, ttl = ttl_storage
        storage.set("u", {"v": 1})
        time.sleep(ttl * 0.6)
        storage.set("u", {"v": 2})
        time.sleep(ttl * 0.6)  # 1.2 ttl since the first write, 0.6 since the last
        assert storage.get("u") == {"v": 2}

    def test_touch_refreshes_expiry(self, ttl_storage):
        storage, ttl = ttl_storage
        storage.set("u", {"v": 1})
        time.sleep(ttl * 0.6)
        storage.touch("u")
        time.sleep(ttl * 0.6)
        assert storage.get("u") == {"v": 1}

    def test_touch_does_not_resurrect_expired_record(self, ttl_storage):
        storage, ttl = ttl_storage
        storage.set("u", {"v": 1})
        time.sleep(ttl * 1.3)
        storage.touch("u")
        assert storage.get("u") is None
        storage.touch("missing")  # must not raise

    def test_purge_expired_deletes_only_expired(self, ttl_storage):
        storage, ttl = ttl_storage
        storage.set("old", {"v": 1})
        time.sleep(ttl * 1.3)
        storage.set("fresh", {"v": 2})
        deleted = storage.purge_expired()
        assert storage.get("old") is None
        assert storage.get("fresh") == {"v": 2}
        raw = _raw_count(storage)
        if raw is not None:  # SQL/memory: the row is physically gone
            assert deleted == 1
            assert raw == 1
        else:  # Redis expires keys itself
            assert deleted == 0

    def test_purge_removes_stale_lock_rows(self, ttl_storage):
        storage, ttl = ttl_storage
        crashed_worker = storage.lock("u", timeout=0.2, blocking_timeout=0.1)
        assert crashed_worker.acquire()  # never released
        time.sleep(0.3)
        storage.purge_expired()
        fresh = storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert fresh.acquire(blocking=False) is True
        fresh.release()

    def test_delete_and_overwrite_still_work(self, ttl_storage):
        storage, ttl = ttl_storage
        storage.set("u", {"v": 1})
        storage.set("u", {"v": 2})
        assert storage.get("u") == {"v": 2}
        storage.delete("u")
        assert storage.get("u") is None


class TestTTLContractAsync:
    async def test_async_expiry_touch_and_purge(self, async_ttl_storage):
        storage, ttl = async_ttl_storage
        await storage.aset("u", {"v": 1})
        await asyncio.sleep(ttl * 0.6)
        await storage.atouch("u")
        await asyncio.sleep(ttl * 0.6)
        assert await storage.aget("u") == {"v": 1}
        await asyncio.sleep(ttl * 1.3)
        assert await storage.aget("u") is None
        assert await storage.aexists("u") is False
        assert await storage.apurge_expired() >= 0
        await storage.aclose()


class TestTTLSpecifics:
    @pytest.mark.parametrize("factory", [_memory, _sqlite, pytest.param(
        _sqlalchemy_sync, marks=pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed"))],
        ids=["memory", "sqlite", "sqlalchemy"])
    def test_automatic_purge_runs_on_writes(self, tmp_path, factory):
        storage = factory(tmp_path, ttl=0.3, purge_interval=0.5)
        storage.set("old", {})
        assert _raw_count(storage) == 1
        time.sleep(0.6)  # "old" expired and the purge interval elapsed
        storage.set("new", {})  # triggers the sweep
        assert _raw_count(storage) == 1
        assert storage.get("new") == {} and storage.get("old") is None

    @pytest.mark.parametrize("factory", [_memory, _sqlite], ids=["memory", "sqlite"])
    def test_automatic_purge_is_throttled(self, tmp_path, factory):
        storage = factory(tmp_path, ttl=0.1, purge_interval=3600)
        storage.set("old", {})
        time.sleep(0.2)
        storage.set("new", {})  # interval not elapsed: no sweep yet
        assert _raw_count(storage) == 2
        assert storage.purge_expired() == 1
        assert _raw_count(storage) == 1
        assert storage.get("old") is None and storage.get("new") == {}

    def test_no_ttl_means_no_expiry(self, tmp_path):
        storage = _sqlite(tmp_path)
        storage.set("u", {"v": 1})
        storage.touch("u")  # no-op
        assert storage.purge_expired() == 0
        assert storage.get("u") == {"v": 1}

    @pytest.mark.parametrize("bad", [0, -1, "60", True])
    def test_invalid_ttl_rejected(self, tmp_path, bad):
        with pytest.raises(ValueError):
            SQLiteStorage(str(tmp_path / "x.db"), ttl=bad)
        with pytest.raises(ValueError):
            MemoryStorage(warn=False, purge_interval=bad)

    def test_touch_coalesces_writes(self, tmp_path):
        """Within 10% of the TTL the timestamp is left alone, so chatty users do not
        cause a write per message."""
        import sqlite3

        storage = _sqlite(tmp_path, ttl=100)  # threshold = 10s
        storage.set("u", {})
        conn = sqlite3.connect(storage.path)
        before = conn.execute("SELECT updated_at FROM whatsapp_user_context").fetchone()[0]
        storage.touch("u")
        after = conn.execute("SELECT updated_at FROM whatsapp_user_context").fetchone()[0]
        conn.close()
        assert before == after

    @pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis[lua] not installed")
    def test_redis_ttl_is_set_on_keys(self):
        client = fakeredis.FakeRedis()
        storage = RedisStorage(client=client, key_prefix="p:", ttl=120)
        storage.set("1", {"a": 1})
        assert 0 < client.ttl("p:1") <= 120
        client.expire("p:1", 5)
        storage.touch("1")
        assert client.ttl("p:1") > 5

    def test_backend_without_ttl_support_must_implement_touch(self):
        class Minimal(ContextStorage):
            def __init__(self):
                super().__init__(ttl=10)

            def get(self, key):
                return None

            def set(self, key, data):
                pass

            def delete(self, key):
                pass

        with pytest.raises(NotImplementedError):
            Minimal().touch("x")
        assert Minimal().purge_expired() == 0


# --------------------------------------------------------------------------- #
# Per-user locks - sync
# --------------------------------------------------------------------------- #


class TestLockContract:
    def test_supports_locking(self, storage):
        assert storage.supports_locking is True
        assert isinstance(storage.lock("u"), ContextLock)

    def test_acquire_release_reacquire(self, storage):
        lock = storage.lock("u", timeout=5, blocking_timeout=0.2)
        assert lock.locked is False
        assert lock.acquire() is True
        assert lock.locked is True
        lock.release()
        assert lock.locked is False
        assert lock.acquire() is True
        lock.release()
        lock.release()  # releasing twice is a no-op

    def test_second_holder_is_blocked_until_release(self, storage):
        first = storage.lock("u", timeout=5, blocking_timeout=0.2)
        second = storage.lock("u", timeout=5, blocking_timeout=0.2)
        assert first.acquire()
        assert second.acquire(blocking=False) is False
        t0 = time.monotonic()
        assert second.acquire() is False  # waits ~0.2s then gives up
        assert 0.15 <= time.monotonic() - t0 < 2
        first.release()
        assert second.acquire() is True
        second.release()

    def test_waiter_gets_lock_when_released(self, storage):
        first = storage.lock("u", timeout=5, blocking_timeout=2)
        second = storage.lock("u", timeout=5, blocking_timeout=2)
        assert first.acquire()
        threading.Timer(0.2, first.release).start()
        t0 = time.monotonic()
        assert second.acquire() is True
        assert 0.1 <= time.monotonic() - t0 < 1.5
        second.release()

    def test_different_users_do_not_block_each_other(self, storage):
        a = storage.lock("a", timeout=5, blocking_timeout=0.1)
        b = storage.lock("b", timeout=5, blocking_timeout=0.1)
        assert a.acquire() and b.acquire()
        a.release()
        b.release()

    def test_expired_lock_can_be_taken_over(self, storage):
        stale = storage.lock("u", timeout=0.2, blocking_timeout=0.1)
        fresh = storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert stale.acquire()
        assert fresh.acquire(blocking=False) is False
        time.sleep(0.3)
        assert stale.expired is True
        assert fresh.acquire() is True
        # The stale owner must not be able to release the new owner's lock.
        stale.release()
        third = storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert third.acquire(blocking=False) is False
        fresh.release()
        assert third.acquire(blocking=False) is True
        third.release()

    def test_release_from_another_thread(self, storage):
        """The dispatcher acquires in the webhook thread and releases in a worker thread."""
        lock = storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert lock.acquire()
        t = threading.Thread(target=lock.release)
        t.start()
        t.join()
        other = storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert other.acquire(blocking=False) is True
        other.release()

    def test_context_manager(self, storage):
        with storage.lock("u", timeout=5, blocking_timeout=0.1) as lock:
            assert lock.locked
            with pytest.raises(ContextLockTimeoutError) as exc:
                with storage.lock("u", timeout=5, blocking_timeout=0.1):
                    pass  # pragma: no cover
            assert exc.value.key == "u"
        assert lock.locked is False
        with storage.lock("u", timeout=5, blocking_timeout=0.1):
            pass

    def test_mutual_exclusion_under_thread_contention(self, storage):
        counter = {"n": 0}
        inside = {"n": 0, "max": 0}
        errors = []

        def worker():
            try:
                for _ in range(10):
                    with storage.lock("u", timeout=5, blocking_timeout=10):
                        inside["n"] += 1
                        inside["max"] = max(inside["max"], inside["n"])
                        v = counter["n"]
                        time.sleep(0.002)
                        counter["n"] = v + 1
                        inside["n"] -= 1
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert inside["max"] == 1
        assert counter["n"] == 50


# --------------------------------------------------------------------------- #
# Per-user locks - async
# --------------------------------------------------------------------------- #


class TestLockContractAsync:
    async def test_async_acquire_release(self, async_storage):
        first = async_storage.lock("u", timeout=5, blocking_timeout=0.2)
        second = async_storage.lock("u", timeout=5, blocking_timeout=0.2)
        assert await first.aacquire() is True
        assert await second.aacquire(blocking=False) is False
        assert await second.aacquire() is False
        await first.arelease()
        assert await second.aacquire() is True
        await second.arelease()
        await async_storage.aclose()

    async def test_async_context_manager_and_timeout(self, async_storage):
        async with async_storage.lock("u", timeout=5, blocking_timeout=0.1) as lock:
            assert lock.locked
            with pytest.raises(ContextLockTimeoutError):
                async with async_storage.lock("u", timeout=5, blocking_timeout=0.1):
                    pass  # pragma: no cover
        assert lock.locked is False
        await async_storage.aclose()

    async def test_async_mutual_exclusion(self, async_storage):
        counter = {"n": 0}
        inside = {"n": 0, "max": 0}

        async def worker():
            for _ in range(5):
                async with async_storage.lock("u", timeout=5, blocking_timeout=10):
                    inside["n"] += 1
                    inside["max"] = max(inside["max"], inside["n"])
                    v = counter["n"]
                    await asyncio.sleep(0.002)
                    counter["n"] = v + 1
                    inside["n"] -= 1

        await asyncio.gather(*(worker() for _ in range(4)))
        assert inside["max"] == 1
        assert counter["n"] == 20
        await async_storage.aclose()

    async def test_async_expired_lock_taken_over(self, async_storage):
        stale = async_storage.lock("u", timeout=0.2, blocking_timeout=0.1)
        fresh = async_storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert await stale.aacquire()
        await asyncio.sleep(0.3)
        assert await fresh.aacquire() is True
        await stale.arelease()  # must not release fresh's lock
        third = async_storage.lock("u", timeout=5, blocking_timeout=0.1)
        assert await third.aacquire(blocking=False) is False
        await fresh.arelease()
        await async_storage.aclose()


# --------------------------------------------------------------------------- #
# Backend specifics
# --------------------------------------------------------------------------- #


class TestMemoryStorage:
    def test_keys_and_clear(self):
        s = MemoryStorage(warn=False)
        s.set("a", {})
        s.set("b", {})
        assert sorted(s.keys()) == ["a", "b"]
        s.clear()
        assert s.keys() == []

    def test_warns_by_default(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="python_whatsapp_bot.context_storage"):
            MemoryStorage()
        assert "NOT shared between worker processes" in caplog.text


class TestSQLiteStorage:
    def test_custom_table_name(self, tmp_path):
        s = SQLiteStorage(str(tmp_path / "x.db"), table_name="my_ctx")
        s.set("1", {"a": 1})
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        rows = conn.execute("SELECT key, data FROM my_ctx").fetchall()
        conn.close()
        assert rows == [("1", '{"a": 1}')]

    def test_invalid_table_name_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            SQLiteStorage(str(tmp_path / "x.db"), table_name="ctx; DROP TABLE users")

    def test_data_shared_between_instances(self, tmp_path):
        """Two instances on the same file (think: two workers) see the same data."""
        path = str(tmp_path / "shared.db")
        a = SQLiteStorage(path)
        b = SQLiteStorage(path)
        a.set("1", {"from": "a"})
        assert b.get("1") == {"from": "a"}
        b.set("1", {"from": "b"})
        assert a.get("1") == {"from": "b"}

    def test_data_shared_between_processes(self, tmp_path):
        """The real multi-worker scenario: separate OS processes share the context."""
        path = str(tmp_path / "procs.db")
        src = str(os.path.join(os.path.dirname(__file__), "..", "src"))
        script = textwrap.dedent(
            """
            import sys, json
            from python_whatsapp_bot.context_storage import SQLiteStorage
            path, worker, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
            s = SQLiteStorage(path)
            for i in range(n):
                s.set("user_{}_{}".format(worker, i), {"worker": worker, "i": i})
            print(json.dumps(s.get("seed")))
            """
        )
        SQLiteStorage(path).set("seed", {"planted": "by parent"})
        env = dict(os.environ, PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script, path, "w{}".format(w), "15"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for w in range(4)
        ]
        for p in procs:
            out, err = p.communicate(timeout=60)
            assert p.returncode == 0, err.decode()
            assert out.decode().strip() == '{"planted": "by parent"}'

        parent = SQLiteStorage(path)
        for w in range(4):
            for i in range(15):
                assert parent.get("user_w{}_{}".format(w, i)) == {"worker": "w{}".format(w), "i": i}


    def test_lock_serializes_processes(self, tmp_path):
        """4 OS processes increment one user's counter under the lock: no lost updates."""
        path = str(tmp_path / "lock.db")
        src = str(os.path.join(os.path.dirname(__file__), "..", "src"))
        script = textwrap.dedent(
            """
            import sys
            from python_whatsapp_bot.context_storage import SQLiteStorage
            s = SQLiteStorage(sys.argv[1])
            for _ in range(int(sys.argv[2])):
                with s.lock("user", timeout=10, blocking_timeout=30):
                    data = s.get("user") or {"n": 0}
                    data["n"] += 1
                    s.set("user", data)
            """
        )
        env = dict(os.environ, PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
        procs = [
            subprocess.Popen([sys.executable, "-c", script, path, "25"], stderr=subprocess.PIPE, env=env)
            for _ in range(4)
        ]
        for p in procs:
            _, err = p.communicate(timeout=120)
            assert p.returncode == 0, err.decode()
        assert SQLiteStorage(path).get("user") == {"n": 100}

    def test_lock_table_name(self, tmp_path):
        s = SQLiteStorage(str(tmp_path / "x.db"), table_name="ctx")
        assert s.lock_table_name == "ctx_locks"
        with s.lock("1"):
            import sqlite3

            conn = sqlite3.connect(str(tmp_path / "x.db"))
            assert conn.execute("SELECT count(*) FROM ctx_locks").fetchone()[0] == 1
            conn.close()


@pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy not installed")
class TestSQLAlchemyStorage:
    def test_requires_url_or_engine(self):
        with pytest.raises(ValueError):
            SQLAlchemyStorage()

    def test_existing_engine_is_reused(self, tmp_path):
        engine = sqlalchemy.create_engine("sqlite:///{}".format(tmp_path / "e.db"))
        s = SQLAlchemyStorage(engine=engine, table_name="ctx_custom")
        assert s.engine is engine
        s.set("1", {"a": 1})
        with engine.connect() as conn:
            rows = conn.execute(sqlalchemy.text("SELECT key, data FROM ctx_custom")).fetchall()
        assert [tuple(r) for r in rows] == [("1", '{"a": 1}')]

    def test_generic_upsert_path(self, tmp_path):
        """Force the portable update-then-insert path used for dialects without upsert."""
        s = SQLAlchemyStorage("sqlite:///{}".format(tmp_path / "g.db"))
        s._dialect = "unknown_dialect"
        s.set("1", {"v": 1})
        s.set("1", {"v": 2})
        assert s.get("1") == {"v": 2}

    def test_create_table_false_fails_without_table(self, tmp_path):
        s = SQLAlchemyStorage("sqlite:///{}".format(tmp_path / "nt.db"), create_table=False)
        with pytest.raises(sqlalchemy.exc.OperationalError):
            s.get("1")

    @pytest.mark.skipif(not HAS_AIOSQLITE, reason="aiosqlite not installed")
    def test_async_engine_rejects_sync_calls(self, tmp_path):
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///{}".format(tmp_path / "a.db"))
        s = SQLAlchemyStorage(engine=engine)
        with pytest.raises(ContextStorageError):
            s.get("1")

    def test_repr_redacts_password(self, tmp_path):
        s = SQLAlchemyStorage("sqlite:///{}".format(tmp_path / "r.db"))
        assert "SQLAlchemyStorage" in repr(s)


@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis[lua] not installed")
class TestRedisStorage:
    def test_requires_some_client(self):
        with pytest.raises(ValueError):
            RedisStorage()

    def test_key_prefix_and_ttl(self):
        client = fakeredis.FakeRedis()
        s = RedisStorage(client=client, key_prefix="p:", ttl=120)
        s.set("1", {"a": 1})
        assert client.get("p:1") == b'{"a": 1}'
        assert 0 < client.ttl("p:1") <= 120

    def test_sync_only_client_still_supports_async(self):
        s = RedisStorage(client=fakeredis.FakeRedis())

        async def run():
            await s.aset("1", {"a": 1})
            return await s.aget("1")

        assert asyncio.run(run()) == {"a": 1}

    def test_async_only_client_rejects_sync_calls(self):
        s = RedisStorage(async_client=fakeredis.FakeAsyncRedis())
        with pytest.raises(ContextStorageError):
            s.get("1")

    def test_repr_redacts_password(self):
        s = RedisStorage("redis://:s3cret@localhost:6379/0")
        assert "s3cret" not in repr(s)


# --------------------------------------------------------------------------- #
# Extensibility & helpers
# --------------------------------------------------------------------------- #


class TestCustomBackend:
    def test_minimal_subclass_gets_async_and_exists_for_free(self):
        class DictStorage(ContextStorage):
            def __init__(self):
                super().__init__()
                self.d = {}

            def get(self, key):
                raw = self.d.get(key)
                return self._loads(raw) if raw is not None else None

            def set(self, key, data):
                self.d[key] = self._dumps(data)

            def delete(self, key):
                self.d.pop(key, None)

        s = DictStorage()
        assert s.exists("1") is False
        s.set("1", {"a": 1})
        assert s.exists("1") is True

        async def run():
            await s.aset("2", {"b": 2})
            return await s.aget("2"), await s.aexists("1")

        assert asyncio.run(run()) == ({"b": 2}, True)

    def test_backend_without_lock_support(self):
        class NoLock(ContextStorage):
            def get(self, key):
                return None

            def set(self, key, data):
                pass

            def delete(self, key):
                pass

        s = NoLock()
        assert s.supports_locking is False
        with pytest.raises(ContextLockNotSupportedError):
            s.lock("1")

    def test_custom_lock_only_needs_two_primitives(self):
        calls = []

        class MyLock(ContextLock):
            def _try_acquire(self):
                calls.append("acquire")
                return True

            def _release(self):
                calls.append("release")

        class WithLock(MemoryStorage):
            def lock(self, key, **kwargs):
                return MyLock(key, **kwargs)

        s = WithLock(warn=False)
        assert s.supports_locking is True
        with s.lock("1"):
            pass

        async def run():
            async with s.lock("1"):
                pass

        asyncio.run(run())
        assert calls == ["acquire", "release"] * 2

    def test_abstract_methods_enforced(self):
        class Broken(ContextStorage):
            pass

        with pytest.raises(TypeError):
            Broken()

    def test_custom_serializer(self):
        class UpperSerializer(Serializer):
            def dumps(self, data):
                return super().dumps(data).upper()

            def loads(self, raw):
                return super().loads(raw.lower())

        s = MemoryStorage(serializer=UpperSerializer(), warn=False)
        s.set("1", {"k": "v"})
        assert s._data["1"] == '{"K": "V"}'
        assert s.get("1") == {"k": "v"}


def test_redact_url():
    assert _redact_url("redis://:pw@host:6379/0") == "redis://***@host:6379/0"
    assert _redact_url("postgresql://u:p@h/db") == "postgresql://***@h/db"
    assert _redact_url("sqlite:///x.db") == "sqlite:///x.db"
    assert _redact_url(None) is None
