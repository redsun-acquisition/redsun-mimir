from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("redsun-mimir")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
