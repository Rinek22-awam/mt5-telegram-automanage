"""Qt Windows dashboard. All trading commands go through desktop.engine."""
import codecs
import copy
import json
import os
import queue
import subprocess
import sys
import tempfile
import time
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt,QTimer,QProcess,QProcessEnvironment
from PySide6.QtGui import QColor,QFont,QFontDatabase,QIcon,QPainter,QPixmap,QAction
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QFrame,QLabel,QPushButton,
    QVBoxLayout,QHBoxLayout,QGridLayout,QStackedWidget,QListWidget,QTabBar,
    QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QSplitter,QScrollArea,
    QMessageBox,QLineEdit,QComboBox,QFormLayout,QInputDialog,QFileDialog,QDialog,
    QPlainTextEdit,QCheckBox,QSystemTrayIcon,QMenu)

from copier.config import load_config,DEFAULTS
from copier.single import claim,BOT_PORT,READER_PORT
from panel.settings import Settings,SECTIONS,parse,show,_get
from panel.yamledit import set_value,add_value,remove_value
from .control import ControlStore,journal_snapshot
from .runtime import child_command,reader_state
from .theme import STYLE
from .polling import DashboardReader, port_in_use as is_running

STATUS={'awaiting_confirm':'Menunggu persetujuan','pending':'Pending','running':'Berjalan',
        'done':'Selesai','cancelled':'Dibatalkan','expired':'Kedaluwarsa',
        'rejected':'Ditolak sistem','declined':'Ditolak user'}


def label(text='',name=None):
    w=QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(True)
    return w


def button(text,callback,primary=False,danger=False):
    b=QPushButton(text)
    b.setProperty('primary',primary)
    b.setProperty('danger',danger)
    b.clicked.connect(callback)
    return b


def panel():
    w=QFrame();w.setObjectName('panel')
    layout=QVBoxLayout(w);layout.setContentsMargins(18,18,18,18);layout.setSpacing(12)
    return w,layout


def stamp(value):
    return datetime.fromtimestamp(value).strftime('%d/%m %H:%M:%S') if value else '—'


def icon():
    pix=QPixmap(64,64);pix.fill(QColor('#3977e6'))
    painter=QPainter(pix);painter.setPen(QColor('white'));painter.setFont(QFont('Segoe UI',20,QFont.Weight.DemiBold))
    painter.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'TM');painter.end()
    return QIcon(pix)


class UtilityDialog(QDialog):
    """Keep existing utility workflows, including local interactive login, in one window."""
    def __init__(self,owner,task,title,file=None):
        super().__init__(owner)
        self.owner=owner;self.setWindowTitle(title);self.resize(850,610)
        self.redactions=[];self.decoder=codecs.getincrementaldecoder('utf-8')('replace')
        layout=QVBoxLayout(self)
        layout.addWidget(label(title,'heading'))
        layout.addWidget(label('Utilitas lokal dari menu lama. Jawab permintaan di kolom bawah; Enter kosong juga bisa.','muted'))
        self.output=QPlainTextEdit();self.output.setReadOnly(True);layout.addWidget(self.output,1)
        row=QHBoxLayout();self.entry=QLineEdit();self.entry.setPlaceholderText('Jawaban / kode login — hanya dikirim ke program lokal')
        self.entry.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(self.entry,1);row.addWidget(button('Kirim / Enter',self.send));layout.addLayout(row)
        visible=QCheckBox('Tampilkan teks yang diketik');visible.toggled.connect(lambda yes:self.entry.setEchoMode(QLineEdit.EchoMode.Normal if yes else QLineEdit.EchoMode.Password))
        layout.addWidget(visible)
        self.close_button=button('Tutup',self.close);self.close_button.setEnabled(False);layout.addWidget(self.close_button)
        self.proc=QProcess(self);self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env=QProcessEnvironment.systemEnvironment();env.insert('PYTHONIOENCODING','utf-8');env.insert('PYTHONUNBUFFERED','1')
        self.proc.setProcessEnvironment(env);self.proc.setWorkingDirectory(str(owner.root))
        self.proc.readyReadStandardOutput.connect(self.read)
        self.proc.finished.connect(self.finished)
        self.proc.errorOccurred.connect(self.error)
        self.entry.returnPressed.connect(self.send)
        argv=child_command(owner.root,'utility','--task',task)
        if file:
            argv+=['--file',file]
        self.proc.start(argv[0],argv[1:])

    def read(self):
        text=self.decoder.decode(bytes(self.proc.readAllStandardOutput()))
        # Never render the project's credential values or local input back into chat/UI logs.
        text=self.owner.redact(text)
        for secret in self.redactions:
            text=text.replace(secret,'••••')
        cursor=self.output.textCursor();cursor.movePosition(cursor.MoveOperation.End);cursor.insertText(text)
        self.output.setTextCursor(cursor);self.output.ensureCursorVisible()

    def send(self):
        value=self.entry.text()
        if len(value)>=4:
            self.redactions.append(value)
        self.proc.write((value+'\n').encode('utf-8'));self.entry.clear()

    def finished(self,code,_status):
        self.read();self.output.appendPlainText(f'\nProgram selesai · kode {code}')
        self.entry.setEnabled(False);self.close_button.setEnabled(True)
        self.owner.reload_settings()

    def error(self,_error):
        self.output.appendPlainText('Program tidak dapat dimulai: '+self.proc.errorString())
        self.close_button.setEnabled(True)

    def closeEvent(self,event):
        if self.proc.state()!=QProcess.ProcessState.NotRunning:
            QMessageBox.information(self,'Utilitas masih berjalan','Selesaikan permintaan program dahulu. Kolom kosong + Kirim dapat dipakai untuk kembali.')
            event.ignore()
        else:
            event.accept()


