from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ACL_PATH_ENV = "LIVE_TRANSLATOR_ACL_FILE"
_ACL_CHECK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = Get-Acl -LiteralPath $env:LIVE_TRANSLATOR_ACL_FILE
if (-not $acl.AreAccessRulesProtected) { exit 2 }
foreach ($rule in $acl.Access) {
    $sid = $rule.IdentityReference.Translate(
        [System.Security.Principal.SecurityIdentifier]
    )
    if (
        $rule.AccessControlType -eq
            [System.Security.AccessControl.AccessControlType]::Allow -and
        $sid.Value -ne $identity.Value
    ) { exit 3 }
}
exit 0
"""


def private_file_acl_warning(path: Path) -> str | None:
    if sys.platform != "win32":
        return None
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        return "Could not verify access permissions on the API key file."
    powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    child_environment = {
        "SystemRoot": system_root,
        "WINDIR": os.environ.get("WINDIR", system_root),
        _ACL_PATH_ENV: str(path),
    }
    for name in ("TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            child_environment[name] = value
    try:
        result = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _ACL_CHECK_SCRIPT,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
            env=child_environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return "Could not verify access permissions on the API key file."
    if result.returncode != 0:
        return "The API key file has permissions that may allow access by another account."
    return None
