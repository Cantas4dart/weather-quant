from __future__ import annotations

import logging
import time
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def setup_logging(log_path: str, level: str = "INFO") -> None:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console)


def retry(times: int = 3, delay: float = 1.0, backoff: float = 2.0) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_error: Exception | None = None
            for _ in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # pragma: no cover - logged at call sites.
                    last_error = exc
                    time.sleep(current_delay)
                    current_delay *= backoff
            if last_error is not None:
                raise last_error
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator

