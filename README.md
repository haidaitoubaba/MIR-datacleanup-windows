# MIR Cleanup — Windows 11 x64

Portable Windows build of the supplied Mac 1.2.1 source. See WINDOWS_APP_GUIDE.md for use.

Download [MIR-Cleanup-Windows-v1.2.1.zip](https://github.com/haidaitoubaba/MIR-datacleanup-windows/releases/tag/v1.2.1) from the release Assets. Extract the whole ZIP before opening `MIR Cleanup.exe`; keep `_internal` beside it.

## Package layout

- Release ZIP: `MIR Cleanup Windows 1.2.1/MIR Cleanup/MIR Cleanup.exe` and its required `_internal` folder.
- The executable uses the supplied MIR cleanup image as its Windows app icon.
- `Source`: Windows source, dependency pins, regression tests and build specification.
- `Verification`: release checks, numerical parity summary, and packaging notes.
- `build-windows.ps1`: repeatable Windows build using Python 3.12 x64.

## Rebuild

Run `./build-windows.ps1` in PowerShell with Python 3.12 x64 installed and available through `py`. Alternatively supply `-Python 'C:\path\to\python.exe'`. The script creates its own environment, installs the full Windows dependency lock, runs tests and builds the portable folder. It stops if any step fails.

The build retains every direct dependency version from the Mac release. Scientific algorithms and session schema are unchanged. Windows-specific changes include UTF-8 text handling, Windows executable metadata, portable packaging, a neutral file-access message, and an opt-in packaged verification command. The Mac directory is not modified.

## Verify a packaged build

From PowerShell, use absolute paths and a **new** output directory:

```powershell
& '.\MIR Cleanup Windows 1.2.1\MIR Cleanup\MIR Cleanup.exe' --verify-windows --data 'C:\path\to\test-data' --verification-output 'C:\path\to\new-verification-output'
```

The command tests `202_STC` and `202_STN` by default, as requested for this Windows release. Use `--properties` followed by exact sheet names to choose another set, or `--properties all` for every sheet. Invalid selected sheets are recorded with their reasons. Progress is written to `verification.json`; a successful run ends with `"passed": true`. Test exclusions solely validate the workflow; do not use the resulting cleaned workbook as an approved scientific cleanup result. Inputs are hashed before and after to verify they are unchanged.

## Clean-machine acceptance

Copy the ZIP and separate test data to a Windows 11 x64 machine without Python. Extract the entire ZIP. Start the executable, create a session, complete PCA and A/B review, export, close, and reopen the saved session. Check file dialogs, offline viewer, workbook opening, and display scaling. Run the packaged verification command above and retain its JSON report. This remains a separate acceptance check until performed on such a machine; a restricted environment on the build computer is not equivalent.
