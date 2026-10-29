"""Store the optional DeepSeek credential in Windows Credential Manager."""
from __future__ import annotations

import ctypes
import sys

TARGET = 'ZhixingLearningStudio/DeepSeek'
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168

# ctypes.wintypes is not importable on every non-Windows Python build. The
# Windows types used by the credential API have portable ctypes equivalents.
DWORD = ctypes.c_ulong
BOOL = ctypes.c_long
LPWSTR = ctypes.c_wchar_p
LPCWSTR = ctypes.c_wchar_p


class FILETIME(ctypes.Structure):
    _fields_ = [('low', DWORD), ('high', DWORD)]


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', DWORD), ('Type', DWORD),
        ('TargetName', LPWSTR), ('Comment', LPWSTR),
        ('LastWritten', FILETIME), ('CredentialBlobSize', DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', DWORD), ('AttributeCount', DWORD),
        ('Attributes', ctypes.c_void_p), ('TargetAlias', LPWSTR),
        ('UserName', LPWSTR),
    ]


def _api():
    if sys.platform != 'win32':
        raise RuntimeError('记住密钥仅支持 Windows 凭据管理器。')
    dll = ctypes.WinDLL('Advapi32', use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), DWORD]
    dll.CredWriteW.restype = BOOL
    dll.CredReadW.argtypes = [LPCWSTR, DWORD, DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    dll.CredReadW.restype = BOOL
    dll.CredDeleteW.argtypes = [LPCWSTR, DWORD, DWORD]
    dll.CredDeleteW.restype = BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


def save_key(key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError('API Key 不能为空。')
    blob = key.encode('utf-16-le')
    if len(blob) > 2560:
        raise ValueError('API Key 长度超过 Windows 凭据限制。')
    raw = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=TARGET,
                            CredentialBlobSize=len(blob), CredentialBlob=raw,
                            Persist=CRED_PERSIST_LOCAL_MACHINE, UserName='DeepSeek')
    if not _api().CredWriteW(ctypes.byref(credential), 0):
        raise OSError(ctypes.get_last_error(), 'Windows 凭据保存失败。')


def load_key() -> str | None:
    api = _api()
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not api.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        code = ctypes.get_last_error()
        if code == ERROR_NOT_FOUND:
            return None
        raise OSError(code, 'Windows 凭据读取失败。')
    try:
        item = pointer.contents
        blob = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        return blob.decode('utf-16-le')
    finally:
        api.CredFree(pointer)


def delete_key() -> None:
    if not _api().CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0):
        code = ctypes.get_last_error()
        if code != ERROR_NOT_FOUND:
            raise OSError(code, 'Windows 凭据删除失败。')


class WindowsVault:
    """Adapter passed to create_app so the web settings page can remember the key."""
    available = sys.platform == 'win32'

    def load(self) -> str | None:
        return load_key()

    def save(self, key: str) -> None:
        save_key(key)

    def delete(self) -> None:
        delete_key()
