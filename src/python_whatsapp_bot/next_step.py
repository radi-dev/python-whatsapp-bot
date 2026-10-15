"""Persistable "next step" conversation state.

``bot.set_next_step(update, function)`` registers the function that must handle
the user's *next* message. To survive worker restarts and to be visible to every
worker process, that state is stored in the user's context record (next to
``user_data``) - but functions cannot be stored in Redis or SQL, so they are
stored as *references* which every worker can resolve:

* ``import:<module>:<qualname>`` - any function importable by name (module-level
  functions). Works with no extra code.
* ``step:<name>`` - a function registered under a stable name with
  ``bot.register_step(name)``. Needed for functions that are not importable:
  closures (e.g. defined inside an app factory), methods, ``functools.partial``.

Lambdas and unregistered nested functions are rejected when the step is set,
with an error explaining both options. A stored reference that no longer
resolves (e.g. after a deploy renamed the function) is logged and discarded so
the user's message falls through to the regular handlers instead of failing
forever.
"""

import importlib
import inspect
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from .context_storage import ContextStorageError
from .handler_classes import InteractiveQueryHandler, MessageHandler, UpdateHandler

logger = logging.getLogger(__name__)

__all__ = [
    "NextStepError",
    "NextStepNotSerializableError",
    "NextStepResolutionError",
    "StepRegistry",
    "build_next_step",
    "build_next_step_handlers",
    "end_conversation",
]


class NextStepError(ContextStorageError):
    """Base class for next-step persistence problems."""


class NextStepNotSerializableError(NextStepError, ValueError):
    """The function given to ``set_next_step`` cannot be referenced from other workers."""


class NextStepResolutionError(NextStepError, LookupError):
    """A stored next-step reference could not be turned back into a function."""


def end_conversation(update):
    # type: (Any) -> None
    """Default ``end_conversation_action``: consumes the end keyword and does nothing."""
    return None


class StepRegistry:
    """Maps stable names to functions (and back) for non-importable callables."""

    def __init__(self):
        # type: () -> None
        self._by_name = {}  # type: Dict[str, Callable]
        self._by_func = {}  # type: Dict[Callable, str]

    def register(self, name, func):
        # type: (str, Callable) -> Callable
        if not isinstance(name, str) or not name:
            raise TypeError("step name must be a non-empty string, got {!r}".format(name))
        if not callable(func):
            raise TypeError("step {!r} must be callable, got {!r}".format(name, func))
        existing = self._by_name.get(name)
        if existing is not None and existing is not func:
            raise ValueError("a different function is already registered as step {!r}".format(name))
        self._by_name[name] = func
        try:
            self._by_func[func] = name
        except TypeError:  # unhashable callable
            pass
        return func

    def get(self, name):
        # type: (str) -> Optional[Callable]
        return self._by_name.get(name)

    def name_of(self, func):
        # type: (Callable) -> Optional[str]
        try:
            return self._by_func.get(func)
        except TypeError:
            return None

    def __contains__(self, name):
        # type: (object) -> bool
        return name in self._by_name

    def __len__(self):
        # type: () -> int
        return len(self._by_name)


# --------------------------------------------------------------------------- #
# Callable <-> reference
# --------------------------------------------------------------------------- #


def _import_ref(obj):
    # type: (Any) -> Optional[str]
    """``module:qualname`` for an object importable by name, else None."""
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if not module or not qualname or "<locals>" in qualname or "<lambda>" in qualname:
        return None
    ref = "import:{}:{}".format(module, qualname)
    try:
        return ref if _resolve_import(ref) is obj else None
    except Exception:
        return None


def _resolve_import(ref):
    # type: (str) -> Any
    _, module_name, qualname = ref.split(":", 2)
    obj = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def callable_to_ref(func, registry, what="function"):
    # type: (Callable, StepRegistry, str) -> str
    """Serialize ``func`` to a reference other workers can resolve. Raises if impossible."""
    if not callable(func):
        raise TypeError("{} must be callable, got {!r}".format(what, func))
    name = registry.name_of(func)
    if name is not None:
        return "step:" + name
    ref = _import_ref(func)
    if ref is not None:
        return ref
    raise NextStepNotSerializableError(
        "The {what} {func!r} cannot be used as a next step: it must be resolvable from every "
        "worker process, but it is not importable by name (lambda, nested function, method or "
        "partial?). Either define it at module level, or register it under a stable name:\n\n"
        "    @wa_bot.register_step('{name}')\n"
        "    def {name}(update, context): ...\n".format(
            what=what, func=func, name=getattr(func, "__name__", "my_step").strip("<>") or "my_step"
        )
    )


