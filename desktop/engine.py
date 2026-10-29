"""Adapter around App. Does not replace gate, executor, guard or Telegram logic."""
import json
import logging
import os
import time
import uuid
from pathlib import Path

from copier.app import App, setup_from_row
from .control import ControlStore, journal_snapshot, scope_for

log = logging.getLogger(__name__)
CALLBACKS = {'approve':'ya', 'reject':'tidak', 'cancel':'batal', 'close':'tutup',
             'cancel_all':'hapuslimit', 'close_all':'tutupsemua', 'reset':'resetjurnal'}


class DesktopTelegram:
    def __init__(self, bot):
        self.bot = bot

    def __getattr__(self, name):
        return getattr(self.bot, name)

    def answer(self, callback_id, *args, **kwargs):
        if str(callback_id).startswith('desktop:'):
            return None
        return self.bot.answer(callback_id, *args, **kwargs)


class DesktopApp(App):
    def __init__(self, *args, control_path, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = DesktopTelegram(self.bot)
        self.control = ControlStore(control_path, self.clock)
        self.control.recover()
        self.session = uuid.uuid4().hex
        self._local_result = None
        self._local_action = False
        self.initial_account = self.account_key()

    def account_key(self):
        acc = self.broker.account()
        if acc is None:
            raise ValueError('MT5 terputus; tidak ada akun tersedia.')
        return f"{acc.login}|{getattr(acc,'server','')}|{acc.currency}"

    def _reply(self, msg_id, text):
        if self._local_action:
            self._local_result = text
            if msg_id is None:
                self.notify(text)
                return
        super()._reply(msg_id, text)

    def notify(self, text, buttons=None):
        if getattr(self, '_local_action', False):
            self._local_result = text
        return super().notify(text, buttons)

    def snapshot(self, online=True):
        account_key = self.account_key()
        if account_key != self.initial_account:
            raise ValueError('Akun MT5 berubah. Matikan bot dan jalankan ulang pada akun yang benar.')
        acc = self.broker.account()
        rows, events = journal_snapshot(self.journal.path)
        floating = 0.0
        for row in rows:
            if row['status']=='awaiting_confirm':
                setup=setup_from_row(row)
                verdict=self.gate.check(setup,recheck=True)
                if verdict.market is not None:
                    plan=self.executor.plan(setup,verdict.market)
                    row['preview']=dict(entry=plan.entry,lot=plan.total_lot,risk=plan.actual_risk,
                                        legs=plan.legs,error=plan.error,reasons=verdict.reasons,
                                        warnings=verdict.warnings)
            for leg in row['legs']:
                if leg['status'] in ('open','pending'):
                    st = self.broker.leg_state(leg['ticket'])
                    leg['live'] = vars(st)
                    if st.state == 'open':
                        floating += st.profit
        return dict(session=self.session, pid=os.getpid(), online=online,
                    account_key=account_key,
                    account=dict(login=acc.login,server=getattr(acc,'server',''),currency=acc.currency,
                                 balance=acc.balance,equity=acc.equity,demo=self.broker.is_demo()),
                    bot_floating=floating, paused=self.journal.get_kv('paused',False),
                    journal=str(Path(self.journal.path).resolve()), setups=rows, events=events)

    def publish(self):
        try:
            self.control.publish(self.snapshot())
        except Exception as exc:
            # Fail closed for local commands, without swallowing the original guard's work.
            self.control.publish(dict(session=self.session,online=False,error=str(exc)))
            log.exception('desktop snapshot failed')

    def tick(self):
        super().tick()  # original guard and expiry, on the same bot thread
        for _ in range(5):
            command = self.control.take()
            if command is None:
                break
            try:
                result = self.dispatch(command)
                self.control.finish(command['id'], 'done', result)
            except Exception as exc:
                log.exception('desktop command failed')
                self.control.finish(command['id'], 'failed', str(exc))
        self.publish()

    def dispatch(self, command):
        if command['session'] != self.session or self.clock() > command['expires']:
            raise ValueError('Perintah basi atau bot sudah restart. Tinjau dan konfirmasi lagi.')
        payload = json.loads(command['payload'])
        action, sid = payload['action'], payload.get('setup_id')
        if action not in (*CALLBACKS, 'pause','resume','shutdown'):
            raise ValueError('Perintah tidak dikenal.')
        snapshot = self.snapshot()
        if payload['account'] != snapshot['account_key']:
            raise ValueError('Akun MT5 berbeda dari akun saat konfirmasi.')
        actual = json.loads(json.dumps(scope_for(snapshot['setups'],action,sid)))
        if payload['scope'] != actual:
            raise ValueError('Status setup berubah. Segarkan dan konfirmasi ulang.')
        row = next((r for r in snapshot['setups'] if r['id']==sid),None)
        if sid is not None and row is None:
            raise ValueError('Setup tidak ditemukan.')
        if action in ('approve','reject') and row['status'] != 'awaiting_confirm':
            raise ValueError('Setup sudah dijawab atau kedaluwarsa.')
        if action=='approve' and row.get('confirm_deadline') and self.clock()>row['confirm_deadline']:
            raise ValueError('Batas waktu persetujuan sudah lewat.')
        if action=='shutdown':
            self.control.finish(command['id'],'done','Bot dihentikan. SL/TP tetap di MT5; penjagaan otomatis berhenti.')
            self.control.publish(dict(snapshot,online=False))
            raise KeyboardInterrupt
        self._local_action, self._local_result = True, None
        try:
            if action in ('pause','resume'):
                self.on_message({'from':{'id':self.admin},'chat':{'id':self.admin},
                                 'text':'/stop' if action=='pause' else '/lanjut'})
            else:
                arg = str(sid) if sid is not None else 'ya'
                self.on_button({'id':'desktop:'+command['id'], 'from':{'id':self.admin},
                                'data':CALLBACKS[action]+':'+arg,
                                'message':{'message_id':row.get('confirm_msg_id')} if row else {}})
            result = self._local_result or 'Perintah selesai. Periksa status terbaru.'
            self.journal.event(sid,'desktop_command',action+': '+result)
            return result
        finally:
            self._local_action = False


def run_bot():
    """Use copier.main unchanged, substituting only its App class in this child process."""
    import copier.app
    from copier.main import main
    original = copier.app.App
    root = Path.cwd()

    class BoundApp(DesktopApp):
        def __init__(self, *a, **kw):
            super().__init__(*a, control_path=root/'data'/'desktop-control.db', **kw)

        def run(self):
            self.publish()
            try:
                super().run()
            finally:
                try:
                    self.control.publish(dict(session=self.session,online=False))
                finally:
                    self.control.close()

    copier.app.App = BoundApp
    try:
        main()
    finally:
        copier.app.App = original
