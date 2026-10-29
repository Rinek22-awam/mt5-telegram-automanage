"""GUI entry point. MENU.bat and its launch path remain unchanged."""
import sys
import os
from pathlib import Path

if os.name=='nt':
    # Broken DLLs should produce an ordinary import error, never an OS modal
    # that stalls an unattended packaging check or a background worker.
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)

if not getattr(sys,'frozen',False):
    deps=Path(__file__).resolve().parent/'.desktop-deps'
    if deps.is_dir():
        sys.path.insert(0,str(deps))

if __name__=='__main__':
    from desktop.runtime import main
    try:
        main()
    except Exception:
        import traceback
        report=traceback.format_exc()
        if '--role' in sys.argv and sys.argv[sys.argv.index('--role')+1]!='gui':
            print(report,file=sys.stderr)
            raise SystemExit(1)
        try:
            from PySide6.QtWidgets import QApplication,QMessageBox
            app=QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None,'Trading Manager gagal dibuka',report)
        except Exception:
            raise
