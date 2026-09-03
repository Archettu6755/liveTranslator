from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

spec_dir = Path(globals()["SPECPATH"])
project_dir = spec_dir.parent

pyaudio_datas, pyaudio_binaries, pyaudio_hiddenimports = collect_all("pyaudiowpatch")
certifi_datas = collect_data_files("certifi")
runtime_metadata = copy_metadata("live-translator-windows", recursive=True)

analysis = Analysis(
    [str(spec_dir / "windows_entry.py")],
    pathex=[str(project_dir / "src")],
    binaries=pyaudio_binaries,
    datas=[
        *pyaudio_datas,
        *certifi_datas,
        *runtime_metadata,
    ],
    hiddenimports=pyaudio_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LiveTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LiveTranslator",
)
