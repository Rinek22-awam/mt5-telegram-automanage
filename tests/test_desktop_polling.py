"""Regression checks for nonblocking dashboard polling and lock probing."""
import json
import shutil
import socket
import time

from copier.single import claim
from desktop.control import ControlStore
from desktop.polling import DashboardReader,port_in_use


def test_repeated_status_checks_do_not_fill_listener_backlog():
    lock=claim(0)
    assert lock is not None
    try:
        port=lock.getsockname()[1]
        for _ in range(100):
            assert port_in_use(port)
        # A real connection must still work after all 100 checks.
        with socket.create_connection(('127.0.0.1',port),timeout=.5):pass
    finally:lock.close()
    assert not port_in_use(port)


def test_poll_reads_results_without_claiming_commands(tmp_path,monkeypatch):
    shutil.copy('config.yaml',tmp_path/'config.yaml')
    store=ControlStore(tmp_path/'data'/'desktop-control.db')
    state=dict(online=True,session='session',account_key='demo',setups=[],events=[])
    store.publish(state)
    cid=store.submit('close_all',store.snapshot())
    (tmp_path/'data'/'desktop-reader.json').write_text(json.dumps(dict(online=True,heartbeat=time.time())),encoding='utf-8')
    def no_probe(_):raise AssertionError('A fresh heartbeat should avoid any port probe')
    monkeypatch.setattr('desktop.polling.port_in_use',no_probe)
    result=DashboardReader(tmp_path,store.path).poll([cid])
    assert result['results'][cid]['status']=='queued'
    assert store.result(cid)['status']=='queued'
    assert result['bot_on'] and result['reader_on']
    store.close()


def test_log_tail_is_cached_and_refreshes_when_file_changes(tmp_path,monkeypatch):
    shutil.copy('config.yaml',tmp_path/'config.yaml')
    monkeypatch.setattr('desktop.polling.port_in_use',lambda _:False)
    (tmp_path/'logs').mkdir()
    log=tmp_path/'logs'/'bot.log';log.write_text('first',encoding='utf-8')
    reader=DashboardReader(tmp_path,tmp_path/'missing.db')
    assert reader.poll(log_index=1)['log_text']=='first'
    assert reader.poll(log_index=1)['log_text']=='first'
    log.write_text('second line',encoding='utf-8')
    assert reader.poll(log_index=1)['log_text']=='second line'
    assert not (tmp_path/'missing.db').exists()
