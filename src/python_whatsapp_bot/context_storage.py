"""Pluggable storage backends for user conversation context.

Every backend implements the same tiny interface (:class:`ContextStorage`), so
the rest of the library (and your handlers) never need to know *where* the
context lives.  Pick a backend, hand it to :class:`~python_whatsapp_bot.Whatsapp`
and the ``context.user_data`` dict in your handlers "just works"::

    from python_whatsapp_bot import Whatsapp, RedisStorage

    wa_bot = Whatsapp(number_id, token, context_storage=RedisStorage("redis://localhost"))

Built-in backends:

* :class:`MemoryStorage`     - process-local dict. Tests / single-worker dev only.
* :class:`SQLiteStorage`     - stdlib ``sqlite3`` file. Multi-worker safe on one host.
* :class:`RedisStorage`      - ``redis`` package. Native sync *and* async clients.
* :class:`SQLAlchemyStorage` - Postgres / MySQL / SQLite / anything SQLAlchemy speaks.

Writing your own backend only requires subclassing :class:`ContextStorage` and
implementing :meth:`~ContextStorage.get`, :meth:`~ContextStorage.set` and
:meth:`~ContextStorage.delete` (plus :meth:`~ContextStorage.lock` if you want
per-user locking - every built-in backend has it).

Expiry (TTL)
------------

Every backend accepts ``ttl=<seconds>``: a user's record disappears ``ttl``
seconds after that user's last activity (any read or write refreshes it). With
Redis this is the server's own key expiry; the SQL and memory backends hide
expired rows immediately and physically delete them in a throttled sweep that
runs on writes (``purge_interval``), or whenever you call
:meth:`ContextStorage.purge_expired` from a cron job.

Per-user locking
----------------

To prevent two workers from processing updates of the *same* user at the same
time (and overwriting each other's ``user_data``), the dispatcher takes a
per-user :class:`ContextLock` for the duration of each update. Locks have a
TTL (``timeout``) so a crashed worker can never block a user forever, and a
bounded wait (``blocking_timeout``); if the wait expires a
:class:`ContextLockTimeoutError` is raised so the webhook can answer with a
non-2xx status and WhatsApp re-delivers the message later.
"""

import asyncio
import datetime
import functools
import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TABLE_NAME = "whatsapp_user_context"
DEFAULT_KEY_PREFIX = "whatsapp:user_context:"
DEFAULT_LOCK_TIMEOUT = 60.0  # seconds a lock may be held before it expires
DEFAULT_LOCK_WAIT = 10.0  # seconds to wait for a busy lock before giving up
DEFAULT_LOCK_RETRY = 0.1  # seconds between acquisition attempts while waiting
DEFAULT_PURGE_INTERVAL = 300.0  # seconds between automatic sweeps of expired rows


class ContextStorageError(Exception):
    """Base class for context storage problems."""


class ContextStorageNotConfiguredError(ContextStorageError, RuntimeError):
    """Raised when the context is used but no storage backend was configured.

    The library refuses to silently fall back to process memory, because that
    breaks as soon as more than one worker process is running.
    """

    DEFAULT_MESSAGE = (
        "No context storage configured. A handler (or your code) is using the "
        "user context, which must live in external storage so that it works "
        "across multiple worker processes. Configure one, for example:\n\n"
        "    from python_whatsapp_bot import Whatsapp, SQLiteStorage\n"
        "    bot = Whatsapp(number_id, token, context_storage=SQLiteStorage('bot.db'))\n\n"
        "or globally:\n\n"
        "    from python_whatsapp_bot import set_context_storage, RedisStorage\n"
        "    set_context_storage(RedisStorage('redis://localhost:6379/0'))\n\n"
        "Available backends: MemoryStorage (single process only), SQLiteStorage, "
        "RedisStorage, SQLAlchemyStorage (Postgres/MySQL/...), or your own "
        "ContextStorage subclass."
    )

    def __init__(self, message=None):
        # type: (Optional[str]) -> None
        super().__init__(message or self.DEFAULT_MESSAGE)


class ContextSerializationError(ContextStorageError, TypeError):
    """Raised when user data cannot be serialized for storage."""


class ContextLockError(ContextStorageError):
    """Base class for per-user lock problems."""


class ContextLockTimeoutError(ContextLockError, TimeoutError):
    """Raised when a user's context lock could not be acquired in time.

    Another worker is still processing an update for this user. Nothing has
    been processed for the current update yet, so it is safe to let your
    webhook answer with a non-2xx status: WhatsApp re-delivers the message
    with exponential backoff.
    """

    def __init__(self, key, waited):
        # type: (str, float) -> None
        self.key = key
        self.waited = waited
        super().__init__(
            "Could not acquire the context lock for user {!r} within {:g}s: another worker "
            "is still processing an update for this user. Return a non-2xx response so "
            "WhatsApp retries the message, or raise context_lock_wait.".format(key, waited)
        )


class ContextLockNotSupportedError(ContextLockError, NotImplementedError):
    """Raised when a storage backend does not implement per-user locking."""

    def __init__(self, storage):
        # type: (Any) -> None
        super().__init__(
            "{!r} does not implement per-user locking (ContextStorage.lock). Implement it "
            "in your backend, or disable locking with Whatsapp(..., context_lock=False) if "
            "you accept that concurrent updates of the same user may overwrite each "
            "other's context.".format(storage)
        )


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


class Serializer:
    """Converts the ``user_data`` dict to/from a string for storage.

    The default implementation is JSON. Provide your own object with ``dumps``
    and ``loads`` methods to a backend if you need something else.
    """

    def dumps(self, data):
        # type: (Dict[str, Any]) -> str
        try:
            return json.dumps(data, ensure_ascii=False, sort_keys=True, default=self._default)
        except (TypeError, ValueError) as exc:
            raise ContextSerializationError(
                "Context user_data must be JSON serializable (str, int, float, "
                "bool, None, list, dict). Store a plain representation of the "
                "value instead, or pass a custom serializer to the storage "
                "backend. Original error: {}".format(exc)
            ) from exc

    def loads(self, raw):
        # type: (str) -> Dict[str, Any]
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ContextSerializationError(
                "Stored context is not a JSON object: {!r}".format(raw[:80])
            )
        return data

    @staticmethod
    def _default(obj):
        # type: (Any) -> Any
        raise TypeError("Object of type {} is not JSON serializable".format(type(obj).__name__))


