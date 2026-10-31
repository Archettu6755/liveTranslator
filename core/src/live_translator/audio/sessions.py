"""Audio source candidates for the picker (PRODUCT_DISCUSSION.md A1/A2).

Sessions are enumerated per active render endpoint. A session PID is not assumed to be the
application root: it is walked up to the outermost ancestor with the same executable, and
candidates are grouped by that root. ``Active`` and the meter peak only rank candidates; they
never filter one out and never prove the right stream was chosen.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass, field

from . import win_com as wc

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    parent_pid: int
    exe: str


def process_table() -> dict[int, ProcessInfo]:
    snapshot = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    table: dict[int, ProcessInfo] = {}
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return table
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = ProcessInfo(
                entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile
            )
            ok = _k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        wc.CloseHandle(snapshot)
    return table


def image_path(pid: int) -> str | None:
    handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        wc.CloseHandle(handle)


def application_root(pid: int, table: dict[int, ProcessInfo]) -> int:
    """Outermost ancestor running the same executable (e.g. a browser's main process)."""
    current = table.get(pid)
    if current is None:
        return pid
    seen = {pid}
    root = current
    while True:
        parent = table.get(root.parent_pid)
        if parent is None or parent.pid in seen or parent.exe.lower() != current.exe.lower():
            return root.pid
        seen.add(parent.pid)
        root = parent


@dataclass(slots=True)
class SourceCandidate:
    root_pid: int
    exe: str
    name: str
    path: str | None
    active: bool = False
    peak: float = 0.0
    session_pids: list[int] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": f"app:{self.root_pid}",
            "kind": "application",
            "root_pid": self.root_pid,
            "exe": self.exe,
            "name": self.name,
            "path": self.path,
            "active": self.active,
            "peak": round(self.peak, 4),
            "session_pids": sorted(set(self.session_pids)),
        }


@dataclass(frozen=True, slots=True)
class OutputDevice:
    device_id: str
    name: str
    is_default: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": f"device:{self.device_id}",
            "kind": "output_device",
            "name": self.name,
            "is_default": self.is_default,
        }


def list_application_candidates() -> list[SourceCandidate]:
    wc.co_initialize_mta()
    enumerator = wc.create_enumerator()
    collection = enumerator.EnumAudioEndpoints(wc.eRender, wc.DEVICE_STATE_ACTIVE)
    table = process_table()
    own_pid = os.getpid()
    candidates: dict[int, SourceCandidate] = {}
    for index in range(collection.GetCount()):
        device = collection.Item(index)
        endpoint_id = wc.take_cowstr(device.GetId())
        manager = wc.activate(device, wc.IAudioSessionManager2)
        sessions = manager.GetSessionEnumerator()
        for s_index in range(sessions.GetCount()):
            control = sessions.GetSession(s_index)
            control2 = control.QueryInterface(wc.IAudioSessionControl2)
            if control2.IsSystemSoundsSession() == 0:  # S_OK means system sounds
                continue
            pid = control2.GetProcessId()
            if pid in (0, own_pid):
                continue
            state = control2.GetState()
            if state == wc.AudioSessionStateExpired:
                continue
            try:
                peak = control.QueryInterface(wc.IAudioMeterInformation).GetPeakValue()
            except Exception:
                peak = 0.0
            root = application_root(pid, table)
            info = table.get(root) or table.get(pid)
            exe = info.exe if info else f"pid {pid}"
            candidate = candidates.get(root)
            if candidate is None:
                display = wc.take_cowstr(control2.GetDisplayName())
                name = display if display and not display.startswith("@") else os.path.splitext(exe)[0]
                candidate = SourceCandidate(root, exe, name, image_path(root) or image_path(pid))
                candidates[root] = candidate
            candidate.active = candidate.active or state == wc.AudioSessionStateActive
            candidate.peak = max(candidate.peak, float(peak))
            candidate.session_pids.append(pid)
            if endpoint_id not in candidate.endpoints:
                candidate.endpoints.append(endpoint_id)
    # Active first, then by current level, then name; nothing is filtered out (A2).
    return sorted(candidates.values(), key=lambda c: (not c.active, -c.peak, c.name.lower()))


def list_output_devices() -> list[OutputDevice]:
    wc.co_initialize_mta()
    enumerator = wc.create_enumerator()
    try:
        default_id = wc.take_cowstr(enumerator.GetDefaultAudioEndpoint(wc.eRender, wc.eConsole).GetId())
    except Exception:
        default_id = ""
    collection = enumerator.EnumAudioEndpoints(wc.eRender, wc.DEVICE_STATE_ACTIVE)
    devices = []
    for index in range(collection.GetCount()):
        device = collection.Item(index)
        device_id = wc.take_cowstr(device.GetId())
        devices.append(OutputDevice(device_id, _friendly_name(device) or device_id, device_id == default_id))
    return devices


def _friendly_name(device: wc.IMMDevice) -> str | None:
    """PKEY_Device_FriendlyName via IPropertyStore; best effort."""
    try:
        from comtypes import GUID, COMMETHOD, IUnknown
        from ctypes import HRESULT, POINTER, Structure

        class PROPERTYKEY(Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class IPropertyStore(IUnknown):
            _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD))),
                COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD), (["out"], POINTER(PROPERTYKEY))),
                COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY)), (["out"], POINTER(wc.PROPVARIANT))),
            ]

        store = ctypes.cast(device.OpenPropertyStore(0), POINTER(IPropertyStore))
        key = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
        value = store.GetValue(ctypes.byref(key))
        if value.vt == 31:  # VT_LPWSTR
            text = ctypes.wstring_at(ctypes.c_void_p.from_buffer(value.value).value)
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))
            return text
    except Exception:
        return None
    return None
