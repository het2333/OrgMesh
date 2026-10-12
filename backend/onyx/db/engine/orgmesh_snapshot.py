# SPDX-License-Identifier: MIT
"""Snapshot-only source connections. Do not change the shared application pool."""

import os
import time
from collections.abc import Callable, Sequence
from inspect import unwrap
from types import CodeType, FunctionType
from typing import Any, Protocol, cast

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from sqlalchemy.util.langhelpers import only_once

CONNECT_TIMEOUT_SECONDS = 2


class _EventNames(Protocol):
    _event_names: Sequence[str]


def _nested_code(function: Callable[..., object], name: str) -> CodeType:
    for item in cast(FunctionType, unwrap(function)).__code__.co_consts:
        if isinstance(item, CodeType) and item.co_name == name:
            return item
    raise ValueError("unsupported SQLAlchemy connection initialization")


_ON_CONNECT_CODE = _nested_code(create_engine, "on_connect")
_FIRST_CONNECT_CODE = _nested_code(create_engine, "first_connect")
_ONCE_CODE = _nested_code(only_once, "go")


def _builtin_connect_hook(hook: object) -> bool:
    if not isinstance(hook, FunctionType):
        return False
    if hook.__code__ is _ON_CONNECT_CODE:
        return True
    if hook.__code__ is _ONCE_CODE and hook.__closure__ is not None:
        for name, cell in zip(hook.__code__.co_freevars, hook.__closure__, strict=True):
            if name == "fn":
                original = cell.cell_contents
                return (
                    isinstance(original, FunctionType)
                    and original.__code__ is _FIRST_CONNECT_CODE
                )
    return False


def _reject_unsupported_hooks(engine: Engine) -> None:
    # The pinned default engine needs only its two built-in pool connect callbacks.
    for dispatch in (engine.dispatch, engine.pool.dispatch, engine.dialect.dispatch):
        for name in cast(_EventNames, dispatch)._event_names:
            listeners = getattr(
                dispatch, name
            )  # ods: ignore[getattr] SQLAlchemy event names vary by dispatcher.
            hooks = tuple(listeners)
            if dispatch is engine.pool.dispatch and name == "connect":
                unsupported = any(not _builtin_connect_hook(hook) for hook in hooks)
            else:
                unsupported = bool(hooks)
            if unsupported:
                raise ValueError("unsupported bounded usage source connection hooks")


def remaining_seconds(deadline: float, *, reserve: float = 0) -> float:
    remaining = deadline - time.monotonic() - reserve
    if remaining <= 0:
        raise TimeoutError("usage snapshot deadline expired")
    return remaining


def bounded_snapshot_engine(engine: Engine, *, deadline: float) -> Engine:
    from onyx.db.engine.sql_engine import SqlEngine

    budget = remaining_seconds(deadline, reserve=CONNECT_TIMEOUT_SECONDS)
    profile = SqlEngine.get_engine_profile()
    kwargs: dict[str, Any] = dict(profile.engine_kwargs)
    args = dict(kwargs.get("connect_args", {}))
    if (
        engine.url.drivername != "postgresql+psycopg2"
        or profile.use_iam
        or any(key in kwargs for key in ("creator", "module", "pool", "plugins"))
        or any(
            key in args or key in engine.url.query
            for key in (
                "service",
                "plugin",
                "plugins",
                "module",
                "creator",
                "pool",
                "dsn",
                "connection_factory",
                "cursor_factory",
                "async_",
                "async",
            )
        )
        or bool(os.environ.get("PGSERVICE"))
    ):
        raise ValueError("unsupported bounded usage source connection")
    _reject_unsupported_hooks(engine)
    hosts = [engine.url.host or ""]
    for key in ("host", "hostaddr", "port"):
        hosts.extend(str(value) for value in engine.url.normalized_query.get(key, ()))
        if key in args:
            hosts.append(str(args[key]))
        elif key not in engine.url.query and not (key == "host" and engine.url.host):
            hosts.append(os.environ.get("PG" + key.upper(), ""))
    if any("," in host for host in hosts) or any(
        len(engine.url.normalized_query.get(key, ())) > 1
        for key in ("host", "hostaddr", "port")
    ):
        raise ValueError("multi-host usage source connections are unsupported")
    for key in (
        "pool_size",
        "max_overflow",
        "pool_timeout",
        "pool_recycle",
        "pool_use_lifo",
    ):
        kwargs.pop(key, None)
    milliseconds = max(1, int(budget * 1000))
    args["connect_timeout"] = CONNECT_TIMEOUT_SECONDS
    options = str(args.get("options", engine.url.query.get("options", "")))
    args["options"] = (
        f"{options} -c statement_timeout={milliseconds}"
        f" -c lock_timeout={min(milliseconds, 2000)}"
        f" -c idle_in_transaction_session_timeout={milliseconds}"
    ).strip()
    kwargs.update(poolclass=NullPool, pool_pre_ping=False, connect_args=args)
    return create_engine(engine.url, **kwargs)
