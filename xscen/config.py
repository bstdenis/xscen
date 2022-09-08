"""
Configuration in this module is taken from yaml files.
Functions wrapped by :py:func:`parse_config` have their kwargs automatically patched by
values in the config.

The ``CONFIG`` dictionary contains all values, structured by submodules and functions. For example,
for function ``function`` defined in ``module.py`` of this package, the config would look like:

.. code-block:: json

    {
        "module": {
            "function": {
                "keywords": "arguments"
             }
        }
    }

The :py:func:`load_config` function fills the ``CONFIG`` dict from yaml files.
It always updates the dictionary, so the latest file read has the highest priority.

At calling time, the priority order is always (from highest to lowest priority):

1. Explicitly passed keyword-args
2. Values in the loaded config
3. Function's default values.

Special sections
~~~~~~~~~~~~~~~~
After parsing the files, :py:func:`load_config` will look into the config and perform some
extra actions when finding the following special sections:

- ``logging``:
  The content of this section will be sent directly to :py:func:`logging.config.dictConfig`.
- ``xarray``:
  The content of this section will be sent directly to :py:func:`xarray.set_options`.
- ``xclim``:
  The content of this section will be sent directly to :py:func:`xclim.set_options`.
- ``warnings``:
  The content of this section must be a simple mapping. The keys are understood as python
  warning categories (types) and the values as an action to add to the filter. The key "all"
  applies the filter to any warnings. Only built-in warnings are supported.
"""
import ast
import builtins
import collections.abc
import inspect
import logging.config
import warnings
from copy import deepcopy
from functools import wraps
from pathlib import Path

import xarray as xr
import xclim as xc
import yaml

logger = logging.getLogger(__name__)
EXTERNAL_MODULES = ["logging", "xarray", "xclim", "warnings"]

__all__ = [
    "CONFIG",
    "load_config",
    "parse_config",
]


class ConfigDict(dict):
    """A special dictionary that returns a copy on getitem."""

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, collections.abc.Mapping):
            return ConfigDict(deepcopy(value))
        return value

    def update_from_list(self, pairs):
        for key, valstr in pairs:
            try:
                val = ast.literal_eval(valstr)
            except ValueError:
                val = valstr

            parts = key.split(".")
            d = self
            for part in parts[:-1]:
                d = d.setdefault(part, {})
                if not isinstance(d, collections.abc.Mapping):
                    raise ValueError(
                        f"Key {key} points to an invalid config section ({part} if not a mapping)."
                    )
            d[parts[-1]] = val


CONFIG = ConfigDict()


def recursive_update(d, other):
    """Update a dictionary recursively with another dictionary.
    Values that are Mappings are updated recursively as well.
    """
    for k, v in other.items():
        if isinstance(v, collections.abc.Mapping):
            old_v = d.get(k)
            if isinstance(old_v, collections.abc.Mapping):
                d[k] = recursive_update(old_v, v)
            else:
                d[k] = v
        else:
            d[k] = v
    return d


def load_config(*files, reset=False, verbose=False):
    """Load configuration from given files (in order, the last has priority).

    If a path to a directory is passed, all `.yml` files of this directory are added, in alphabetical order.
    When no files are passed, the default locations are used.
    If reset is True, the current config is erased before loading files.
    """
    if reset:
        CONFIG.clear()

    old_external = [deepcopy(CONFIG.get(module, {})) for module in EXTERNAL_MODULES]

    # Use of map(Path, ...) ensures that "file" is a Path, no matter if a Path or a str was given.
    for file in map(Path, files):
        if file.is_dir():
            # Get all yml files, sort by name
            configfiles = sorted(file.glob("*.yml"), key=lambda p: p.name)
        else:
            configfiles = [file]

        for configfile in configfiles:
            with configfile.open() as f:
                recursive_update(CONFIG, yaml.safe_load(f))
                if verbose:
                    logger.info(f"Updated the config with {configfile}.")

    for module, old in zip(EXTERNAL_MODULES, old_external):
        if old != CONFIG.get(module, {}):
            _setup_external(module, CONFIG.get(module, {}))


def parse_config(func_or_cls):

    module = ".".join(func_or_cls.__module__.split(".")[1:])

    if isinstance(func_or_cls, type):
        func = func_or_cls.__init__
    else:
        func = func_or_cls

    @wraps(func)
    def _wrapper(*args, **kwargs):
        # Get dotted module name, excluding the main package name.

        from_config = CONFIG.get(module, {}).get(func.__name__, {})
        sig = inspect.signature(func)
        if CONFIG.get("print_it_all"):
            logger.debug(f"For func {func}, found config {from_config}.")
            logger.debug("Original kwargs :", kwargs)
        for k, v in from_config.items():
            if k in sig.parameters:
                kwargs.setdefault(k, v)
        if CONFIG.get("print_it_all"):
            logger.debug("Modified kwargs :", kwargs)

        return func(*args, **kwargs)

    if isinstance(func_or_cls, type):
        func_or_cls.__init__ = _wrapper
        return func_or_cls
    return _wrapper


def _setup_external(module, config):
    if module == "logging":
        config.update(version=1)
        logging.config.dictConfig(config)
    elif module == "xclim":
        xc.set_options(**config)
    elif module == "xarray":
        xr.set_options(**config)
    elif module == "warning":
        for category, action in config.items():
            if category == "all":
                warnings.simplefilter(action)
            elif issubclass(getattr(builtins, category), builtins.Warning):
                warnings.simplefilter(action, category=getattr(builtins, category))
