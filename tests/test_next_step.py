"""Tests for persisted next-step (multi-step conversation) state."""

import os
import subprocess
import sys
import textwrap
from unittest.mock import Mock, patch

import pytest

from python_whatsapp_bot import Whatsapp
from python_whatsapp_bot.context_storage import (
    ContextStorageNotConfiguredError,
    MemoryStorage,
    SQLiteStorage,
)
from python_whatsapp_bot.dispatcher import Dispatcher
from python_whatsapp_bot.handler_classes import InteractiveQueryHandler, MessageHandler, Update
from python_whatsapp_bot.next_step import (
    NextStepNotSerializableError,
    NextStepResolutionError,
    StepRegistry,
    build_next_step,
    build_next_step_handlers,
    callable_to_ref,
    end_conversation,
    ref_to_callable,
)
from python_whatsapp_bot.user_context import User_context

PHONE = "1234567890"


def make_bot():
    bot = Mock()
    bot.id = "123456789"
    bot.threaded = False
    bot.mark_as_read = Mock()
    return bot


def text_update(bot_id, message_text="Hello", phone_number=PHONE):
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


def button_update(bot_id, button_id, phone_number=PHONE):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": bot_id},
                            "messages": [
                                {
                                    "id": "msg_123",
                                    "type": "interactive",
                                    "interactive": {"type": "button_reply", "button_reply": {"id": button_id}},
                                }
                            ],
                            "contacts": [{"wa_id": phone_number, "profile": {"name": "Test User"}}],
                        }
                    }
                ]
            }
        ]
    }


# Module-level steps: importable by name, the normal production case.
CALLS = []


def step_get_name(update, context):
    context.user_data["name"] = update.message_text
    CALLS.append(("name", update.message_text))


def step_get_email(update, context):
    context.user_data["email"] = update.message_text
    CALLS.append(("email", update.message_text))


def step_without_context(update):
    CALLS.append(("nocontext", update.message_text))


def step_end(update):
    CALLS.append(("end", update.message_text))


def only_digits(text):
    return text.isdigit()


async def astep_get_name(update, context):
    context.user_data["name"] = update.message_text
    CALLS.append(("aname", update.message_text))


class Steps:
    def method(self, update, context):  # pragma: no cover - never called
        pass


@pytest.fixture(autouse=True)
def _reset_calls():
    del CALLS[:]


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #


