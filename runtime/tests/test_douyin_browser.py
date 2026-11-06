from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest

try:
    from PySide6.QtWebView import QWebView
except ImportError:
    QWebView = None


@unittest.skipUnless(sys.platform == 'win32' and QWebView is not None, 'Native Douyin browser requires Windows and Qt 6.11')
class DouyinBrowserTests(unittest.TestCase):
    def test_official_login_button_logic_native_video_and_local_login_persistence(self):
        runtime_roots = [Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/EdgeWebView/Application',
                         Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Microsoft/EdgeWebView/Application']
        if not any(root.is_dir() for root in runtime_roots):
            self.skipTest('Windows WebView2 runtime is not installed')

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                content = b'''<!doctype html><title>Native browser test</title>
                  <button data-e2e="top-login-button" onclick="document.getElementById('state').textContent='login-opened'">\xe7\x99\xbb\xe5\xbd\x95</button>
                  <div id="state">ready</div>'''
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                try:
                    self.wfile.write(content)
                except ConnectionError:
                    pass  # Switching modes deliberately cancels in-flight browser requests.

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                environment = {**os.environ, 'DSH_DAFEIYU_LAYOUT_PATH': str(Path(directory) / 'layout.json')}
                url = f'http://127.0.0.1:{server.server_port}/'
                for mode in ('write', 'read', 'clear', 'video'):
                    result = subprocess.run([sys.executable, '-m', 'runtime.tests.douyin_probe', url, mode],
                                            env=environment, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, mode + ': ' + result.stdout + result.stderr)
                self.assertTrue((Path(directory) / 'douyin-browser').is_dir())
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
