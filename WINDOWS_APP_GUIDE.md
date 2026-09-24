# MIR Cleanup for Windows — 1.2.1, Windows build 1

For Windows 11 on 64-bit Intel/AMD computers.

## Open the app

1. Extract the entire ZIP to a local folder, such as Documents\MIR Cleanup.
2. Open the MIR Cleanup folder and double-click **MIR Cleanup.exe**.
3. Keep the `_internal` folder beside the executable. Do not launch from inside the ZIP.

The executable uses the MIR cleanup image as its app icon. Windows may cache an older icon briefly; refreshing the folder or restarting Explorer updates the display.

Python and all runtime dependencies are bundled. No Python installation or administrator access is needed for normal operation. Internet access is not needed for calculations or the offline PCA viewer. Excel is needed only if you want to open and edit exported workbooks in Excel; the app itself reads and writes workbooks without Excel.

For the supplied test dataset, select `data/reference/reference_value_ZL_trt.xlsx` and `data/spectra/Complete`. Keep test sessions and exports in a separate writable folder. These test inputs are not included in the distribution ZIP.

## Supplied test workbook

For this Windows release, testing uses **202_STC and 202_STN**. The supplied workbook has 27 property sheets. An initial input check also found that the existing validation rejects `202_POM-C`, `202_POM-N`, `213_SIC`, and `Combined_SIC`; selecting all sheets together therefore prevents session creation. The original data has not been changed.

The two POM sheets have missing filenames/groups in Excel rows 746–748 and also contain inconsistent sample values. The two SIC sheets contain inconsistent values for sample `213-12AB`. Detailed affected sample names are recorded in `Verification/input-data-issues.json` in the development package. Resolve these in your source-data workflow before selecting those sheets.

## Moving a saved session from Mac

Copy the whole session folder, including session.json and every .npz file, to Windows. Open that session. Use **Locate original workbook** to select an identical copy of its original workbook before exporting. Prepared spectra travel with the session, so the original spectra directory is not needed when resuming. Undo history does not survive app restarts.

## Troubleshooting

If startup fails, check `%TEMP%\mir-cleanup-runtime.log` and `%TEMP%\mir-cleanup-startup-error.log`. Include these logs when requesting help. If saving or exporting fails, use a writable local folder and close files held open by other applications. This build is unsigned; organizational Windows policies may require IT approval.

## Start and review

1. Click **New session**. Choose your original reference workbook, OPUS spectra folder, and a parent folder for saved sessions.
2. Use **Browse** to select the input file/folders; choose a location you can read and write. Click **Read properties from workbook**, select the properties, then click **OK**. The app creates a dated session folder. Invalid input records must be corrected in the source workflow before starting; the app does not repair them.
3. Review **PCA**. Change X/Y components, colour and visible records. Click points or select table rows; rectangle and lasso modes are also available. Selection alone does not remove data.
4. Optionally choose a reason, choose the spectrum/sample unit, then click **Confirm exclusion**. Check the expanded filenames in the confirmation dialog. Exclusions belong to the selected property only.
5. Click **Refit PCA** after PCA exclusions. The updated fit changes coordinates and explained variance. Up to three PCA fits are available per session. **Finish PCA review / split** creates A/B assignments only after the current fit is reviewed. With no exclusions, proceed directly.
6. In stage **A**, click **Calculate half A**. The app selects preprocessing/rank against B, then displays A's calibration fit at rank 15 where feasible. Inspect the plotted values and residual table. Confirm exclusions with **Unit: spectrum** for one record or **Unit: sample** for all its replicates, then **Finish A review**.
7. Calculate and review **B**. B reuses exactly A’s selected preprocessing and selection rank. The preprocessing is fitted on B (including its own MSC reference when applicable), and its prediction error is evaluated on retained A without a new optimization search. Exclusion diagnostics use rank 15 where feasible, just as for A. If B cannot support A’s selected rank, calculation stops with an explanation. Finish B review.
8. Repeat for other selected properties, then **Export cleaned dataset**. The app creates a new dated export folder containing `reference_cleaned.xlsx`, its `.cleanup.json` provenance, audit, Excel review, offline PCA viewer and reports. In the cleaned workbook, the original property sheet names contain the retained records.

## Plot and data controls

