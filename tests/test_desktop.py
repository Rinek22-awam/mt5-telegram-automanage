"""Integration checks for the new command boundary, with fake MT5 only."""
import json
import pytest

from copier.broker import Broker
from copier.config import with_defaults
from copier.journal import Journal
from desktop.control import ControlStore,journal_snapshot
from desktop.engine import DesktopApp
from .fake_mt5 import FakeMT5
from .test_flow import Clock,FakeBot,post,press


def make_desktop(tmp_path):
    cfg=with_defaults({'simbol':{'XAUUSD':'XAUUSDm'}})
    clock=Clock();mt5=FakeMT5(bid=3995);bot=FakeBot()
    journal=Journal(str(tmp_path/'journal.db'),clock=clock)
    app=DesktopApp(cfg,Broker(cfg,mt5_module=mt5),journal,bot,-1001,42,clock=clock,
                   control_path=tmp_path/'control.db')
    client=ControlStore(tmp_path/'control.db',clock=clock)
    return app,client,mt5,bot,clock


def test_desktop_and_telegram_approval_cannot_execute_twice(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);app.publish()
    cid=client.submit('approve',client.snapshot(),1)
    press(app,'ya:1')  # Telegram gets there before the queued GUI click.
    tickets=app.broker.bot_tickets()
    app.tick()
    assert app.broker.bot_tickets()==tickets
    assert client.result(cid)['status']=='failed'
    assert len(app.journal.legs(1))==3


def test_desktop_approval_updates_original_telegram_message(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);app.publish()
    cid=client.submit('approve',client.snapshot(),1)
    app.tick()
    assert client.result(cid)['status']=='done'
    assert len(app.journal.legs(1))==3
    assert bot.edits[-1]['id']==app.journal.get(1)['confirm_msg_id']
    press(app,'ya:1')
    assert len(app.journal.legs(1))==3


def test_cancel_pending_uses_original_guard(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);press(app,'ya:1');app.tick()
    cid=client.submit('cancel',client.snapshot(),1)
    app.tick();app.tick()
    assert client.result(cid)['status']=='done'
    assert not app.broker.bot_tickets()
    assert app.journal.get(1)['status']=='cancelled'


def test_order_filled_after_confirmation_requires_new_confirmation(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);press(app,'ya:1');app.tick()
    cid=client.submit('close',client.snapshot(),1)
    mt5.set_price(3989)
    app.tick()
    assert client.result(cid)['status']=='failed'
    assert app.journal.get(1)['status']=='running'
    assert app.broker.bot_tickets()


@pytest.mark.parametrize('change',['session','expiry','account'])
def test_commands_fail_closed_for_old_session_expiry_or_account(tmp_path,change):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);app.publish()
    cid=client.submit('approve',client.snapshot(),1)
    if change=='session':app.session='new-session'
    elif change=='expiry':clock.t+=100
    else:mt5.currency='USC'
    app.tick()
    assert client.result(cid)['status']=='failed'
    assert not app.broker.bot_tickets()


def test_expired_setup_is_not_executed_by_desktop(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);app.publish()
    clock.t=app.journal.get(1)['confirm_deadline']-10
    app.publish();cid=client.submit('approve',client.snapshot(),1)
    clock.t+=20;app.tick()
    assert client.result(cid)['status']=='failed'
    assert app.journal.get(1)['status']=='expired'


def test_queue_recovers_processing_as_unknown_without_replay(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);app.publish()
    cid=client.submit('approve',client.snapshot(),1)
    assert client.take()['id']==cid
    client.recover()
    assert client.result(cid)['status']=='unknown'
    assert client.take() is None


def test_stale_snapshot_cannot_enqueue(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    app.publish();snapshot=client.snapshot();clock.t+=31
    with pytest.raises(ValueError):client.submit('close_all',snapshot)
    assert client.take() is None


def test_journal_read_does_not_create_missing_database(tmp_path):
    path=tmp_path/'missing.db'
    assert journal_snapshot(path)==([],[])
    assert not path.exists()


def test_reset_with_active_setup_is_refused_by_existing_logic(tmp_path):
    app,client,mt5,bot,clock=make_desktop(tmp_path)
    post(app);press(app,'ya:1');app.tick()
    cid=client.submit('reset',client.snapshot())
    app.tick()
    assert 'Belum bisa reset' in client.result(cid)['result']
    assert len(app.journal.legs(1))==3
