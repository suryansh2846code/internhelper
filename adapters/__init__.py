"""Adapter registry. Add a new platform by registering its adapter here."""
from adapters.base import PlatformAdapter
from adapters.internshala import InternshalaAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {
    InternshalaAdapter.name: InternshalaAdapter(),
}

DEFAULT_PLATFORM = InternshalaAdapter.name


def get_adapter(name: str | None = None) -> PlatformAdapter:
    """Return the adapter for `name`, falling back to the default platform."""
    return _ADAPTERS.get(name or DEFAULT_PLATFORM, _ADAPTERS[DEFAULT_PLATFORM])


def list_platforms() -> list[dict]:
    """[{name, label}] of every registered platform, for the UI."""
    return [{"name": a.name, "label": a.label} for a in _ADAPTERS.values()]
