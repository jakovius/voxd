# voxt.utils.libw
# -----------------------------------------------------------------------------
# Misc utility helpers that are safe to import from anywhere in the project.
#
# IMPORTANT: Do **not** put heavy top-level imports here (especially ones that
# in turn import `voxt.paths`, `voxt.core.config`, …) as that easily leads to
# circular-import hell.  Keep everything lightweight and import lazily inside
# the individual helpers instead.
# -----------------------------------------------------------------------------

from __future__ import annotations

from functools import lru_cache
import os, sys


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
    """Return a cached instance of :class:`voxt.core.config.AppConfig`."""
    # Import **inside** the function to avoid circular imports during the Python
    # module import phase.  The first call constructs the config object; later
    # calls re-use that same instance.
    from voxt.core.config import AppConfig  # local import – deliberate

    return AppConfig()


# -----------------------------------------------------------------------------
# Public helpers
# -----------------------------------------------------------------------------

# a function that will take a string argument and print it out if the verbosity
# flag in the user config is **true**.  It can be imported and used anywhere in
# the codebase **without** causing circular-import problems.


def verbo(what_string: str, *args, **kwargs):
    """Conditionally ``print`` *what_string* depending on the user's settings.

    The string is formatted with ``str.format(*args, **kwargs)`` exactly like
    ``print`` would do.
    """

    cfg = _app_cfg()
    if getattr(cfg, "verbosity", False):
        msg = what_string.format(*args, **kwargs)
        if _color_enabled():
            if msg.startswith("[recorder]"):
                msg = f"{ORANGE}{msg}{RESET}"
            elif msg.startswith("[logger]") or msg.startswith("[aipp]"):
                msg = f"{GREEN}{msg}{RESET}"
        print(msg)

def verr(what_string: str, *args, **kwargs):
    """Unconditional error print, colored red when TTY.

    Intended for critical errors regardless of verbosity.
    """
    msg = what_string.format(*args, **kwargs)
    if _color_enabled():
        msg = f"{RED}{msg}{RESET}"
    print(msg)

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