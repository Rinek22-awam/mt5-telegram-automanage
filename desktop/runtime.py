"""Launch modes shared by the Python source and packaged Windows executable."""
import argparse
import asyncio
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path


def workspace(explicit=None):
    if explicit:
        p=Path(explicit).resolve()
        if not (p/'config.yaml').is_file():
            raise ValueError('Folder harus berisi config.yaml.')
        return p
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    for p in (base,base.parent,base.parent.parent,Path.cwd()):
        if (p/'config.yaml').is_file():
            return p.resolve()
    raise ValueError('config.yaml tidak ditemukan. Letakkan folder aplikasi di folder proyek.')


def child_command(root, role, *args):
    if getattr(sys,'frozen',False):
        return [sys.executable,'--workspace',str(root),'--role',role,*args]
    return [sys.executable,str(Path(__file__).resolve().parents[1]/'desktop_entry.py'),
            '--workspace',str(root),'--role',role,*args]


def restore_stdio():
    """PyInstaller windowed workers receive pipes; restore Python streams on them."""
    if os.name=='nt':
        import ctypes
        import msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetStdHandle.restype=ctypes.c_void_p
        for name,kind,mode in [('stdin',-10,'r'),('stdout',-11,'w'),('stderr',-12,'w')]:
            if getattr(sys,name) is None:
                handle=kernel.GetStdHandle(kind)
                if handle and handle != ctypes.c_void_p(-1).value:
                    fd=msvcrt.open_osfhandle(handle,os.O_RDONLY if mode=='r' else os.O_WRONLY)
                    setattr(sys,name,os.fdopen(fd,mode,encoding='utf-8',errors='replace',buffering=1))
                else:
                    setattr(sys,name,open(os.devnull,mode,encoding='utf-8'))
    for stream in (sys.stdout,sys.stderr):
        if stream and hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace',line_buffering=True)


def reader_state(root):
    try:
        return json.loads((Path(root)/'data'/'desktop-reader.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return {}


def run_reader(root):
    import logging
    from copier.config import load_config
    from copier.single import claim, READER_PORT
    from reader.main import run
    lock=claim(READER_PORT)
    if lock is None:
        raise SystemExit('Pembaca sudah berjalan di jendela lain.')
    (root/'logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    token=uuid.uuid4().hex
    path=root/'data'/'desktop-reader.json'
    stop=root/'data'/('desktop-reader-stop-'+token)
    path.parent.mkdir(exist_ok=True)

    async def supervise():
        task=asyncio.create_task(run(load_config(),False))
        try:
            while not task.done():
                temp=path.with_suffix('.tmp')
                temp.write_text(json.dumps(dict(pid=os.getpid(),token=token,heartbeat=time.time(),online=True)),encoding='utf-8')
                temp.replace(path)
                if stop.exists():
                    task.cancel()
                    break
                await asyncio.sleep(1)
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            path.write_text(json.dumps(dict(pid=os.getpid(),token=token,online=False)),encoding='utf-8')
            stop.unlink(missing_ok=True)
    asyncio.run(supervise())


def utility(task, file=None):
    from copier.config import load_config
    from copier.single import BOT_PORT, READER_PORT, is_running
    cfg=load_config()
    if task=='source':
        if is_running(READER_PORT):
            raise ValueError('Matikan pembaca sebelum memilih sumber atau login Telegram.')
        from reader.main import main
        sys.argv=['reader','--cari-channel']
        main()
    elif task=='match':
        from panel.symbols import match_screen
        from panel.settings import Settings
        match_screen(Settings('config.yaml',lambda:is_running(BOT_PORT)))
    elif task=='image':
        from reader.main import try_image
        if not file:
            raise ValueError('Pilih file gambar dahulu.')
        try_image(cfg,file)
    elif task=='ready':
        from panel.check import run_all
        run_all(cfg)
    elif task=='ids':
        if is_running(BOT_PORT):
            raise ValueError('Matikan bot dahulu agar polling Telegram tidak bentrok.')
        from copier.main import main
        sys.argv=['copier','--cari-id']
        main()
    elif task=='reset':
        from panel import main as panel_main
        panel_main.ROOT=str(Path.cwd())
        panel_main.reset_journal(cfg)
    elif task=='tests':
        import pytest
        test_root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'tests'
        result=pytest.main([str(test_root),'-q','-p','no:cacheprovider',
                            '--basetemp',str(Path.cwd()/'data'/('desktop-tests-'+uuid.uuid4().hex))])
        raise SystemExit(result)
    else:
        raise ValueError('Utilitas tidak dikenal.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace')
    parser.add_argument('--role',choices=['gui','bot','reader','utility','self-check'],default='gui')
    parser.add_argument('--task')
    parser.add_argument('--file')
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--screenshot')
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    restore_stdio()
    root=workspace(args.workspace)
    os.chdir(root)
    # A GUI preview never loads credentials or talks to MT5 / Telegram.
    if args.role!='gui':
        from dotenv import load_dotenv
        load_dotenv(root/'.env')
    if args.role=='bot':
        from .engine import run_bot
        sys.argv=['copier']
        run_bot()
    elif args.role=='reader':
        run_reader(root)
    elif args.role=='utility':
        utility(args.task,args.file)
    elif args.role=='self-check':
        import MetaTrader5, telethon, yaml, pytest
        from PySide6 import QtCore,QtWidgets
        print('Runtime OK: Qt, MT5, Telethon, YAML, pytest')
    else:
        from .ui import run
        run(root,args)
