"""Minimal Core Audio COM declarations for comtypes (Windows only).

Covers endpoint enumeration, audio session enumeration, IAudioClient capture and the
ActivateAudioInterfaceAsync process-loopback activation. Layouts follow the Windows SDK headers
mmdeviceapi.h, audioclient.h, audiopolicy.h, endpointvolume.h and audioclientactivationparams.h.
"""

from __future__ import annotations

import sys

sys.coinit_flags = 0  # type: ignore[attr-defined]  # COINIT_MULTITHREADED before comtypes import

import ctypes  # noqa: E402
from ctypes import HRESULT, POINTER, Structure, Union, c_float, c_int, c_uint32, c_uint64, c_void_p  # noqa: E402
from ctypes import wintypes  # noqa: E402

import comtypes  # noqa: E402
from comtypes import COMMETHOD, GUID, IUnknown  # noqa: E402

CLSCTX_ALL = 23
COINIT_MULTITHREADED = 0
eRender, eCapture, eAll = 0, 1, 2
eConsole, eMultimedia, eCommunications = 0, 1, 2
DEVICE_STATE_ACTIVE = 0x1

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
AUDCLNT_BUFFERFLAGS_SILENT = 0x2

AudioSessionStateInactive, AudioSessionStateActive, AudioSessionStateExpired = 0, 1, 2

VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
VT_BLOB = 65
WAVE_FORMAT_PCM = 1

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
REFERENCE_TIME = ctypes.c_longlong


class WAVEFORMATEX(Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


def pcm16_format(sample_rate: int, channels: int) -> WAVEFORMATEX:
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_PCM
    fmt.nChannels = channels
    fmt.nSamplesPerSec = sample_rate
    fmt.wBitsPerSample = 16
    fmt.nBlockAlign = channels * 2
    fmt.nAvgBytesPerSec = sample_rate * channels * 2
    fmt.cbSize = 0
    return fmt


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", c_int)]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
    _fields_ = [
        ("ActivationType", c_int),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class BLOB(Structure):
    _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", c_void_p)]


class _PropVariantValue(Union):
    _fields_ = [("blob", BLOB), ("pad", ctypes.c_byte * 16)]


class PROPVARIANT(Structure):
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.WORD),
        ("wReserved2", wintypes.WORD),
        ("wReserved3", wintypes.WORD),
        ("value", _PropVariantValue),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate",
                  (["in"], POINTER(GUID), "iid"), (["in"], wintypes.DWORD, "clsctx"),
                  (["in"], c_void_p, "params"), (["out"], POINTER(c_void_p), "ppv")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], wintypes.DWORD), (["out"], POINTER(c_void_p))),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(wintypes.LPWSTR), "id")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(wintypes.DWORD), "state")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint32), "count")),
        COMMETHOD([], HRESULT, "Item", (["in"], c_uint32, "index"), (["out"], POINTER(POINTER(IMMDevice)), "device")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                  (["in"], c_int, "flow"), (["in"], wintypes.DWORD, "mask"),
                  (["out"], POINTER(POINTER(IMMDeviceCollection)), "devices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                  (["in"], c_int, "flow"), (["in"], c_int, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "device")),
        COMMETHOD([], HRESULT, "GetDevice", (["in"], wintypes.LPCWSTR, "id"), (["out"], POINTER(POINTER(IMMDevice)), "device")),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback", (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback", (["in"], c_void_p)),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(c_void_p), "data"), (["out"], POINTER(c_uint32), "frames"),
                  (["out"], POINTER(wintypes.DWORD), "flags"), (["out"], POINTER(c_uint64), "device_position"),
                  (["out"], POINTER(c_uint64), "qpc_position")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "frames")),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize",
                  (["in"], c_int, "share_mode"), (["in"], wintypes.DWORD, "flags"),
                  (["in"], REFERENCE_TIME, "buffer_duration"), (["in"], REFERENCE_TIME, "periodicity"),
                  (["in"], POINTER(WAVEFORMATEX), "format"), (["in"], c_void_p, "session_guid")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32))),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(REFERENCE_TIME))),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32))),
        COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_int), (["in"], POINTER(WAVEFORMATEX)), (["out"], POINTER(POINTER(WAVEFORMATEX)))),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)))),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(REFERENCE_TIME)), (["out"], POINTER(REFERENCE_TIME))),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "event")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"), (["out"], POINTER(c_void_p), "ppv")),
    ]


