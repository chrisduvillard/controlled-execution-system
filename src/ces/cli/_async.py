"""Async wrapper for Typer commands.

Typer commands are synchronous, but CES services are async.
This module provides a decorator that bridges the gap by calling
asyncio.run() inside a synchronous wrapper.

Exports:
    run_async: Decorator that wraps an async function for Typer.
"""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any, Callable, Coroutine, TypeVar

T = TypeVar("T")


def run_async(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
    """Wrap an async function so it can be used as a Typer command.

    Uses asyncio.run() to execute the coroutine synchronously.
    Preserves the original function's name, docstring, and type hints
    so Typer can introspect parameters for --help generation.

    Args:
        func: An async function to wrap.

    Returns:
        A synchronous wrapper that calls asyncio.run(func(...)).

    Example::

        @run_async
        async def my_command(name: str) -> None:
            await some_async_operation(name)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return asyncio.run(func(*args, **kwargs))

    return wrapper
