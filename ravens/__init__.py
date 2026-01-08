from contextlib import suppress
import importlib.metadata
from pathlib import Path


def extract_version() -> str:
    # Try to get installed package version first
    try:
        return importlib.metadata.version("mg-ravens")
    except importlib.metadata.PackageNotFoundError:
        pass

    # Fall back to reading from pyproject.toml for development
    with suppress(FileNotFoundError, StopIteration):
        with open((root_dir := Path(__file__).parent.parent) / "pyproject.toml", encoding="utf-8") as pyproject_toml:
            version = next(line for line in pyproject_toml if line.startswith("version")).split("=")[1].strip("'\"\n ")
            return f"{version}-dev"

    # Last resort fallback
    return "0.0.0-dev"


__version__ = extract_version()

from .base import RavensData
