from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

DEFAULT_PORT = 8765
DISCOVERY_PORT = 8766
BEACON_PREFIX = "SLIMPORT1|"


def probe_headset(host: str, port: int = DEFAULT_PORT, timeout: float = 2.5) -> dict:
    host = (host or "").strip()
    if not host or host.lower() == "adb":
        return {"ok": False, "message": "No headset IP yet — use Find headset on the same Wi‑Fi."}
    url = f"http://{host}:{int(port or DEFAULT_PORT)}/health"
    try:
        response = httpx.get(url, timeout=timeout)
        if response.status_code >= 400:
            return {"ok": False, "message": f"Headset returned HTTP {response.status_code}"}
        payload = _parse_health(response.text)
        return {
            "ok": True,
            "message": f"Reachable at {url}",
            "url": url,
            "host": host,
            "port": int(payload.get("port") or port or DEFAULT_PORT),
            "token": payload.get("token") or "",
            "body": response.text[:200],
        }
    except Exception as exc:
        return {"ok": False, "message": f"Cannot reach headset: {exc}"}


def discover_headset(timeout: float = 4.0, port: int = DEFAULT_PORT) -> dict:
    """Find SpatialLauncher via USB/adb IP hint, UDP beacon, then subnet health scan."""
    adb_hint = _adb_wlan_ip()
    if adb_hint:
        check = probe_headset(adb_hint, port, timeout=1.2)
        if check.get("ok"):
            return {
                "ok": True,
                "message": f"Found headset via USB/adb at {adb_hint}:{check.get('port') or port}",
                "host": adb_hint,
                "port": int(check.get("port") or port),
                "token": check.get("token") or "",
                "url": check.get("url") or f"http://{adb_hint}:{port}/health",
            }

    found = _listen_beacon(timeout=min(timeout, 3.0))
    if found:
        return {
            "ok": True,
            "message": f"Found headset at {found['host']}:{found['port']}",
            **found,
        }

    hosts = _candidate_hosts()
    if adb_hint and adb_hint not in hosts:
        hosts.insert(0, adb_hint)
    if not hosts:
        return {
            "ok": False,
            "message": "No local network found. Connect PC and Quest to the same Wi‑Fi, open SpatialLauncher, then try again.",
        }

    hits: list[dict] = []
    with ThreadPoolExecutor(max_workers=48) as pool:
        futures = {pool.submit(probe_headset, host, port, 0.7): host for host in hosts}
        for fut in as_completed(futures):
            result = fut.result()
            if result.get("ok"):
                hits.append(result)

    if not hits:
        hint = f" Quest Wi‑Fi IP looks like {adb_hint}." if adb_hint else ""
        return {
            "ok": False,
            "message": (
                "No SpatialLauncher import server found."
                + hint
                + " Install the latest SpatialLauncher build, keep it open on the Quest, stay on the same Wi‑Fi, then Find headset again."
            ),
        }

    best = hits[0]
    return {
        "ok": True,
        "message": f"Found headset at {best.get('host')}:{best.get('port')}",
        "host": best.get("host") or "",
        "port": int(best.get("port") or port),
        "token": best.get("token") or "",
        "url": best.get("url") or "",
    }


