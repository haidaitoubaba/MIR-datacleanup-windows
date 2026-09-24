from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'mir_cleanup_app.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root / 'mir_cleanup_viewer.html'), '.'),
                        (str(root / 'assets' / 'mir-cleanup-icon.png'), 'assets')]
    + collect_data_files('plotly'),
    hiddenimports=['soil_mir_plsr_Nested_LOGO_stepwise_regions_rank_reuse',
                   'brukeropusreader', 'mir_windows_verify'],
    runtime_hooks=[str(root / 'mir_runtime_hook.py')],
    hooksconfig={'matplotlib': {'backends': ['QtAgg', 'Agg']}},
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'tkinter', 'torch', 'tensorflow',
              'IPython', 'notebook', 'pytest'],
    module_collection_mode={'scipy': 'py'}, noarchive=False)
# Qt 6.11 imports the unversioned ICU API supplied by Windows 11. Some Python
# distributions carry a different icuuc.dll (version-suffixed ICU 78 exports).
# PyInstaller can mistakenly resolve Qt's import to that DLL. Do not shadow
# Windows' ICU with the development interpreter's unrelated ICU distribution.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MIR Cleanup',
          debug=False, strip=False, upx=False, console=False,
          version=str(root / 'windows-version.txt'),
          icon=str(root / 'assets' / 'mir-cleanup-icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MIR Cleanup')
