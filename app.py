#!/usr/bin/env python3
"""A small local desktop-style manager for Reims vGPU VMs.

Uses only Python's standard library and the installed reims-ctl / QEMU tools.
The HTTP server binds to loopback and requires a per-run random URL token.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "reims-manager"
USB_STATE_FILE = CONFIG_DIR / "usb-devices.json"
USB_HOST_STATE_FILE = CONFIG_DIR / "usb-host-state.json"
UPDATE_SETTINGS_FILE = CONFIG_DIR / "update-settings.json"
REIMS = shutil.which("reims-ctl") or str(HOME / ".cargo" / "bin" / "reims-ctl")
APP_VERSION = "1.0.2-2"
APP_PRERELEASE = True
GITHUB_RELEASES_URL = "https://api.github.com/repos/phuf2012/Reims-Manager/releases?per_page=20"
UPDATE_CHECK_INTERVAL = 24 * 60 * 60
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
USB_DEVICE_ID_RE = re.compile(r"usb-\d{3}-\d{3}")
LSUSB_RE = re.compile(
    r"^Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s*(.*)$"
)
SHARE_NET_ID = "reims_manager_share_net"
SHARE_DEVICE_ID = "reims_manager_share_nic"
SHARE_URL = "smb://10.0.3.4/qemu"
USB_ACTION_LOCK = threading.Lock()


class ManagerError(Exception):
    pass


def load_update_settings() -> dict:
    try:
        saved = json.loads(UPDATE_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {
        "auto_check": saved.get("auto_check") is True,
        "last_checked": saved.get("last_checked") if isinstance(saved.get("last_checked"), (int, float)) else None,
    }


def write_update_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = UPDATE_SETTINGS_FILE.with_name(f".update-settings-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, UPDATE_SETTINGS_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def save_update_settings(auto_check: bool) -> dict:
    if not isinstance(auto_check, bool):
        raise ManagerError("Automatic update checking must be enabled or disabled.")
    current = load_update_settings()
    current["auto_check"] = auto_check
    write_update_settings(current)
    return current


def update_settings_status() -> dict:
    settings = load_update_settings()
    last_checked = settings["last_checked"]
    settings.update({
        "current_version": APP_VERSION,
        "check_due": last_checked is None or time.time() - last_checked >= UPDATE_CHECK_INTERVAL,
    })
    return settings


def version_key(tag: str, prerelease: bool = False) -> tuple[tuple[int, ...], int, int] | None:
    normalized = tag.removeprefix("v")
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-(\d+))?", normalized)
    if not match:
        return None
    base = [int(part) for part in match.group(1).split(".")]
    while len(base) > 1 and base[-1] == 0:
        base.pop()
    return tuple(base), 0 if prerelease else 1, int(match.group(2) or 0)


def check_for_updates() -> dict:
    request = urllib.request.Request(
        GITHUB_RELEASES_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Reims-Manager"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            releases = json.loads(response.read(2_000_001))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ManagerError(f"Could not check GitHub releases: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManagerError("GitHub returned an unreadable update list.") from exc
    if not isinstance(releases, list):
        raise ManagerError("GitHub returned an unexpected update response.")

    current_key = version_key(APP_VERSION, prerelease=APP_PRERELEASE)
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        key = version_key(str(release.get("tag_name", "")), prerelease=release.get("prerelease") is True)
        if key is not None:
            candidates.append((key, release))
    if not candidates:
        raise ManagerError("No published Reims Manager releases with readable version tags were found.")
    latest_key, latest = max(candidates, key=lambda item: item[0])
    assets = latest.get("assets", [])
    if not isinstance(assets, list):
        assets = []
    deb_asset = next(
        (asset for asset in assets if isinstance(asset, dict) and str(asset.get("name", "")).lower().endswith(".deb")),
        None,
    )
    download_url = deb_asset.get("browser_download_url") if deb_asset else None
    release_url = latest.get("html_url")
    if not isinstance(release_url, str) or not release_url.startswith("https://github.com/phuf2012/Reims-Manager/releases/"):
        release_url = "https://github.com/phuf2012/Reims-Manager/releases"
    if not isinstance(download_url, str) or not download_url.startswith("https://github.com/phuf2012/Reims-Manager/releases/download/"):
        download_url = None

    settings = load_update_settings()
    settings["last_checked"] = time.time()
    write_update_settings(settings)
    return {
        "current_version": APP_VERSION,
        "latest_version": str(latest.get("tag_name", "Unknown")),
        "release_name": str(latest.get("name") or latest.get("tag_name") or "Reims Manager update"),
        "update_available": latest_key > (current_key or ((), 0, 0)),
        "release_url": release_url,
        "download_url": download_url,
        "published_at": latest.get("published_at"),
    }


def run_reims(*args: str, timeout: int = 120) -> str:
    if not Path(REIMS).is_file():
        raise ManagerError("reims-ctl was not found. Install Reims first, then reopen this app.")
    env = os.environ.copy()
    env["PATH"] = f"{HOME / '.cargo' / 'bin'}:{env.get('PATH', '')}"
    try:
        result = subprocess.run(
            [REIMS, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagerError(f"Reims command timed out after {timeout} seconds.") from exc
    except OSError as exc:
        raise ManagerError(f"Could not run reims-ctl: {exc}") from exc
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode:
        raise ManagerError(error or output or f"reims-ctl exited with status {result.returncode}")
    return output


def valid_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise ManagerError("Invalid VM name.")
    return name


def parse_show(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def list_vms() -> list[dict]:
    try:
        rows = json.loads(run_reims("list", "--json", timeout=30))
    except json.JSONDecodeError as exc:
        raise ManagerError("Reims returned an unreadable VM list.") from exc
    result = []
    for row in rows:
        name = valid_name(str(row.get("name", "")))
        try:
            details = parse_show(run_reims("show", name, timeout=30))
        except ManagerError as exc:
            details = {"details_error": str(exc)}
        result.append(
            {
                "name": name,
                "state": row.get("state", "unknown"),
                "pid": row.get("pid"),
                "dir": row.get("dir", ""),
                "details": details,
            }
        )
    return result


def get_vm(name: str) -> dict:
    name = valid_name(name)
    for vm in list_vms():
        if vm["name"] == name:
            return vm
    raise ManagerError(f"VM '{name}' was not found in Reims.")


def smbd_path() -> str | None:
    """Return Samba's daemon path when it is installed for QEMU's SMB helper."""
    return shutil.which("smbd") or ("/usr/sbin/smbd" if Path("/usr/sbin/smbd").is_file() else None)


def qemu_option_fields(value: str) -> list[str]:
    """Split a QEMU comma-separated option string, treating doubled commas as literals."""
    fields: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == ",":
            if index + 1 < len(value) and value[index + 1] == ",":
                current.append(",")
                index += 2
            else:
                fields.append("".join(current))
                current.clear()
                index += 1
        else:
            current.append(value[index])
            index += 1
    fields.append("".join(current))
    return fields


def qemu_extra_args(details: dict[str, str]) -> list[str]:
    try:
        return shlex.split(details.get("extra args", ""))
    except ValueError as exc:
        raise ManagerError("This VM has malformed extra QEMU arguments. Fix them in Reims before sharing a folder.") from exc


def shared_folder_path(details: dict[str, str]) -> str | None:
    args = qemu_extra_args(details)
    for index, option in enumerate(args[:-1]):
        if option != "-netdev":
            continue
        fields = qemu_option_fields(args[index + 1])
        if f"id={SHARE_NET_ID}" not in fields:
            continue
        for field in fields:
            if field.startswith("smb="):
                return field[4:]
    return None


def strip_shared_folder_args(args: list[str]) -> list[str]:
    cleaned = []
    index = 0
    while index < len(args):
        if args[index] in ("-netdev", "-device") and index + 1 < len(args):
            fields = qemu_option_fields(args[index + 1])
            managed = (
                args[index] == "-netdev" and f"id={SHARE_NET_ID}" in fields
            ) or (
                args[index] == "-device" and f"id={SHARE_DEVICE_ID}" in fields
            )
            if managed:
                index += 2
                continue
        cleaned.append(args[index])
        index += 1
    return cleaned


def checked_shared_folder(path: str) -> Path:
    folder = Path(path).expanduser()
    if any(ord(character) < 32 for character in str(folder)):
        raise ManagerError("Folder paths with control characters cannot be shared.")
    try:
        folder = folder.resolve(strict=True)
    except OSError as exc:
        raise ManagerError("The selected shared folder no longer exists.") from exc
    if not folder.is_dir():
        raise ManagerError("Choose a folder, not a file.")
    if not os.access(folder, os.R_OK | os.W_OK | os.X_OK):
        raise ManagerError("The selected folder must be readable and writable by your Linux account.")
    return folder


def shared_folder_status(name: str) -> dict:
    vm = get_vm(name)
    return {
        "path": shared_folder_path(vm["details"]) or "",
        "smbd_available": bool(smbd_path()),
        "url": SHARE_URL,
    }


def configure_shared_folder(name: str, path: str) -> str:
    name = valid_name(name)
    vm = get_vm(name)
    if vm["state"] == "running":
        raise ManagerError("Stop the VM before changing its shared folder.")
    args = strip_shared_folder_args(qemu_extra_args(vm["details"]))
    if path.strip():
        if not smbd_path():
            raise ManagerError("QEMU needs Samba's smbd to share a folder. Install it with `sudo apt install samba`, then try again.")
        folder = checked_shared_folder(path)
        qemu_path = str(folder).replace(",", ",,")
        args.extend([
            "-netdev",
            f"user,id={SHARE_NET_ID},ipv6=off,net=10.0.3.0/24,smb={qemu_path},smbserver=10.0.3.4",
            "-device",
            f"virtio-net-pci,id={SHARE_DEVICE_ID},netdev={SHARE_NET_ID},mac=52:54:00:52:4d:53",
        ])
        result = run_reims("set", name, "--extra-args", shlex.join(args))
        return f"Shared folder saved. It will be available in macOS at {SHARE_URL} when the VM runs."
    run_reims("set", name, "--extra-args", shlex.join(args))
    return "Shared folder removed from this VM."


def read_usb_state() -> dict[str, dict]:
    try:
        data = json.loads(USB_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_usb_state(data: dict[str, dict]) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = USB_STATE_FILE.with_name(f".usb-devices-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, USB_STATE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def read_usb_host_state() -> dict:
    try:
        value = json.loads(USB_HOST_STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_usb_host_state(data: dict) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = USB_HOST_STATE_FILE.with_name(f".usb-host-state-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, USB_HOST_STATE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def set_usbmuxd(action: str) -> None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise ManagerError("Cannot manage Mint's Apple USB service: systemctl is missing.")
    try:
        result = subprocess.run(
            [systemctl, action, "usbmuxd.service"],
            check=False, capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"Could not {action} usbmuxd.service: {exc}") from exc
    if result.returncode:
        pkexec = shutil.which("pkexec")
        if pkexec:
            try:
                result = subprocess.run(
                    [pkexec, systemctl, action, "usbmuxd.service"],
                    check=False, capture_output=True, text=True, timeout=45,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ManagerError(f"Could not {action} usbmuxd.service: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "Authorization was canceled.").strip()
        raise ManagerError(f"Could not {action} usbmuxd.service: {detail}")


def usbmuxd_active() -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    result = subprocess.run([systemctl, "is-active", "--quiet", "usbmuxd.service"], check=False)
    return result.returncode == 0


def suspend_usbmuxd_for_apple() -> bool:
    was_active = usbmuxd_active()
    if was_active:
        set_usbmuxd("stop")
    return was_active


def restore_usbmuxd_if_needed(name: str, attached: dict) -> bool:
    if not any(device.get("vendor") == "05ac" for device in attached.values()):
        host_state = read_usb_host_state()
        pending = host_state.pop(name, False)
        if pending:
            set_usbmuxd("start")
        write_usb_host_state(host_state)
        return True
    return False


def list_usb_devices(name: str) -> list[dict]:
    vm = get_vm(name)
    state = read_usb_state().get(name, {})
    if vm["state"] != "running" and state:
        # QEMU releases host devices when the VM exits; clear the app's remembered hotplugs.
        restore_usbmuxd_if_needed(name, state)
        all_state = read_usb_state()
        all_state.pop(name, None)
        write_usb_state(all_state)
        state = {}
    elif vm["state"] == "running" and state:
        # QMP can accept device_add while libusb later drops a busy host device.
        # Reconcile remembered rows against QEMU's live tree before offering Detach.
        try:
            with QMP(str(qmp_path(vm))) as qmp:
                tree = qmp_hmp(qmp, "info qtree")
            live = {
                device_id: saved for device_id, saved in state.items()
                if saved.get("qemu_id") and saved["qemu_id"] in tree
            }
            if len(live) != len(state):
                all_state = read_usb_state()
                all_state[name] = live
                write_usb_state(all_state)
                state = live
                restore_usbmuxd_if_needed(name, state)
        except ManagerError:
            pass  # Keep the saved rows if the VM monitor is briefly unavailable.
    elif vm["state"] == "running" and read_usb_host_state().get(name):
        # Recover a stale iPhone-service hold after an interrupted attach/detach.
        # Do not restart usbmuxd if QEMU still has any manager-owned USB device.
        try:
            with QMP(str(qmp_path(vm))) as qmp:
                tree = qmp_hmp(qmp, "info qtree")
            if "reims_usb_" not in tree:
                restore_usbmuxd_if_needed(name, {})
        except ManagerError:
            pass
    try:
        result = subprocess.run(
            ["lsusb"], check=False, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"Could not list USB devices: {exc}") from exc
    if result.returncode:
        raise ManagerError((result.stderr or "lsusb failed").strip())
    devices_by_id = {}
    for line in result.stdout.splitlines():
        match = LSUSB_RE.match(line)
        if not match:
            continue
        bus, address, vendor, product, description = match.groups()
        device_id = f"usb-{int(bus):03d}-{int(address):03d}"
        saved = state.get(device_id)
        attached = saved and (
            saved.get("vendor", "").lower() == vendor.lower()
            and saved.get("product", "").lower() == product.lower()
        )
        devices_by_id[device_id] = {
            "id": device_id,
            "bus": int(bus),
            "address": int(address),
            "vendor": vendor.lower(),
            "product": product.lower(),
            "description": description.strip() or "USB device",
            "attached": bool(attached),
            "attached_to_running_vm": bool(attached and vm["state"] == "running"),
        }
    # Keep a remembered attached row visible even if host enumeration changes while
    # QEMU owns the device. Detach uses QEMU's saved id, not the transient host address.
    for device_id, saved in state.items():
        present = devices_by_id.get(device_id)
        same_device = present and present["vendor"] == saved.get("vendor") and present["product"] == saved.get("product")
        if not same_device:
            # Bus/address pairs are reused by Linux. Keep the old VM-owned device
            # separately so Detach can never accidentally target a newly plugged-in
            # device that inherited the same address.
            row_id = f"attached-{saved['qemu_id']}" if present and saved.get("qemu_id") else device_id
            if present:
                present["available_on_host"] = False
            devices_by_id[row_id] = {
                **saved,
                "id": row_id,
                "attached": True,
                "attached_to_running_vm": vm["state"] == "running",
                "available_on_host": False,
            }
        else:
            present["available_on_host"] = True
    for device in devices_by_id.values():
        device.setdefault("available_on_host", True)
    return list(devices_by_id.values())


class QMP:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.sock: socket.socket | None = None
        self.stream = None
        self.sequence = 0

    def __enter__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        try:
            self.sock.connect(self.socket_path)
            self.stream = self.sock.makefile("rwb", buffering=0)
            self._read_message()  # QMP greeting
            self.call("qmp_capabilities")
            return self
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.__exit__(None, None, None)
            raise ManagerError(f"Could not connect to the running VM's QMP socket: {exc}") from exc

    def __exit__(self, *_):
        if self.stream:
            self.stream.close()
        if self.sock:
            self.sock.close()

    def _read_message(self) -> dict:
        assert self.stream is not None
        line = self.stream.readline()
        if not line:
            raise ManagerError("QEMU closed the monitor connection.")
        return json.loads(line.decode("utf-8"))

    def call(self, command: str, arguments: dict | None = None):
        assert self.stream is not None
        self.sequence += 1
        request = {"execute": command, "id": self.sequence}
        if arguments is not None:
            request["arguments"] = arguments
        self.stream.write((json.dumps(request) + "\r\n").encode("utf-8"))
        while True:
            response = self._read_message()
            if response.get("id") != self.sequence:
                continue  # Ignore asynchronous QMP events.
            if "error" in response:
                description = response["error"].get("desc", "QEMU rejected the request")
                raise ManagerError(description)
            return response.get("return", {})


def qmp_hmp(qmp: QMP, command: str) -> str:
    """Run a read-only HMP inspection command through QMP."""
    result = qmp.call("human-monitor-command", {"command-line": command})
    return result if isinstance(result, str) else str(result)


def usb_diagnostics(name: str) -> dict:
    vm = get_vm(name)
    if vm["state"] != "running":
        raise ManagerError("Start the VM before checking its USB bus.")
    state = read_usb_state().get(name, {})
    with QMP(str(qmp_path(vm))) as qmp:
        guest_usb = qmp_hmp(qmp, "info usb")
        tree = qmp_hmp(qmp, "info qtree")
    active = []
    for device in state.values():
        qemu_id = device.get("qemu_id")
        if not qemu_id:
            continue
        matches = [
            index for index, line in enumerate(tree.splitlines())
            if qemu_id in line
        ]
        if matches:
            lines = tree.splitlines()
            for index in matches:
                active.extend(lines[max(0, index - 1): min(len(lines), index + 12)])
        else:
            active.append(f"{qemu_id}: not present in QEMU's device tree")
    return {
        "guest_usb": guest_usb.strip() or "QEMU reports no guest USB devices.",
        "passthrough_devices": "\n".join(dict.fromkeys(active)) or "No USB passthrough devices are recorded.",
    }


def qmp_path(vm: dict) -> Path:
    directory = Path(vm["dir"]).expanduser()
    if not directory.is_absolute() or not directory.is_dir():
        raise ManagerError("Reims did not report a usable VM directory.")
    return directory / "qmp.sock"


def unmount_matching_usb_mount(device: dict) -> list[str]:
    """Unmount matching GVFS MTP/GPhoto2 mounts for this exact USB address."""
    gio = shutil.which("gio")
    if not gio:
        return []
    try:
        result = subprocess.run(
            [gio, "mount", "-l"], check=False, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"Could not check Mint's phone mounts: {exc}") from exc
    if result.returncode:
        raise ManagerError((result.stderr or "Could not check Mint's phone mounts.").strip())

    bus = int(device["bus"])
    address = int(device["address"])
    # GVFS encodes USB locations in MTP and GPhoto2 URIs as [usb:BBB,DDD].
    expected = re.compile(
        rf"^(?:mtp|gphoto2)://\[usb:0*{bus},0*{address}\]/?$", re.IGNORECASE
    )
    mounts = []
    for line in result.stdout.splitlines():
        for uri in re.findall(r"(?:mtp|gphoto2)://\[[^\]]+\]/?", line, re.IGNORECASE):
            if expected.fullmatch(uri):
                mounts.append(uri)
    for uri in dict.fromkeys(mounts):
        try:
            unmounted = subprocess.run(
                [gio, "mount", "-u", uri],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagerError(f"Could not unmount this phone from Mint: {exc}") from exc
        if unmounted.returncode:
            detail = (unmounted.stderr or unmounted.stdout or "Mount is busy.").strip()
            raise ManagerError(
                f"Mint still has this phone mounted ({detail}). Close its file window or "
                "finish any transfer, then try Attach again."
            )
    return list(dict.fromkeys(mounts))


def usb_node_path(device: dict) -> Path:
    return Path("/dev/bus/usb") / f"{int(device['bus']):03d}" / f"{int(device['address']):03d}"


def usb_node_matches(device: dict) -> bool:
    """Confirm the transient USB address still belongs to the selected device."""
    return usb_sysfs_node(device) is not None


def usb_sysfs_node(device: dict) -> Path | None:
    for node in Path("/sys/bus/usb/devices").glob("*"):
        try:
            bus = int((node / "busnum").read_text().strip())
            address = int((node / "devnum").read_text().strip())
            vendor = (node / "idVendor").read_text().strip().lower()
            product = (node / "idProduct").read_text().strip().lower()
        except (OSError, ValueError):
            continue
        if (bus, address, vendor, product) == (
            int(device["bus"]), int(device["address"]),
            str(device["vendor"]).lower(), str(device["product"]).lower(),
        ):
            return node.resolve()
    return None


def unmount_usb_storage(device: dict) -> list[str]:
    """Safely unmount mounted partitions on this USB disk before QEMU opens it."""
    usb_root = usb_sysfs_node(device)
    if usb_root is None:
        raise ManagerError("That USB device disconnected or changed identity. Scan and retry.")
    lsblk = shutil.which("lsblk")
    if not lsblk:
        raise ManagerError("Cannot safely prepare USB storage because lsblk is missing.")
    try:
        result = subprocess.run(
            [lsblk, "--json", "--paths", "--output", "PATH,TYPE,MOUNTPOINTS"],
            check=False, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"Could not check whether this USB drive is mounted: {exc}") from exc
    if result.returncode:
        raise ManagerError((result.stderr or "Could not inspect mounted drives.").strip())
    try:
        block_devices = json.loads(result.stdout).get("blockdevices", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ManagerError("Linux returned an unreadable list of mounted drives.") from exc

    def is_selected_usb(path: str) -> bool:
        block_name = Path(path).name
        try:
            block_sysfs = (Path("/sys/class/block") / block_name / "device").resolve(strict=True)
            return block_sysfs.is_relative_to(usb_root)
        except (OSError, ValueError):
            return False

    def mounted_paths(tree: list[dict]) -> list[tuple[str, str]]:
        found = []
        for item in tree:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            children = item.get("children") or []
            if path and is_selected_usb(path):
                found.extend(mounted_paths(children))
                points = item.get("mountpoints") or []
                if isinstance(points, str):
                    points = [points]
                for mountpoint in points:
                    if mountpoint:
                        found.append((path, str(mountpoint)))
            else:
                found.extend(mounted_paths(children))
        return found

    mounts = mounted_paths(block_devices)
    if not mounts:
        return []
    udisksctl = shutil.which("udisksctl")
    if not udisksctl:
        mountpoint = mounts[0][1]
        raise ManagerError(
            f"Linux has this drive mounted at {mountpoint}, but udisksctl is missing. "
            "Safely eject it in Linux Files, then reconnect it to the VM."
        )
    released = []
    for block_path, mountpoint in mounts:
        try:
            result = subprocess.run(
                [udisksctl, "unmount", "--block-device", block_path],
                check=False, capture_output=True, text=True, timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ManagerError(f"Could not safely unmount {mountpoint}: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout or "The volume is busy.").strip()
            raise ManagerError(
                f"Linux could not safely release {mountpoint} ({detail}). Close files using "
                "the drive, wait for transfers to finish, then connect it again."
            )
        released.append(mountpoint)
    return released


def grant_temporary_usb_access(device: dict, path: Path) -> None:
    """Use the desktop authorization prompt to grant this user access to one USB node."""
    if os.access(path, os.R_OK | os.W_OK):
        return
    if not path.exists():
        raise ManagerError("The USB device disconnected or changed address. Rescan and retry.")
    pkexec = shutil.which("pkexec")
    setfacl = shutil.which("setfacl")
    if not pkexec or not setfacl:
        raise ManagerError(
            f"Your account cannot access {path}, and this system lacks pkexec or setfacl "
            "for a temporary permission prompt. No changes were made."
        )
    try:
        result = subprocess.run(
            [pkexec, setfacl, "-m", f"u:{os.getuid()}:rw", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagerError("The USB permission prompt timed out; no system rule was created.") from exc
    except OSError as exc:
        raise ManagerError(f"Could not request temporary USB access: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if result.returncode in (126, 127) or not detail:
            detail = "Authorization was canceled or denied."
        raise ManagerError(f"Temporary access was not granted: {detail}")
    if not path.exists():
        raise ManagerError("The device changed address during authorization. Rescan and retry.")
    if not os.access(path, os.R_OK | os.W_OK):
        raise ManagerError("Mint did not grant access to this device; no persistent rule was created.")


def usb_action(name: str, action: str, device_id: str) -> str:
    # QMP hotplug and the on-disk attachment record must be updated as one
    # operation. Serializing clicks avoids two requests attaching the same node.
    if not USB_ACTION_LOCK.acquire(blocking=False):
        raise ManagerError("A USB action is already in progress. Wait for it to finish, then try again.")
    try:
        return _usb_action_locked(name, action, device_id)
    finally:
        USB_ACTION_LOCK.release()


def _usb_action_locked(name: str, action: str, device_id: str) -> str:
    name = valid_name(name)
    if not isinstance(device_id, str) or not (
        USB_DEVICE_ID_RE.fullmatch(device_id)
        or re.fullmatch(r"attached-reims_usb_[a-f0-9]{12}", device_id)
    ):
        raise ManagerError("Invalid USB device selection.")
    vm = get_vm(name)
    if vm["state"] != "running":
        raise ManagerError("Start the VM before changing its USB devices.")
    devices = {device["id"]: device for device in list_usb_devices(name)}
    state = read_usb_state()
    attached = state.setdefault(name, {})
    with QMP(str(qmp_path(vm))) as qmp:
        if action == "attach":
            device = devices.get(device_id)
            if device is None:
                raise ManagerError("That USB device is no longer connected to the host.")
            if device_id in attached:
                raise ManagerError("That device is already attached to this VM.")
            usb_node = usb_node_path(device)
            if not usb_node.exists() or not usb_node_matches(device):
                raise ManagerError(
                    "That USB device disconnected or changed identity. Reconnect it, scan again, and retry."
                )
            storage_mounts = unmount_usb_storage(device)
            try:
                grant_temporary_usb_access(device, usb_node)
            except ManagerError as exc:
                if storage_mounts:
                    raise ManagerError(
                        f"{exc} The drive volume was safely unmounted from Linux; open it again "
                        "in Files if you cancel the connection."
                    ) from exc
                raise
            host_mounts = unmount_matching_usb_mount(device)
            if device["vendor"] == "05ac":
                host_state = read_usb_host_state()
                if usbmuxd_active():
                    set_usbmuxd("stop")
                    host_state[name] = True
                    write_usb_host_state(host_state)
            if not usb_node.exists() or not usb_node_matches(device):
                if device["vendor"] == "05ac":
                    restore_usbmuxd_if_needed(name, read_usb_state().get(name, {}))
                raise ManagerError("The USB device changed while connecting. Reconnect it and scan again.")
            qemu_id = f"reims_usb_{uuid.uuid4().hex[:12]}"
            qemu_device = {
                "driver": "usb-host",
                "id": qemu_id,
                "bus": "hostpass.0",
                "hostbus": device["bus"],
                "hostaddr": device["address"],
            }
            # iOS devices can be reset into their deactivated USB configuration
            # by the guest. Keep the default reset behavior for other USB devices.
            if device["vendor"] == "05ac":
                qemu_device["guest-reset"] = False
            try:
                qmp.call("device_add", qemu_device)
            except ManagerError as exc:
                detail = str(exc)
                if "permission" in detail.lower() or "access denied" in detail.lower():
                    detail += (
                        " Mint's USB permissions do not allow QEMU to open this device. "
                        "This manager will not change system permissions."
                    )
                if host_mounts:
                    detail += " Its matching Mint mount was released; unplug/reconnect it to restore host access."
                else:
                    detail += (
                        " If the device node is accessible, close Mint Files and eject/unmount "
                        "the device there, then reconnect it and retry."
                    )
                if device["vendor"] == "05ac":
                    state_for_vm = read_usb_state().get(name, {})
                    restore_usbmuxd_if_needed(name, state_for_vm)
                raise ManagerError(detail) from exc
            attached[device_id] = {**device, "qemu_id": qemu_id}
            write_usb_state(state)
            released = [*storage_mounts, *host_mounts]
            suffix = f" Linux released {', '.join(released)}." if released else ""
            return (
                f"{device['description']} is connected to the VM."
                f"{suffix} Check macOS System Information → USB to confirm guest detection."
            )
        if action == "detach":
            state_key = device_id if device_id in attached else next(
                (key for key, value in attached.items() if f"attached-{value.get('qemu_id')}" == device_id),
                None,
            )
            saved = attached.get(state_key) if state_key else None
            if saved is None:
                raise ManagerError("That device is not recorded as attached to this VM.")
            qmp.call("device_del", {"id": saved["qemu_id"]})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if saved["qemu_id"] not in qmp_hmp(qmp, "info qtree"):
                    break
                time.sleep(0.2)
            else:
                raise ManagerError(
                    "QEMU has not finished removing this USB device yet. It remains marked "
                    "as attached; wait a few seconds and press Detach again."
                )
            del attached[state_key]
            write_usb_state(state)
            restore_usbmuxd_if_needed(name, attached)
            return "Device returned to Linux. You can use or mount it in Mint again."
    raise ManagerError("Unknown USB action.")


def apply_settings(name: str, payload: dict) -> str:
    name = valid_name(name)
    vm = get_vm(name)
    if vm["state"] == "running":
        raise ManagerError("Stop the VM before changing its saved settings.")
    try:
        cpus = int(payload.get("cpus", 4))
        memory = int(payload.get("memory", 16))
    except (TypeError, ValueError) as exc:
        raise ManagerError("CPU and memory values must be numbers.") from exc
    if cpus not in (1, 2, 3, 4):
        raise ManagerError("Choose between 1 and 4 CPU cores.")
    if memory not in (4, 8, 12, 16):
        raise ManagerError("Choose 4, 8, 12, or 16 GB of RAM.")
    resolution = payload.get("resolution", "host")
    if resolution not in ("host", "1920x1080", "1600x900", "1280x800", "1280x720"):
        raise ManagerError("Choose a supported resolution.")
    refresh = payload.get("refresh")
    if refresh is not None:
        refresh = str(refresh)
        if refresh not in ("host", "60", "120"):
            raise ManagerError("Choose host refresh, 60 Hz, or 120 Hz.")
    gpu = str(payload.get("gpu", "auto"))
    if not re.fullmatch(r"(?:auto|[1-9][0-9]*|[A-Za-z0-9 _().:-]+|/[^\s]+\.json)", gpu):
        raise ManagerError("Invalid GPU selection.")
    borderless = bool(payload.get("borderless", True))
    hidpi = bool(payload.get("hidpi", False))
    audio = bool(payload.get("audio", True))
    video_acceleration = payload.get("video_acceleration")
    if video_acceleration is not None and not isinstance(video_acceleration, bool):
        raise ManagerError("Video acceleration must be enabled or disabled.")
    network = bool(payload.get("network", True))
    logs = bool(payload.get("logs", False))
    args = [
        "set", name,
        "--cpus", str(cpus),
        "--memory", f"{memory}G",
        "--resolution", resolution,
        "--borderless", "true" if borderless else "false",
        "--hidpi", "true" if hidpi else "false",
        "--audio", "true" if audio else "false",
        "--network", "true" if network else "false",
        "--logs", "true" if logs else "false",
        "--gpu", gpu,
    ]
    if refresh is not None:
        args.extend(["--refresh", "0" if refresh == "host" else refresh])
    if video_acceleration is not None:
        args.extend(["--video-acceleration", "true" if video_acceleration else "false"])
    return run_reims(*args)


def do_action(name: str, action: str) -> str:
    name = valid_name(name)
    if action == "start":
        vm = get_vm(name)
        folder = shared_folder_path(vm["details"])
        if folder:
            if not smbd_path():
                raise ManagerError("This VM has a shared folder configured, but Samba's smbd is missing. Install it with `sudo apt install samba`, or remove the shared folder setting.")
            checked_shared_folder(folder)
        return run_reims("start", name, timeout=180)
    if action == "stop":
        result = run_reims("stop", name, timeout=120)
        release_vm_usb_state(name)
        return result
    if action == "force-stop":
        result = run_reims("stop", name, "--force", timeout=30)
        release_vm_usb_state(name)
        return result
    raise ManagerError("Unknown VM action.")


def release_vm_usb_state(name: str) -> None:
    state = read_usb_state()
    attached = state.pop(name, {})
    restore_usbmuxd_if_needed(name, attached)
    write_usb_state(state)


def gpu_list() -> list[dict]:
    output = run_reims("gpus", timeout=30)
    items = []
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\.\s+(.+?)\s+\[([0-9a-fA-F:]+)\]\s*(.*)$", line)
        if match:
            number, label, device_id, detail = match.groups()
            items.append({"number": number, "label": f"{label} [{device_id}]", "detail": detail.strip()})
    return items


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, token: str):
        self.token = token
        super().__init__(address, handler)


class Handler(BaseHTTPRequestHandler):
    server: AppServer

    def log_message(self, fmt, *args):
        # Avoid leaking the random UI token from request paths to the console.
        clean_path = self.path.split("?", 1)[0]
        print(f"[reims-manager] {self.command} {clean_path}")

    def _send(self, status: int, payload, content_type: str = "application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _authorized_path(self) -> str | None:
        parsed = urlparse(self.path)
        prefix = f"/{self.server.token}"
        if parsed.path == prefix or parsed.path == prefix + "/":
            return "/"
        if parsed.path.startswith(prefix + "/"):
            route = parsed.path[len(prefix):]
            return route + (f"?{parsed.query}" if parsed.query else "")
        return None

    def _check_origin(self):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host", "") != expected_host:
            raise ManagerError("This local manager only accepts requests from its own browser tab.")
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected_host}":
            raise ManagerError("Cross-origin requests are not allowed.")

    def _json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ManagerError("Invalid request size.") from exc
        if length < 0 or length > 65536:
            raise ManagerError("Request is too large.")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ManagerError("Invalid JSON request.") from exc

    def do_GET(self):
        route = self._authorized_path()
        if route is None:
            self._send(404, {"error": "Not found"})
            return
        if route == "/":
            try:
                body = (WEB_DIR / "index.html").read_bytes()
            except OSError:
                self._send(500, {"error": "App UI files are missing."})
                return
            self._send(200, body, "text/html; charset=utf-8")
            return
        parsed = urlparse(route)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/state":
                self._send(200, {"vms": list_vms(), "gpus": gpu_list()})
            elif parsed.path == "/api/updates/settings":
                self._send(200, update_settings_status())
            elif parsed.path == "/api/updates/check":
                self._send(200, check_for_updates())
            elif parsed.path == "/api/shared-folder":
                self._send(200, shared_folder_status(query.get("name", [""])[0]))
            elif parsed.path == "/api/usb":
                self._send(200, {"devices": list_usb_devices(query.get("name", [""])[0])})
            elif parsed.path == "/api/usb/diagnostics":
                self._send(200, usb_diagnostics(query.get("name", [""])[0]))
            elif parsed.path == "/api/logs":
                name = valid_name(query.get("name", [""])[0])
                output = run_reims("logs", name, "-n", "100", timeout=30)
                self._send(200, {"logs": output or "No recent log output."})
            else:
                self._send(404, {"error": "Not found"})
        except ManagerError as exc:
            self._send(400, {"error": str(exc)})

    def do_POST(self):
        route = self._authorized_path()
        if route is None:
            self._send(404, {"error": "Not found"})
            return
        try:
            self._check_origin()
            body = self._json_body()
            if route == "/api/vm/action":
                message = do_action(body.get("name", ""), body.get("action", ""))
                self._send(200, {"message": message or "Done."})
            elif route == "/api/vm/settings":
                message = apply_settings(body.get("name", ""), body)
                self._send(200, {"message": message or "Settings saved. They apply on the next start."})
            elif route == "/api/shared-folder":
                message = configure_shared_folder(body.get("name", ""), str(body.get("path", "")))
                self._send(200, {"message": message})
            elif route == "/api/updates/settings":
                settings = save_update_settings(body.get("auto_check"))
                settings.update({"current_version": APP_VERSION, "check_due": settings["last_checked"] is None or time.time() - settings["last_checked"] >= UPDATE_CHECK_INTERVAL})
                self._send(200, settings)
            elif route == "/api/usb":
                message = usb_action(body.get("name", ""), body.get("action", ""), body.get("id", ""))
                self._send(200, {"message": message})
            elif route == "/api/quit":
                self._send(200, {"message": "Manager stopped. You can close this browser tab."})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._send(404, {"error": "Not found"})
        except ManagerError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # Surface unexpected local tool failures to the UI.
            self._send(500, {"error": f"Unexpected error: {exc}"})


def main() -> int:
    if not Path(REIMS).is_file():
        print(f"reims-ctl not found at {REIMS}. Install Reims first.", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(24)
    server = AppServer(("127.0.0.1", 0), Handler, token)
    port = server.server_port
    url = f"http://127.0.0.1:{port}/{token}/"
    print("Reims Manager is running locally. Close this terminal to stop it.")
    print(url)
    threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