- Use the **Plot** and **Data sheet** tabs to switch between views. Selection stays linked between them. **Full dataset (A + B)** shows all original records for the selected property, their half, retained/excluded status, decision details and available calibration predictions. It includes PCA exclusions as unassigned records; use its search box and sortable headings to inspect the full dataset. Make decisions in the original PCA/A/B stage.
- Click a column heading to sort; click again to reverse. Double-click a heading to filter, or right-click a heading for **Sort ascending**, **Sort descending**, or **Filter: contains…**. Filters are case-insensitive and combine across columns. Active headings show ▾. Filters apply to both the table and plot; hidden records are deselected. Use **Clear filters** to show all records again.
- Click a selected point again to deselect it. **Clear selection** is available in both tabs. Escape while the plot has keyboard focus, or clicking empty plot space in Click points mode, also clears selection.
- Use the small arrow beside the **magnifier** to choose **Zoom in — drag rectangle** or **Zoom out — drag rectangle**. Then drag with the left mouse button or touchpad on the plot. The main magnifier button toggles zoom mode; its tooltip shows the selected direction. Home resets the view and Back returns to the previous zoom. Zoom mode temporarily pauses point-selection tools.
- Rectangle and lasso selections toggle the points enclosed: new points are added, previously selected points are removed, and other selected points remain. Selection changes preserve zoom.
- Status and treatment colours have legends; Reference value colouring has a labelled colour bar. Selected points have black outlines.
- Reasons and comments are optional. Calibration A/B exclusions can use spectrum or sample units. An enabled concentration limit counts unique affected samples, including partial-replicate exclusions and blank reasons.

## Decisions, settings and saved sessions

- All candidates remain until explicitly confirmed. Red marks mean confirmed exclusions; orange calibration points are numerical candidates.
- The limit defaults to **disabled**, with 1% entered as the initial percentage. Edit the controls and click **Save limit**. An enabled limit counts unique concentration-excluded samples per property across both halves, against the original input sample count.
- When opening a session with an older independently optimized B result, the app archives that result and asks you to calculate B again under the new settings rule. Existing exclusion decisions remain saved, but B must be reviewed and finished again.
- Every confirmed action saves `session.json`. Use **Open session** to resume. Keep the entire session folder, including its `.npz` files, together.
- **Undo decision** restores the previous in-memory action snapshot, including the dependent state. Undo history itself does not persist across app restarts; saved audit history does.
- Changing PCA decisions invalidates the split and both calibration results. Changing A decisions invalidates B and clears B confirmations for renewed review. Older results remain in the saved archive.
- Marking calibration exclusions does not refit the calibration model. This version 1.2 intentionally displays the original diagnostic fit for that half.
- **Open offline PCA** shows the current basis with original/retained visibility and explained variance. Earlier PCA removals are not projected into a later refitted basis. Each PCA fit also has a separate HTML snapshot in the session folder.
- Excel export/import is optional. Edit only Confirm, Reason, Unit and Comment. Import one dependent review stage at a time. Blank/NO restores a previous decision; contradictory whole-sample YES and explicit NO are rejected.
- **Locate original workbook** allows relocating the original source, verified by its fingerprint. Prepared spectra are included in the session, so resuming does not require the original spectra folder. A new session does require spectra.

## Calibration metrics

A/B plots and exported calibration figures show R², RMSE, RPD and RPIQ. These are calibration-fit statistics for the displayed spectra, on the selected modelled/original scale. They are not independent validation scores. Filtering or hiding exclusions changes the displayed subset and its metrics, without refitting the model.

- R² = 1 − sum of squared errors / total sum of squares.
- RMSE = square root of the mean squared error.
- RPD = sample standard deviation of reference values / RMSE.
- RPIQ = reference interquartile range / RMSE.
- Undefined values (for example, RPD with zero RMSE) are shown as N/A.

## Export correction in version 1.2.1

The exporter preserves the workbook's original XML namespace declarations, including Excel compatibility metadata, and reopens every exported sheet to verify its retained values against the confirmed decisions. It refuses to report success if verification fails. Revised decisions clear the shortcut to any older export so it cannot be mistaken for the current result.

To replace an earlier incorrect export, open the saved session, finish any outstanding reviews, and click **Export cleaned dataset** again. A new folder is created. The original workbook and previous exports remain unchanged.

## Interpretation and boundaries

The plot defaults to the modelled scale. Select **Original units** to view back-transformed fitted values. Metadata controls transformations; reference-sheet values remain untransformed. Selection rank and diagnostic rank have different roles. If rank 15 is unsupported, the actual rank and explanation appear above the plot.

The candidate statistic is a Python approximation, `|studentised residual| > 2.5`, with leverage reported separately. It is not OPUS F Value/F Prob. Raw-spectrum overlays, iterative same-half calibration refits and final LOGO/Monte Carlo model execution are outside this release.

Use the cleaned workbook with the existing `_with_cleanup.py` modelling copies and keep the adjacent `.cleanup.json` file. Model results describe performance on the precleaned dataset.

