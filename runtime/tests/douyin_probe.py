"""Opt-in native browser checks against a loopback-only test site."""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


def main():
    url, mode = sys.argv[1:3]
    if urlparse(url).hostname != '127.0.0.1':
        raise ValueError('Browser persistence probes only run on the local test server')
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    import runtime.douyin_browser as browser_module

    browser_module.DOUYIN_HOME = url
    app = QApplication([])
    if mode == 'video':
        return check_video_mode(app, url)
    parent = QWidget()
    parent.resize(850, 600)
    status = []
    browser = browser_module.DouyinBrowser(parent, status.append, app.quit)
    QVBoxLayout(parent).addWidget(browser.widget)
    result = {'ok': False}
    started = False

    def complete(ok):
        result['ok'] = bool(ok)
        browser.dispose()
        app.quit()

    def readback(value):
        try:
            data = json.loads(value)
            if mode == 'read':
                complete(data['cookie'] and data['storage'] == 'kept')
            elif mode == 'clear':
                complete(not data['cookie'])
            else:
                complete(data['clicked'] == 'login-opened' and data['h264'] in ('probably', 'maybe'))
        except (ValueError, KeyError, TypeError):
            complete(False)

    def loaded(info):
        nonlocal started
        from PySide6.QtWebView import QWebViewLoadingInfo
        if started or info.status() != QWebViewLoadingInfo.LoadStatus.Succeeded or browser.page.url().host() != '127.0.0.1':
            return
        started = True
        if mode == 'write':
            script = browser_module.OPEN_LOGIN_SCRIPT + "; document.cookie='pet_test=kept; Max-Age=3600; Path=/'; localStorage.setItem('pet_test','kept'); JSON.stringify({clicked:document.getElementById('state').textContent,h264:document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')});"
            browser.page.runJavaScript(script, readback)
        elif mode == 'read':
            browser.page.runJavaScript("JSON.stringify({cookie:document.cookie.includes('pet_test=kept'),storage:localStorage.getItem('pet_test')})", readback)
        else:
            browser.clear_login()
            QTimer.singleShot(400, lambda: browser.page.runJavaScript("JSON.stringify({cookie:document.cookie.includes('pet_test=kept')})", readback))

    browser.page.loadingChanged.connect(loaded)
    parent.show()
    browser.resume()
    QTimer.singleShot(10000, app.quit)
    app.exec()
    print('Browser probe ' + mode + ': ' + ('PASS' if result['ok'] else 'FAIL'), flush=True)
    return 0 if result['ok'] else 1


def check_video_mode(app, url):
    from types import SimpleNamespace
    from PySide6.QtCore import QRect, QTimer
    from PySide6.QtWidgets import QWidget
    from runtime.video_mode import VideoMode

    owner = QWidget()
    owner.watching_video = owner.chess_mode = False
    owner.voice_mode = 'off'
    owner.novel_reader = SimpleNamespace(dialog=None, state={})
    owner.task_dialog = None
    owner.pet_x, owner.pet_y = 1100, 500
    owner._screen_geometry_at = lambda _x, _y: QRect(0, 0, 1920, 1040)
    owner._pet_size = lambda: (412, 344)
    owner._sync_bubble_size = lambda: None
    owner._show_overlay = lambda *_args: None
    mode = VideoMode(owner)
    result = {'ok': False}
    owner.show()
    if not mode.enter() or not mode.show_douyin():
        return 1

    def finished(info):
        from PySide6.QtWebView import QWebViewLoadingInfo
        if info.status() != QWebViewLoadingInfo.LoadStatus.Succeeded or mode.browser.page.url().host() != '127.0.0.1':
            return
        valid = (mode.source == 'douyin' and not mode.local_panel.isVisible()
                 and mode.browser.widget.isVisible() and all(not shortcut.isEnabled() for shortcut in mode.shortcuts))
        original = mode.browser
        mode.use_local()
        valid = valid and mode.local_panel.isVisible() and not original.active and all(shortcut.isEnabled() for shortcut in mode.shortcuts)
        mode.show_douyin()
        valid = valid and mode.browser is original
        mode.leave()
        result['ok'] = valid and not owner.watching_video and not original.active
        mode.dispose()
        app.quit()

    mode.browser.page.loadingChanged.connect(finished)
    QTimer.singleShot(10000, app.quit)
    app.exec()
    mode.dispose()
    print('Video/browser mode switching: ' + ('PASS' if result['ok'] else 'FAIL'), flush=True)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
