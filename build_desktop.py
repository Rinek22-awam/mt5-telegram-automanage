"""Build the GUI alongside MENU.bat. Never include configuration or login files."""
import os
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DEPS=ROOT/'.desktop-deps'
if DEPS.exists():
    sys.path.insert(0,str(DEPS))

if __name__=='__main__':
    # Do not resolve Qt's system ICU dependency against unrelated tools on PATH
    # (for example Poppler's version-suffixed ICU, which is ABI-incompatible).
    windows=Path(os.environ.get('WINDIR','C:/Windows'))
    os.environ['PATH']=os.pathsep.join([str(Path(sys.executable).parent),str(windows/'System32'),str(windows)])
    import PyInstaller.__main__
    # Explicit source allowlist: .env, session, data/, logs/ and config.yaml are excluded.
    PyInstaller.__main__.run([
        str(ROOT/'desktop_entry.py'),'--name','TradingManager','--onedir','--windowed',
        '--noconfirm','--clean','--paths',str(DEPS),
        '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build'),
        '--collect-submodules','copier','--collect-submodules','reader','--collect-submodules','panel',
        '--collect-submodules','desktop','--collect-submodules','telethon',
        '--hidden-import','MetaTrader5','--hidden-import','dotenv',
        '--hidden-import','yaml','--hidden-import','pytest',
        '--hidden-import','PySide6.QtWidgets',
        '--copy-metadata','PySide6-Essentials','--copy-metadata','shiboken6',
        '--add-data',str(ROOT/'tests')+';tests',
        '--exclude-module','PyQt5','--exclude-module','PyQt6',
        '--exclude-module','matplotlib','--exclude-module','pandas','--exclude-module','IPython',
        # Unused here: Pillow is only an optional Telethon extra; the GUI has no network code.
        '--exclude-module','PIL','--exclude-module','PySide6.QtNetwork',
    ])
    bundle=ROOT/'dist'/'TradingManager'
    # Software OpenGL fallback (PCs without a GPU driver) and Qt's own UI translations.
    (bundle/'_internal'/'PySide6'/'opengl32sw.dll').unlink(missing_ok=True)
    shutil.rmtree(bundle/'_internal'/'PySide6'/'translations',ignore_errors=True)
    # Replace, not merge: files dropped from the build must not linger in the old copy.
    shutil.rmtree(ROOT/'_internal',ignore_errors=True)
    shutil.copytree(bundle/'_internal',ROOT/'_internal')
    shutil.copy2(bundle/'TradingManager.exe',ROOT/'TradingManager.exe')
    print('Built:',ROOT/'TradingManager.exe')
