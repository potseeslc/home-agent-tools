#!/usr/bin/env python3
"""Probe the configured read-only trial without displaying credentials or data."""
import argparse
import json
import os
from pathlib import Path
import stat
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def private_token(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Token must be an owned private regular file (0600).")
    token = path.read_text().strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError("Invalid token file.")
    return token


def rpc(base, token, method, params):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        base + "/rpc",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers=headers,
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:4444")
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    url = urllib.parse.urlsplit(base)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Use a gateway origin without credentials, query, or fragment.")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Use HTTPS, or HTTP on a local tunnel.")
    token = private_token(args.token_file)
    params = {"name": "ha-api-status", "arguments": {}}
    status, _ = rpc(base, None, "tools/call", params)
    if status not in {401, 403}:
        raise ValueError("Anonymous call was not denied.")
    status, data = rpc(base, token, "tools/list", {})
    if status != 200 or "error" in data:
        raise ValueError("Tool discovery failed.")
    names = {tool["name"] for tool in data.get("result", {}).get("tools", [])}
    if "ha-api-status" not in names:
        raise ValueError("Availability tool was not exposed.")
    status, data = rpc(base, token, "tools/call", params)
    result = data.get("result", {})
    if status != 200 or "error" in data or result.get("isError") or not result.get("content"):
        raise ValueError("Authenticated availability call failed.")
    content = result["content"]
    if not any(item.get("type") == "text" and json.loads(item.get("text", "{}")) == {"message": "API running."} for item in content):
        raise ValueError("Unexpected upstream availability response.")
    print("PASS: anonymous denial, scoped discovery, live HA availability call.")
    status, data = rpc(base, token, "tools/call", {"name": "ha-api-status", "arguments": {"unexpected": "must reject"}})
    if status == 200 and "error" not in data and not data.get("result", {}).get("isError"):
        raise ValueError("Unexpected arguments were not rejected.")
    print("PASS: anonymous denial, scoped discovery, live HA call, argument rejection.")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        raise SystemExit("FAIL: " + str(error))
    except (OSError, urllib.error.URLError):
        raise SystemExit("FAIL: inspect gateway access, configuration, and private token; no secrets printed.")
