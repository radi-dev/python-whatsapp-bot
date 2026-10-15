"""Per-user conversation context backed by external storage.

Handlers keep using the same syntax they always did::

    @wa_bot.on_message()
    def handler(update, context):
        context.user_data["name"] = update.message_text
        cart = context.user_data.setdefault("cart", [])
        cart.append("apple")

The dispatcher loads ``user_data`` from the configured
:class:`~python_whatsapp_bot.context_storage.ContextStorage` right before the
handler runs and writes it back afterwards *if it changed* (nested mutations
included). Because the data lives in Redis/SQL/SQLite instead of process
memory, every worker process sees the same conversation state.

Outside of handlers you can use the class directly::

    with User_context("2348145xxxxx") as ctx:   # saved on exit
        ctx.user_data["vip"] = True

Storage record layout
---------------------

One record per user, stored under the user's WhatsApp id::

    {"user_data": {...}, "next_step": {...}}

``user_data`` is the developer-facing dict; ``next_step`` (absent when not in
a conversation) is the persisted ``set_next_step`` state, kept *outside*
``user_data`` so that ``user_data.clear()`` cannot accidentally abort a
conversation, yet saved atomically together with it.
"""

import threading
from typing import Any, Dict, Optional

from .context_storage import ContextStorage, ContextStorageNotConfiguredError

__all__ = [
    "User_context",
    "UserContext",
    "set_context_storage",
    "get_context_storage",
    "resolve_context_storage",
]

_default_storage = None  # type: Optional[ContextStorage]
_default_storage_lock = threading.Lock()


def set_context_storage(storage):
    # type: (Optional[ContextStorage]) -> None
    """Set the process-wide default context storage.

    Used by every bot and every ``User_context`` that was not given a storage
    explicitly. Pass ``None`` to unset it.
    """
    global _default_storage
    if storage is not None and not isinstance(storage, ContextStorage):
        raise TypeError(
            "storage must be a ContextStorage instance (e.g. RedisStorage, "
            "SQLiteStorage, SQLAlchemyStorage), got {!r}".format(type(storage).__name__)
        )
    with _default_storage_lock:
        _default_storage = storage


def get_context_storage():
    # type: () -> Optional[ContextStorage]
    """Return the process-wide default context storage, or ``None``."""
    return _default_storage


def resolve_context_storage(storage=None):
    # type: (Optional[ContextStorage]) -> ContextStorage
    """Return ``storage`` if given, else the global default; hard-fail otherwise."""
    if storage is not None:
        if not isinstance(storage, ContextStorage):
            raise TypeError(
                "context_storage must be a ContextStorage instance, got {!r}".format(
                    type(storage).__name__
                )
            )
        return storage
    if _default_storage is None:
        raise ContextStorageNotConfiguredError()
    return _default_storage


