"""Regional upstream exit-node support.

Each region can point at an authenticated SOCKS5 or HTTP CONNECT proxy.
Secrets stay in Railway Variables; nothing sensitive belongs in Git.

This module is deliberately transport-only: the existing VLESS/XHTTP server
can call `open_connection(host, port, region=...)` when a link is assigned an
exit region. If a region has no configured upstream, it falls back to direct
connection only when EXIT_ALLOW_DIRECT_FALLBACK=true.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_TIMEOUT = float(os.getenv("EXIT_CONNECT_TIMEOUT", "10"))
HEALTH_TIMEOUT = float(os.getenv("EXIT_HEALTH_TIMEOUT", "5"))


@dataclass(frozen=True)
class ExitNode:
    region: str
    url: str
    enabled: bool = True


class ExitNodeError(ConnectionError):
    pass


def _nodes_from_env() -> dict[str, list[ExitNode]]:
    nodes: dict[str, list[ExitNode]] = {}
    for region in ("NL", "DE", "GB", "US"):
        raw = os.getenv(f"EXIT_{region}_URL", "").strip()
        if not raw:
            continue
        # Allow comma-separated nodes per country for simple failover.
        items = [x.strip() for x in raw.split(",") if x.strip()]
        nodes[region] = [ExitNode(region=region, url=x) for x in items]
    return nodes


class ExitRegistry:
    def __init__(self) -> None:
        self.nodes = _nodes_from_env()
        self.dead_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def regions(self) -> list[str]:
        return sorted(self.nodes)

    def has_region(self, region: str | None) -> bool:
        return bool(region and region.upper() in self.nodes)

    async def mark_failed(self, node: ExitNode, backoff: float = 15.0) -> None:
        async with self._lock:
            self.dead_until[node.url] = time.monotonic() + backoff

    async def mark_healthy(self, node: ExitNode) -> None:
        async with self._lock:
            self.dead_until.pop(node.url, None)

    async def candidates(self, region: str) -> list[ExitNode]:
        region = region.upper().strip()
        now = time.monotonic()
        async with self._lock:
            candidates = [
                n for n in self.nodes.get(region, [])
                if n.enabled and self.dead_until.get(n.url, 0) <= now
            ]
        return candidates


REGISTRY = ExitRegistry()


def _parse_proxy(url: str):
    p = urlparse(url)
    scheme = p.scheme.lower()
    if scheme not in {"socks5", "socks5h", "http", "https"}:
        raise ValueError(f"Unsupported exit proxy scheme: {scheme}")
    if not p.hostname or not p.port:
        raise ValueError("Exit proxy URL must contain host and port")
    return scheme, p.hostname, p.port, p.username, p.password


async def _open_direct(host: str, port: int):
    return await asyncio.wait_for(asyncio.open_connection(host, port), DEFAULT_TIMEOUT)


async def _open_http_connect(proxy_url: str, host: str, port: int):
    _, proxy_host, proxy_port, username, password = _parse_proxy(proxy_url)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(proxy_host, proxy_port), DEFAULT_TIMEOUT
    )
    target = f"{host}:{port}"
    lines = [f"CONNECT {target} HTTP/1.1", f"Host: {target}"]
    if username is not None:
        token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {token}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await asyncio.wait_for(writer.drain(), DEFAULT_TIMEOUT)
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), DEFAULT_TIMEOUT)
    status = head.split(b"\r\n", 1)[0]
    if b" 200 " not in status:
        writer.close()
        await writer.wait_closed()
        raise ExitNodeError(f"HTTP CONNECT failed: {status.decode(errors='replace')}")
    return reader, writer


async def _socks5_auth(writer, reader, username, password):
    if username is None:
        writer.write(b"\x05\x01\x00")
    else:
        writer.write(b"\x05\x01\x02")
    await writer.drain()
    method = await reader.readexactly(2)
    if method[0] != 5 or method[1] == 0xFF:
        raise ExitNodeError("SOCKS5 authentication rejected")
    if method[1] == 2:
        u = (username or "").encode()
        p = (password or "").encode()
        writer.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await writer.drain()
        if (await reader.readexactly(2))[1] != 0:
            raise ExitNodeError("SOCKS5 username/password rejected")


async def _open_socks5(proxy_url: str, host: str, port: int):
    _, proxy_host, proxy_port, username, password = _parse_proxy(proxy_url)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(proxy_host, proxy_port), DEFAULT_TIMEOUT
    )
    try:
        await _socks5_auth(writer, reader, username, password)
        # SOCKS5 domain-name addressing keeps DNS resolution at the exit node.
        target = host.encode()
        if len(target) > 255:
            raise ExitNodeError("Target hostname too long")
        writer.write(b"\x05\x01\x00\x03" + bytes([len(target)]) + target + port.to_bytes(2, "big"))
        await writer.drain()
        reply = await reader.readexactly(4)
        if reply[0] != 5 or reply[1] != 0:
            raise ExitNodeError(f"SOCKS5 CONNECT failed: code={reply[1]}")
        atyp = reply[3]
        if atyp == 1:
            await reader.readexactly(4)
        elif atyp == 3:
            n = (await reader.readexactly(1))[0]
            await reader.readexactly(n)
        elif atyp == 4:
            await reader.readexactly(16)
        else:
            raise ExitNodeError("SOCKS5 returned invalid address type")
        await reader.readexactly(2)
        return reader, writer
    except Exception:
        writer.close()
        await writer.wait_closed()
        raise


async def _open_via_node(node: ExitNode, host: str, port: int):
    scheme, *_ = _parse_proxy(node.url)
    if scheme in {"socks5", "socks5h"}:
        return await _open_socks5(node.url, host, port)
    return await _open_http_connect(node.url, host, port)


async def open_connection(host: str, port: int, region: str | None = None):
    """Open a destination TCP connection, optionally through a country exit.

    Multiple configured nodes are tried in order. Failed nodes are temporarily
    quarantined so a dead upstream does not cause every new connection to wait
    on the same timeout.
    """
    region = (region or os.getenv("EXIT_DEFAULT_REGION", "")).strip().upper()
    if not region or not REGISTRY.has_region(region):
        if os.getenv("EXIT_ALLOW_DIRECT_FALLBACK", "true").lower() == "true":
            return await _open_direct(host, port)
        raise ExitNodeError(f"No exit node configured for region {region or 'NONE'}")

    last_error: Exception | None = None
    for node in await REGISTRY.candidates(region):
        try:
            result = await _open_via_node(node, host, port)
            await REGISTRY.mark_healthy(node)
            return result
        except Exception as exc:
            last_error = exc
            await REGISTRY.mark_failed(node)

    raise ExitNodeError(f"All exit nodes failed for region {region}: {last_error}")


async def health_check(region: str) -> dict:
    """Check TCP reachability through each configured proxy without credentials exposure."""
    result = {"region": region.upper(), "healthy": [], "failed": []}
    for node in await REGISTRY.candidates(region):
        try:
            reader, writer = await asyncio.wait_for(
                _open_via_node(node, "example.com", 443), HEALTH_TIMEOUT
            )
            writer.close()
            await writer.wait_closed()
            await REGISTRY.mark_healthy(node)
            result["healthy"].append(node.url.split("@")[-1])
        except Exception as exc:
            await REGISTRY.mark_failed(node)
            result["failed"].append({"endpoint": node.url.split("@")[-1], "error": str(exc)})
    return result