JSONSerializer = Serializer  # explicit alias


# --------------------------------------------------------------------------- #
# Locks
# --------------------------------------------------------------------------- #


class ContextLock(ABC):
    """A distributed, expiring lock on one user's context.

    Subclasses implement the two primitives :meth:`_try_acquire` (non-blocking,
    must atomically take over an *expired* lock) and :meth:`_release` (must only
    release if the lock is still owned). Waiting/retrying, expiry bookkeeping and
    the async variants are handled here. Override ``_atry_acquire`` /
    ``_arelease`` for a native async client.

    A lock acquired with the sync API must be released with the sync API, and
    likewise for async.

    Args:
        key: The user id being locked.
        timeout: TTL in seconds. The lock expires after this even if never
            released, so a crashed worker cannot block a user forever. Must be
            longer than your slowest handler.
        blocking_timeout: Max seconds :meth:`acquire` waits for a busy lock.
        retry_interval: Seconds between attempts while waiting.
    """

    def __init__(self, key, timeout=DEFAULT_LOCK_TIMEOUT, blocking_timeout=DEFAULT_LOCK_WAIT, retry_interval=DEFAULT_LOCK_RETRY):
        # type: (str, float, float, float) -> None
        self.key = str(key)
        self.timeout = float(timeout)
        self.blocking_timeout = float(blocking_timeout)
        self.retry_interval = float(retry_interval)
        self.token = uuid.uuid4().hex  # type: str
        self._acquired_at = None  # type: Optional[float]

    # -- primitives to implement ------------------------------------------- #

    @abstractmethod
    def _try_acquire(self):
        # type: () -> bool
        """Single non-blocking attempt. True if the lock is now ours."""

    @abstractmethod
    def _release(self):
        # type: () -> None
        """Release if (and only if) we still own the lock."""

    async def _atry_acquire(self):
        # type: () -> bool
        return await ContextStorage._run_sync(self._try_acquire)

    async def _arelease(self):
        # type: () -> None
        await ContextStorage._run_sync(self._release)

    # -- public API ------------------------------------------------------- #

    @property
    def locked(self):
        # type: () -> bool
        """True between a successful acquire and release (locally tracked)."""
        return self._acquired_at is not None

    @property
    def held_for(self):
        # type: () -> float
        """Seconds since acquisition (0 if not held)."""
        return time.monotonic() - self._acquired_at if self._acquired_at is not None else 0.0

    @property
    def expired(self):
        # type: () -> bool
        """True if we held the lock longer than its TTL, i.e. it may be gone."""
        return self.locked and self.held_for > self.timeout

    def acquire(self, blocking=True, blocking_timeout=None):
        # type: (bool, Optional[float]) -> bool
        """Acquire the lock. Returns False if it could not be acquired in time."""
        wait = self.blocking_timeout if blocking_timeout is None else float(blocking_timeout)
        deadline = time.monotonic() + wait
        while True:
            if self._try_acquire():
                self._acquired_at = time.monotonic()
                return True
            remaining = deadline - time.monotonic()
            if not blocking or remaining <= 0:
                return False
            time.sleep(min(self.retry_interval, remaining))

    async def aacquire(self, blocking=True, blocking_timeout=None):
        # type: (bool, Optional[float]) -> bool
        wait = self.blocking_timeout if blocking_timeout is None else float(blocking_timeout)
        deadline = time.monotonic() + wait
        while True:
            if await self._atry_acquire():
                self._acquired_at = time.monotonic()
                return True
            remaining = deadline - time.monotonic()
            if not blocking or remaining <= 0:
                return False
            await asyncio.sleep(min(self.retry_interval, remaining))

    def release(self):
        # type: () -> None
        """Release the lock. Safe to call if not held (no-op)."""
        if self._acquired_at is None:
            return
        try:
            self._release()
        finally:
            self._acquired_at = None

    async def arelease(self):
        # type: () -> None
        if self._acquired_at is None:
            return
        try:
            await self._arelease()
        finally:
            self._acquired_at = None

    # -- context manager ---------------------------------------------------- #

    def __enter__(self):
        # type: () -> "ContextLock"
        if not self.acquire():
            raise ContextLockTimeoutError(self.key, self.blocking_timeout)
        return self

    def __exit__(self, exc_type, exc, tb):
        # type: (Any, Any, Any) -> None
        self.release()

    async def __aenter__(self):
        # type: () -> "ContextLock"
        if not await self.aacquire():
            raise ContextLockTimeoutError(self.key, self.blocking_timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # type: (Any, Any, Any) -> None
        await self.arelease()

    def __repr__(self):
        # type: () -> str
        return "<{} key={!r} locked={}>".format(self.__class__.__name__, self.key, self.locked)


class _MemoryLock(ContextLock):
    """Process-local expiring lock (used by :class:`MemoryStorage`)."""

    def __init__(self, table, mutex, key, **kwargs):
        # type: (Dict[str, tuple], threading.Lock, str, **Any) -> None
        super().__init__(key, **kwargs)
        self._table = table
        self._mutex = mutex

    def _try_acquire(self):
        # type: () -> bool
        now = time.time()
        with self._mutex:
            current = self._table.get(self.key)
            if current is None or current[1] <= now:
                self._table[self.key] = (self.token, now + self.timeout)
                return True
        return False

    def _release(self):
        # type: () -> None
        with self._mutex:
            current = self._table.get(self.key)
            if current is not None and current[0] == self.token:
                del self._table[self.key]


class _SQLiteLock(ContextLock):
    """Expiring lock stored in a ``<table>_locks`` table (used by :class:`SQLiteStorage`)."""

    def __init__(self, storage, key, **kwargs):
        # type: (SQLiteStorage, str, **Any) -> None
        super().__init__(key, **kwargs)
        self._storage = storage

    def _try_acquire(self):
        # type: () -> bool
        now = time.time()
        table = self._storage.lock_table_name
        conn = self._storage._connect()
        try:
            try:
                conn.execute(
                    "INSERT INTO {} (key, token, expires_at) VALUES (?, ?, ?)".format(table),
                    (self.key, self.token, now + self.timeout),
                )
                return True
            except sqlite3.IntegrityError:
                # Held by someone: take it over only if it has expired.
                cur = conn.execute(
                    "UPDATE {} SET token = ?, expires_at = ? WHERE key = ? AND expires_at <= ?".format(table),
                    (self.token, now + self.timeout, self.key, now),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def _release(self):
        # type: () -> None
        conn = self._storage._connect()
        try:
            cur = conn.execute(
                "DELETE FROM {} WHERE key = ? AND token = ?".format(self._storage.lock_table_name),
                (self.key, self.token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "Context lock for user %s expired before release (held %.1fs > timeout %.0fs); "
                    "another worker may have processed this user concurrently.",
                    self.key, self.held_for, self.timeout,
                )
        finally:
            conn.close()


class _RedisLock(ContextLock):
    """Wraps redis-py's ``Lock`` (SET NX PX + Lua release/extend)."""

    def __init__(self, storage, key, **kwargs):
        # type: (RedisStorage, str, **Any) -> None
        super().__init__(key, **kwargs)
        self._storage = storage
        self._sync_lock = None
        self._async_lock = None

    def _make_lock(self, client):
        # type: (Any) -> Any
        # thread_local=False: the dispatcher acquires in the webhook thread and
        # releases in the worker thread.
        return client.lock(
            self._storage.key_prefix + "lock:" + self.key,
            timeout=self.timeout,
            blocking=False,
            thread_local=False,
        )

    def _warn_not_owned(self):
        # type: () -> None
        logger.warning(
            "Context lock for user %s expired before release (held %.1fs > timeout %.0fs); "
            "another worker may have processed this user concurrently.",
            self.key, self.held_for, self.timeout,
        )

    def _try_acquire(self):
        # type: () -> bool
        if self._sync_lock is None:
            self._sync_lock = self._make_lock(self._storage.client)
        return bool(self._sync_lock.acquire(blocking=False))

    def _release(self):
        # type: () -> None
        if self._sync_lock is None:
            return
        from redis.exceptions import LockError

        try:
            self._sync_lock.release()
        except LockError:
            self._warn_not_owned()

    async def _atry_acquire(self):
        # type: () -> bool
        client = self._storage.async_client
        if client is None:
            return await super()._atry_acquire()
        if self._async_lock is None:
            self._async_lock = self._make_lock(client)
        return bool(await self._async_lock.acquire(blocking=False))

    async def _arelease(self):
        # type: () -> None
        if self._async_lock is None:
            return await super()._arelease()
        from redis.exceptions import LockError

        try:
            await self._async_lock.release()
        except LockError:
            self._warn_not_owned()


class _SQLAlchemyLock(ContextLock):
    """Expiring lock stored in a ``<table>_locks`` table (used by :class:`SQLAlchemyStorage`)."""

    def __init__(self, storage, key, **kwargs):
        # type: (SQLAlchemyStorage, str, **Any) -> None
        super().__init__(key, **kwargs)
        self._storage = storage

    def _acquire_with(self, conn):
        # type: (Any) -> bool
        """Runs inside a transaction on a *sync* connection."""
        sa = _import_sqlalchemy()
        table = self._storage.lock_table
        now = time.time()
        try:
            with conn.begin_nested():
                conn.execute(sa.insert(table).values(key=self.key, token=self.token, expires_at=now + self.timeout))
            return True
        except sa.exc.IntegrityError:
            result = conn.execute(
                sa.update(table)
                .where(table.c.key == self.key, table.c.expires_at <= now)
                .values(token=self.token, expires_at=now + self.timeout)
            )
            return result.rowcount == 1

    def _release_with(self, conn):
        # type: (Any) -> None
        sa = _import_sqlalchemy()
        table = self._storage.lock_table
        result = conn.execute(sa.delete(table).where(table.c.key == self.key, table.c.token == self.token))
        if result.rowcount == 0:
            logger.warning(
                "Context lock for user %s expired before release (held %.1fs > timeout %.0fs); "
                "another worker may have processed this user concurrently.",
                self.key, self.held_for, self.timeout,
            )

    def _try_acquire(self):
        # type: () -> bool
        self._storage._require_sync()
        self._storage._ensure_table()
        with self._storage.engine.begin() as conn:
            return self._acquire_with(conn)

    def _release(self):
        # type: () -> None
        self._storage._require_sync()
        with self._storage.engine.begin() as conn:
            self._release_with(conn)

    async def _atry_acquire(self):
        # type: () -> bool
        if not self._storage._is_async:
            return await super()._atry_acquire()
        await self._storage._aensure_table()
        async with self._storage.engine.begin() as conn:
            return await conn.run_sync(self._acquire_with)

    async def _arelease(self):
        # type: () -> None
        if not self._storage._is_async:
            return await super()._arelease()
        async with self._storage.engine.begin() as conn:
            await conn.run_sync(self._release_with)


# --------------------------------------------------------------------------- #
# Base class
# --------------------------------------------------------------------------- #


class ContextStorage(ABC):
    """Abstract key/value store for per-user context.

    Keys are the user's WhatsApp id (phone number); values are the
    ``user_data`` dict. Subclasses implement :meth:`get`, :meth:`set`
    and :meth:`delete`. The async variants (``aget`` / ``aset`` / ``adelete``)
    default to running the sync implementation in the event loop's thread
    pool, so every backend automatically works with async handlers. Backends
    with a native async client (e.g. Redis) override them.

    Implementations must be safe to use from multiple threads, because the
    bot processes updates in threads by default.
    """

    def __init__(self, serializer=None, ttl=None):
        # type: (Optional[Serializer], Optional[float]) -> None
        self.serializer = serializer or Serializer()  # type: Serializer
        self.ttl = _validate_ttl(ttl)  # type: Optional[float]

    # -- required ----------------------------------------------------------- #

    @abstractmethod
    def get(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        """Return the user's data dict, or ``None`` if nothing is stored."""

    @abstractmethod
    def set(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        """Persist the user's data dict (create or overwrite)."""

    @abstractmethod
    def delete(self, key):
        # type: (str) -> None
        """Remove the user's data. Must not fail if the key does not exist."""

    # -- optional ----------------------------------------------------------- #

    def exists(self, key):
        # type: (str) -> bool
        return self.get(key) is not None

    def touch(self, key):
        # type: (str) -> None
        """Refresh the expiry of ``key`` (counts as activity). No-op without ``ttl``.

        Backends that support ``ttl`` must implement this. The dispatcher calls
        it after every message that did not change the record.
        """
        if self.ttl is not None:
            raise NotImplementedError("{!r} accepts ttl but does not implement touch()".format(self))

    def purge_expired(self):
        # type: () -> int
        """Physically delete expired records (and stale lock rows). Returns the count.

        Safe to call from a cron job at any frequency; the backends also call it
        automatically (throttled by ``purge_interval``) on writes.
        """
        return 0

    def close(self):
        # type: () -> None
        """Release connections/resources. No-op by default."""

    def ping(self):
        # type: () -> None
        """Verify the backend is reachable. Raises on failure.

        Called once by the bot before the first update that needs context so
        misconfiguration fails loudly and early. Default: a cheap read.
        """
        self.get("__ping__")

    def lock(self, key, timeout=DEFAULT_LOCK_TIMEOUT, blocking_timeout=DEFAULT_LOCK_WAIT, retry_interval=DEFAULT_LOCK_RETRY):
        # type: (str, float, float, float) -> ContextLock
        """Return a :class:`ContextLock` for ``key`` (not yet acquired).

        Backends that cannot provide a cross-process lock should leave this
        unimplemented; the dispatcher then fails loudly unless locking is
        disabled with ``context_lock=False``.
        """
        raise ContextLockNotSupportedError(self)

    @property
    def supports_locking(self):
        # type: () -> bool
        return type(self).lock is not ContextStorage.lock

    # -- async ------------------------------------------------------------- #

    async def aget(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        return await self._run_sync(self.get, key)

    async def aset(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        await self._run_sync(self.set, key, data)

    async def adelete(self, key):
        # type: (str) -> None
        await self._run_sync(self.delete, key)

    async def aexists(self, key):
        # type: (str) -> bool
        return (await self.aget(key)) is not None

    async def atouch(self, key):
        # type: (str) -> None
        await self._run_sync(self.touch, key)

    async def apurge_expired(self):
        # type: () -> int
        return await self._run_sync(self.purge_expired)

    async def aclose(self):
        # type: () -> None
        await self._run_sync(self.close)

    async def aping(self):
        # type: () -> None
        await self._run_sync(self.ping)

    # -- helpers ---------------------------------------------------------- #

    @staticmethod
    async def _run_sync(func, *args, **kwargs):
        # type: (Callable, *Any, **Any) -> Any
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

    def _dumps(self, data):
        # type: (Dict[str, Any]) -> str
        return self.serializer.dumps(data)

    def _loads(self, raw):
        # type: (Any) -> Dict[str, Any]
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return self.serializer.loads(raw)

    # -- TTL helpers for backends that implement expiry themselves ---------- #

    def _init_purging(self, purge_interval):
        # type: (Optional[float]) -> None
        self.purge_interval = _validate_ttl(purge_interval)  # type: Optional[float]
        self._last_purge = time.monotonic()
        self._purge_lock = threading.Lock()

    def _purge_due(self):
        # type: () -> bool
        """True (once) when an automatic sweep should run now."""
        if self.ttl is None or not self.purge_interval:
            return False
        with self._purge_lock:
            if time.monotonic() - self._last_purge < self.purge_interval:
                return False
            self._last_purge = time.monotonic()
            return True

    def _touch_threshold(self):
        # type: () -> float
        """Coalesce refreshes: only bump the timestamp if it is older than this
        many seconds (10% of the TTL, at most a minute), so chatty users do not
        cause one write per message while the record still lives ~ttl."""
        return min(self.ttl * 0.1, 60.0) if self.ttl else 0.0

    def _maybe_purge(self):
        # type: () -> None
        if self._purge_due():
            try:
                self.purge_expired()
            except Exception as exc:  # pragma: no cover - never break a write over housekeeping
                logger.warning("Automatic purge of expired context failed: %s", exc)

    async def _amaybe_purge(self):
        # type: () -> None
        if self._purge_due():
            try:
                await self.apurge_expired()
            except Exception as exc:  # pragma: no cover
                logger.warning("Automatic purge of expired context failed: %s", exc)

    def __repr__(self):
        # type: () -> str
        return "<{}>".format(self.__class__.__name__)


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #


class MemoryStorage(ContextStorage):
    """In-process storage. **Not shared between worker processes.**

    Meant for tests and single-process development. Data is stored in
    serialized form so behaviour is identical to the external backends
    (e.g. only JSON-serializable values, changes are persisted on save).
    """

    def __init__(self, serializer=None, warn=True, ttl=None, purge_interval=DEFAULT_PURGE_INTERVAL):
        # type: (Optional[Serializer], bool, Optional[float], Optional[float]) -> None
        super().__init__(serializer, ttl=ttl)
        self._init_purging(purge_interval)
        self._data = {}  # type: Dict[str, str]
        self._updated = {}  # type: Dict[str, float]
        self._lock = threading.Lock()
        self._locks = {}  # type: Dict[str, tuple]
        if warn:
            logger.warning(
                "MemoryStorage keeps context in process memory: it is NOT shared "
                "between worker processes. Use SQLiteStorage, RedisStorage or "
                "SQLAlchemyStorage in production."
            )

    def _expired(self, key, now):
        # type: (str, float) -> bool
        return self.ttl is not None and now - self._updated.get(key, now) > self.ttl

    def get(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        with self._lock:
            if self._expired(key, time.time()):
                self._data.pop(key, None)
                self._updated.pop(key, None)
            raw = self._data.get(key)
        return self._loads(raw) if raw is not None else None

    def set(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        raw = self._dumps(data)
        with self._lock:
            self._data[key] = raw
            self._updated[key] = time.time()
        self._maybe_purge()

    def delete(self, key):
        # type: (str) -> None
        with self._lock:
            self._data.pop(key, None)
            self._updated.pop(key, None)

    def touch(self, key):
        # type: (str) -> None
        if self.ttl is None:
            return
        now = time.time()
        with self._lock:
            if key in self._data and not self._expired(key, now):
                if now - self._updated[key] >= self._touch_threshold():
                    self._updated[key] = now

    def purge_expired(self):
        # type: () -> int
        now = time.time()
        with self._lock:
            stale = [k for k in self._data if self._expired(k, now)]
            for k in stale:
                del self._data[k]
                self._updated.pop(k, None)
            stale_locks = [k for k, (_, exp) in self._locks.items() if exp <= now]
            for k in stale_locks:
                del self._locks[k]
        return len(stale)

    def keys(self):
        # type: () -> list
        now = time.time()
        with self._lock:
            return [k for k in self._data if not self._expired(k, now)]

    def clear(self):
        # type: () -> None
        with self._lock:
            self._data.clear()
            self._updated.clear()
            self._locks.clear()

    def ping(self):
        # type: () -> None
        return None

    def lock(self, key, **kwargs):
        # type: (str, **Any) -> ContextLock
        return _MemoryLock(self._locks, self._lock, key, **kwargs)


# --------------------------------------------------------------------------- #
# SQLite (stdlib)
# --------------------------------------------------------------------------- #


class SQLiteStorage(ContextStorage):
    """SQLite file storage using only the standard library.

    Safe for several worker processes on the same machine (WAL journal mode and
    a busy timeout are enabled). A fresh connection is opened per operation,
    which keeps it thread- and process-safe with no pooling logic.

    Args:
        path: Database file path. ``":memory:"`` is accepted but then the data
            is per-connection, i.e. useless - use :class:`MemoryStorage` instead.
        table_name: Table to store the context in (created if missing).
        timeout: Seconds to wait when the database is locked by another writer.
        ttl: Optional expiry in seconds after a user's last activity.
        purge_interval: Seconds between automatic deletions of expired rows
            (run on writes). ``None``/``0`` disables it; call
            :meth:`purge_expired` yourself instead.
    """

    def __init__(
        self,
        path="whatsapp_context.db",  # type: str
        table_name=DEFAULT_TABLE_NAME,  # type: str
        timeout=10.0,  # type: float
        serializer=None,  # type: Optional[Serializer]
        ttl=None,  # type: Optional[float]
        purge_interval=DEFAULT_PURGE_INTERVAL,  # type: Optional[float]
    ):
        # type: (...) -> None
        super().__init__(serializer, ttl=ttl)
        self._init_purging(purge_interval)
        self.path = str(path)
        self.table_name = _validate_identifier(table_name)
        self.lock_table_name = self.table_name + "_locks"
        self.timeout = timeout
        self._initialized = False
        self._init_lock = threading.Lock()

    def _connect(self):
        # type: () -> sqlite3.Connection
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    if self.path != ":memory:":
                        try:
                            conn.execute("PRAGMA journal_mode=WAL")
                        except sqlite3.DatabaseError:  # e.g. read-only filesystems
                            pass
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS {} ("
                        "key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL)".format(self.table_name)
                    )
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS {} ("
                        "key TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at REAL NOT NULL)".format(self.lock_table_name)
                    )
                    self._initialized = True
        return conn

    def get(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT data, updated_at FROM {} WHERE key = ?".format(self.table_name), (key,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        if self.ttl is not None and time.time() - row[1] > self.ttl:
            return None  # expired: invisible until the next sweep deletes it
        return self._loads(row[0])

    def set(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        raw = self._dumps(data)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO {} (key, data, updated_at) VALUES (?, ?, ?)".format(self.table_name),
                (key, raw, time.time()),
            )
        finally:
            conn.close()
        self._maybe_purge()

    def touch(self, key):
        # type: (str) -> None
        if self.ttl is None:
            return
        now = time.time()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE {} SET updated_at = ? WHERE key = ? AND updated_at <= ? AND updated_at > ?".format(
                    self.table_name
                ),
                (now, key, now - self._touch_threshold(), now - self.ttl),
            )
        finally:
            conn.close()

    def purge_expired(self):
        # type: () -> int
        now = time.time()
        conn = self._connect()
        try:
            deleted = 0
            if self.ttl is not None:
                deleted = conn.execute(
                    "DELETE FROM {} WHERE updated_at < ?".format(self.table_name), (now - self.ttl,)
                ).rowcount
            conn.execute("DELETE FROM {} WHERE expires_at <= ?".format(self.lock_table_name), (now,))
        finally:
            conn.close()
        return deleted

    def delete(self, key):
        # type: (str) -> None
        conn = self._connect()
        try:
            conn.execute("DELETE FROM {} WHERE key = ?".format(self.table_name), (key,))
        finally:
            conn.close()

    def ping(self):
        # type: () -> None
        self._connect().close()

    def lock(self, key, **kwargs):
        # type: (str, **Any) -> ContextLock
        return _SQLiteLock(self, key, **kwargs)

    def __repr__(self):
        # type: () -> str
        return "<SQLiteStorage path={!r} table={!r} ttl={!r}>".format(self.path, self.table_name, self.ttl)


# --------------------------------------------------------------------------- #
# Redis
# --------------------------------------------------------------------------- #


class RedisStorage(ContextStorage):
    """Redis storage. Requires the ``redis`` package (``pip install redis``).

    Uses a native async client for async handlers, so the event loop is never
    blocked. Pass a URL and both clients are created lazily, or pass your own
    client(s).

    Args:
        url: ``redis://[:password@]host:port/db`` (or ``rediss://``).
        client: An existing ``redis.Redis`` instance (optional).
        async_client: An existing ``redis.asyncio.Redis`` instance (optional).
        key_prefix: Prefix for all keys, handy when sharing one Redis.
        ttl: Optional expiry in seconds, refreshed on every write. Lets idle
            conversations disappear automatically.
    """

    def __init__(
        self,
        url=None,  # type: Optional[str]
        client=None,  # type: Optional[Any]
        async_client=None,  # type: Optional[Any]
        key_prefix=DEFAULT_KEY_PREFIX,  # type: str
        ttl=None,  # type: Optional[int]
        serializer=None,  # type: Optional[Serializer]
        **client_kwargs  # type: Any
    ):
        # type: (...) -> None
        super().__init__(serializer, ttl=ttl)
        if url is None and client is None and async_client is None:
            raise ValueError("RedisStorage needs a url, a client or an async_client")
        self.url = url
        self.key_prefix = key_prefix
        self._client_kwargs = client_kwargs
        self._client = client
        self._async_client = async_client
        self._lock = threading.Lock()

    # -- clients ------------------------------------------------------------ #

    @property
    def client(self):
        # type: () -> Any
        if self._client is None:
            with self._lock:
                if self._client is None:
                    if self.url is None:
                        raise ContextStorageError(
                            "RedisStorage was given only an async client; pass a url or a sync "
                            "`client` as well to use it from sync handlers."
                        )
                    redis = _import_redis()
                    self._client = redis.Redis.from_url(self.url, **self._client_kwargs)
        return self._client

    @property
    def async_client(self):
        # type: () -> Any
        if self._async_client is None:
            with self._lock:
                if self._async_client is None:
                    if self.url is None:
                        return None  # fall back to running the sync client in a thread
                    _import_redis()
                    import redis.asyncio as aioredis

                    self._async_client = aioredis.Redis.from_url(self.url, **self._client_kwargs)
        return self._async_client

    def _key(self, key):
        # type: (str) -> str
        return self.key_prefix + key

    # -- sync --------------------------------------------------------------- #

    def get(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        raw = self.client.get(self._key(key))
        return self._loads(raw) if raw is not None else None

    def set(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        self.client.set(self._key(key), self._dumps(data), ex=self._ex())

    def _ex(self):
        # type: () -> Optional[int]
        return int(math.ceil(self.ttl)) if self.ttl is not None else None

    def delete(self, key):
        # type: (str) -> None
        self.client.delete(self._key(key))

    def exists(self, key):
        # type: (str) -> bool
        return bool(self.client.exists(self._key(key)))

    def touch(self, key):
        # type: (str) -> None
        if self.ttl is not None:
            self.client.expire(self._key(key), int(math.ceil(self.ttl)))

    def ping(self):
        # type: () -> None
        self.client.ping()

    def lock(self, key, **kwargs):
        # type: (str, **Any) -> ContextLock
        return _RedisLock(self, key, **kwargs)

    def close(self):
        # type: () -> None
        if self._client is not None:
            self._client.close()

    # -- async -------------------------------------------------------------- #

    async def aget(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        client = self.async_client
        if client is None:
            return await super().aget(key)
        raw = await client.get(self._key(key))
        return self._loads(raw) if raw is not None else None

    async def aset(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        client = self.async_client
        if client is None:
            return await super().aset(key, data)
        await client.set(self._key(key), self._dumps(data), ex=self._ex())

    async def adelete(self, key):
        # type: (str) -> None
        client = self.async_client
        if client is None:
            return await super().adelete(key)
        await client.delete(self._key(key))

    async def aexists(self, key):
        # type: (str) -> bool
        client = self.async_client
        if client is None:
            return await super().aexists(key)
        return bool(await client.exists(self._key(key)))

    async def atouch(self, key):
        # type: (str) -> None
        if self.ttl is None:
            return
        client = self.async_client
        if client is None:
            return await super().atouch(key)
        await client.expire(self._key(key), int(math.ceil(self.ttl)))

    async def aping(self):
        # type: () -> None
        client = self.async_client
        if client is None:
            return await super().aping()
        await client.ping()

    async def aclose(self):
        # type: () -> None
        if self._async_client is not None:
            # redis>=5.0.1 has aclose(); older versions use close()
            aclose = getattr(self._async_client, "aclose", None) or self._async_client.close
            result = aclose()
            if asyncio.iscoroutine(result):
                await result
        await super().aclose()

    def __repr__(self):
        # type: () -> str
        return "<RedisStorage url={!r} prefix={!r} ttl={!r}>".format(_redact_url(self.url), self.key_prefix, self.ttl)


# --------------------------------------------------------------------------- #
# SQLAlchemy (Postgres, MySQL, SQLite, ...)
# --------------------------------------------------------------------------- #


class SQLAlchemyStorage(ContextStorage):
    """SQL storage via SQLAlchemy Core. Requires ``sqlalchemy`` (1.4+ or 2.x).

    Works with any database SQLAlchemy supports - PostgreSQL, MySQL/MariaDB,
    SQLite, MSSQL, Oracle... Pass a database URL, or reuse the ``Engine`` (or
    ``AsyncEngine``) your application already has.

    Examples::

        SQLAlchemyStorage("postgresql+psycopg2://user:pass@host/db")
        SQLAlchemyStorage("mysql+pymysql://user:pass@host/db")
        SQLAlchemyStorage(engine=my_app_engine)
        SQLAlchemyStorage(engine=my_async_engine)   # asyncpg / aiomysql / aiosqlite

    With a sync ``Engine`` async handlers run the queries in a thread pool.
    With an ``AsyncEngine`` async handlers use it natively, and the sync
    methods are unavailable (use async handlers, or pass a sync engine too).

    Args:
        url: SQLAlchemy database URL.
        engine: Existing ``Engine`` or ``AsyncEngine``.
        table_name: Table to store the context in (created if missing).
        create_table: Create the table on first use (default True).
        ttl: Optional expiry in seconds after a user's last activity.
        purge_interval: Seconds between automatic deletions of expired rows
            (run on writes). ``None``/``0`` disables it; call
            :meth:`purge_expired` yourself instead.
        engine_kwargs: Extra arguments for ``create_engine`` when using ``url``.
    """

    def __init__(
        self,
        url=None,  # type: Optional[str]
        engine=None,  # type: Optional[Any]
        table_name=DEFAULT_TABLE_NAME,  # type: str
        create_table=True,  # type: bool
        serializer=None,  # type: Optional[Serializer]
        ttl=None,  # type: Optional[float]
        purge_interval=DEFAULT_PURGE_INTERVAL,  # type: Optional[float]
        **engine_kwargs  # type: Any
    ):
        # type: (...) -> None
        super().__init__(serializer, ttl=ttl)
        self._init_purging(purge_interval)
        if url is None and engine is None:
            raise ValueError("SQLAlchemyStorage needs a url or an engine")
        sa = _import_sqlalchemy()
        self.table_name = _validate_identifier(table_name)
        self.create_table = create_table

        self._is_async = False
        if engine is None:
            engine = sa.create_engine(url, **engine_kwargs)
        else:
            try:
                from sqlalchemy.ext.asyncio import AsyncEngine

                self._is_async = isinstance(engine, AsyncEngine)
            except ImportError:  # very old SQLAlchemy without asyncio support
                pass
        self.engine = engine

        self._metadata = sa.MetaData()
        self.table = sa.Table(
            self.table_name,
            self._metadata,
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("data", sa.Text, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        self.lock_table_name = self.table_name + "_locks"
        self.lock_table = sa.Table(
            self.lock_table_name,
            self._metadata,
            sa.Column("key", sa.String(64), primary_key=True),
            sa.Column("token", sa.String(32), nullable=False),
            sa.Column("expires_at", sa.Float, nullable=False),
        )
        self._dialect = (engine.dialect.name if engine is not None else "")
        self._initialized = False
        self._init_lock = threading.Lock()
        self._async_init_lock = None  # type: Optional[asyncio.Lock]

    # -- setup -------------------------------------------------------------- #

    def _ensure_table(self):
        # type: () -> None
        if self._initialized or not self.create_table:
            self._initialized = True
            return
        with self._init_lock:
            if not self._initialized:
                self._metadata.create_all(self.engine, checkfirst=True)
                self._initialized = True

    async def _aensure_table(self):
        # type: () -> None
        if self._initialized or not self.create_table:
            self._initialized = True
            return
        if self._async_init_lock is None:
            self._async_init_lock = asyncio.Lock()
        async with self._async_init_lock:
            if not self._initialized:
                async with self.engine.begin() as conn:
                    await conn.run_sync(self._metadata.create_all, checkfirst=True)
                self._initialized = True

    def _require_sync(self):
        # type: () -> None
        if self._is_async:
            raise ContextStorageError(
                "SQLAlchemyStorage was configured with an AsyncEngine, which cannot be used "
                "from sync handlers. Use async handlers (aprocess_update) or pass a sync Engine."
            )

    # -- statements --------------------------------------------------------- #

    def _select(self, key):
        # type: (str) -> Any
        sa = _import_sqlalchemy()
        return sa.select(self.table.c.data, self.table.c.updated_at).where(self.table.c.key == key)

    def _row_to_data(self, row):
        # type: (Any) -> Optional[Dict[str, Any]]
        if not row:
            return None
        if self.ttl is not None:
            updated_at = row[1]
            if updated_at.tzinfo is not None:
                updated_at = updated_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            if (_utcnow() - updated_at).total_seconds() > self.ttl:
                return None  # expired: invisible until the next sweep deletes it
        return self._loads(row[0])

    def _touch_stmt(self, key):
        # type: (str) -> Any
        sa = _import_sqlalchemy()
        now = _utcnow()
        return (
            sa.update(self.table)
            .where(
                self.table.c.key == key,
                self.table.c.updated_at <= now - datetime.timedelta(seconds=self._touch_threshold()),
                self.table.c.updated_at > now - datetime.timedelta(seconds=self.ttl),  # type: ignore[arg-type]
            )
            .values(updated_at=now)
        )

    def _purge_with(self, conn):
        # type: (Any) -> int
        """Runs on a sync connection inside a transaction."""
        sa = _import_sqlalchemy()
        deleted = 0
        if self.ttl is not None:
            cutoff = _utcnow() - datetime.timedelta(seconds=self.ttl)
            deleted = conn.execute(sa.delete(self.table).where(self.table.c.updated_at < cutoff)).rowcount
        conn.execute(sa.delete(self.lock_table).where(self.lock_table.c.expires_at <= time.time()))
        return deleted

    def _upsert(self, key, raw):
        # type: (str, str) -> Any
        """Build a dialect-aware upsert; returns None if the dialect has none."""
        values = {"key": key, "data": raw, "updated_at": _utcnow()}
        if self._dialect in ("postgresql", "sqlite"):
            if self._dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            stmt = insert(self.table).values(**values)
            return stmt.on_conflict_do_update(
                index_elements=[self.table.c.key],
                set_={"data": stmt.excluded.data, "updated_at": stmt.excluded.updated_at},
            )
        if self._dialect in ("mysql", "mariadb"):
            from sqlalchemy.dialects.mysql import insert

            stmt = insert(self.table).values(**values)
            return stmt.on_duplicate_key_update(data=stmt.inserted.data, updated_at=stmt.inserted.updated_at)
        return None

    def _generic_upsert(self, conn, key, raw):
        # type: (Any, str, str) -> None
        """Portable update-then-insert for dialects without native upsert."""
        sa = _import_sqlalchemy()
        now = _utcnow()
        result = conn.execute(
            sa.update(self.table).where(self.table.c.key == key).values(data=raw, updated_at=now)
        )
        if result.rowcount == 0:
            try:
                conn.execute(sa.insert(self.table).values(key=key, data=raw, updated_at=now))
            except sa.exc.IntegrityError:
                # Lost a race with a concurrent insert: update instead.
                conn.execute(
                    sa.update(self.table).where(self.table.c.key == key).values(data=raw, updated_at=now)
                )

    # -- sync --------------------------------------------------------------- #

    def get(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        self._require_sync()
        self._ensure_table()
        with self.engine.connect() as conn:
            row = conn.execute(self._select(key)).first()
        return self._row_to_data(row)

    def set(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        self._require_sync()
        self._ensure_table()
        raw = self._dumps(data)
        stmt = self._upsert(key, raw)
        with self.engine.begin() as conn:
            if stmt is not None:
                conn.execute(stmt)
            else:
                self._generic_upsert(conn, key, raw)
        self._maybe_purge()

    def touch(self, key):
        # type: (str) -> None
        if self.ttl is None:
            return
        self._require_sync()
        self._ensure_table()
        with self.engine.begin() as conn:
            conn.execute(self._touch_stmt(key))

    def purge_expired(self):
        # type: () -> int
        self._require_sync()
        self._ensure_table()
        with self.engine.begin() as conn:
            return self._purge_with(conn)

    def delete(self, key):
        # type: (str) -> None
        self._require_sync()
        self._ensure_table()
        sa = _import_sqlalchemy()
        with self.engine.begin() as conn:
            conn.execute(sa.delete(self.table).where(self.table.c.key == key))

    def ping(self):
        # type: () -> None
        self._require_sync()
        self._ensure_table()

    def lock(self, key, **kwargs):
        # type: (str, **Any) -> ContextLock
        return _SQLAlchemyLock(self, key, **kwargs)

    def close(self):
        # type: () -> None
        if not self._is_async:
            self.engine.dispose()

    # -- async -------------------------------------------------------------- #

    async def aget(self, key):
        # type: (str) -> Optional[Dict[str, Any]]
        if not self._is_async:
            return await super().aget(key)
        await self._aensure_table()
        async with self.engine.connect() as conn:
            row = (await conn.execute(self._select(key))).first()
        return self._row_to_data(row)

    async def aset(self, key, data):
        # type: (str, Dict[str, Any]) -> None
        if not self._is_async:
            return await super().aset(key, data)
        await self._aensure_table()
        raw = self._dumps(data)
        stmt = self._upsert(key, raw)
        async with self.engine.begin() as conn:
            if stmt is not None:
                await conn.execute(stmt)
            else:
                await conn.run_sync(lambda sync_conn: self._generic_upsert(sync_conn, key, raw))
        await self._amaybe_purge()

    async def atouch(self, key):
        # type: (str) -> None
        if self.ttl is None:
            return
        if not self._is_async:
            return await super().atouch(key)
        await self._aensure_table()
        async with self.engine.begin() as conn:
            await conn.execute(self._touch_stmt(key))

    async def apurge_expired(self):
        # type: () -> int
        if not self._is_async:
            return await super().apurge_expired()
        await self._aensure_table()
        async with self.engine.begin() as conn:
            return await conn.run_sync(self._purge_with)

    async def adelete(self, key):
        # type: (str) -> None
        if not self._is_async:
            return await super().adelete(key)
        await self._aensure_table()
        sa = _import_sqlalchemy()
        async with self.engine.begin() as conn:
            await conn.execute(sa.delete(self.table).where(self.table.c.key == key))

    async def aping(self):
        # type: () -> None
        if not self._is_async:
            return await super().aping()
        await self._aensure_table()

    async def aclose(self):
        # type: () -> None
        if self._is_async:
            await self.engine.dispose()
        else:
            await super().aclose()

    def __repr__(self):
        # type: () -> str
        return "<SQLAlchemyStorage url={!r} table={!r} ttl={!r}>".format(
            _redact_url(str(self.engine.url)), self.table_name, self.ttl
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _utcnow():
    # type: () -> datetime.datetime
    """Naive UTC timestamp (portable across DB DateTime columns)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _validate_ttl(value):
    # type: (Optional[float]) -> Optional[float]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("ttl / purge_interval must be a positive number of seconds or None, got {!r}".format(value))
    return float(value)


def _validate_identifier(name):
    # type: (str) -> str
    """Guard table names that get interpolated into SQL."""
    if not name or not all(ch.isalnum() or ch == "_" for ch in name) or name[0].isdigit():
        raise ValueError("Invalid table name: {!r}".format(name))
    return name


def _redact_url(url):
    # type: (Optional[str]) -> Optional[str]
    if not url or "@" not in url:
        return url
    scheme_sep = url.find("://")
    at = url.rfind("@")
    if scheme_sep == -1 or at < scheme_sep:
        return url
    return url[: scheme_sep + 3] + "***@" + url[at + 1 :]


def _import_redis():
    # type: () -> Any
    try:
        import redis
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "RedisStorage requires the 'redis' package: pip install 'python-whatsapp-bot[redis]'"
        ) from exc
    return redis


def _import_sqlalchemy():
    # type: () -> Any
    try:
        import sqlalchemy
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "SQLAlchemyStorage requires the 'sqlalchemy' package: "
            "pip install 'python-whatsapp-bot[sqlalchemy]'"
        ) from exc
    return sqlalchemy