class TestReferences:
    def test_module_level_function_is_referenced_by_import_path(self):
        reg = StepRegistry()
        ref = callable_to_ref(step_get_name, reg)
        assert ref == "import:{}:step_get_name".format(__name__)
        assert ref_to_callable(ref, reg) is step_get_name

    def test_registered_function_is_referenced_by_name(self):
        reg = StepRegistry()

        def closure(update, context):  # pragma: no cover
            pass

        reg.register("my_step", closure)
        assert callable_to_ref(closure, reg) == "step:my_step"
        assert ref_to_callable("step:my_step", reg) is closure

    @pytest.mark.parametrize(
        "func",
        [
            lambda update: None,
            Steps().method,
            __import__("functools").partial(step_get_name),
        ],
        ids=["lambda", "bound-method", "partial"],
    )
    def test_unreferencable_callables_are_rejected_with_guidance(self, func):
        with pytest.raises(NextStepNotSerializableError) as exc:
            callable_to_ref(func, StepRegistry())
        assert "register_step" in str(exc.value)

    def test_nested_function_is_rejected(self):
        def nested(update, context):  # pragma: no cover
            pass

        with pytest.raises(NextStepNotSerializableError) as exc:
            callable_to_ref(nested, StepRegistry())
        assert "register_step('nested')" in str(exc.value)

    def test_non_callable_rejected(self):
        with pytest.raises(TypeError):
            callable_to_ref("not a function", StepRegistry())

    def test_unknown_references_fail_to_resolve(self):
        reg = StepRegistry()
        with pytest.raises(NextStepResolutionError):
            ref_to_callable("step:never_registered", reg)
        with pytest.raises(NextStepResolutionError):
            ref_to_callable("import:no.such.module:fn", reg)
        with pytest.raises(NextStepResolutionError):
            ref_to_callable("import:{}:no_such_function".format(__name__), reg)
        with pytest.raises(NextStepResolutionError):
            ref_to_callable("garbage", reg)
        with pytest.raises(NextStepResolutionError):
            ref_to_callable(None, reg)

    def test_registry_rules(self):
        reg = StepRegistry()
        reg.register("a", step_get_name)
        reg.register("a", step_get_name)  # idempotent
        with pytest.raises(ValueError):
            reg.register("a", step_get_email)
        with pytest.raises(TypeError):
            reg.register("", step_get_name)
        with pytest.raises(TypeError):
            reg.register("b", "nope")
        assert "a" in reg and len(reg) == 1

    def test_spec_roundtrip(self):
        reg = StepRegistry()
        spec = build_next_step(
            step_get_name,
            reg,
            handler_type=MessageHandler,
            regex=r"^\w+$",
            func=only_digits,
            end_conversation_keyword_regex=r"(?i)^quit$",
        )
        assert spec["handler_type"].endswith(":MessageHandler")
        assert spec["end_action"].endswith(":end_conversation")
        fallback, handler = build_next_step_handlers(spec, reg)
        assert isinstance(handler, MessageHandler)
        assert handler.action is step_get_name and handler.regex == r"^\w+$" and handler.func is only_digits
        assert isinstance(fallback, MessageHandler)
        assert fallback.regex == r"(?i)^quit$" and fallback.action is end_conversation

    def test_spec_without_end_keyword_has_no_fallback(self):
        reg = StepRegistry()
        spec = build_next_step(step_get_name, reg, end_conversation_keyword_regex=None)
        fallback, handler = build_next_step_handlers(spec, reg)
        assert fallback is None and handler.action is step_get_name

    def test_bad_handler_type(self):
        with pytest.raises(TypeError):
            build_next_step(step_get_name, StepRegistry(), handler_type=dict)
        with pytest.raises(NextStepResolutionError):
            build_next_step_handlers({"handler": "import:{}:step_get_name".format(__name__),
                                      "handler_type": "import:builtins:dict"}, StepRegistry())
        with pytest.raises(NextStepResolutionError):
            build_next_step_handlers("nonsense", StepRegistry())


# --------------------------------------------------------------------------- #
# Storage layout
# --------------------------------------------------------------------------- #


class TestRecordLayout:
    def test_next_step_lives_next_to_user_data(self, memory_context_storage):
        ctx = User_context(PHONE)
        ctx.user_data["name"] = "Ada"
        ctx.next_step = {"handler": "x"}
        ctx.save()
        assert memory_context_storage.get(PHONE) == {"user_data": {"name": "Ada"}, "next_step": {"handler": "x"}}
        again = User_context(PHONE)
        assert again.user_data == {"name": "Ada"}
        assert again.next_step == {"handler": "x"}

    def test_user_data_clear_does_not_touch_next_step(self, memory_context_storage):
        ctx = User_context(PHONE)
        ctx.user_data["name"] = "Ada"
        ctx.next_step = {"handler": "x"}
        ctx.user_data.clear()
        ctx.user_data = {}
        assert ctx.next_step == {"handler": "x"}
        ctx.save()
        assert memory_context_storage.get(PHONE) == {"user_data": {}, "next_step": {"handler": "x"}}

    def test_context_clear_removes_both(self, memory_context_storage):
        ctx = User_context(PHONE)
        ctx.user_data["a"] = 1
        ctx.next_step = {"handler": "x"}
        ctx.save()
        ctx.clear()
        assert ctx.next_step is None and ctx.user_data == {}
        assert memory_context_storage.get(PHONE) is None

    def test_setting_none_removes_key(self, memory_context_storage):
        ctx = User_context(PHONE)
        ctx.next_step = {"handler": "x"}
        ctx.next_step = None
        ctx.save(force=True)
        assert memory_context_storage.get(PHONE) == {"user_data": {}}

    def test_type_checked(self):
        ctx = User_context(PHONE)
        with pytest.raises(TypeError):
            ctx.next_step = "x"

    def test_flat_record_written_by_hand_is_read_as_user_data(self, memory_context_storage):
        memory_context_storage.set(PHONE, {"legacy": True})
        ctx = User_context(PHONE)
        assert ctx.user_data == {"legacy": True} and ctx.next_step is None
        ctx.user_data["x"] = 1
        ctx.save()
        assert memory_context_storage.get(PHONE) == {"user_data": {"legacy": True, "x": 1}}

    def test_garbage_next_step_in_storage_is_ignored(self, memory_context_storage):
        memory_context_storage.set(PHONE, {"user_data": {}, "next_step": "garbage"})
        assert User_context(PHONE).next_step is None


