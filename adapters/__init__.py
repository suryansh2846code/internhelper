"""Adapter registry. Add a new platform by registering its adapter here."""
from adapters.base import PlatformAdapter
from adapters.internshala import InternshalaAdapter
from adapters.unstop import UnstopAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {
    InternshalaAdapter.name: InternshalaAdapter(),
    UnstopAdapter.name: UnstopAdapter(),
}

DEFAULT_PLATFORM = InternshalaAdapter.name


def get_adapter(name: str | None = None) -> PlatformAdapter:
    """Return the adapter for `name`, falling back to the default platform."""
    return _ADAPTERS.get(name or DEFAULT_PLATFORM, _ADAPTERS[DEFAULT_PLATFORM])


def list_platforms() -> list[dict]:
    """[{name, label, supports_auto_apply, login_url}] of every platform."""
    return [
        {"name": a.name, "label": a.label,
         "supports_auto_apply": a.supports_auto_apply, "login_url": a.login_url}
        for a in _ADAPTERS.values()
    ]
