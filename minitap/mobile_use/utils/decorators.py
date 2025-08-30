import asyncio
from functools import wraps
from typing import Any, TypeVar, cast, overload
from collections.abc import Awaitable, Callable

R = TypeVar("R")


def wrap_with_callbacks_sync(
    fn: Callable[..., R],
    *,
    before: Callable[..., None] | None = None,
    on_success: Callable[[R], None] | None = None,
    on_failure: Callable[[Exception], None] | None = None,
    suppress_exceptions: bool = False,
) -> Callable[..., R]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> R:
        if before:
            before()
        try:
            result = fn(*args, **kwargs)
            if on_success:
                on_success(result)
            return result
        except Exception as e:
            if on_failure:
                on_failure(e)
            if suppress_exceptions:
                return None  # type: ignore
            raise

    return wrapper


def wrap_with_callbacks_async(
    fn: Callable[..., Awaitable[R]],
    *,
    before: Callable[..., None] | None = None,
    on_success: Callable[[R], None] | None = None,
    on_failure: Callable[[Exception], None] | None = None,
    suppress_exceptions: bool = False,
) -> Callable[..., Awaitable[R]]:
    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> R:
        if before:
            before()
        try:
            result = await fn(*args, **kwargs)
            if on_success:
                on_success(result)
            return result
        except Exception as e:
            if on_failure:
                on_failure(e)
            if suppress_exceptions:
                return None  # type: ignore
            raise

    return wrapper


@overload
def wrap_with_callbacks(
    fn: Callable[..., Awaitable[R]],
    *,
    before: Callable[[], None] | None = ...,
    on_success: Callable[[R], None] | None = ...,
    on_failure: Callable[[Exception], None] | None = ...,
    suppress_exceptions: bool = ...,
) -> Callable[..., Awaitable[R]]: ...


@overload
def wrap_with_callbacks(
    *,
    before: Callable[..., None] | None = ...,
    on_success: Callable[[Any], None] | None = ...,
    on_failure: Callable[[Exception], None] | None = ...,
    suppress_exceptions: bool = ...,
) -> Callable[[Callable[..., R]], Callable[..., R]]: ...


@overload
def wrap_with_callbacks(
    fn: Callable[..., R],
    *,
    before: Callable[[], None] | None = ...,
    on_success: Callable[[R], None] | None = ...,
    on_failure: Callable[[Exception], None] | None = ...,
    suppress_exceptions: bool = ...,
) -> Callable[..., R]: ...


def wrap_with_callbacks(
    fn: Callable[..., Any] | None = None,
    *,
    before: Callable[[], None] | None = None,
    on_success: Callable[[Any], None] | None = None,
    on_failure: Callable[[Exception], None] | None = None,
    suppress_exceptions: bool = False,
) -> Any:
    def decorator(func: Callable[..., Any]) -> Any:
        if asyncio.iscoroutinefunction(func):
            return wrap_with_callbacks_async(
                cast(Callable[..., Awaitable[Any]], func),
                before=before,
                on_success=on_success,
                on_failure=on_failure,
                suppress_exceptions=suppress_exceptions,
            )
        else:
            return wrap_with_callbacks_sync(
                cast(Callable[..., Any], func),
                before=before,
                on_success=on_success,
                on_failure=on_failure,
                suppress_exceptions=suppress_exceptions,
            )

    if fn is None:
        return decorator
    else:
        return decorator(fn)
