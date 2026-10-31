"""Build and verify a self-contained Windows x64 portable client from locked local dependencies."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13.5"
PYTHON_ARCHIVE = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ARCHIVE}"
PYTHON_SHA256 = "7d2650fd9d1b9d002d4a315d5f354247fd6a44f30517c7ef577b08f57a0fb6d9"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def python_archive() -> Path:
    target = ROOT / "artifacts/build-cache" / PYTHON_ARCHIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        print("Downloading private CPython runtime (about 11 MB) from python.org", flush=True)
        with urllib.request.urlopen(PYTHON_URL, timeout=60) as response:
            data = response.read(16 * 1024 * 1024)
        if sha(data) != PYTHON_SHA256:
            raise RuntimeError("CPython download checksum mismatch")
        target.write_bytes(data)
    if sha(target.read_bytes()) != PYTHON_SHA256:
        raise RuntimeError("Cached CPython checksum mismatch")
    return target


def vendor_dependencies(destination: Path) -> list[dict]:
    site = ROOT / "core/.venv/Lib/site-packages"
    lock = tomllib.loads((ROOT / "core/uv.lock").read_text(encoding="utf-8"))
    packages = {item["name"]: item for item in lock["package"]}
    wanted = set()

    def include(name: str) -> None:
        if name in wanted:
            return
        wanted.add(name)
        for dependency in packages[name].get("dependencies", []):
            include(dependency["name"])

    for dependency in packages["live-translator-core"]["dependencies"]:
        include(dependency["name"])
    installed = {dist.metadata["Name"].lower().replace("_", "-"): dist for dist in importlib.metadata.distributions(path=[str(site)])}
    result = []
    for name in sorted(wanted):
        dist = installed[name]
        if dist.version != packages[name]["version"]:
            raise RuntimeError(f"Installed {name} does not match uv.lock")
        copied = 0
        for entry in dist.files or []:
            source = Path(dist.locate_file(entry)).resolve()
            if not source.is_relative_to(site.resolve()) or not source.is_file():
                continue
            relative = source.relative_to(site.resolve())
            if "__pycache__" in relative.parts or source.suffix in {".pyc", ".pth"} or source.name in {"direct_url.json", "uv_cache.json", "INSTALLER", "REQUESTED"}:
                continue
            data = source.read_bytes()
            if entry.hash:
                value = base64.urlsafe_b64encode(hashlib.new(entry.hash.mode, data).digest()).decode().rstrip("=")
                if value != entry.hash.value:
                    raise RuntimeError(f"Dependency RECORD integrity mismatch: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            copied += 1
        result.append({"name": name, "version": dist.version, "files": copied, "source": "locked production wheel", "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", "See bundled dist-info/licenses"), "project_urls": dist.metadata.get_all("Project-URL", [])})
    return result


def pe_imports(path: Path) -> set[str]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return set()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise RuntimeError(f"Invalid PE image: {path.name}")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    wide = struct.unpack_from("<H", data, opt)[0] == 0x20B
    directories = opt + (112 if wide else 96)
    image_base = struct.unpack_from("<Q" if wide else "<I", data, opt + (24 if wide else 28))[0]
    sections = []
    for index in range(count):
        cursor = opt + opt_size + index * 40
        size, virtual, raw_size, raw = struct.unpack_from("<IIII", data, cursor + 8)
        sections.append((virtual, max(size, raw_size), raw))

    def offset(rva: int) -> int:
        for virtual, size, raw in sections:
            if virtual <= rva < virtual + size:
                return raw + rva - virtual
        raise RuntimeError(f"Invalid import address in {path.name}")

    names = set()
    for directory, stride, name_offset in [(1, 20, 12), (13, 32, 4)]:
        rva, size = struct.unpack_from("<II", data, directories + directory * 8)
        if not rva or not size:
            continue
        start = offset(rva)
        for index in range(min(size // stride, 4096)):
            cursor = start + index * stride
            name = struct.unpack_from("<I", data, cursor + name_offset)[0]
            if not name:
                break
            if directory == 13 and not struct.unpack_from("<I", data, cursor)[0] & 1:
                name -= image_base
            address = offset(name)
            end = data.find(b"\0", address, address + 512)
            if end < 0:
                raise RuntimeError(f"Invalid DLL name in {path.name}")
            names.add(data[address:end].decode("ascii").lower())
    return names


def audit_native_files(folder: Path) -> dict:
    binaries = [path for path in folder.rglob("*") if path.suffix.lower() in {".exe", ".dll", ".pyd"}]
    included = {path.name.lower() for path in binaries}
    system = Path(os.environ["SystemRoot"]) / "System32"
    missing = []
    for path in binaries:
        for name in pe_imports(path):
            if name in included or name.startswith(("api-ms-win-", "ext-ms-win-")):
                continue
            redistributable = name.startswith(("vcruntime", "msvcp", "concrt", "vcomp"))
            if redistributable or not (system / name).is_file():
                missing.append({"file": path.relative_to(folder).as_posix(), "dll": name})
    if missing:
        raise RuntimeError(f"Unbundled native dependencies: {missing}")
    return {"binary_files_checked": len(binaries), "unbundled_runtime_dependencies": missing, "os_baseline": "Windows 11 x64 system DLLs and API sets"}


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Build and validation require Windows")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    package = json.loads((ROOT / "desktop/package.json").read_text(encoding="utf-8"))
    version = package["version"]
    folder = ROOT / "artifacts/package-builds" / f"LiveTranslator-{version}-win-x64-{stamp}"
    if folder.exists():
        raise FileExistsError(folder)
    npm = shutil.which("npm.cmd")
    if not npm:
        raise RuntimeError("The build machine needs npm; users of the client do not")
    subprocess.run([npm, "run", "build"], cwd=ROOT / "desktop", check=True, timeout=120)
    archive = python_archive()
    print("Assembling the bundled Electron and Python runtimes", flush=True)
    shutil.copytree(ROOT / "desktop/node_modules/electron/dist", folder)
    (folder / "electron.exe").rename(folder / "LiveTranslator.exe")
    if (folder / "electron_wer.dll").exists():
        (folder / "electron_wer.dll").rename(folder / "LiveTranslator_wer.dll")
    default_app = folder / "resources/default_app.asar"
    if default_app.exists():
        default_app.unlink()
    resources = folder / "resources"
    application = resources / "app"
    (application / "dist/main").mkdir(parents=True)
    for source in (ROOT / "desktop/dist/main").glob("*.js"):
        if source.name.endswith(".test.js") or source.name in {"smoke.js", "audio-probe.js"}:
            continue
        shutil.copy2(source, application / "dist/main" / source.name)
    for part in ("renderer", "preload"):
        shutil.copytree(ROOT / "desktop/dist" / part, application / "dist" / part)
    write_json(application / "package.json", {"name": "live-translator", "productName": "Live Translator", "version": version, "main": "dist/main/main.js", "private": True})
    python = resources / "python"
    python.mkdir()
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise RuntimeError("Unsafe runtime archive path")
        source.extractall(python)
    (python / "python313._pth").write_text("python313.zip\n.\nLib/site-packages\n../core\nimport site\n", encoding="ascii")
    dependencies = vendor_dependencies(python / "Lib/site-packages")
    # NumPy vendors this redistributable under a collision-resistant DLL name.
    # soxr imports its original name; provide the identical binary app-locally.
    msvcp_sources = list((python / "Lib/site-packages/numpy.libs").glob("msvcp140-*.dll"))
    if len(msvcp_sources) != 1:
        raise RuntimeError("Expected one locked NumPy MSVCP140 redistributable")
    shutil.copy2(msvcp_sources[0], python / "msvcp140.dll")
    dll_alias = {"path": "python/msvcp140.dll", "source": msvcp_sources[0].relative_to(resources).as_posix(), "sha256": sha(msvcp_sources[0].read_bytes())}
    shutil.copytree(ROOT / "core/src/live_translator", resources / "core/live_translator", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    notices = ["Live Translator bundled runtime notices", "", f"CPython {PYTHON_VERSION}: resources/python/LICENSE.txt", "Electron: LICENSE and LICENSES.chromium.html", "", "Python packages retain their wheel metadata and license files in resources/python/Lib/site-packages.", "Package sources and versions are recorded in resources/runtime-manifest.json.", "", "This bundle contains no ASR model weights, user settings, API keys or development environments."]
    (folder / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(notices) + "\n", encoding="utf-8")
    (folder / "开始使用.txt").write_text("Live Translator\n\n双击 LiveTranslator.exe 启动，首次可直接播放离线字幕演示。\n无需安装 Python、uv、Conda、Node.js、npm 或 Electron。\n请保留整个文件夹，不要单独移动 exe。设置由客户端保存在当前 Windows 用户目录。\n真实 ASR 模型配置单独处理；包内预设模拟器不识别语音。\n此便携包未作发布者代码签名。\n", encoding="utf-8")
    native = audit_native_files(folder)
    write_json(resources / "runtime-manifest.json", {"format_version": 1, "application_version": version, "platform": "win32-x64", "python": {"version": PYTHON_VERSION, "source": PYTHON_URL, "archive_sha256": PYTHON_SHA256}, "electron": {"version": (folder / "version").read_text().strip()}, "dependencies": dependencies, "native_runtime_aliases": [dll_alias], "native_dependency_audit": native, "asr_model_included": False, "code_signed": False, "lock_sha256": {"core": sha((ROOT / "core/uv.lock").read_bytes()), "desktop": sha((ROOT / "desktop/package-lock.json").read_bytes())}})
    validation_root = ROOT / "artifacts/package-validation" / stamp
    relocated = validation_root / "独立客户端 空格路径" / folder.name
    print("Copying to a relocated Unicode path and testing without developer tools on PATH", flush=True)
    shutil.copytree(folder, relocated)
    report = validation_root / "verification"
    report.mkdir(parents=True)
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "SYSTEMDRIVE", "COMSPEC"}}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env.update(PYTHONHOME=r"Z:\unavailable-python", PYTHONPATH=r"Z:\unavailable-python-packages", CONDA_PREFIX=r"Z:\unavailable-conda", NODE_PATH=r"Z:\unavailable-node", UV_PROJECT_ENVIRONMENT=r"Z:\unavailable-uv")
    test = subprocess.run([str(relocated / "LiveTranslator.exe"), "--self-test", str(report)], cwd=validation_root, env=env, capture_output=True, timeout=90)
    if test.returncode or not (report / "result.json").exists() or json.loads((report / "result.json").read_text(encoding="utf-8"))["result"] != "PASS":
        detail = (report / "result.json").read_text(encoding="utf-8") if (report / "result.json").exists() else test.stderr.decode(errors="replace")[-1500:]
        raise RuntimeError(f"Packaged verification failed; see {report}. Exit={test.returncode}; {detail}")
    files = [{"path": path.relative_to(folder).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())} for path in sorted(folder.rglob("*")) if path.is_file()]
    write_json(folder / "FILE_MANIFEST.json", {"files": files})
    published = ROOT / "dist" / folder.name
    published.parent.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to((ROOT / "artifacts/package-builds").resolve()) or not published.resolve().is_relative_to((ROOT / "dist").resolve()) or published.exists():
        raise RuntimeError("Unsafe or occupied package output path")
    folder.rename(published)
    folder = published
    zip_path = folder.parent / (folder.name + ".zip")
    print("Compressing the verified portable client", flush=True)
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                output.write(path, Path(folder.name) / path.relative_to(folder))
    with zipfile.ZipFile(zip_path) as output:
        if output.testzip() is not None:
            raise RuntimeError("Portable ZIP integrity check failed")
    digest = sha(zip_path.read_bytes())
    zip_path.with_suffix(".zip.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    result = {"result": "PASS", "folder": str(folder), "archive": str(zip_path), "archive_bytes": zip_path.stat().st_size, "archive_sha256": digest, "verification": str(report / "result.json"), "runtime_audit": str(report / "runtime-audit.json"), "files": len(files), "native_audit": native}
    write_json(ROOT / "dist/latest-package.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
