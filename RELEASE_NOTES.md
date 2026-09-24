# MIR Cleanup Windows 1.2.1 — build 1

This portable Windows 11 x64 build uses the supplied MIR cleanup image as the executable icon. The Mac application remains unchanged.

Completed checks:

- Python 3.12 x64 environment with the pinned release dependencies installed; `pip check` passes.
- 15 automated regression tests pass, including real-workbook Excel namespace/export checks and Unicode-path/session relocation checks.
- `202_STC` and `202_STN` complete the supplied-data workflow: PCA, A/B calibration, exclusions, session reopen, workbook relocation, Excel review roundtrip, export verification, and input-integrity checks.
- The native Windows app opens with its main window, file picker, plot toolbar, Plot/Data sheet/Full dataset tabs, and exclusion/export controls visible.
- The first packaged build exposed an ICU DLL conflict; the build specification now excludes the incompatible development ICU files, and the packaged Qt library loads against Windows 11 ICU.

Remaining acceptance check:

- Run the packaged verification on a separate clean Windows 11 x64 computer without Python installed. This environment has no Windows Sandbox, so that final machine-level check cannot be performed here.

The supplied workbook has four sheets that the app’s existing validation rejects (`202_POM-C`, `202_POM-N`, `213_SIC`, and `Combined_SIC`). The default verification intentionally uses `202_STC` and `202_STN`; the original data is unchanged.
