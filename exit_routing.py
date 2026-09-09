"""Runtime bridge that routes X4G outbound TCP connections via regional exits.

The existing relay files call asyncio.open_connection() directly. This module
keeps those files unchanged and wraps only calls originating from relay_vless.py
or xhttp_siz10.py. The region is read from the authenticated link's LINKS entry
using the VLESS UUID found in the caller stack.

For backward compatibility, a link may select its country either with a future
`region`/`exit_region` field or simply by putting a country code in its label,
for example `NL - Premium`, `DE - 100GB`, `GB`, or `US Home`. If no region is
selected, the existing direct connection behavior is preserved.
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


def _caller_uuid() -> str | None:
    """Find the active X4G UUID without changing the existing relay signatures."""
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
        return None
    try:
        # main.LINKS is populated after startup; importing here avoids a startup
        # cycle because this bridge is loaded before main imports relay modules.
        import main
        link = main.LINKS.get(uuid) or {}
        region = link.get("region") or link.get("exit_region")
        if region:
            region = str(region).strip().upper()
            if region in {"NL", "DE", "GB", "US"}:
                return region
        label = str(link.get("label") or "")
        match = _REGION_RE.search(label.upper())
        if match:
            return match.group(1).upper()
    except Exception:
        pass
    return None


async def _patched_open_connection(host, port, *args, **kwargs):
    # Never intercept the bridge implementation itself, otherwise proxy setup
    # would recurse through this wrapper.
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
