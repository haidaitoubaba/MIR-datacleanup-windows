# Windows ICU packaging correction

The initial frozen launch failed when importing QtCore with Windows error 0xc0000139 (entry point not found). The build interpreter carried ICU 78.3 under the name `icuuc.dll`; PyInstaller resolved Qt's system ICU dependency to that file. Qt 6.11 imports unversioned functions such as `ucnv_open`, whereas that ICU 78 build exports version-suffixed functions.

PE import inspection confirmed that Qt6Core.dll was the only other bundled binary importing ICU, and that Windows 11's System32/icuuc.dll provides the required unversioned function. The Windows specification excludes the incorrectly collected `icuuc.dll` and its `icudt78.dll` companion, allowing Qt to use the Windows 11 system library. No Python package versions or scientific calculations were changed.

The correction is part of the build specification, not a manual change to the delivered executable folder. The final packaged verification must pass before distribution.