def ref_to_callable(ref, registry, what="function"):
    # type: (str, StepRegistry, str) -> Callable
    """Resolve a reference produced by :func:`callable_to_ref`."""
    if not isinstance(ref, str):
        raise NextStepResolutionError("invalid {} reference: {!r}".format(what, ref))
    if ref.startswith("step:"):
        func = registry.get(ref[5:])
        if func is None:
            raise NextStepResolutionError(
                "next-step {} {!r} is not registered in this process; register it with "
                "bot.register_step({!r}) in every worker (at import time).".format(what, ref[5:], ref[5:])
            )
        return func
    if ref.startswith("import:"):
        try:
            func = _resolve_import(ref)
        except Exception as exc:
            raise NextStepResolutionError(
                "could not import next-step {} {!r}: {}".format(what, ref[7:], exc)
            ) from exc
        if not callable(func):
            raise NextStepResolutionError("next-step {} {!r} is not callable".format(what, ref[7:]))
        return func
    raise NextStepResolutionError("invalid {} reference: {!r}".format(what, ref))


# --------------------------------------------------------------------------- #
# Next-step spec
# --------------------------------------------------------------------------- #


def build_next_step(
    function,  # type: Callable
    registry,  # type: StepRegistry
    handler_type=UpdateHandler,  # type: type
    regex=None,  # type: Optional[str]
    func=None,  # type: Optional[Callable]
    end_conversation_action=end_conversation,  # type: Callable
    end_conversation_keyword_regex=r"(?i)^(end|stop|cancel)$",  # type: str
):
    # type: (...) -> Dict[str, Any]
    """Validate the arguments of ``set_next_step`` and turn them into a storable dict."""
    if not (inspect.isclass(handler_type) and issubclass(handler_type, UpdateHandler)):
        raise TypeError("handler_type must be an UpdateHandler subclass, got {!r}".format(handler_type))
    handler_type_ref = _import_ref(handler_type)
    if handler_type_ref is None:
        raise NextStepNotSerializableError(
            "handler_type {!r} must be importable by name from every worker".format(handler_type)
        )
    if regex is not None and not isinstance(regex, str):
        raise TypeError("regex must be a string or None")
    if end_conversation_keyword_regex is not None and not isinstance(end_conversation_keyword_regex, str):
        raise TypeError("end_conversation_keyword_regex must be a string or None")
    spec = {
        "handler": callable_to_ref(function, registry, "next-step function"),
        "handler_type": handler_type_ref,
        "regex": regex,
        "func": callable_to_ref(func, registry, "filter function") if func is not None else None,
        "end_action": callable_to_ref(end_conversation_action, registry, "end_conversation_action")
        if end_conversation_action is not None
        else None,
        "end_regex": end_conversation_keyword_regex,
    }  # type: Dict[str, Any]
    return spec


def build_next_step_handlers(spec, registry):
    # type: (Dict[str, Any], StepRegistry) -> Tuple[Optional[UpdateHandler], UpdateHandler]
    """Turn a stored spec back into ``(fallback_handler, next_step_handler)``.

    Raises :class:`NextStepResolutionError` if any reference cannot be resolved.
    """
    if not isinstance(spec, dict) or "handler" not in spec:
        raise NextStepResolutionError("invalid next-step record: {!r}".format(spec))
    function = ref_to_callable(spec["handler"], registry, "function")
    handler_type = ref_to_callable(spec.get("handler_type") or "", registry, "handler_type")
    if not (inspect.isclass(handler_type) and issubclass(handler_type, UpdateHandler)):
        raise NextStepResolutionError("next-step handler_type {!r} is not an UpdateHandler".format(handler_type))
    regex = spec.get("regex")
    func = ref_to_callable(spec["func"], registry, "filter function") if spec.get("func") else None

    fallback = None  # type: Optional[UpdateHandler]
    if spec.get("end_action") and spec.get("end_regex"):
        end_action = ref_to_callable(spec["end_action"], registry, "end_conversation_action")
        fallback = MessageHandler(regex=spec["end_regex"], action=end_action)

    if handler_type is MessageHandler:
        next_handler = MessageHandler(regex=regex, func=func, action=function)  # type: UpdateHandler
    elif handler_type is InteractiveQueryHandler:
        next_handler = InteractiveQueryHandler(regex=regex, func=func, action=function)
    else:
        try:
            next_handler = handler_type(regex=regex, func=func, action=function)
        except TypeError:
            next_handler = handler_type()
        # Base UpdateHandler accepts (and ignores) arbitrary kwargs: assign explicitly.
        next_handler.regex = regex
        next_handler.func = func
        next_handler.action = function
    return fallback, next_handler