# --------------------------------------------------------------------------- #
# Dispatcher behaviour
# --------------------------------------------------------------------------- #


class TestDispatcherNextStep:
    def test_next_step_survives_across_workers(self, memory_context_storage):
        """Worker A sets the step, worker B (a different Dispatcher) handles the reply."""
        bot = make_bot()
        worker_a, worker_b = Dispatcher(bot), Dispatcher(bot)
        for w in (worker_a, worker_b):

            @w.add_message_handler(regex=r"^/register")
            def start(update, context):
                w.set_next_handler(update, step_get_name, handler_type=MessageHandler)

            @w.add_message_handler()
            def default(update, context):
                CALLS.append(("default", update.message_text))

        worker_a.process_update(text_update(bot.id, "/register"))
        record = memory_context_storage.get(PHONE)
        assert record["next_step"]["handler"] == "import:{}:step_get_name".format(__name__)

        worker_b.process_update(text_update(bot.id, "Ada"))
        assert CALLS == [("name", "Ada")]
        assert memory_context_storage.get(PHONE) == {"user_data": {"name": "Ada"}}  # step cleared

        worker_a.process_update(text_update(bot.id, "hello"))
        assert CALLS[-1] == ("default", "hello")

    def test_registered_closures_work_across_workers(self, memory_context_storage):
        bot = make_bot()
        seen = []

        def make_worker():
            w = Dispatcher(bot)

            @w.register_step("ask_age")
            def ask_age(update, context):  # a closure: not importable, hence registered
                seen.append(update.message_text)

            @w.add_message_handler(regex=r"^/start")
            def start(update, context):
                w.set_next_handler(update, ask_age, handler_type=MessageHandler)

            return w

        a, b = make_worker(), make_worker()
        a.process_update(text_update(bot.id, "/start"))
        assert memory_context_storage.get(PHONE)["next_step"]["handler"] == "step:ask_age"
        b.process_update(text_update(bot.id, "42"))
        assert seen == ["42"]

    def test_unregistered_closure_hard_fails_at_set_time(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        @d.add_message_handler()
        def start(update, context):
            def nested(update, context):  # pragma: no cover
                pass

            d.set_next_handler(update, nested, handler_type=MessageHandler)

        with pytest.raises(NextStepNotSerializableError):
            d.process_update(text_update(bot.id, "go"))
        assert memory_context_storage.get(PHONE) is None  # nothing persisted

    def test_lambda_end_action_rejected(self, memory_context_storage):
        d = Dispatcher(make_bot())
        with pytest.raises(NextStepNotSerializableError):
            d.set_next_handler(Update(d.bot, text_update(d.bot.id)["entry"][0]["changes"][0]["value"]),
                               step_get_name, end_conversation_action=lambda u: u)

    def test_stale_reference_is_dropped_and_regular_handlers_run(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        @d.add_message_handler()
        def default(update, context):
            CALLS.append(("default", update.message_text))

        memory_context_storage.set(
            PHONE,
            {"user_data": {"keep": 1}, "next_step": {"handler": "import:{}:renamed_away".format(__name__),
                                                      "handler_type": "import:python_whatsapp_bot.handler_classes:MessageHandler"}},
        )
        with patch("python_whatsapp_bot.dispatcher.logger") as logger:
            d.process_update(text_update(bot.id, "hi"))
        assert any("Dropping stored next step" in str(c) for c in logger.error.call_args_list)
        assert CALLS == [("default", "hi")]
        assert memory_context_storage.get(PHONE) == {"user_data": {"keep": 1}}

    def test_set_from_handler_without_context_is_persisted_in_one_write(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        @d.add_message_handler(regex=r"^/go")
        def start(update):  # no context parameter at all
            d.set_next_handler(update, step_without_context, handler_type=MessageHandler)

        with patch.object(memory_context_storage, "set", wraps=memory_context_storage.set) as set_:
            d.process_update(text_update(bot.id, "/go"))
        assert set_.call_count == 1
        assert memory_context_storage.get(PHONE)["next_step"]["handler"].endswith(":step_without_context")
        d.process_update(text_update(bot.id, "next"))
        assert CALLS == [("nocontext", "next")]

    def test_chained_steps(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        def get_name_then_email(update, context):
            step_get_name(update, context)
            d.set_next_handler(update, step_get_email, handler_type=MessageHandler)

        d.register_step("get_name_then_email")(get_name_then_email)

        @d.add_message_handler(regex=r"^/register")
        def start(update, context):
            d.set_next_handler(update, get_name_then_email, handler_type=MessageHandler)

        d.process_update(text_update(bot.id, "/register"))
        d.process_update(text_update(bot.id, "Ada"))
        assert memory_context_storage.get(PHONE)["next_step"]["handler"].endswith(":step_get_email")
        d.process_update(text_update(bot.id, "ada@x.io"))
        assert CALLS == [("name", "Ada"), ("email", "ada@x.io")]
        assert memory_context_storage.get(PHONE) == {"user_data": {"name": "Ada", "email": "ada@x.io"}}

    def test_step_retained_if_its_handler_raises(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        def flaky(update, context):
            raise RuntimeError("boom")

        d.register_step("flaky")(flaky)
        d.set_next_handler(Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]), flaky)
        d.process_update(text_update(bot.id, "x"))
        assert memory_context_storage.get(PHONE)["next_step"]["handler"] == "step:flaky"

    def test_end_keyword_uses_default_end_action(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)
        d.set_next_handler(Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]), step_get_name)
        d.process_update(text_update(bot.id, "cancel"))
        assert CALLS == []
        assert d.get_next_step(PHONE) is None

    def test_custom_end_action_and_regex(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)
        d.set_next_handler(
            Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]),
            step_get_name,
            handler_type=MessageHandler,
            end_conversation_action=step_end,
            end_conversation_keyword_regex=r"(?i)^quit$",
        )
        d.process_update(text_update(bot.id, "cancel"))  # not the end keyword: handled by the step
        d.process_update(text_update(bot.id, "quit"))  # step already consumed
        assert CALLS == [("name", "cancel")]
        d.set_next_handler(
            Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]),
            step_get_name,
            end_conversation_action=step_end,
            end_conversation_keyword_regex=r"(?i)^quit$",
        )
        d.process_update(text_update(bot.id, "QUIT"))
        assert CALLS[-1] == ("end", "QUIT")
        assert d.get_next_step(PHONE) is None

    def test_filters_persist(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        @d.add_message_handler()
        def default(update, context):
            CALLS.append(("default", update.message_text))

        d.set_next_handler(
            Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]),
            step_get_name,
            handler_type=MessageHandler,
            func=only_digits,
        )
        d.process_update(text_update(bot.id, "abc"))  # filter rejects: nothing runs, step kept
        assert CALLS == [] and d.get_next_step(PHONE) is not None
        d.process_update(text_update(bot.id, "42"))
        assert CALLS == [("name", "42")] and d.get_next_step(PHONE) is None

    def test_interactive_handler_type(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)
        d.set_next_handler(
            Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]),
            step_get_name,
            handler_type=InteractiveQueryHandler,
        )
        d.process_update(text_update(bot.id, "text is ignored"))
        assert CALLS == []
        d.process_update(button_update(bot.id, "btn_yes"))
        assert CALLS == [("name", "btn_yes")]

    def test_clear_next_step_from_handler_and_outside(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        @d.add_message_handler(regex=r"^/abort", persistent=True)
        def abort(update):
            CALLS.append(("abort", d.clear_next_step(update)))

        d.set_next_handler(Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]), step_get_name)
        d.process_update(text_update(bot.id, "/abort"))
        assert CALLS == [("abort", True)]
        assert d.get_next_step(PHONE) is None
        d.set_next_handler(Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]), step_get_name)
        assert d.clear_next_step(PHONE) is True
        assert d.clear_next_step(PHONE) is False

    def test_set_next_step_without_storage_hard_fails(self, no_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)
        with pytest.raises(ContextStorageNotConfiguredError):
            d.set_next_handler(Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]), step_get_name)

    def test_register_step_forms(self, memory_context_storage):
        d = Dispatcher(make_bot())

        @d.register_step
        def bare(update, context):  # pragma: no cover
            pass

        @d.register_step("named")
        def named(update, context):  # pragma: no cover
            pass

        assert d.steps.get("bare") is bare and d.steps.get("named") is named

    def test_sets_context_required(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)
        assert d.context_required is False
        d.set_next_handler(Update(bot, text_update(bot.id)["entry"][0]["changes"][0]["value"]), step_get_name)
        assert d.context_required is True

    async def test_async_flow(self, memory_context_storage):
        bot = make_bot()
        d = Dispatcher(bot)

        async def start(update, context):
            d.set_next_handler(update, astep_get_name, handler_type=MessageHandler)

        d._register_handler(MessageHandler(regex=r"^/register", action=start))
        await d.aprocess_update(text_update(bot.id, "/register"))
        assert memory_context_storage.get(PHONE)["next_step"]["handler"].endswith(":astep_get_name")
        await d.aprocess_update(text_update(bot.id, "Ada"))
        assert CALLS == [("aname", "Ada")]
        assert memory_context_storage.get(PHONE) == {"user_data": {"name": "Ada"}}

    def test_whatsapp_facade(self):
        storage = MemoryStorage(warn=False)
        bot = Whatsapp("123", "token", mark_as_read=False, context_storage=storage)
        bot.threaded = False

        @bot.register_step("ask")
        def ask(update, context):
            context.user_data["answer"] = update.message_text

        @bot.on_message(regex=r"^/q")
        def q(update, context):
            bot.set_next_step(update, ask, handler_type=MessageHandler)

        bot.process_update(text_update("123", "/q"))
        assert bot.get_next_step(PHONE)["handler"] == "step:ask"
        bot.process_update(text_update("123", "yes"))
        assert storage.get(PHONE) == {"user_data": {"answer": "yes"}}
        assert bot.clear_next_step(PHONE) is False

    def test_next_step_across_processes(self, tmp_path, no_context_storage):
        """Process 1 starts the conversation, process 2 receives the reply (shared SQLite)."""
        db = str(tmp_path / "bot.db")
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        module = tmp_path / "botapp.py"
        module.write_text(
            textwrap.dedent(
                """
                import sys
                from python_whatsapp_bot import Whatsapp, SQLiteStorage, MessageHandler

                def make_bot(db):
                    bot = Whatsapp("123", "token", mark_as_read=False, context_storage=SQLiteStorage(db))
                    bot.threaded = False

                    @bot.on_message(regex=r"^/register")
                    def start(update, context):
                        bot.set_next_step(update, get_name, handler_type=MessageHandler)

                    @bot.on_message()
                    def default(update, context):
                        print("DEFAULT", update.message_text)

                    return bot

                def get_name(update, context):
                    context.user_data["name"] = update.message_text
                    print("STEP", update.message_text)

                def update(text):
                    return {"entry": [{"changes": [{"value": {
                        "metadata": {"phone_number_id": "123"},
                        "messages": [{"id": "m", "type": "text", "text": {"body": text}}],
                        "contacts": [{"wa_id": "555", "profile": {"name": "Ada"}}]}}]}]}

                def main(db, text):
                    make_bot(db).process_update(update(text))
                """
            )
        )
        env = dict(os.environ, PYTHONPATH=src + os.pathsep + str(tmp_path))

        def run(text):
            # Imported as a module (as gunicorn/uvicorn do), so refs are "import:botapp:..."
            out = subprocess.run(
                [sys.executable, "-c", "import sys, botapp; botapp.main(sys.argv[1], sys.argv[2])", db, text],
                capture_output=True, env=env, timeout=60,
            )
            assert out.returncode == 0, out.stderr.decode()
            return out.stdout.decode().strip()

        assert run("/register") == ""
        assert SQLiteStorage(db).get("555")["next_step"]["handler"] == "import:botapp:get_name"
        assert run("Ada") == "STEP Ada"
        assert run("hello") == "DEFAULT hello"
        assert SQLiteStorage(db).get("555") == {"user_data": {"name": "Ada"}}
