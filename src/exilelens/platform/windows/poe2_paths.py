"""PoE2 path utilities for Windows.

Uses the Windows Known Folder API (SHGetKnownFolderPath) to reliably locate
the Documents folder, supporting redirected folders and OneDrive.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Optional

# Known Folder GUIDs
FOLDERID_Documents = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    def __init__(self, guid_string: str) -> None:
        # Parse GUID string format: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
        guid_string = guid_string.strip("{}")
        parts = guid_string.split("-")
        if len(parts) != 5:
            raise ValueError(f"Invalid GUID format: {guid_string}")
        self.Data1 = int(parts[0], 16)
        self.Data2 = int(parts[1], 16)
        self.Data3 = int(parts[2], 16)
        # Data4 is 8 bytes: first 2 bytes from parts[3], remaining 6 from parts[4]
        data4_bytes = bytes.fromhex(parts[3] + parts[4])
        if len(data4_bytes) != 8:
            raise ValueError(f"Invalid Data4 length for GUID: {guid_string}")
        self.Data4 = (wintypes.BYTE * 8)(*data4_bytes)


# Load shell32.dll
_shell32 = ctypes.windll.shell32

# SHGetKnownFolderPath signature
# HRESULT SHGetKnownFolderPath(
#   REFKNOWNFOLDERID rfid,
#   DWORD dwFlags,
#   HANDLE hToken,
#   PWSTR *ppszPath
# )
_SHGetKnownFolderPath = _shell32.SHGetKnownFolderPath
_SHGetKnownFolderPath.argtypes = [
    ctypes.POINTER(_GUID),  # rfid
    wintypes.DWORD,         # dwFlags
    wintypes.HANDLE,        # hToken
    ctypes.POINTER(wintypes.LPWSTR),  # ppszPath
]
_SHGetKnownFolderPath.restype = wintypes.HRESULT

# KF_FLAG_DEFAULT = 0x00000000
KF_FLAG_DEFAULT = 0x00000000
# KF_FLAG_DONT_VERIFY = 0x00004000
KF_FLAG_DONT_VERIFY = 0x00004000

# HRESULT constants
S_OK = 0
E_INVALIDARG = 0x80070057
E_FAIL = 0x80004005


def get_known_folder_path(folder_id: str, flags: int = KF_FLAG_DEFAULT) -> Optional[Path]:
    """Get the path of a known folder using SHGetKnownFolderPath.

    Args:
        folder_id: GUID string of the known folder (e.g., FOLDERID_Documents)
        flags: Flags for SHGetKnownFolderPath

    Returns:
        Path object if successful, None otherwise.
    """
    guid = _GUID(folder_id)
    path_ptr = wintypes.LPWSTR()

    hr = _SHGetKnownFolderPath(
        ctypes.byref(guid),
        flags,
        None,  # hToken = None for current user
        ctypes.byref(path_ptr)
    )

    if hr != S_OK:
        return None

    try:
        path_str = path_ptr.value
        if path_str:
            return Path(path_str)
        return None
    finally:
        # Free the memory allocated by SHGetKnownFolderPath
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def get_documents_folder() -> Optional[Path]:
    """Get the user's Documents folder using Known Folder API.

    This correctly handles:
    - Standard locations
    - Redirected Documents folders
    - OneDrive-synced Documents folders

    Returns:
        Path to Documents folder, or None if not found.
    """
    return get_known_folder_path(FOLDERID_Documents, KF_FLAG_DEFAULT)


def get_poe2_filter_directory() -> Optional[Path]:
    """Get the Path of Exile 2 filter directory.

    The standard location is: Documents/My Games/Path of Exile 2

    Returns:
        Path to the PoE2 filter directory, or None if Documents folder not found.
    """
    docs = get_documents_folder()
    if docs is None:
        return None
    return docs / "My Games" / "Path of Exile 2"


def verify_poe2_filter_directory(path: Path) -> bool:
    """Verify that a directory is a valid PoE2 filter directory.

    Checks for the presence of game configuration files that indicate
    this is the correct PoE2 directory.

    Args:
        path: Path to verify

    Returns:
        True if the directory appears to be a valid PoE2 directory.
    """
    if not path.exists() or not path.is_dir():
        return False

    # Check for PoE2 configuration files
    # The game creates poe2_production_Config.ini in this directory
    config_files = [
        "poe2_production_Config.ini",
        "poe2_production_Config_local.ini",
    ]

    for config_file in config_files:
        if (path / config_file).exists():
            return True

    # Validation is read-only: never overwrite a fixed probe filename in a user folder.
    return path.name.casefold() == "path of exile 2" and path.parent.name.casefold() == "my games"


def find_poe2_filter_directory() -> Optional[Path]:
    """Find the PoE2 filter directory using multiple strategies.

    Strategies (in order):
    1. Known Folder API (Documents/My Games/Path of Exile 2)
    2. Fallback to USERPROFILE/Documents/My Games/Path of Exile 2
    3. Check for game config files to verify

    Returns:
        Path to PoE2 filter directory, or None if not found.
    """
    # Strategy 1: Known Folder API
    path = get_poe2_filter_directory()
    if path and verify_poe2_filter_directory(path):
        return path

    # Strategy 2: Fallback to USERPROFILE
    userprofile = Path.home() / "Documents" / "My Games" / "Path of Exile 2"
    if userprofile.exists() and verify_poe2_filter_directory(userprofile):
        return userprofile

    # Strategy 3: Check common alternative locations
    # OneDrive Documents
    onedrive = Path.home() / "OneDrive" / "Documents" / "My Games" / "Path of Exile 2"
    if onedrive.exists() and verify_poe2_filter_directory(onedrive):
        return onedrive

    return None
