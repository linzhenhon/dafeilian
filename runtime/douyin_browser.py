"""Embed the official Douyin website using Windows' Edge WebView2 runtime."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

DOUYIN_HOME = 'https://www.douyin.com/'
OPEN_LOGIN_SCRIPT = """(function(){
  var items = document.querySelectorAll('[data-e2e="top-login-button"],button,[role="button"],a');
  var button = Array.from(items).find(function(item){
    return item.getClientRects().length && item.textContent.trim() === '登录';
  });
  if (button) { button.click(); return 'opened'; }
  return 'waiting';
})()"""


def browser_profile_path() -> Path:
    try:
        from .layout_store import default_layout_path
    except ImportError:
        from layout_store import default_layout_path
    return default_layout_path().parent / 'douyin-browser'


class DouyinBrowser:
    def __init__(self, parent: Any, on_status, on_close) -> None:
        if sys.platform != 'win32':
            raise RuntimeError('内嵌抖音目前支持 Windows；请使用本地视频模式。')
        try:
            from PySide6.QtWebView import QWebView, QWebViewSettings, QtWebView
        except ImportError as error:
            raise RuntimeError('内嵌抖音需要 PySide6 6.11 及以上版本。') from error
        from PySide6.QtCore import QTimer, QUrl, Qt
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

        profile = browser_profile_path()
        profile.mkdir(parents=True, exist_ok=True)
        # These variables apply to this Helper and its WebView2 child processes only.
        os.environ['QT_WEBVIEW_PLUGIN'] = 'webview2'
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(profile.resolve())
        QtWebView.initialize()
        self.on_status = on_status
        self.active = False
        self.ready = False
        self.resume_url = DOUYIN_HOME
        self.login_attempts = 0
        self.page = QWebView()
        settings = self.page.settings()
        settings.setAttribute(QWebViewSettings.WebAttribute.JavaScriptEnabled, True)
        settings.setAttribute(QWebViewSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebViewSettings.WebAttribute.AllowFileAccess, False)
        settings.setAttribute(QWebViewSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        self.widget = QWidget(parent)
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.back_button = QPushButton('返回')
        self.back_button.clicked.connect(self.page.goBack)
        self.home_button = QPushButton('抖音首页')
        self.home_button.clicked.connect(self.home)
        self.login_button = QPushButton('扫码登录')
        self.login_button.clicked.connect(self.open_login)
        self.reload_button = QPushButton('刷新')
        self.reload_button.clicked.connect(self.page.reload)
        self.clear_button = QPushButton('清除本机登录')
        self.clear_button.clicked.connect(self.clear_login)
        self.close_button = QPushButton('收起视频')
        self.close_button.clicked.connect(on_close)
        for button in (self.back_button, self.home_button, self.login_button, self.reload_button, self.clear_button):
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.address = QLabel('抖音官方网站 · www.douyin.com')
        self.address.setTextFormat(Qt.TextFormat.PlainText)
        self.address.setStyleSheet('color: #A9BBC3; font-size: 11px;')
        layout.addWidget(self.address)
        self.container = QWidget.createWindowContainer(self.page, self.widget)
        self.container.setMinimumSize(360, 240)
        layout.addWidget(self.container, 1)
        self.hint = QLabel('点击「扫码登录」，在抖音官方页面用手机抖音扫码并确认；登录后可查看自己的个人主页和关注内容。')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color: #9AB5BC; font-size: 12px;')
        layout.addWidget(self.hint)
        self.page.loadingChanged.connect(self._loading_changed)
        self.page.urlChanged.connect(self._url_changed)
        self.login_timer = QTimer(self.widget)
        self.login_timer.setSingleShot(True)
        self.login_timer.timeout.connect(self._click_login)

    def resume(self) -> None:
        from PySide6.QtCore import QUrl

        if self.active:
            return
        self.active = True
        self.widget.show()
        self.page.setUrl(QUrl(self.resume_url))

    def suspend(self) -> None:
        from PySide6.QtCore import QUrl

        if not self.active:
            return
        current = self.page.url()
        if current.scheme() == 'https' and current.host() == 'www.douyin.com':
            self.resume_url = current.toString()
        self.active = self.ready = False
        self.login_timer.stop()
        self.login_attempts = 0
        # An empty document stops playback and timers while leaving browser login storage intact.
        self.page.stop()
        self.page.setUrl(QUrl('about:blank'))
        self.widget.hide()

    def home(self) -> None:
        from PySide6.QtCore import QUrl

        self.resume_url = DOUYIN_HOME
        self.page.setUrl(QUrl(DOUYIN_HOME))

    def open_login(self) -> None:
        self.login_attempts = 12
        self.on_status('请在抖音官方页面扫码并用手机确认；登录后可在网页中查看自己的个人主页。')
        if self.ready and self.page.url().host() == 'www.douyin.com':
            self._click_login()
        else:
            self.home()

    def _click_login(self) -> None:
        if not self.active or not self.login_attempts or self.page.url().host() != 'www.douyin.com':
            return
        self.login_attempts -= 1

        def clicked(result):
            if not self.active:
                return
            if result == 'opened':
                self.login_attempts = 0
            elif self.login_attempts:
                self.login_timer.start(400)

        # This clicks the website's ordinary login button; QR generation and authentication stay on Douyin.
        self.page.runJavaScript(OPEN_LOGIN_SCRIPT, clicked)

    def clear_login(self) -> None:
        self.login_timer.stop()
        self.login_attempts = 0
        self.page.deleteAllCookies()

        def cleared(_result):
            self.on_status('已清除本机浏览器 Cookie；可在抖音页面重新登录。')
            self.home()

        if self.page.url().host() == 'www.douyin.com':
            self.page.runJavaScript('localStorage.clear(); sessionStorage.clear();', cleared)
        else:
            cleared(None)

    def _url_changed(self, url) -> None:
        if self.active and url.scheme() == 'https':
            self.address.setText('当前网页 · https://' + url.host())

    def _loading_changed(self, info) -> None:
        if not self.active:
            return
        from PySide6.QtWebView import QWebViewLoadingInfo

        status = info.status()
        if status == QWebViewLoadingInfo.LoadStatus.Started:
            self.ready = False
            self.on_status('正在打开抖音官方网页…')
        elif status == QWebViewLoadingInfo.LoadStatus.Succeeded:
            self.ready = True
            self.on_status('抖音官方网页 · 点击「扫码登录」，登录后可在网页中查看自己的个人主页。')
            if self.login_attempts:
                self.login_timer.start(400)
        elif status == QWebViewLoadingInfo.LoadStatus.Failed:
            self.ready = False
            self.on_status('抖音页面暂时未能加载，请检查网络后点击「刷新」。')

    def dispose(self) -> None:
        self.suspend()
        self.page.stop()
