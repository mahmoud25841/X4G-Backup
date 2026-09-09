"""Runtime bridge for Railway regional egress.

The existing relay modules call asyncio.open_connection() directly. This
bridge intercepts only calls originating from relay_vless.py/xhttp_siz10.py.
A link may select NL/DE/GB/US through `region`/`exit_region`, or by putting the
country code in its label. If neither is present, EXIT_DEFAULT_REGION is used.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
from pathlib import Path
import importlib.util

_BASE = Path(__file__).resolve().parent
_IMPL_PATH = _BASE / "v2ray-railway" / "exit_nodes.py"
_SPEC = importlib.util.spec_from_file_location("x4g_exit_nodes", _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load exit node implementation: {_IMPL_PATH}")
_IMPL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPL)

_ORIGINAL_OPEN_CONNECTION = asyncio.open_connection
_INSTALLED = False
_REGION_RE = re.compile(r"(?<![A-Z])(NL|DE|GB|US)(?![A-Z])", re.IGNORECASE)
_ALLOWED = {"NL", "DE", "GB", "US"}


def _caller_uuid() -> str | None:
    for frame_info in inspect.stack(context=0):
        filename = os.path.basename(frame_info.filename)
        if filename not in {"relay_vless.py", "xhttp_siz10.py"}:
            continue
        value = frame_info.frame.f_locals.get("uuid")
        if isinstance(value, str) and value:
            return value
    return None


def _region_for_uuid(uuid: str | None) -> str | None:
    if not uuid:
        region = os.environ.get("EXIT_DEFAULT_REGION", "NL")
        return region.strip().upper() if region.strip().upper() in _ALLOWED else "NL"
    try:
        import main
        link = main.LINKS.get(uuid) or {}
        region = link.get("region") or link.get("exit_region")
        if region:
            region = str(region).strip().upper()
            if region in _ALLOWED:
                return region
        label = str(link.get("label") or "")
        match = _REGION_RE.search(label.upper())
        if match:
            return match.group(1).upper()
    except Exception:
        pass
    default_region = os.environ.get("EXIT_DEFAULT_REGION", "NL").strip().upper()
    return default_region if default_region in _ALLOWED else "NL"


async def _patched_open_connection(host, port, *args, **kwargs):
    for frame_info in inspect.stack(context=0):
        if os.path.basename(frame_info.filename) == "exit_nodes.py":
            return await _ORIGINAL_OPEN_CONNECTION(host, port, *args, **kwargs)

    uuid = _caller_uuid()
    region = _region_for_uuid(uuid)
    if region:
        return await _IMPL.open_connection(host, port, region=region)
    return await _ORIGINAL_OPEN_CONNECTION(host, port, *args, **kwargs)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    asyncio.open_connection = _patched_open_connection
    _INSTALLED = True


install()
