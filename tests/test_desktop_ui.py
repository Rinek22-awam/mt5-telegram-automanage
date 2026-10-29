"""Optional Qt checks. The console-only installation can still run the original suite."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import shutil
import threading
import time
from types import SimpleNamespace
import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from desktop.ui import MainWindow
from panel.settings import SECTIONS


@pytest.fixture
def window(tmp_path):
    app=QApplication.instance() or QApplication([])
    shutil.copy('config.yaml',tmp_path/'config.yaml')
    args=SimpleNamespace(demo=True,smoke=True)
    win=MainWindow(tmp_path,args)
    yield win
    win.closing=True;win.close()


def test_all_menu_setting_fields_have_gui_controls(window):
    for i,(_,items) in enumerate(SECTIONS):
        window.setting_category(i)
        assert len(window.fields)==len(items)
        assert [f[0] for f in window.fields]==[f[0] for f in items]
    window.setting_category(len(SECTIONS))
    assert window.symbol_table.rowCount()>0


def test_preview_does_not_create_live_data_or_enable_trading(window):
    assert not (window.root/'data').exists()
    assert not any(b.isEnabled() for b in window.global_actions.values())
    before=(window.root/'config.yaml').read_bytes()
    window.info=lambda *args:None
    window.start('bot');window.start('reader');window.trade('approve',43)
    assert not window.children
    assert (window.root/'config.yaml').read_bytes()==before


def test_settings_reject_external_change_without_overwrite(window):
    window.demo=False
    before=window.settings.load_text()
    (window.root/'config.yaml').write_text(before+'\n# external edit\n',encoding='utf-8')
    window.info=lambda *args:None
    assert not window.can_edit()
    assert '# external edit' in window.settings.load_text()


def test_table_filters_keep_mixed_pending_setup_visible(window):
    running=next(r for r in window.rows if r['status']=='running')
    running['legs'][0]['status']='pending'
    window.tabs.setCurrentIndex(1)
    assert running in window.filtered_rows()
    window.tabs.setCurrentIndex(2)
    assert running in window.filtered_rows()


def test_unchanged_refresh_preserves_keyboard_focus_and_text_selection(window):
    window.table.setCurrentCell(0,2)
    cursor=window.detail.textCursor();cursor.setPosition(0)
    cursor.setPosition(5,cursor.MoveMode.KeepAnchor);window.detail.setTextCursor(cursor)
    selected=window.detail.textCursor().selectedText()
    for _ in range(3):window.refresh()
    assert window.table.currentColumn()==2
    assert window.detail.textCursor().selectedText()==selected


def test_slow_disk_read_does_not_block_qt_events(window,monkeypatch):
    window.timer.stop();window.demo=False
    entered,release=threading.Event(),threading.Event()
    original=window.reader.poll
    calls=[]
    def slow(*args):
        calls.append(1);entered.set();release.wait(2)
        return original(*args)
    monkeypatch.setattr(window.reader,'poll',slow)
    try:
        started=time.monotonic();window.refresh()
        assert time.monotonic()-started<.25
        assert entered.wait(.5)
        for _ in range(5):window.refresh()
        heartbeat=[];QTimer.singleShot(0,lambda:heartbeat.append(True))
        QApplication.processEvents()
        assert heartbeat==[True]
        assert len(calls)==1  # No buildup of overlapping polling jobs.
    finally:
        release.set()
        until=time.monotonic()+3
        while window._polling and time.monotonic()<until:
            QApplication.processEvents();window.poll_ready();time.sleep(.001)
