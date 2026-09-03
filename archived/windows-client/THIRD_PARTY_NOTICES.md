# Third-party notices

The portable client includes unmodified third-party Python packages and native libraries. Exact versions, package metadata and the license files shipped by each wheel are included under `_internal/*-dist-info/`. Additional license texts required by the frozen runtime are in `licenses/`.

The direct runtime dependencies are certifi, HTTPX, NumPy, PyAudioWPatch, PySide6 Essentials, Python-SoXR and websockets. Their transitive runtime dependencies are also represented by bundled distribution metadata.

PySide6 Essentials and Shiboken6 are Qt for Python components. This project uses them under the LGPL option stated in their package metadata. The libraries remain separate DLLs in the onedir distribution. `licenses/LGPL-3.0-only.txt` and `licenses/GPL-3.0-only.txt` contain the applicable terms. Corresponding source information is available from the [Qt for Python licensing page](https://doc.qt.io/qtforpython-6/licenses.html) and the [Qt source archive](https://download.qt.io/archive/qt/).

Python-SoXR and libsoxr are distributed under LGPL terms described in the bundled `soxr-*.dist-info/licenses/` files. Other packages retain their own BSD, MIT, Apache, MPL or composite notices in their bundled metadata directories.

The bundled CPython runtime is covered by `licenses/PSF-LICENSE.txt`. The PyInstaller bootloader notice is in `licenses/PYINSTALLER-COPYING.txt`.

This file is a directory guide, not a replacement for those license texts.