def send_epub_file(
    path: str | Path,
    host: str,
    port: int = DEFAULT_PORT,
    token: str = "",
    timeout: float = 120.0,
) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return {"ok": False, "message": f"EPUB not found: {file_path}"}
    if file_path.suffix.lower() != ".epub":
        return {"ok": False, "message": "Only .epub files can be sent right now."}

    host = (host or "").strip()
    if host.lower() == "adb":
        return _adb_push(file_path)

    if not host:
        discovered = discover_headset(timeout=3.5, port=port)
        if not discovered.get("ok"):
            return discovered
        host = discovered.get("host") or ""
        port = int(discovered.get("port") or port or DEFAULT_PORT)
        token = token or (discovered.get("token") or "")

    url = f"http://{host}:{int(port or DEFAULT_PORT)}/import"
    headers = {
        "Content-Type": "application/epub+zip",
        "X-Filename": file_path.name,
    }
    if (token or "").strip():
        headers["X-Import-Token"] = token.strip()
    try:
        data = file_path.read_bytes()
        response = httpx.post(url, content=data, headers=headers, timeout=timeout)
        if response.status_code == 401:
            return {"ok": False, "message": "Unauthorized — token mismatch. Tap Find headset again."}
        if response.status_code >= 400:
            return {
                "ok": False,
                "message": f"Headset rejected upload (HTTP {response.status_code}): {response.text[:200]}",
            }
        return {
            "ok": True,
            "message": f"Sent {file_path.name} to {host}",
            "url": url,
            "host": host,
            "port": int(port or DEFAULT_PORT),
            "token": token or "",
        }
    except Exception as exc:
        return {"ok": False, "message": f"Send failed: {exc}"}


def _parse_health(text: str) -> dict:
    try:
        data = json.loads(text or "{}")
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _listen_beacon(timeout: float = 3.0) -> dict | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.settimeout(0.4)
        deadline = time.time() + max(0.5, timeout)
        while time.time() < deadline:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            text = data.decode("utf-8", errors="ignore").strip()
            if not text.startswith(BEACON_PREFIX):
                continue
            parts = text.split("|")
            if len(parts) < 4:
                continue
            host = parts[1].strip()
            try:
                port = int(parts[2])
            except ValueError:
                port = DEFAULT_PORT
            token = parts[3].strip()
            if not host or host.startswith("0."):
                continue
            # Confirm health before accepting.
            check = probe_headset(host, port, timeout=1.0)
            if check.get("ok"):
                return {
                    "host": host,
                    "port": port,
                    "token": token or check.get("token") or "",
                    "url": check.get("url") or f"http://{host}:{port}/health",
                }
            return {"host": host, "port": port, "token": token, "url": f"http://{host}:{port}/health"}
    except OSError:
        return None
    finally:
        sock.close()
    return None


def _adb_wlan_ip() -> str:
    adb = _adb_path()
    if not adb:
        return ""
    try:
        result = subprocess.run(
            [adb, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return ""
    match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", result.stdout or "")
    return match.group(1) if match else ""


def _adb_path() -> str:
    which = shutil.which("adb")
    if which:
        return which
    candidate = Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"
    return str(candidate) if candidate.exists() else ""


def _candidate_hosts() -> list[str]:
    local_ip = _local_ipv4()
    if not local_ip:
        return []
    parts = local_ip.split(".")
    if len(parts) != 4:
        return []
    prefixes = [".".join(parts[:3])]
    try:
        third = int(parts[2])
        for delta in (-1, 1, -2, 2, -3, 3):
            n = third + delta
            if 0 <= n <= 255:
                prefixes.append(f"{parts[0]}.{parts[1]}.{n}")
    except ValueError:
        pass
    me = parts[3]
    hosts: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        for i in range(1, 255):
            if prefix == ".".join(parts[:3]) and str(i) == me:
                continue
            host = f"{prefix}.{i}"
            if host in seen:
                continue
            seen.add(host)
            hosts.append(host)
    return hosts


def _local_ipv4() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return ""


def _adb_push(file_path: Path) -> dict:
    """Fallback when Wi‑Fi import is down: `adb push` into Download if device is USB-connected."""
    remote = f"/sdcard/Download/{file_path.name}"
    try:
        result = subprocess.run(
            ["adb", "push", str(file_path), remote],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "message": "adb not found on PATH. Install platform-tools or use LAN import."}
    except Exception as exc:
        return {"ok": False, "message": f"adb push failed: {exc}"}
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        return {"ok": False, "message": f"adb push failed: {err[:300]}"}
    return {
        "ok": True,
        "message": f"Pushed via adb to {remote}. Open that file with the EPUB picker on the headset.",
    }
