"""Ship the small Windows WebView2 backend, without a second Chromium runtime."""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths

_, package_path = get_package_paths('PySide6')
root = Path(package_path)
hiddenimports = ['PySide6.QtCore', 'PySide6.QtGui']
binaries = []
if sys.platform == 'win32':
    binaries = [
        (str(root / 'Qt6WebView.dll'), 'PySide6'),
        (str(root / 'plugins/webview/qtwebview_webview2.dll'), 'PySide6/plugins/webview'),
    ]
