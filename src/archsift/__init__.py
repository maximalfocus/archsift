"""ArchSift public package."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Return the installed ArchSift distribution version."""
    try:
        return version("archsift")
    except PackageNotFoundError:
        return "0+unknown"


__all__ = ["package_version"]