class User_context:
    """Manages a single user's ``user_data`` dict in the configured storage.

    The user's WhatsApp id (phone number) is the storage key.

    Args:
        phone_num: The user's WhatsApp id / phone number.
        storage: Storage backend. Defaults to the global one set with
            :func:`set_context_storage`. Raises
            :class:`~python_whatsapp_bot.context_storage.ContextStorageNotConfiguredError`
            if neither is available.

    ``user_data`` is loaded lazily on first access (or eagerly via
    :meth:`load` / :meth:`aload`). Call :meth:`save` / :meth:`asave` to
    persist changes - the dispatcher does this automatically after a handler
    runs, and using the object as a (async) context manager does it on exit.
    """

    USER_DATA_KEY = "user_data"
    NEXT_STEP_KEY = "next_step"

    def __init__(self, phone_num, storage=None):
        # type: (Any, Optional[ContextStorage]) -> None
        self.phone_num = str(phone_num)  # type: str
        self.storage = resolve_context_storage(storage)  # type: ContextStorage
        self._record = None  # type: Optional[Dict[str, Any]]
        self._snapshot = None  # type: Optional[str]

    # -- public API ------------------------------------------------------- #

    @property
    def user_data(self):
        # type: () -> Dict[str, Any]
        """The user's data dict. Loaded from storage on first access."""
        return self.record[self.USER_DATA_KEY]

    @user_data.setter
    def user_data(self, value):
        # type: (Dict[str, Any]) -> None
        if not isinstance(value, dict):
            raise TypeError("user_data must be a dict, got {!r}".format(type(value).__name__))
        if self._record is None:
            # Replacing without loading: treat the stored value as unknown so
            # that save() always writes.
            self._record = self._empty_record()
            self._snapshot = None
        self._record[self.USER_DATA_KEY] = value

    @property
    def next_step(self):
        # type: () -> Optional[Dict[str, Any]]
        """Persisted ``set_next_step`` state (a plain dict), or None.

        Managed by the dispatcher; stored next to ``user_data`` so clearing
        one never affects the other.
        """
        return self.record.get(self.NEXT_STEP_KEY)

    @next_step.setter
    def next_step(self, value):
        # type: (Optional[Dict[str, Any]]) -> None
        if value is not None and not isinstance(value, dict):
            raise TypeError("next_step must be a dict or None, got {!r}".format(type(value).__name__))
        record = self.record
        if value is None:
            record.pop(self.NEXT_STEP_KEY, None)
        else:
            record[self.NEXT_STEP_KEY] = value

    @property
    def record(self):
        # type: () -> Dict[str, Any]
        """The whole stored record (``{"user_data": ..., "next_step": ...}``)."""
        if self._record is None:
            self.load()
        return self._record  # type: ignore[return-value]

    @property
    def loaded(self):
        # type: () -> bool
        return self._record is not None

    @property
    def changed(self):
        # type: () -> bool
        """True if the record differs from what was loaded from storage."""
        if self._record is None:
            return False
        return self._serialize() != self._snapshot

    def load(self):
        # type: () -> "User_context"
        """(Re)load ``user_data`` from storage, discarding unsaved changes."""
        self._set_loaded(self.storage.get(self.phone_num))
        return self

    def save(self, force=False):
        # type: (bool) -> bool
        """Persist the record (``user_data`` and ``next_step``) to storage.

        Returns True if a write happened. Only writes when something changed
        since it was loaded, unless ``force``.
        """
        if self._record is None:
            return False
        serialized = self._serialize()
        if not force and serialized == self._snapshot:
            return False
        self.storage.set(self.phone_num, self._record)
        self._snapshot = serialized
        return True

    def touch(self):
        # type: () -> None
        """Refresh the record's expiry (only meaningful when the storage has a ``ttl``)."""
        if self.storage.ttl is not None:
            self.storage.touch(self.phone_num)

    def clear(self):
        # type: () -> None
        """Delete everything stored for this user (``user_data`` *and* ``next_step``)."""
        self._record = self._empty_record()
        self.storage.delete(self.phone_num)
        self._snapshot = self._serialize()

    refresh = load  # alias

    # -- async API -------------------------------------------------------- #

    async def aload(self):
        # type: () -> "User_context"
        self._set_loaded(await self.storage.aget(self.phone_num))
        return self

    async def asave(self, force=False):
        # type: (bool) -> bool
        if self._record is None:
            return False
        serialized = self._serialize()
        if not force and serialized == self._snapshot:
            return False
        await self.storage.aset(self.phone_num, self._record)
        self._snapshot = serialized
        return True

    async def atouch(self):
        # type: () -> None
        if self.storage.ttl is not None:
            await self.storage.atouch(self.phone_num)

    async def aclear(self):
        # type: () -> None
        self._record = self._empty_record()
        await self.storage.adelete(self.phone_num)
        self._snapshot = self._serialize()

    arefresh = aload  # alias

    # -- context manager support ------------------------------------------ #

    def __enter__(self):
        # type: () -> "User_context"
        self.load()
        return self

    def __exit__(self, exc_type, exc, tb):
        # type: (Any, Any, Any) -> None
        self.save()

    async def __aenter__(self):
        # type: () -> "User_context"
        await self.aload()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # type: (Any, Any, Any) -> None
        await self.asave()

    # -- internals -------------------------------------------------------- #

    @classmethod
    def _empty_record(cls):
        # type: () -> Dict[str, Any]
        return {cls.USER_DATA_KEY: {}}

    def _set_loaded(self, data):
        # type: (Optional[Dict[str, Any]]) -> None
        if data is None:
            record = self._empty_record()
        elif isinstance(data.get(self.USER_DATA_KEY), dict):
            record = dict(data)
            if not isinstance(record.get(self.NEXT_STEP_KEY), dict):
                record.pop(self.NEXT_STEP_KEY, None)
        else:
            # A flat dict (written directly to the storage by hand): treat it as user_data.
            record = {self.USER_DATA_KEY: data}
        self._record = record
        self._snapshot = self._serialize()

    def _serialize(self):
        # type: () -> str
        return self.storage.serializer.dumps(self._record or self._empty_record())

    def __repr__(self):
        # type: () -> str
        return "<User_context phone_num={!r} loaded={} storage={!r}>".format(
            self.phone_num, self.loaded, self.storage
        )


UserContext = User_context  # PEP8-friendly alias
