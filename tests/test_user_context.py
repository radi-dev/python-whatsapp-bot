"""Tests for User_context and its integration with the Dispatcher / Whatsapp bot."""

import copy
import os
import subprocess
import sys
import textwrap
import threading
import time
from unittest.mock import Mock, patch

import pytest

from python_whatsapp_bot import Whatsapp
from python_whatsapp_bot.context_storage import (
    ContextLockNotSupportedError,
    ContextLockTimeoutError,
    ContextSerializationError,
    ContextStorage,
    ContextStorageNotConfiguredError,
    MemoryStorage,
    SQLiteStorage,
)
from python_whatsapp_bot.dispatcher import Dispatcher
from python_whatsapp_bot.handler_classes import MessageHandler
from python_whatsapp_bot.user_context import (
    User_context,
    UserContext,
    get_context_storage,
    set_context_storage,
)


def module_level_step(update, context):
    """A step importable by name (what production code normally uses)."""
    context.user_data["step_seen"] = update.message_text


def stored(storage, key):
    """The user_data part of a stored record (records are {"user_data": ..., "next_step": ...})."""
    record = storage.get(key)
    return None if record is None else record["user_data"]


def make_bot(storage=None):
    bot = Mock()
    bot.id = "123456789"
    bot.threaded = False
    bot.mark_as_read = Mock()
    return bot


