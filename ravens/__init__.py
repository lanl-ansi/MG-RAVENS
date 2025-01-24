from contextlib import suppress
import importlib.metadata
from pathlib import Path


def extract_version() -> str:
    with suppress(FileNotFoundError, StopIteration):
        with open((root_dir := Path(__file__).parent.parent) / "pyproject.toml", encoding="utf-8") as pyproject_toml:
            version = next(line for line in pyproject_toml if line.startswith("version")).split("=")[1].strip("'\"\n ")
            return f"{version}-dev"
    return importlib.metadata.version(__package__ or __name__.split(".", maxsplit=1)[0])


__version__ = extract_version()