class IAudioMeterInformation(IUnknown):
    _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetPeakValue", (["out"], POINTER(c_float), "peak")),
        COMMETHOD([], HRESULT, "GetMeteringChannelCount", (["out"], POINTER(c_uint32))),
        COMMETHOD([], HRESULT, "GetChannelsPeakValues", (["in"], c_uint32), (["in"], POINTER(c_float))),
        COMMETHOD([], HRESULT, "QueryHardwareSupport", (["out"], POINTER(wintypes.DWORD))),
    ]


class IAudioSessionControl(IUnknown):
    _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_int), "state")),
        COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(wintypes.LPWSTR), "name")),
        COMMETHOD([], HRESULT, "SetDisplayName", (["in"], wintypes.LPCWSTR), (["in"], POINTER(GUID))),
        COMMETHOD([], HRESULT, "GetIconPath", (["out"], POINTER(wintypes.LPWSTR), "path")),
        COMMETHOD([], HRESULT, "SetIconPath", (["in"], wintypes.LPCWSTR), (["in"], POINTER(GUID))),
        COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], POINTER(GUID))),
        COMMETHOD([], HRESULT, "SetGroupingParam", (["in"], POINTER(GUID)), (["in"], POINTER(GUID))),
        COMMETHOD([], HRESULT, "RegisterAudioSessionNotification", (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification", (["in"], c_void_p)),
    ]


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], POINTER(wintypes.LPWSTR))),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (["out"], POINTER(wintypes.LPWSTR))),
        COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(wintypes.DWORD), "pid")),
        COMMETHOD([], HRESULT, "IsSystemSoundsSession"),
        COMMETHOD([], HRESULT, "SetDuckingPreference", (["in"], wintypes.BOOL)),
    ]


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_int), "count")),
        COMMETHOD([], HRESULT, "GetSession", (["in"], c_int, "index"), (["out"], POINTER(POINTER(IAudioSessionControl)), "session")),
    ]


class IAudioSessionManager(IUnknown):
    _iid_ = GUID("{BFA971F1-4D5E-40BB-935E-967039BFBEE4}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetAudioSessionControl", (["in"], POINTER(GUID)), (["in"], wintypes.DWORD), (["out"], POINTER(c_void_p))),
        COMMETHOD([], HRESULT, "GetSimpleAudioVolume", (["in"], POINTER(GUID)), (["in"], wintypes.DWORD), (["out"], POINTER(c_void_p))),
    ]


class IAudioSessionManager2(IAudioSessionManager):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetSessionEnumerator", (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "enum")),
        COMMETHOD([], HRESULT, "RegisterSessionNotification", (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterSessionNotification", (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "RegisterDuckNotification", (["in"], wintypes.LPCWSTR), (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "UnregisterDuckNotification", (["in"], c_void_p)),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult",
                  (["out"], POINTER(HRESULT), "result"), (["out"], POINTER(POINTER(IUnknown)), "iface")),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "operation")),
    ]


class IAgileObject(IUnknown):
    """Marker interface: the completion handler is called from an arbitrary MTA thread."""

    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_: list[object] = []


def co_initialize_mta() -> None:
    try:
        comtypes.CoInitializeEx(COINIT_MULTITHREADED)
    except OSError:
        pass  # already initialized on this thread


def create_enumerator() -> IMMDeviceEnumerator:
    return comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)


def activate(device: IMMDevice, interface: type[IUnknown]) -> IUnknown:
    ptr = device.Activate(ctypes.byref(interface._iid_), CLSCTX_ALL, None)
    return ctypes.cast(ptr, POINTER(interface))


def take_cowstr(value: wintypes.LPWSTR | str | None) -> str:
    """Strings from Core Audio are CoTaskMem-allocated; comtypes already copies LPWSTR."""
    return value or ""


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CreateEventW = _kernel32.CreateEventW
CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
CreateEventW.restype = wintypes.HANDLE
WaitForSingleObject = _kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
WaitForSingleObject.restype = wintypes.DWORD
SetEvent = _kernel32.SetEvent
SetEvent.argtypes = [wintypes.HANDLE]
CloseHandle = _kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
WAIT_OBJECT_0 = 0

_mmdevapi = ctypes.WinDLL("Mmdevapi")
ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
ActivateAudioInterfaceAsync.argtypes = [
    wintypes.LPCWSTR,
    POINTER(GUID),
    POINTER(PROPVARIANT),
    POINTER(IActivateAudioInterfaceCompletionHandler),
    POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
]
ActivateAudioInterfaceAsync.restype = HRESULT
