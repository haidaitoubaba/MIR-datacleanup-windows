# MIR Cleanup Windows 1.4.0

Portable build for Windows 11 x64 (Intel/AMD). Extract `MIR-Cleanup-Windows-v1.4.0.zip` and run `MIR Cleanup/MIR Cleanup.exe`. The required runtime is bundled.

## Changes

- The redesigned workbench puts the property list beside the plot, data table, and selection details.
- Light, Night and System appearance modes cover the workbench and plots.
- Automatic cleanup reviews eligible properties in a session copy. It applies candidate exclusions at the sample level, records decisions and failures, and reports whether the copy is ready for export.

## Verification

- The Windows test suite covers 23 regression tests, including automatic cleanup recovery, appearance, manual review, Excel export and Unicode paths.
- The packaged checks use `202_STC` and `202_STN` for manual review, session reopen, workbook relocation, Excel roundtrip, automatic cleanup and export verification. See the accompanying reports for results.
- A separate clean Windows 11 x64 machine check remains pending.

The supplied workbook has four sheets that the app’s existing validation rejects (`202_POM-C`, `202_POM-N`, `213_SIC`, and `Combined_SIC`). The default verification intentionally uses `202_STC` and `202_STN`; the original data is unchanged.
