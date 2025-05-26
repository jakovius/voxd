# this is a library of useful functions that canbe used in the project

from whisp.core.config import AppConfig

_cfg = AppConfig()  # Create once, reuse

# a function that will take a string argument and print it out if the verbosity is true in config.yaml
# it can be called in any script in the codebase
def verbo(what_string: str, *args, **kwargs):
    """Prints what_string if verbosity is enabled in config."""
    if getattr(_cfg, "verbosity", False):
        print(what_string.format(*args, **kwargs))

def main():
    # testing example
    print(_cfg.verbosity)
    verbo(f"Verbosity is {_cfg.verbosity}ly on.".lower())

if __name__ == "__main__":
    main()
    