class MainWindow(QMainWindow):
    def __init__(self,root,args):
        super().__init__()
        self.root=Path(root);self.args=args;self.demo=args.demo;self.snapshot={};self.rows=[];self.events=[]
        self.pending={};self.children={};self.closing=False;self.selected=None;self.current_setting=0
        self.temp=tempfile.TemporaryDirectory(prefix='trading-manager-preview-') if self.demo else None
        self.store=ControlStore(Path(self.temp.name if self.temp else self.root/'data')/'desktop-control.db',timeout=.1)
        self.reader=DashboardReader(self.root,self.store.path)
        self._poll_queue=queue.SimpleQueue();self._polling=False
        self._table_signature=None;self._log_text='Memuat log…';self._log_index=None
        self.settings=Settings(str(self.root/'config.yaml'),lambda:is_running(BOT_PORT))
        self.secrets=[]
        if not self.demo:
            from dotenv import dotenv_values
            env=dotenv_values(self.root/'.env')
            self.secrets=[str(v) for k,v in env.items() if v and k in ('TG_BOT_TOKEN','TG_API_ID','TG_API_HASH','MT5_PASSWORD')]
        self.setWindowTitle('Trading Manager'+(' — PRATINJAU' if self.demo else ''))
        self.setWindowIcon(icon());self.resize(1280,900);self.setMinimumSize(980,680)
        central=QWidget();self.setCentralWidget(central);base=QHBoxLayout(central);base.setContentsMargins(0,0,0,0);base.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(205);nav=QVBoxLayout(side);nav.setContentsMargins(16,22,16,22);nav.setSpacing(10)
        brand=label('TM  Trading Manager');brand.setFont(QFont('Segoe UI',15,QFont.Weight.DemiBold));nav.addWidget(brand)
        nav.addWidget(label('Local workspace','muted'));nav.addSpacing(25)
        self.nav_buttons=[]
        for i,title in enumerate(['Dashboard','Pengaturan','Utilitas','Aktivitas','Bot & pembaca']):
            b=button(title,lambda _=False,index=i:self.navigate(index));b.setCheckable(True);nav.addWidget(b);self.nav_buttons.append(b)
        nav.addStretch();self.account_label=label('Akun belum terhubung','muted');nav.addWidget(self.account_label)
        nav.addWidget(button('Buka folder proyek',lambda:self.open_path(self.root)))
        nav.addWidget(button('Keluar aplikasi',self.exit_app))
        base.addWidget(side)
        right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(28,22,28,16);rl.setSpacing(15)
        self.heading=label('Kontrol trading','heading');rl.addWidget(self.heading)
        self.status=label('','muted');rl.addWidget(self.status)
        self.notice=label('','badge');rl.addWidget(self.notice)
        self.pages=QStackedWidget();rl.addWidget(self.pages,1)
        self.footer=label('','muted');rl.addWidget(self.footer)
        base.addWidget(right,1)
        self.build_dashboard();self.build_settings();self.build_tools();self.build_activity();self.build_system()
        self.tray=None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip('Trading Manager')
            menu=QMenu();menu.addAction('Tampilkan',self.restore);menu.addAction('Keluar aplikasi',self.exit_app)
            self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.restore() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None);self.tray.show()
        self.navigate(0)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(1800)
        self.result_timer=QTimer(self);self.result_timer.timeout.connect(self.poll_ready);self.result_timer.start(100)
        self.refresh()

    def redact(self,text):
        for value in self.secrets:
            text=text.replace(value,'••••')
        return text

    def navigate(self,index):
        self.pages.setCurrentIndex(index)
        self.heading.setText(['Kontrol trading','Pengaturan lengkap','Utilitas','Aktivitas sistem','Bot & pembaca'][index])
        for i,b in enumerate(self.nav_buttons):
            b.setChecked(i==index)
        if hasattr(self,'timer') and index==3:
            self.refresh_activity();self.refresh()

    def add_page(self):
        w=QWidget();layout=QVBoxLayout(w);layout.setContentsMargins(0,0,0,0);layout.setSpacing(15);self.pages.addWidget(w)
        return layout

    def build_dashboard(self):
        layout=self.add_page();metrics=QHBoxLayout();self.metrics=[]
        for title in ['Saldo','Equity','Floating posisi bot']:
            box,bl=panel();bl.addWidget(label(title,'muted'));val=label('—','metric');bl.addWidget(val);metrics.addWidget(box,1);self.metrics.append(val)
        layout.addLayout(metrics)
        self.tabs=QTabBar();self.tabs.setExpanding(False)
        for title in ['Persetujuan','Pending order','Berjalan','Riwayat']:
            self.tabs.addTab(title)
        self.tabs.currentChanged.connect(self.refresh_table);layout.addWidget(self.tabs)
        splitter=QSplitter();self.table=QTableWidget(0,5)
        self.table.setHorizontalHeaderLabels(['Setup / pair','Arah','Entry','Lot / hasil','Status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide();self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        splitter.addWidget(self.table)
        detail,dl=panel();detail.setMinimumWidth(275);detail.setMaximumWidth(390)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);dl.addWidget(self.detail,1)
        self.actions={}
        for key,title,primary,danger in [('approve','Setujui setup',True,False),('reject','Tolak setup',False,False),('cancel','Batalkan pending setup',False,True),('close','Tutup seluruh setup',False,True)]:
            b=button(title,lambda _=False,k=key:self.trade(k,self.selected),primary,danger);self.actions[key]=b;dl.addWidget(b)
        splitter.addWidget(detail);splitter.setSizes([640,340]);layout.addWidget(splitter,1)
        controls=QHBoxLayout();self.global_actions={}
        for key,title,danger in [('pause','Jeda setup baru',False),('resume','Lanjutkan setup baru',False),('cancel_all','Batalkan semua pending',False),('close_all','Tutup semua',True)]:
            b=button(title,lambda _=False,k=key:self.trade(k),danger=danger);controls.addWidget(b);self.global_actions[key]=b
        layout.addLayout(controls)
        self.recent=label('Belum ada aktivitas.','muted');layout.addWidget(self.recent)

    def build_settings(self):
        layout=self.add_page();layout.addWidget(label('Menggunakan validasi dan penyimpanan yang sama dengan menu lama. Perubahan berlaku setelah restart.','muted'))
        row=QHBoxLayout();self.categories=QListWidget();self.categories.setMaximumWidth(220)
        for title,_ in SECTIONS:
            self.categories.addItem(title)
        self.categories.addItem('Nama simbol broker');self.categories.addItem('Aplikasi')
        row.addWidget(self.categories)
        self.form_scroll=QScrollArea();self.form_scroll.setWidgetResizable(True);row.addWidget(self.form_scroll,1)
        layout.addLayout(row,1);self.categories.currentRowChanged.connect(self.setting_category);self.categories.setCurrentRow(0)

    def reload_settings(self):
        if hasattr(self,'categories'):
            self.setting_category(self.categories.currentRow())

    def setting_category(self,index):
        if index<0:
            return
        self.current_setting=index
        box,layout=panel();self.form_scroll.setWidget(box);self.fields=[]
        try:
            self.baseline=self.settings.load_text();cfg=self.settings.cfg()
        except Exception as exc:
            layout.addWidget(label('Konfigurasi tidak terbaca: '+str(exc)));return
        if index<len(SECTIONS):
            title,items=SECTIONS[index];layout.addWidget(label(title,'heading'))
            form=QFormLayout();form.setVerticalSpacing(15);form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for path,title,kind,options,note in items:
                value=_get(cfg,path)
                if kind in ('choice','bool'):
                    w=QComboBox();w.addItems(options if kind=='choice' else ['ya','tidak']);w.setCurrentText(str(value) if kind=='choice' else ('ya' if value else 'tidak'))
                else:
                    w=QLineEdit('' if value is None else ' '.join(map(str,value)) if kind=='split' else str(value))
                w.setMinimumWidth(210);w.setToolTip(note);form.addRow(title,w);self.fields.append((path,kind,options,w))
            layout.addLayout(form)
            if any(it[2]=='split' for it in items):
                layout.addWidget(label('Pisahkan angka dengan spasi. Nilai 0 = tanpa lot di TP tersebut.','muted'))
                layout.addWidget(button('Pulihkan seluruh pembagian partial ke bawaan',self.reset_splits))
            layout.addStretch();layout.addWidget(button('Simpan perubahan',self.save_settings,True))
        elif index==len(SECTIONS):
            layout.addWidget(label('Nama simbol broker','heading'))
            self.symbol_table=QTableWidget(0,2);self.symbol_table.setHorizontalHeaderLabels(['Pair di setup','Nama persis di MT5'])
            self.symbol_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.symbol_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.symbol_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for k,v in cfg['simbol'].items():
                row=self.symbol_table.rowCount();self.symbol_table.insertRow(row);self.symbol_table.setItem(row,0,QTableWidgetItem(k));self.symbol_table.setItem(row,1,QTableWidgetItem(v))
            layout.addWidget(self.symbol_table)
            row=QHBoxLayout()
            for title,fn in [('Tambah',lambda:self.edit_symbol(True)),('Edit',self.edit_symbol),('Hapus',self.delete_symbol),('Cocokkan broker',lambda:self.utility('match'))]:
                row.addWidget(button(title,fn))
            layout.addLayout(row)
        else:
            layout.addWidget(label('Perilaku aplikasi','heading'))
            layout.addWidget(label('Tema: gelap netral dengan aksen biru.\n\nTutup jendela: sembunyikan ke tray.\nKeluar aplikasi: program trading tetap berjalan kecuali kamu menghentikannya dari halaman Bot & pembaca.\n\nLokasi data: '+str(self.root)))
            layout.addWidget(button('Buka folder data',lambda:self.open_path(self.root/'data')));layout.addStretch()

    def can_edit(self):
        if self.demo:
            self.info('Mode pratinjau: tidak ada konfigurasi yang diubah.');return False
        if self.settings.load_text()!=self.baseline:
            self.reload_settings();self.info('Config berubah di luar aplikasi. Form dimuat ulang; silakan tinjau lagi.');return False
        return True

    def save_settings(self):
        try:
            if not self.can_edit():return
            text=self.baseline
            for path,kind,options,w in self.fields:
                raw=w.currentText() if isinstance(w,QComboBox) else w.text()
                value=parse(kind,options,raw)
                if path==('akun','hanya_demo') and not value and self.settings.cfg()['akun']['hanya_demo']:
                    typed,ok=QInputDialog.getText(self,'Izinkan akun REAL?','Ketik REAL untuk mematikan pembatas akun demo:')
                    if not ok or typed!='REAL':return
                text=set_value(text,path,value)
            if not self.can_edit():return
            self.settings.save(text);self.reload_settings();self.info('Tersimpan. Restart bot/pembaca agar perubahan berlaku.')
        except Exception as exc:self.info(str(exc),True)

    def reset_splits(self):
        if not self.confirm('Pulihkan pembagian partial?','Semua pembagian 1–5 TP kembali ke bawaan.'):return
        if self.can_edit():
            text=self.baseline
            for n,split in DEFAULTS['tp']['bagi'].items():text=set_value(text,('tp','bagi',str(n)),split)
            self.settings.save(text);self.reload_settings()

    def edit_symbol(self,new=False):
        if not self.can_edit():return
        row=self.symbol_table.currentRow()
        if not new and row<0:return
        key='' if new else self.symbol_table.item(row,0).text()
        value='' if new else self.symbol_table.item(row,1).text()
        if new:
            key,ok=QInputDialog.getText(self,'Tambah simbol','Nama pair di setup:')
            if not ok or not key.strip():return
            key=key.strip().upper()
            if key in self.settings.cfg()['simbol']:
                self.info('Pair sudah ada. Gunakan Edit.');return
            if not key.replace('_','').replace('.','').isalnum():
                self.info('Nama pair hanya boleh huruf, angka, titik, atau garis bawah.');return
        value,ok=QInputDialog.getText(self,'Pemetaan '+key,'Nama persis simbol di MT5:',text=value)
        if ok and value.strip():
            if not self.can_edit():return
            text=add_value(self.baseline,('simbol',),key,value.strip()) if new else set_value(self.baseline,('simbol',key),value.strip())
            self.settings.save(text);self.reload_settings()

    def delete_symbol(self):
        if not self.can_edit():return
        row=self.symbol_table.currentRow()
        if row>=0:
            key=self.symbol_table.item(row,0).text()
            if self.confirm('Hapus pemetaan?',key+' dihapus dari konfigurasi.'):
                if not self.can_edit():return
                self.settings.save(remove_value(self.baseline,('simbol',key)));self.reload_settings()

    def build_tools(self):
        layout=self.add_page();layout.addWidget(label('Seluruh utilitas MENU.bat tersedia. Login dan jawaban diketik di jendela lokal aplikasi.','muted'))
        grid=QGridLayout()
        tools=[('source','Channel & topik sumber','Pilih sumber, topik, dan login pembaca.'),('match','Cocokkan simbol broker','Tinjau nama simbol dari akun MT5.'),('image','Coba baca gambar','Baca gambar lokal tanpa memposting setup.'),('ready','Cek kesiapan','MT5, Telegram, Claude, dan kelengkapan konfigurasi.'),('ids','Cari ID Telegram','ID channel kotak masuk dan admin.'),('tests','Tes logika program','Menjalankan pengujian dengan layanan tiruan.'),('history','Riwayat setup','Daftar hasil dan kejadian dari jurnal.'),('reset','Reset jurnal','Cadangan dibuat dahulu. Ditolak saat masih aktif.')]
        for i,(task,title,desc) in enumerate(tools):
            b=button(title+'\n\n'+desc,lambda _=False,t=task:self.utility(t));b.setMinimumHeight(110);grid.addWidget(b,i//2,i%2)
        layout.addLayout(grid);layout.addStretch()

    def utility(self,task):
        if task=='history':self.navigate(0);self.tabs.setCurrentIndex(3);return
        if self.demo:self.info('Mode pratinjau. Utilitas tidak dijalankan.');return
        if task=='reset' and self.store.fresh(self.snapshot):self.trade('reset');return
        if task=='reset' and is_running(BOT_PORT):
            self.info('Bot sedang jalan tanpa penghubung desktop. Gunakan /resetjurnal atau matikan bot dahulu.');return
        file=None
        if task=='image':
            file,_=QFileDialog.getOpenFileName(self,'Pilih gambar sinyal',str(self.root),'Gambar (*.png *.jpg *.jpeg *.webp)')
            if not file:return
        if task in ('source','ids') and is_running(READER_PORT if task=='source' else BOT_PORT):
            self.info('Matikan '+('pembaca' if task=='source' else 'bot')+' dahulu agar tidak bentrok.');return
        if task=='reset' and not self.confirm('Reset jurnal?','Utilitas akan meminta RESET dan membuat cadangan sebelum menghapus riwayat.'):return
        UtilityDialog(self,task,{'source':'Channel & topik sumber','match':'Cocokkan simbol broker','image':'Coba baca gambar','ready':'Cek kesiapan','ids':'Cari ID Telegram','tests':'Tes logika program','reset':'Reset jurnal'}[task],file).exec()

    def build_activity(self):
        layout=self.add_page();row=QHBoxLayout();self.log_choice=QComboBox();self.log_choice.addItems(['Kejadian jurnal','Bot','Pembaca','Desktop bot','Desktop pembaca']);self.log_choice.currentIndexChanged.connect(self.change_log);row.addWidget(self.log_choice);row.addStretch();layout.addLayout(row)
        self.activity=QPlainTextEdit();self.activity.setReadOnly(True);layout.addWidget(self.activity,1)

    def refresh_activity(self):
        if not hasattr(self,'activity'):return
        index=self.log_choice.currentIndex()
        if index==0:
            text='\n'.join(f"{stamp(e['time'])}  #{e.get('setup_id') or '—'}  {e['kind']}  {e.get('detail','')}" for e in self.events)
        else:
            text=self._log_text if self._log_index==index else 'Memuat log…'
        text=self.redact(text or 'Belum ada aktivitas.')
        if self.activity.toPlainText()!=text:
            scroll=self.activity.verticalScrollBar();position=scroll.value()
            self.activity.setPlainText(text);scroll.setValue(position)

    def change_log(self):
        self.refresh_activity()
        if hasattr(self,'timer'):self.refresh()

    def build_system(self):
        layout=self.add_page();box,bl=panel()
        bl.addWidget(label('Jalankan program','heading'))
        row=QHBoxLayout();row.addWidget(button('Jalankan bot saja',lambda:self.start('bot'),True));row.addWidget(button('Jalankan bot + pembaca',self.start_both));bl.addLayout(row)
        self.program_status=label('');bl.addWidget(self.program_status)
        bl.addWidget(label('Tombol jeda ada di Dashboard. Mematikan bot menghentikan penjagaan otomatis; SL/TP tetap berada di MT5.','muted'))
        row=QHBoxLayout();row.addWidget(button('Matikan pembaca',self.stop_reader));row.addWidget(button('Matikan bot',lambda:self.trade('shutdown'),danger=True));bl.addLayout(row)
        bl.addWidget(button('Buka MENU.bat lama',lambda:self.open_path(self.root/'MENU.bat')))
        layout.addWidget(box);layout.addStretch()

    def start(self,role):
        if self.demo:self.info('Mode pratinjau. Program sungguhan tidak dijalankan.');return
        port=BOT_PORT if role=='bot' else READER_PORT
        if is_running(port):self.info('Program sudah berjalan.');return
        previous=self.children.get(role)
        if previous and previous.poll() is None:self.info('Program sedang mulai. Tunggu sebentar.');return
        if not (self.root/'.env').is_file():self.info('File .env belum tersedia. Isi sendiri dari .env.example.');return
        if role=='reader' and not (self.root/'pembaca.session').is_file():
            self.info('Login pembaca dahulu melalui Utilitas → Channel & topik sumber.');self.utility('source');return
        (self.root/'logs').mkdir(exist_ok=True)
        with (self.root/'logs'/('desktop-'+role+'.log')).open('ab') as log:
            env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
            self.children[role]=subprocess.Popen(child_command(self.root,role),cwd=self.root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.footer.setText('Menyalakan '+role+'… status akan diperbarui otomatis.')

    def start_both(self):
        self.start('bot');self.start('reader')

    def stop_reader(self):
        if self.demo:self.info('Mode pratinjau.');return
        s=reader_state(self.root)
        if not s.get('online') or time.time()-s.get('heartbeat',0)>15:
            self.info('Pembaca desktop tidak aktif. Jika dimulai dari MENU.bat, tutup jendela pembaca itu.');return
        if self.confirm('Matikan pembaca?','Pesan sumber baru tidak akan dibaca sampai pembaca dijalankan lagi.'):
            (self.root/'data'/('desktop-reader-stop-'+s['token'])).touch();self.footer.setText('Menunggu pembaca berhenti dengan aman…')

    def refresh(self):
        if self.closing:return
        if self.demo:
            if not self.rows:self.demo_data()
            self.apply_poll(dict(snapshot=self.snapshot,rows=self.rows,events=self.events,
                                 bot_on=True,reader_on=True,results={}))
            return
        if self._polling:return
        self._polling=True
        reader,outbox=self.reader,self._poll_queue
        ids=tuple(self.pending)
        log_index=self.log_choice.currentIndex() if self.pages.currentIndex()==3 else 0
        # The daemon only touches plain data and its own read-only connections.
        # It never calls a QWidget or shares the UI's SQLite connection.
        def work():
            try:outbox.put((reader.poll(ids,log_index),None))
            except Exception as exc:outbox.put((None,str(exc)))
        threading.Thread(target=work,name='dashboard-reader',daemon=True).start()

    def poll_ready(self):
        try:data,error=self._poll_queue.get_nowait()
        except queue.Empty:return
        self._polling=False
        if self.closing:return
        if error:
            self.notice.setText('Tidak bisa menyegarkan: '+error)
            for b in (*self.actions.values(),*self.global_actions.values()):b.setEnabled(False)
            return
        self.apply_poll(data)

    def apply_poll(self,data):
        try:
            self.snapshot,self.rows,self.events=data['snapshot'],data['rows'],data['events']
            if 'log_text' in data:
                self._log_text,self._log_index=data['log_text'],data['log_index']
            fresh=self.demo or self.store.fresh(self.snapshot)
            bot_on,reader_on=data['bot_on'],data['reader_on']
            self.status.setText(f"Bot: {'berjalan' if bot_on else 'mati'}   •   Pembaca: {'berjalan' if reader_on else 'mati'}   •   "+('MT5: terhubung lewat bot' if fresh else 'MT5: status belum tersedia'))
            if self.demo:self.notice.setText('PRATINJAU · data contoh · semua tindakan sungguhan dinonaktifkan')
            elif fresh:self.notice.setText('Setup baru '+('dijeda' if self.snapshot.get('paused') else 'aktif')+' · kontrol desktop dan Telegram tersinkron')
            elif bot_on:self.notice.setText(self.snapshot.get('error') or 'Bot menu lama aktif / penghubung belum siap. Kontrol desktop dinonaktifkan; Telegram tetap bisa dipakai.')
            else:self.notice.setText('Bot belum berjalan. Menampilkan jurnal tersimpan; jalankan dari Bot & pembaca untuk kontrol langsung.')
            account=self.snapshot.get('account',{}) if fresh else {}
            self.account_label.setText(f"{'DEMO' if account.get('demo') else 'REAL'} · {account['login']}\n{account.get('server','')}\n{account.get('currency','')}" if account else 'Akun belum terverifikasi')
            for i,key in enumerate(['balance','equity','bot_floating']):
                val=self.snapshot.get(key) if key=='bot_floating' else account.get(key)
                self.metrics[i].setText(f"{val:,.2f} {account.get('currency','')}" if val is not None and fresh else '—')
            self.program_status.setText(self.status.text()+'\n\nFolder kerja: '+str(self.root))
            self.global_actions['pause'].setVisible(not self.snapshot.get('paused',False))
            self.global_actions['resume'].setVisible(self.snapshot.get('paused',False))
            for role,proc in list(self.children.items()):
                if proc.poll() is not None:
                    self.footer.setText(f"{role} berhenti (kode {proc.returncode}). Lihat Aktivitas → Desktop {role}.");del self.children[role]
            for cid in list(self.pending):
                r=data.get('results',{}).get(cid)
                if r and r['status'] not in ('queued','processing'):
                    del self.pending[cid];self.footer.setText(r['result']);self.info(r['result'],r['status']!='done')
                elif time.time()-self.pending[cid]>90:
                    del self.pending[cid];self.info('Hasil perintah belum diketahui. Periksa status/jurnal sebelum mengulang.',True)
            for b in self.global_actions.values():b.setEnabled(fresh and not self.pending and not self.demo)
            self.refresh_table()
            if self.pages.currentIndex()==3:self.refresh_activity()
            self.recent.setText('\n'.join(f"{stamp(e['time'])}  {e['kind']} · {e.get('detail','')}" for e in self.events[:3]) or 'Belum ada kejadian jurnal.')
        except Exception as exc:
            self.notice.setText('Tidak bisa menyegarkan: '+str(exc))

    def filtered_rows(self):
        tab=self.tabs.currentIndex()
        return [r for r in self.rows if (r['status']=='awaiting_confirm' if tab==0 else
                any(l['status']=='pending' for l in r.get('legs',[])) and r['status'] in ('pending','running') if tab==1 else
                r['status']=='running' if tab==2 else r['status'] not in ('awaiting_confirm','pending','running'))]

    def refresh_table(self):
        if not hasattr(self,'table'):return
        rows=self.filtered_rows();selected=self.selected
        projection=[]
        for r in rows:
            live=sum(l.get('live',{}).get('profit',0) for l in r.get('legs',[]) if l.get('live',{}).get('state')=='open')
            value=f"{r.get('pnl'):+.2f}" if r.get('pnl') is not None else f"{live:+.2f}" if r['status']=='running' else str(r.get('total_lot') or '—')
            vals=[f"#{r['id']}  {r.get('broker_symbol') or r['symbol']}",r['side'],str(r.get('entry') or 'MARKET'),value,STATUS.get(r['status'],r['status'])]
            projection.append((r['id'],tuple(vals)))
        signature=(self.tabs.currentIndex(),tuple(projection))
        if signature!=self._table_signature:
            scroll=self.table.verticalScrollBar();position=scroll.value()
            self.table.blockSignals(True);self.table.setUpdatesEnabled(False)
            try:
                self.table.setRowCount(len(rows))
                for i,(sid,vals) in enumerate(projection):
                    for j,v in enumerate(vals):
                        item=self.table.item(i,j)
                        if item is None:
                            item=QTableWidgetItem(v);self.table.setItem(i,j,item)
                        elif item.text()!=v:item.setText(v)
                        item.setData(Qt.ItemDataRole.UserRole,sid)
                    self.table.setRowHeight(i,54)
                index=next((i for i,r in enumerate(rows) if r['id']==selected),0)
                if rows:
                    column=max(0,self.table.currentColumn())
                    self.table.setCurrentCell(index,column)
                    self.table.selectRow(index);self.selected=rows[index]['id']
                else:self.selected=None
                scroll.setValue(position);self._table_signature=signature
            finally:
                self.table.setUpdatesEnabled(True);self.table.blockSignals(False)
        self.update_detail()

    def selection_changed(self):
        row=self.table.currentRow()
        self.selected=self.table.item(row,0).data(Qt.ItemDataRole.UserRole) if row>=0 and self.table.item(row,0) else None
        self.update_detail()

    def update_detail(self):
        r=next((r for r in self.rows if r['id']==self.selected),None)
        active=[]
        if r and r['status']=='awaiting_confirm':active=['approve','reject']
        elif r and r['status'] in ('pending','running'):
            active=['close']
            if any(l['status']=='pending' for l in r.get('legs',[])):active.append('cancel')
        for key,b in self.actions.items():
            b.setVisible(key in active)
            b.setEnabled(key in active and self.store.fresh(self.snapshot) and not self.pending and not self.demo)
        if not r:
            if self.detail.toPlainText()!='Pilih setup untuk melihat detail.':
                self.detail.setPlainText('Pilih setup untuk melihat detail.')
            return
        lines=[f"Setup #{r['id']} · {r['side']}",str(r.get('broker_symbol') or r['symbol']),STATUS.get(r['status'],r['status']),
               f"Sumber: {r.get('source') or '—'}",f"Entry: {r.get('entry') or 'MARKET'}",f"SL awal: {r['sl']}"]
        lines += [f"TP{i+1}: {tp}" for i,tp in enumerate(r['tps'])]
        lines += [f"Lot total: {r.get('total_lot') or '—'}",f"Risiko: {r.get('risk_amount') or '—'}",f"TP tercapai: {r.get('tp_level') or 0}"]
        preview=r.get('preview')
        if preview:
            lines += [f"\nEstimasi lot: {preview['lot']}",f"Estimasi risiko: {preview['risk']} {self.snapshot.get('account',{}).get('currency','')}"]
            lines += [f"TP{i+1}: {leg[0]} lot @ {leg[1]}" for i,leg in enumerate(preview['legs'])]
            if preview.get('error'):lines.append('Estimasi: '+preview['error'])
            lines += ['Cek saat ini: '+reason for reason in preview.get('reasons',[])]
            lines += ['Peringatan: '+reason for reason in preview.get('warnings',[])]
        if r.get('confirm_deadline'):lines.append('Batas jawaban: '+stamp(r['confirm_deadline']))
        if r.get('expires'):lines.append('Pending habis: '+stamp(r['expires']))
        if r.get('warning'):lines.append('\nPERINGATAN: '+r['warning'])
        if r.get('reason'):lines.append('\nAlasan: '+r['reason'])
        lines.append('\nRincian kaki order:')
        for leg in r.get('legs',[]):
            live=leg.get('live',{})
            lines.append(f"TP{leg['idx']+1} · #{leg['ticket']} · {leg['volume']} lot\n{leg['status']} · SL {live.get('sl','—')} · TP {live.get('tp',leg['tp'])}")
        text='\n'.join(lines)
        if self.detail.toPlainText()!=text:
            scroll=self.detail.verticalScrollBar();position=scroll.value()
            self.detail.setPlainText(text);scroll.setValue(position)

    def trade(self,action,sid=None):
        if self.demo:self.info('Mode pratinjau. Tidak ada perintah yang dikirim.');return
        if self.pending:self.info('Tunggu hasil perintah sebelumnya dahulu.');return
        expected=copy.deepcopy(self.snapshot)
        if not self.store.fresh(expected):self.info('Bot desktop belum terhubung. Jalankan dari halaman Bot & pembaca.');return
        title={'approve':'Setujui setup?','reject':'Tolak setup?','cancel':'Batalkan pending setup?','close':'Tutup seluruh setup?',
               'pause':'Jeda setup baru?','resume':'Lanjutkan setup baru?','cancel_all':'Batalkan semua pending?',
               'close_all':'Tutup semua milik bot?','reset':'Reset jurnal?','shutdown':'Matikan bot?'}[action]
        rows=[r for r in expected.get('setups',[]) if sid is None or r['id']==sid]
        legs=[l for r in rows if r['status'] in ('pending','running') for l in r.get('legs',[])]
        n_pending=sum(l['status']=='pending' for l in legs);n_open=sum(l['status']=='open' for l in legs)
        acc=expected['account'];body=f"Akun {'DEMO' if acc['demo'] else 'REAL'} {acc['login']} · {acc.get('server','')}\n"
        if sid:body+=f"Setup #{sid}\n"
        descriptions={'approve':'Bot memeriksa ulang harga dan pengaman sebelum memasang order.',
                      'reject':'Setup tidak akan dieksekusi.','cancel':f'{n_pending} pending order akan dibatalkan.',
                      'close':f'{n_open} posisi ditutup dan {n_pending} pending dibatalkan.',
                      'pause':f'Setup baru ditolak dan {n_pending} pending dibatalkan. Posisi berjalan tetap dijaga.',
                      'resume':'Bot kembali menerima setup baru.',
                      'cancel_all':f'{n_pending} pending dibatalkan. Posisi berjalan tetap dijaga.',
                      'close_all':f'{n_open} posisi ditutup dan {n_pending} pending dibatalkan.',
                      'reset':'Riwayat dihapus setelah dicadangkan. Ditolak jika masih ada setup aktif.',
                      'shutdown':'BE/trailing berhenti. SL/TP tetap terpasang di MT5.'}
        if not self.confirm(title,body+'\n'+descriptions[action]):return
        try:
            cid=self.store.submit(action,expected,sid);self.pending[cid]=time.time();self.footer.setText('Perintah dikirim; menunggu hasil bot…')
            for b in (*self.actions.values(),*self.global_actions.values()):b.setEnabled(False)
            self.refresh()
        except Exception as exc:self.info(str(exc),True)

    def demo_data(self):
        now=time.time()
        def row(sid,status,symbol,side,entry,sl,tps):
            legs=[] if status=='awaiting_confirm' else [dict(idx=i,ticket=5000+sid*10+i,volume=.02,tp=tp,status='pending' if status=='pending' else 'open',live=dict(state='open' if status=='running' else 'pending',sl=sl,tp=tp,profit=12.25)) for i,tp in enumerate(tps)]
            return dict(id=sid,created=now-600,status=status,symbol=symbol,broker_symbol=symbol,side=side,entry=entry,sl=sl,tps=tps,source='outlook',legs=legs,total_lot=.06,risk_amount=10,tp_level=1 if status=='running' else 0,expires=now+3600,confirm_deadline=now+1800)
        self.rows=[row(43,'awaiting_confirm','GBPUSDm','BUY',1.298,1.295,[1.301,1.304]),row(42,'pending','XAUUSDm','BUY',2740,2730,[2750,2760,2770]),row(40,'running','XAUUSDm','BUY',2725,2726,[2745,2755])]
        self.snapshot=dict(online=False,account=dict(login='•••• 4821',server='Exness Demo',demo=True,currency='USD',balance=1024.5,equity=1049),bot_floating=24.5,setups=self.rows)
        self.events=[dict(time=now-25,setup_id=43,kind='setup',detail='Menunggu persetujuan'),dict(time=now-120,setup_id=42,kind='placed',detail='3 pending order terpasang')]

    def info(self,text,error=False):
        (QMessageBox.warning if error else QMessageBox.information)(self,'Trading Manager',self.redact(str(text)))

    def confirm(self,title,text):
        return QMessageBox.question(self,title,text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def open_path(self,path):
        if self.demo and str(path).endswith('.bat'):self.info('Peluncuran dinonaktifkan dalam pratinjau.');return
        if not Path(path).exists():self.info('Lokasi belum tersedia: '+str(path));return
        os.startfile(str(path))

    def restore(self):
        self.showNormal();self.raise_();self.activateWindow()

    def exit_app(self):
        if self.confirm('Keluar aplikasi?',
            'Jendela dan ikon tray ditutup. Bot/pembaca yang sudah dijalankan tetap berjalan.\n\nUntuk mematikan program juga, gunakan halaman Bot & pembaca sebelum keluar.'):
            self.closing=True;self.close();QApplication.instance().quit()

    def closeEvent(self,event):
        if not self.closing and self.tray and not self.args.smoke:
            event.ignore();self.hide();self.tray.showMessage('Trading Manager','Aplikasi berada di tray. Bot tetap berjalan.',QSystemTrayIcon.MessageIcon.Information,2500)
        else:
            self.timer.stop();self.result_timer.stop();self.store.close()
            if self.tray:self.tray.hide()
            event.accept()


def run(root,args):
    app=QApplication.instance() or QApplication(sys.argv)
    for font in ['segoeui.ttf','seguisb.ttf']:
        file=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/font
        if file.exists():QFontDatabase.addApplicationFont(str(file))
    app.setFont(QFont('Segoe UI',10))
    app.setApplicationName('Trading Manager');app.setStyle('Fusion');app.setStyleSheet(STYLE)
    # Prevent two GUIs competing for launch/utility operations on one workspace.
    lock=claim(47653)
    if lock is None:
        QMessageBox.information(None,'Trading Manager','Aplikasi sudah terbuka. Cari ikon TM di dekat jam Windows.');return
    window=MainWindow(root,args);window.show()
    if args.smoke:
        def finish():
            if args.screenshot:window.grab().save(args.screenshot)
            window.closing=True;window.close();app.quit()
        QTimer.singleShot(1200,finish)
    app.exec()
