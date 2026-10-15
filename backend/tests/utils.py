"""Shared test utilities and typed async runners."""

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Execute a coroutine synchronously with strict type preservation."""
    return asyncio.run(coro)
