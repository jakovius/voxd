# voxd.utils.libw
# -----------------------------------------------------------------------------
# Misc utility helpers that are safe to import from anywhere in the project.
#
# IMPORTANT: Do **not** put heavy top-level imports here (especially ones that
# in turn import `voxd.paths`, `voxd.core.config`, …) as that easily leads to
# circular-import hell.  Keep everything lightweight and import lazily inside
# the individual helpers instead.
# -----------------------------------------------------------------------------

from __future__ import annotations

from functools import lru_cache
import os, re, sys


# ANSI colors
ORANGE = "\033[38;5;208m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

def _color_enabled():
    try:
        return sys.stdout.isatty() and os.getenv("NO_COLOR") is None
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _app_cfg():
    """Return a cached instance of :class:`voxd.core.config.AppConfig`."""
    # Import **inside** the function to avoid circular imports during the Python
    # module import phase.  The first call constructs the config object; later
    # calls re-use that same instance.
    from voxd.core.config import AppConfig  # local import – deliberate

    return AppConfig()


# -----------------------------------------------------------------------------
# Rotating file log (mirror of verbose console output)
# -----------------------------------------------------------------------------

# Strip ANSI color codes before writing to the log file.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@lru_cache(maxsize=1)
def _file_logger():
    """Return a cached :class:`logging.Logger` writing to the rotating voxd log.

    The log file lives at ``<XDG_DATA>/voxd/logs/voxd.log`` and rotates at ~1 MB,
    keeping 3 backups. Returns *None* if the handler can't be created (logging then
    degrades to console-only). Imports are local to avoid circular-import issues.
    """
    try:
        import logging
        from logging.handlers import RotatingFileHandler
        from voxd.paths import LOG_DIR  # local import – avoids circular import

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("voxd")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        # Attach our handler only once even if this module is imported repeatedly.
        if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            handler = RotatingFileHandler(
                LOG_DIR / "voxd.log",
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                   datefmt="%Y-%m-%d %H:%M:%S")
            )
            logger.addHandler(handler)
        return logger
    except Exception:
        return None


def _file_log(msg: str, *, is_error: bool = False) -> None:
    """Append *msg* to the rotating log file.

    Errors (``is_error=True``) are always persisted, independent of ``verbosity`` –
    so failures are captured durably even when the console is quiet. Verbose
    ``INFO`` lines reach here only from :func:`verbo`, which already gates itself on
    ``verbosity``. The log directory is created lazily on the first write, so an
    error-free run with verbosity off leaves no log footprint.
    """
    logger = _file_logger()
    if logger is None:
        return
    try:
        import logging
        logger.log(logging.ERROR if is_error else logging.INFO,
                   _ANSI_RE.sub("", msg))
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Public helpers
# -----------------------------------------------------------------------------

# a function that will take a string argument and print it out if the verbosity
# flag in the user config is **true**.  It can be imported and used anywhere in
# the codebase **without** causing circular-import problems.


def verbo(what_string: str, *args, **kwargs):
    """Record a verbose detail line to the rotating log file (never to the console).

    Emitted only when ``verbosity`` is enabled, and only to the log file – the
    console is reserved for errors (see :func:`verr`). The string is formatted with
    ``str.format(*args, **kwargs)``.
    """

    cfg = _app_cfg()
    if getattr(cfg, "verbosity", False):
        _file_log(what_string.format(*args, **kwargs))

def verr(what_string: str, *args, **kwargs):
    """Print an error to the console and persist it to the rotating log file.

    Errors are shown regardless of ``verbosity`` (colored red when TTY) and are
    *always* written to the log file too — even when verbose logging is off — so
    failures are never lost. Verbosity only governs the extra ``verbo`` chatter.
    """
    msg = what_string.format(*args, **kwargs)
    _file_log(msg, is_error=True)
    print(f"{RED}{msg}{RESET}" if _color_enabled() else msg)

def diagn(value, *, label: str | None = None):
    """
    Diagnostic print that tries hard to show:
        file:line | variable = repr(value)
    If automatic name detection fails you can supply an explicit *label*.
    """
    import inspect, pathlib, textwrap, re

    frame = inspect.currentframe()
    outer = inspect.getouterframes(frame, 2)[1]          # caller
    filename = pathlib.Path(outer.filename).name
    lineno   = outer.lineno

    # Try to extract the expression passed to diagn()
    if label is None:
        if outer.code_context:
            src_line = outer.code_context[-1]  # last line corresponds to *this* call
        else:
            src_line = ""
        src = textwrap.dedent(src_line).strip()
        m = re.search(r"diagn\(\s*(.+?)(?:,\s*\*\w+=|,\s*label=|[\s\)])", src)
        label = m.group(1).strip() if m else "?"
    print(f"---> {filename}:{lineno} | {label} = {value!r}")


def main():
    # testing example
    cfg = _app_cfg()
    verb_flag = getattr(cfg, "verbosity", False)
    print(verb_flag)
    verbo(f"Verbosity is {verb_flag}ly on.".lower())

if __name__ == "__main__":
    main()