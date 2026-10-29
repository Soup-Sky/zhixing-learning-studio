"""Local error log: redacted, size-limited, on this machine only. Never records learner content."""
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .provider import redact

LOGGER = 'zhixing'
log = logging.getLogger(LOGGER)


class Redacting(logging.Filter):
    def filter(self, record):
        # Format first, so arguments and tracebacks are redacted together with the message.
        message = record.getMessage()
        if record.exc_info:
            message += '\n' + logging.Formatter().formatException(record.exc_info)
            record.exc_info = None; record.exc_text = None
        record.msg = redact(message); record.args = None
        return True


def setup(directory: Path, max_bytes: int = 512 * 1024, backups: int = 3) -> Path:
    """Attach one rotating file handler; repeated calls (tests, self-test) reuse it."""
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'errors.log'
    for handler in log.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == path.resolve():
            return path
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding='utf-8', delay=True)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    handler.addFilter(Redacting())
    log.addHandler(handler); log.setLevel(logging.INFO); log.propagate = False
    # Uvicorn reports unhandled request errors here; route them to the same redacted file.
    for name in ('uvicorn.error',):
        other = logging.getLogger(name)
        if handler not in other.handlers: other.addHandler(handler)
    return path


def current_file() -> Path | None:
    for handler in log.handlers:
        if isinstance(handler, RotatingFileHandler): return Path(handler.baseFilename)
    return None
