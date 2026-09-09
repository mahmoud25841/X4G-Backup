"""Generate VLESS URLs suitable for importing into v2rayNG.

Example:
    python v2ray-railway/vless_link.py --uuid UUID --host example.up.railway.app \
      --path /xhttp-siz10/UUID --region NL

The transport/security values must match the deployed server. This tool does
not claim REALITY/TLS settings unless they are explicitly supplied.
"""

from __future__ import annotations

import argparse
import urllib.parse


def make_vless(
    uuid: str,
    host: str,
    port: int = 443,
    path: str = "/",
    region: str = "",
    security: str = "tls",
    sni: str = "",
    fp: str = "chrome",
    alpn: str = "h2,http/1.1",
    name: str = "Kouch VPN",
) -> str:
    params = {
        "type": "xhttp",
        "security": security,
        "path": path,
    }
    if sni:
        params["sni"] = sni
    if fp:
        params["fp"] = fp
    if alpn:
        params["alpn"] = alpn
    if region:
        params["region"] = region.upper()
    query = urllib.parse.urlencode(params, safe="/," )
    return f"vless://{uuid}@{host}:{port}?{query}#{urllib.parse.quote(name)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uuid", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--path", default="/")
    parser.add_argument("--region", default="")
    parser.add_argument("--security", default="tls", choices=["tls", "none", "reality"])
    parser.add_argument("--sni", default="")
    parser.add_argument("--fp", default="chrome")
    parser.add_argument("--alpn", default="h2,http/1.1")
    parser.add_argument("--name", default="Kouch VPN")
    args = parser.parse_args()
    print(make_vless(**vars(args)))


if __name__ == "__main__":
    main()