def text_update(bot_id, message_text="Hello", phone_number="1234567890"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": bot_id},
                            "messages": [
                                {"id": "msg_123", "type": "text", "text": {"body": message_text}}
                            ],
                            "contacts": [
                                {"wa_id": phone_number, "profile": {"name": "Test User"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }


# --------------------------------------------------------------------------- #
# Configuration / hard failure
# --------------------------------------------------------------------------- #


class TestStorageConfiguration:
    def test_user_context_without_storage_hard_fails(self, no_context_storage):
        with pytest.raises(ContextStorageNotConfiguredError) as exc:
            User_context("123")
        assert "SQLiteStorage" in str(exc.value)

    def test_global_storage_is_used(self):
        storage = MemoryStorage(warn=False)
        set_context_storage(storage)
        assert get_context_storage() is storage
        assert User_context("1").storage is storage

    def test_explicit_storage_wins_over_global(self):
        explicit = MemoryStorage(warn=False)
        assert User_context("1", storage=explicit).storage is explicit

    def test_set_context_storage_type_checked(self):
        with pytest.raises(TypeError):
            set_context_storage({"not": "a storage"})

    def test_user_context_storage_type_checked(self):
        with pytest.raises(TypeError):
            User_context("1", storage=object())

    def test_dispatcher_storage_type_checked(self):
        with pytest.raises(TypeError):
            Dispatcher(make_bot(), context_storage="redis://localhost")

    def test_alias(self):
        assert UserContext is User_context


class TestDispatcherHardFail:
    def test_process_update_without_storage_raises_when_handler_uses_context(self, no_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        assert dispatcher.context_required is True
        with pytest.raises(ContextStorageNotConfiguredError):
            dispatcher.process_update(text_update(bot.id))

    async def test_aprocess_update_without_storage_raises_when_handler_uses_context(self, no_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        async def handler(update, context):
            pass

        dispatcher._register_handler(MessageHandler(action=handler))
        with pytest.raises(ContextStorageNotConfiguredError):
            await dispatcher.aprocess_update(text_update(bot.id))

    def test_hard_fail_even_in_threaded_mode(self, no_context_storage):
        bot = make_bot()
        bot.threaded = True
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        with pytest.raises(ContextStorageNotConfiguredError):
            dispatcher.process_update(text_update(bot.id))

    def test_hard_fail_even_if_no_handler_matches(self, no_context_storage):
        """The check is about configuration, not about which handler runs."""
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler(regex=r"^/never")
        def handler(update, context):
            pass

        with pytest.raises(ContextStorageNotConfiguredError):
            dispatcher.process_update(text_update(bot.id, "hello"))

    def test_no_storage_needed_when_handlers_do_not_take_context(self, no_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        called = []

        @dispatcher.add_message_handler()
        def handler(update):
            called.append(update.message_text)

        assert dispatcher.context_required is False
        dispatcher.process_update(text_update(bot.id, "hi"))
        assert called == ["hi"]

    def test_no_storage_needed_when_context_disabled_on_handler(self, no_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        called = []

        @dispatcher.add_message_handler(context=False)
        def handler(update, context=None):
            called.append(context)

        assert dispatcher.context_required is False
        dispatcher.process_update(text_update(bot.id))
        assert called == [None]

    def test_set_next_step_requires_storage(self, no_context_storage):
        """Next-step state is persisted, so setting it without storage hard-fails - even from
        a handler that does not take context, and the error is not swallowed."""
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def start(update):
            dispatcher.set_next_handler(update, module_level_step, handler_type=MessageHandler)

        with pytest.raises(ContextStorageNotConfiguredError) as exc:
            dispatcher.process_update(text_update(bot.id, "start"))
        assert "set_next_step" in str(exc.value)

    def test_storage_is_pinged_once(self):
        storage = MemoryStorage(warn=False)
        bot = make_bot()
        dispatcher = Dispatcher(bot, context_storage=storage)

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        with patch.object(storage, "ping", wraps=storage.ping) as ping:
            dispatcher.process_update(text_update(bot.id))
            dispatcher.process_update(text_update(bot.id))
        assert ping.call_count == 1

    def test_unreachable_storage_fails_loudly(self):
        storage = MemoryStorage(warn=False)
        storage.ping = Mock(side_effect=ConnectionError("redis down"))
        bot = make_bot()
        dispatcher = Dispatcher(bot, context_storage=storage)

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        with pytest.raises(ConnectionError):
            dispatcher.process_update(text_update(bot.id))


# --------------------------------------------------------------------------- #
# User_context semantics
# --------------------------------------------------------------------------- #


class TestUserContext:
    def test_lazy_load_and_save(self, memory_context_storage):
        ctx = User_context("123")
        assert ctx.loaded is False
        assert ctx.user_data == {}
        assert ctx.loaded is True
        assert ctx.save() is False  # nothing changed, nothing written
        ctx.user_data["name"] = "Ada"
        assert ctx.changed is True
        assert ctx.save() is True
        assert stored(memory_context_storage, "123") == {"name": "Ada"}
        assert ctx.changed is False
        assert ctx.save() is False

    def test_phone_number_is_normalized_to_str(self, memory_context_storage):
        ctx = User_context(2348145000000)
        ctx.user_data["x"] = 1
        ctx.save()
        assert User_context("2348145000000").user_data == {"x": 1}

    def test_changes_visible_to_other_instances_after_save(self):
        """Simulates two workers: separate objects, shared storage."""
        a = User_context("1")
        a.user_data["step"] = "email"
        b = User_context("1")
        assert b.user_data == {}  # not saved yet
        a.save()
        assert User_context("1").user_data == {"step": "email"}
        b.load()
        assert b.user_data == {"step": "email"}

    def test_nested_mutation_is_detected(self, memory_context_storage):
        ctx = User_context("1")
        ctx.user_data["cart"] = []
        ctx.save()
        ctx.user_data["cart"].append("apple")
        assert ctx.changed is True
        assert ctx.save() is True
        assert stored(memory_context_storage, "1") == {"cart": ["apple"]}

    def test_replace_user_data(self, memory_context_storage):
        ctx = User_context("1")
        ctx.user_data = {"fresh": True}
        assert ctx.save() is True
        assert stored(memory_context_storage, "1") == {"fresh": True}
        with pytest.raises(TypeError):
            ctx.user_data = ["not", "a", "dict"]

    def test_clear(self, memory_context_storage):
        ctx = User_context("1")
        ctx.user_data["a"] = 1
        ctx.save()
        ctx.clear()
        assert ctx.user_data == {}
        assert memory_context_storage.get("1") is None
        assert ctx.save() is False

    def test_refresh_discards_unsaved_changes(self, memory_context_storage):
        memory_context_storage.set("1", {"a": 1})
        ctx = User_context("1")
        ctx.user_data["a"] = 2
        ctx.refresh()
        assert ctx.user_data == {"a": 1}

    def test_force_save(self, memory_context_storage):
        ctx = User_context("1")
        assert ctx.save(force=True) is False  # never loaded: nothing to write
        ctx.user_data  # loads
        with patch.object(memory_context_storage, "set", wraps=memory_context_storage.set) as set_:
            assert ctx.save(force=True) is True
        set_.assert_called_once_with("1", {"user_data": {}})

    def test_context_manager_saves_on_exit(self, memory_context_storage):
        with User_context("1") as ctx:
            ctx.user_data["lang"] = "en"
        assert stored(memory_context_storage, "1") == {"lang": "en"}

    def test_non_serializable_value_raises_on_save(self):
        ctx = User_context("1")
        ctx.user_data["obj"] = object()
        with pytest.raises(ContextSerializationError):
            ctx.save()

    def test_repr(self):
        assert "User_context" in repr(User_context("1"))

    async def test_async_api(self, memory_context_storage):
        ctx = User_context("1")
        await ctx.aload()
        ctx.user_data["a"] = 1
        assert await ctx.asave() is True
        assert await ctx.asave() is False
        assert stored(memory_context_storage, "1") == {"a": 1}
        await ctx.aclear()
        assert memory_context_storage.get("1") is None

        async with User_context("2") as ctx2:
            ctx2.user_data["b"] = 2
        assert stored(memory_context_storage, "2") == {"b": 2}


# --------------------------------------------------------------------------- #
# Dispatcher integration
# --------------------------------------------------------------------------- #


class TestDispatcherIntegration:
    def test_context_persists_between_updates(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        seen = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            seen.append(copy.deepcopy(context.user_data))
            context.user_data["last"] = update.message_text
            context.user_data.setdefault("history", []).append(update.message_text)

        dispatcher.process_update(text_update(bot.id, "one"))
        dispatcher.process_update(text_update(bot.id, "two"))
        dispatcher.process_update(text_update(bot.id, "three", phone_number="999"))

        assert seen == [{}, {"last": "one", "history": ["one"]}, {}]
        assert stored(memory_context_storage, "1234567890") == {"last": "two", "history": ["one", "two"]}
        assert stored(memory_context_storage, "999") == {"last": "three", "history": ["three"]}

    def test_context_shared_between_dispatchers(self, tmp_path):
        """Two bots/dispatchers (i.e. two worker processes) sharing one SQLite file."""
        storage_a = SQLiteStorage(str(tmp_path / "shared.db"))
        storage_b = SQLiteStorage(str(tmp_path / "shared.db"))
        bot = make_bot()
        worker_a = Dispatcher(bot, context_storage=storage_a)
        worker_b = Dispatcher(bot, context_storage=storage_b)
        names = []

        def set_name(update, context):
            context.user_data["name"] = update.message_text

        def get_name(update, context):
            names.append(context.user_data.get("name"))

        worker_a._register_handler(MessageHandler(action=set_name))
        worker_b._register_handler(MessageHandler(action=get_name))

        worker_a.process_update(text_update(bot.id, "Ada"))
        worker_b.process_update(text_update(bot.id, "whatever"))
        assert names == ["Ada"]

    def test_no_write_when_context_untouched(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def handler(update, context):
            context.user_data.get("nothing")

        with patch.object(memory_context_storage, "set", wraps=memory_context_storage.set) as set_:
            dispatcher.process_update(text_update(bot.id))
        set_.assert_not_called()

    def test_unchanged_context_refreshes_ttl(self):
        storage = MemoryStorage(warn=False, ttl=3600)
        bot = make_bot()
        dispatcher = Dispatcher(bot, context_storage=storage)

        @dispatcher.add_message_handler()
        def handler(update, context):
            if update.message_text == "change":
                context.user_data["x"] = 1

        with patch.object(storage, "touch", wraps=storage.touch) as touch, \
                patch.object(storage, "set", wraps=storage.set) as set_:
            dispatcher.process_update(text_update(bot.id, "read only"))
            assert touch.call_count == 1 and set_.call_count == 0
            dispatcher.process_update(text_update(bot.id, "change"))
            assert touch.call_count == 1 and set_.call_count == 1

    async def test_unchanged_context_refreshes_ttl_async(self):
        storage = MemoryStorage(warn=False, ttl=3600)
        bot = make_bot()
        dispatcher = Dispatcher(bot, context_storage=storage)

        async def handler(update, context):
            pass

        dispatcher._register_handler(MessageHandler(action=handler))
        with patch.object(storage, "atouch", wraps=storage.atouch) as touch:
            await dispatcher.aprocess_update(text_update(bot.id))
        assert touch.call_count == 1

    def test_no_touch_without_ttl(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        with patch.object(memory_context_storage, "touch", wraps=memory_context_storage.touch) as touch:
            dispatcher.process_update(text_update(bot.id))
        touch.assert_not_called()

    def test_context_saved_even_if_handler_raises(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def handler(update, context):
            context.user_data["written"] = True
            raise RuntimeError("boom")

        dispatcher.process_update(text_update(bot.id))  # error is logged, not raised
        assert stored(memory_context_storage, "1234567890") == {"written": True}

    def test_save_failure_is_logged_not_raised(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        @dispatcher.add_message_handler()
        def handler(update, context):
            context.user_data["obj"] = object()  # not serializable

        with patch("python_whatsapp_bot.dispatcher.logger") as logger:
            dispatcher.process_update(text_update(bot.id))
        assert any("Failed to save context" in str(c) for c in logger.error.call_args_list)

    def test_multi_step_conversation(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        done = []

        @dispatcher.register_step("get_email")
        def get_email(update, context):
            context.user_data["email"] = update.message_text
            done.append((context.user_data["name"], context.user_data["email"]))

        @dispatcher.register_step("get_name")
        def get_name(update, context):
            context.user_data["name"] = update.message_text
            dispatcher.set_next_handler(update, get_email, handler_type=MessageHandler)

        @dispatcher.add_message_handler(regex=r"^/register")
        def start(update, context):
            context.user_data.clear()
            dispatcher.set_next_handler(update, get_name, handler_type=MessageHandler)

        dispatcher.process_update(text_update(bot.id, "/register"))
        dispatcher.process_update(text_update(bot.id, "Ada"))
        dispatcher.process_update(text_update(bot.id, "ada@example.com"))
        assert done == [("Ada", "ada@example.com")]
        assert stored(memory_context_storage, "1234567890") == {"name": "Ada", "email": "ada@example.com"}
        assert memory_context_storage.get("1234567890").get("next_step") is None

    def test_dispatcher_user_context_helper(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        with dispatcher.user_context("555") as ctx:
            ctx.user_data["vip"] = True
        assert stored(memory_context_storage, "555") == {"vip": True}

    async def test_async_context_persists_between_updates(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        seen = []

        async def handler(update, context):
            seen.append(dict(context.user_data))
            context.user_data["count"] = context.user_data.get("count", 0) + 1

        dispatcher._register_handler(MessageHandler(action=handler))
        await dispatcher.aprocess_update(text_update(bot.id))
        await dispatcher.aprocess_update(text_update(bot.id))
        assert seen == [{}, {"count": 1}]
        assert stored(memory_context_storage, "1234567890") == {"count": 2}

    async def test_async_context_saved_even_if_handler_raises(self, memory_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)

        async def handler(update, context):
            context.user_data["written"] = True
            raise RuntimeError("boom")

        dispatcher._register_handler(MessageHandler(action=handler))
        await dispatcher.aprocess_update(text_update(bot.id))
        assert stored(memory_context_storage, "1234567890") == {"written": True}


# --------------------------------------------------------------------------- #
# Per-user locking in the dispatcher
# --------------------------------------------------------------------------- #


class TestDispatcherLocking:
    def _dispatcher(self, storage, **kwargs):
        bot = make_bot()
        kwargs.setdefault("lock_wait", 0.2)
        dispatcher = Dispatcher(bot, context_storage=storage, **kwargs)
        return bot, dispatcher

    def test_defaults(self):
        bot = make_bot()
        d = Dispatcher(bot)
        assert d.context_lock is True
        assert d.lock_timeout == 60.0
        assert d.lock_wait == 10.0

    def test_lock_held_during_handler_and_released_after(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)
        observed = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            probe = memory_context_storage.lock("1234567890", blocking_timeout=0)
            observed.append(probe.acquire(blocking=False))

        dispatcher.process_update(text_update(bot.id))
        assert observed == [False]  # could not be taken while the handler ran
        assert memory_context_storage.lock("1234567890").acquire(blocking=False) is True

    def test_lock_released_when_handler_raises(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)

        @dispatcher.add_message_handler()
        def handler(update, context):
            raise RuntimeError("boom")

        dispatcher.process_update(text_update(bot.id))
        assert memory_context_storage.lock("1234567890").acquire(blocking=False) is True

    def test_busy_user_raises_lock_timeout_before_processing(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=0.2)
        called = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            called.append(1)

        other_worker = memory_context_storage.lock("1234567890")
        assert other_worker.acquire()
        t0 = time.monotonic()
        with pytest.raises(ContextLockTimeoutError) as exc:
            dispatcher.process_update(text_update(bot.id))
        assert 0.15 <= time.monotonic() - t0 < 2
        assert exc.value.key == "1234567890"
        assert called == []  # nothing was processed, so a WhatsApp retry is safe
        bot.mark_as_read.assert_not_called()
        other_worker.release()
        dispatcher.process_update(text_update(bot.id))
        assert called == [1]

    def test_waits_for_busy_user(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=2)
        called = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            called.append(1)

        other_worker = memory_context_storage.lock("1234567890")
        assert other_worker.acquire()
        threading.Timer(0.2, other_worker.release).start()
        dispatcher.process_update(text_update(bot.id))
        assert called == [1]

    def test_other_users_are_not_blocked(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)
        called = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            called.append(update.user_phone_number)

        busy = memory_context_storage.lock("1234567890")
        assert busy.acquire()
        dispatcher.process_update(text_update(bot.id, phone_number="999"))
        assert called == ["999"]
        busy.release()

    def test_threaded_mode_acquires_in_caller_and_releases_in_worker(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)
        bot.threaded = True
        done = threading.Event()
        proceed = threading.Event()

        @dispatcher.add_message_handler()
        def handler(update, context):
            proceed.wait(5)
            context.user_data["done"] = True
            done.set()

        dispatcher.process_update(text_update(bot.id))  # returns immediately (thread)
        # lock is already held by the in-flight thread
        assert memory_context_storage.lock("1234567890").acquire(blocking=False) is False
        proceed.set()
        assert done.wait(5)
        deadline = time.monotonic() + 5
        while memory_context_storage.lock("1234567890").acquire(blocking=False) is False:
            assert time.monotonic() < deadline, "lock was not released by worker thread"
            time.sleep(0.01)
        assert stored(memory_context_storage, "1234567890") == {"done": True}

    def test_threaded_mode_timeout_raises_in_caller(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=0.1)
        bot.threaded = True

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        busy = memory_context_storage.lock("1234567890")
        assert busy.acquire()
        with pytest.raises(ContextLockTimeoutError):
            dispatcher.process_update(text_update(bot.id))
        busy.release()

    def test_threaded_mode_serializes_same_user(self, memory_context_storage):
        """Rapid messages from one user are processed one at a time, in order."""
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=10)
        bot.threaded = True
        order = []
        inside = {"n": 0, "max": 0}

        @dispatcher.add_message_handler()
        def handler(update, context):
            inside["n"] += 1
            inside["max"] = max(inside["max"], inside["n"])
            time.sleep(0.02)
            context.user_data["count"] = context.user_data.get("count", 0) + 1
            order.append(update.message_text)
            inside["n"] -= 1

        for i in range(5):
            dispatcher.process_update(text_update(bot.id, str(i)))
        deadline = time.monotonic() + 10
        while len(order) < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert order == ["0", "1", "2", "3", "4"]
        assert inside["max"] == 1
        assert stored(memory_context_storage, "1234567890") == {"count": 5}

    def test_locking_can_be_disabled(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage, context_lock=False)
        called = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            called.append(1)

        busy = memory_context_storage.lock("1234567890")
        assert busy.acquire()
        dispatcher.process_update(text_update(bot.id))  # does not wait or fail
        assert called == [1]
        busy.release()

    def test_lock_taken_even_if_handler_ignores_context(self, memory_context_storage):
        """Every message is locked when a storage is configured: the user's record must be
        read anyway to find a pending next step, and a handler may call set_next_step."""
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=0.1)
        called = []

        @dispatcher.add_message_handler()
        def handler(update):
            called.append(1)

        busy = memory_context_storage.lock("1234567890")
        assert busy.acquire()
        with pytest.raises(ContextLockTimeoutError):
            dispatcher.process_update(text_update(bot.id))
        busy.release()
        dispatcher.process_update(text_update(bot.id))
        assert called == [1]

    def test_no_lock_without_storage(self, no_context_storage):
        bot = make_bot()
        dispatcher = Dispatcher(bot)
        called = []

        @dispatcher.add_message_handler()
        def handler(update):
            called.append(1)

        with patch.object(dispatcher, "_acquire_user_lock", wraps=dispatcher._acquire_user_lock) as acq:
            dispatcher.process_update(text_update(bot.id))
        assert called == [1]
        assert acq.call_args[0][1] is None  # no storage -> nothing to lock

    def test_no_lock_for_non_message_or_foreign_updates(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        busy = memory_context_storage.lock("1234567890")
        assert busy.acquire()
        status_update = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": bot.id},
                                                            "statuses": [{"id": "x"}]}}]}]}
        dispatcher.process_update(status_update)
        foreign = text_update("other-bot")
        dispatcher.process_update(foreign)
        dispatcher.process_update({"invalid": True})
        busy.release()

    def test_storage_without_locking_hard_fails(self):
        class NoLock(ContextStorage):
            def get(self, key):
                return None

            def set(self, key, data):
                pass

            def delete(self, key):
                pass

        bot, dispatcher = self._dispatcher(NoLock())

        @dispatcher.add_message_handler()
        def handler(update, context):
            pass

        with pytest.raises(ContextLockNotSupportedError):
            dispatcher.process_update(text_update(bot.id))

        dispatcher.context_lock = False
        dispatcher.process_update(text_update(bot.id))  # explicit opt-out works

    def test_expired_lock_is_logged(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_timeout=0.05)

        @dispatcher.add_message_handler()
        def handler(update, context):
            time.sleep(0.1)

        with patch("python_whatsapp_bot.dispatcher.logger") as logger:
            dispatcher.process_update(text_update(bot.id))
        assert any("lock expired" in str(c) for c in logger.warning.call_args_list)

    async def test_async_lock_held_and_released(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)
        observed = []

        async def handler(update, context):
            observed.append(memory_context_storage.lock("1234567890").acquire(blocking=False))
            context.user_data["n"] = 1

        dispatcher._register_handler(MessageHandler(action=handler))
        await dispatcher.aprocess_update(text_update(bot.id))
        assert observed == [False]
        assert memory_context_storage.lock("1234567890").acquire(blocking=False) is True
        assert stored(memory_context_storage, "1234567890") == {"n": 1}

    async def test_async_busy_user_raises(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=0.1)

        async def handler(update, context):
            pass  # pragma: no cover

        dispatcher._register_handler(MessageHandler(action=handler))
        busy = memory_context_storage.lock("1234567890")
        assert busy.acquire()
        with pytest.raises(ContextLockTimeoutError):
            await dispatcher.aprocess_update(text_update(bot.id))
        busy.release()

    async def test_async_lock_released_when_handler_raises(self, memory_context_storage):
        bot, dispatcher = self._dispatcher(memory_context_storage)

        async def handler(update, context):
            raise RuntimeError("boom")

        dispatcher._register_handler(MessageHandler(action=handler))
        await dispatcher.aprocess_update(text_update(bot.id))
        assert memory_context_storage.lock("1234567890").acquire(blocking=False) is True

    def test_each_call_handles_only_its_own_update(self, memory_context_storage):
        """Two webhook requests at once: a lock timeout must be reported to the request
        that delivered the affected message, and the other request must not process it."""
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=0.2)
        b_arrived = threading.Event()
        processed = []

        @dispatcher.add_message_handler()
        def handler(update, context):
            if update.user_phone_number == "A":
                b_arrived.wait(5)  # A is mid-handler while B's request comes in
            processed.append(update.user_phone_number)

        busy = memory_context_storage.lock("B")
        assert busy.acquire()
        results = {}

        def request(name, phone):
            try:
                dispatcher.process_update(text_update(bot.id, "hi", phone_number=phone))
                results[name] = "ok"
            except ContextLockTimeoutError as exc:
                results[name] = "busy:" + exc.key

        t_a = threading.Thread(target=request, args=("A", "A"))
        t_b = threading.Thread(target=request, args=("B", "B"))
        t_a.start()
        t_b.start()
        b_arrived.set()
        t_a.join(5)
        t_b.join(5)
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results == {"A": "ok", "B": "busy:B"}
        assert processed == ["A"]
        busy.release()

    def test_concurrent_webhook_calls_process_every_update_exactly_once(self, memory_context_storage):
        """Models a threaded web server: many simultaneous process_update calls."""
        bot, dispatcher = self._dispatcher(memory_context_storage, lock_wait=10)
        seen = []
        seen_lock = threading.Lock()

        @dispatcher.add_message_handler()
        def handler(update, context):
            time.sleep(0.005)
            context.user_data["n"] = context.user_data.get("n", 0) + 1
            with seen_lock:
                seen.append((update.user_phone_number, update.message_text))

        def request(user, i):
            dispatcher.process_update(text_update(bot.id, str(i), phone_number=user))

        threads = [
            threading.Thread(target=request, args=("user%d" % u, i)) for u in range(8) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        assert not any(t.is_alive() for t in threads), "a process_update call hung"
        assert sorted(seen) == sorted(("user%d" % u, str(i)) for u in range(8) for i in range(5))
        for u in range(8):
            assert stored(memory_context_storage, "user%d" % u) == {"n": 5}

    def test_four_bot_processes_share_one_user_without_lost_updates(self, tmp_path, no_context_storage):
        """The `uvicorn -w 4` scenario, end to end: separate processes, each with its own
        Whatsapp instance in the default threaded mode, all handling the same user."""
        db = str(tmp_path / "bot.db")
        src = str(os.path.join(os.path.dirname(__file__), "..", "src"))
        script = textwrap.dedent(
            """
            import sys, time, json
            from python_whatsapp_bot import Whatsapp, SQLiteStorage
            db, n = sys.argv[1], int(sys.argv[2])
            bot = Whatsapp("123", "token", mark_as_read=False,
                           context_storage=SQLiteStorage(db), context_lock_wait=30)
            assert bot.threaded  # library default: handlers run in threads

            @bot.on_message()
            def count(update, context):
                context.user_data["count"] = context.user_data.get("count", 0) + 1

            def update(text):
                return {"entry": [{"changes": [{"value": {
                    "metadata": {"phone_number_id": "123"},
                    "messages": [{"id": "m", "type": "text", "text": {"body": text}}],
                    "contacts": [{"wa_id": "2348145000000", "profile": {"name": "Ada"}}]}}]}]}

            for i in range(n):
                bot.process_update(update(str(i)))
            time.sleep(1)  # let the worker threads finish
            """
        )
        env = dict(os.environ, PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
        procs = [
            subprocess.Popen([sys.executable, "-c", script, db, "10"], stderr=subprocess.PIPE, env=env)
            for _ in range(4)
        ]
        for p in procs:
            _, err = p.communicate(timeout=120)
            assert p.returncode == 0, err.decode()
        assert stored(SQLiteStorage(db), "2348145000000") == {"count": 40}


# --------------------------------------------------------------------------- #
# Whatsapp facade
# --------------------------------------------------------------------------- #


class TestWhatsappFacade:
    def test_constructor_accepts_storage(self):
        storage = MemoryStorage(warn=False)
        bot = Whatsapp("123", "token", context_storage=storage)
        assert bot.context_storage is storage
        assert bot.dispatcher.context_storage is storage

    def test_update_reply_media_reaches_send_media_message(self):
        from python_whatsapp_bot import Update

        bot = Whatsapp("123", "token")
        update = Update(bot, {"messages": [{"id": "m"}], "contacts": [{"wa_id": "555"}]})
        with patch("python_whatsapp_bot.whatsapp.message_media") as send:
            update.reply_media("https://example.com/a.jpg", caption="hi")
        assert send.call_args[0][2] == "555"
        assert send.call_args[0][3] == "https://example.com/a.jpg"
        with patch("python_whatsapp_bot.whatsapp.message_media") as send:
            bot.reply_media("777", "https://example.com/b.jpg")
        assert send.call_args[0][2] == "777"

    def test_send_template_message_defaults_language(self):
        import json

        bot = Whatsapp("123", "token")
        with patch("python_whatsapp_bot.message.requests.post") as post:
            bot.send_template_message("555", "hello_world")
        assert json.loads(post.call_args.kwargs["data"])["template"]["language"] == {"code": "en_US"}

    def test_constructor_lock_options(self):
        bot = Whatsapp("123", "token", context_lock=False, context_lock_timeout=120, context_lock_wait=3)
        assert bot.dispatcher.context_lock is False
        assert bot.dispatcher.lock_timeout == 120
        assert bot.dispatcher.lock_wait == 3

    def test_set_context_storage_later(self):
        bot = Whatsapp("123", "token")
        assert bot.context_storage is None
        storage = MemoryStorage(warn=False)
        bot.set_context_storage(storage)
        assert bot.dispatcher.context_storage is storage

    def test_user_context_helper(self):
        storage = MemoryStorage(warn=False)
        bot = Whatsapp("123", "token", context_storage=storage)
        with bot.user_context("777") as ctx:
            ctx.user_data["k"] = "v"
        assert stored(storage, "777") == {"k": "v"}

    def test_end_to_end_with_sqlite(self, tmp_path, no_context_storage):
        storage = SQLiteStorage(str(tmp_path / "bot.db"))
        bot = Whatsapp("123", "token", mark_as_read=False, context_storage=storage)
        bot.threaded = False
        replies = []

        @bot.on_message(regex=r"^/setname (.+)")
        def set_name(update, context):
            context.user_data["name"] = update.message_text.split(" ", 1)[1]

        @bot.on_message(regex=r"^/getname")
        def get_name(update, context):
            replies.append(context.user_data.get("name", "Not set"))

        bot.process_update(text_update("123", "/getname"))
        bot.process_update(text_update("123", "/setname Ada"))
        bot.process_update(text_update("123", "/getname"))
        assert replies == ["Not set", "Ada"]
        assert stored(SQLiteStorage(str(tmp_path / "bot.db")), "1234567890") == {"name": "Ada"}
