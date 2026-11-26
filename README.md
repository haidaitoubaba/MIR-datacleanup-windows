# MIR Cleanup 1.4.0 for Windows 11 x64

MIR Cleanup supports review and cleanup of mid-infrared spectra and reference data before modelling. The Windows port uses the [Mac v1.4.0 source](https://github.com/haidaitoubaba/MIR-datacleanup-mac/tree/v1.4.0). This version adds the redesigned review workbench, Light, Night and System appearance modes, and automatic candidate cleanup in a separate session copy.

Download the Windows ZIP from [Windows Releases](https://github.com/haidaitoubaba/MIR-datacleanup-windows/releases). Extract the whole ZIP, open the `MIR Cleanup` folder, and run `MIR Cleanup.exe`. Keep `_internal` beside the executable. See [the Windows app guide](WINDOWS_APP_GUIDE.md) for the workflow.

## Package layout

- Release ZIP `MIR-Cleanup-Windows-v1.4.0.zip` contains `MIR Cleanup/MIR Cleanup.exe` and its required `_internal` folder.
- The executable uses the supplied MIR cleanup image as its Windows app icon.
- `Source`: Windows source, dependency pins, regression tests and build specification.
- `Verification`: release checks, numerical parity summary, and packaging notes.
- `build-windows.ps1`: repeatable Windows build using Python 3.12 x64.

## Rebuild

Run `./build-windows.ps1` in PowerShell with Python 3.12 x64 installed and available through `py`. Alternatively supply `-Python 'C:\path\to\python.exe'`. The script creates its own environment, installs the full Windows dependency lock, runs tests and builds the portable folder. It stops if any step fails.

The build uses the Windows dependency lock and writes the app to `Portable/MIR Cleanup`. The regression test log is saved at `Build/regression-tests.log`.

## Verify a packaged build

From PowerShell, use absolute paths and a **new** output directory:

```powershell
& '.\Portable\MIR Cleanup\MIR Cleanup.exe' --verify-windows --data 'C:\path\to\test-data' --verification-output "$PWD\Build\verification"
```

The command tests manual and automatic cleanup on `202_STC` and `202_STN` by default. Use `--properties` followed by exact sheet names or `--properties all` to check a different set. `verification.json` records invalid sheets, progress, the executable checksum and the final result. Inputs are hashed before and after the run. The generated exports are test data.

To reproduce a source baseline, run `Build/venv/Scripts/python.exe Source/mir_cleanup_app.py` with the same verification flags and a different output directory. Use `Source/compare_verification.py` with the source baseline session, the packaged manual session, and `Verification/numerical-parity.json` as the output. Pass `--packaged-report Build/verification/verification.json` to record the executable checksum with the comparison. Run `Build/venv/Scripts/python.exe package-windows.py` to create the release ZIP and its checksum. Packaging checks that the validation and parity reports match the executable being distributed.

## Clean-machine acceptance

Copy the ZIP and test data to a Windows 11 x64 machine without Python. Extract the entire ZIP. Launch the app, complete a session through PCA, A/B review and export, then reopen the saved session. Check file dialogs, the offline viewer, workbook opening, appearance and display scaling. Run packaged verification from the extracted `MIR Cleanup` folder and retain the JSON report.
