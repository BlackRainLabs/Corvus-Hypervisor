"""Server-side Memory Service."""

__all__ = ["MemoryService"]


def __getattr__(name: str):
    if name == "MemoryService":
        from corvus.memory.service import MemoryService

        return MemoryService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
