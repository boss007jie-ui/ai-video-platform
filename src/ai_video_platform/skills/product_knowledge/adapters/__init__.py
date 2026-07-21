"""Product Library adapters."""

from .memory import InMemoryProductLibrary
from .filesystem import FilesystemProductLibrary

__all__ = ["FilesystemProductLibrary", "InMemoryProductLibrary"]
