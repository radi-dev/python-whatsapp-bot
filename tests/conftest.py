"""Shared pytest fixtures.

The library refuses to use the user context unless a storage backend is
configured. Tests opt in to an isolated, in-process ``MemoryStorage`` for
every test so the dispatcher tests keep working without external services.
Tests that specifically verify the "no storage configured" behaviour use the
``no_context_storage`` fixture.
"""

import pytest

from python_whatsapp_bot.context_storage import MemoryStorage
from python_whatsapp_bot.user_context import set_context_storage


@pytest.fixture(autouse=True)
def memory_context_storage():
    """Fresh global MemoryStorage for each test; unset afterwards."""
    storage = MemoryStorage(warn=False)
    set_context_storage(storage)
    yield storage
    set_context_storage(None)


@pytest.fixture
def no_context_storage():
    """Guarantee that no global storage is configured for the test."""
    set_context_storage(None)
    yield
    set_context_storage(None)
