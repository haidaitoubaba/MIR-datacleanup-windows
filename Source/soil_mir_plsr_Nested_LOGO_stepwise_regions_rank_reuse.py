#!/usr/bin/env python3
"""
=============================================================================
SOIL MIR PLSR / NESTED TREATMENT LOGO PIPELINE
=============================================================================

Covers every section of the SOP:
  Section 1  — Load OPUS spectra + align reference data (replaces VLOOKUP/VBA)
  Section 2  — Remove extreme reference values
  Section 3  — Nested treatment LOGO calibration/validation splits
  Section 4  — Training-only preprocessing/rank optimization + outlier removal
  Section 5  — Validation metrics, plots, Excel export, and final model bundle

INSTALL DEPENDENCIES (run once in your terminal / Anaconda prompt):
    pip install brukeropusreader pandas numpy scipy scikit-learn matplotlib openpyxl joblib

USAGE:
  1. Edit the CONFIG block below to match your file paths and property name
  2. Run:  python soil_mir_plsr_Nested_LOGO_stepwise_regions_rank_reuse.py
  3. Check the output folder for nested treatment validation results, plots, Excel export,
     and PLSR_Nested_LOGO_<property>_Model.joblib
=============================================================================
"""

import os
import sys
import glob
import re
import warnings
import traceback
import time
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from joblib import Parallel, delayed
from sklearn.model_selection import LeaveOneGroupOut
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')           # headless rendering — safe on all platforms
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from scipy.signal import savgol_filter
from sklearn.cross_decomposition import PLSRegression
from sklearn.metrics import r2_score
import joblib
try:
    from threadpoolctl import threadpool_limits
except ImportError:
    threadpool_limits = None

SPECTRA_CACHE_VERSION = 2

try:
    from brukeropusreader import read_file as opus_read
    OPUS_READER = True
except ImportError:
    OPUS_READER = False


# =============================================================================
# USER CONFIGURATION  ←  EDIT THIS SECTION BEFORE RUNNING
# =============================================================================

CONFIG = {

    # ------------------------------------------------------------------
    # PATHS
    # ------------------------------------------------------------------

    # Folder containing your OPUS spectral files (the files ending .0 .1 .2 etc.)
    "spectra_dir": str(Path(__file__).resolve().parent / "Python code for MIR/data/spectra/Complete"),

    # Separate versioned cache in the optimized output folder; preserves the old cache.
    # Reused across all properties. Older caches are rejected by the version check.
    "spectra_cache": str(Path(__file__).resolve().parent / "Python code for MIR/output/Nested LOGO stepwise regions/opus_spectra_cache_v2.joblib"),

    # Excel file with reference data (Sample, File Name, Reference Value, and Group columns)
    "reference_excel": str(Path(__file__).resolve().parent / "Python code for MIR/data/reference/reference_value_ZL_trt.xlsx"),

    # Base folder where each property's output subfolder will be created automatically
    "output_base_dir": str(Path(__file__).resolve().parent / "Python code for MIR/output/Nested LOGO stepwise regions"),

    # Batch property modeling settings
    # Set property_sheets to "auto" to model every valid property sheet, or use
    # a list such as ["202_STC"] for one property.
    "run_all_properties": True,
    "property_sheets": ["202_STC_OPUS", "202_STN_OPUS"],  # "auto" or list of sheet names to model
    "metadata_sheet": "Property Metadata",
    "skip_sheets": ["Lookup table", "Transformation", "Property Metadata"],
    "default_units": "",
    "default_transform": "none",
    "continue_on_property_error": True,

    # Used only when run_all_properties is False
    "reference_sheet": "202_STN",

    # Sample IDs keep replicate spectra together in every split.
    "sample_id_col": "Sample",

    # Exact per-spectrum reference matching. Set None for legacy sample-key matching.
    "reference_file_col": "File Name",

    # Column name in Excel for the reference property values
    "reference_value_col": "Reference Value",

    # Nested LOGO validation settings
    "group_col": "Group",  # Hold out these treatment labels at both CV levels.
    "random_seed": 42,  # Retained search identifier; LOGO splits are deterministic.

    # ------------------------------------------------------------------
    # SPECTRAL SETTINGS
    # ------------------------------------------------------------------

    # Wavenumber range to include (cm-1)
    "wn_min": 600,
    "wn_max": 4000,

    # Default/fallback CO2 exclusion setting and CO2 range.
    # The Property Metadata sheet can override exclude_co2 per property using the Exclude CO2 column.
    # co2_exclude_min/max define the removed CO2 region whenever exclusion is enabled.
    "exclude_co2": False,
    "co2_exclude_min": 2300,
    "co2_exclude_max": 2400,

    # ------------------------------------------------------------------
    # MODELLING SETTINGS
    # ------------------------------------------------------------------

    # Maximum PLS ranks (factors) to test during optimization
    "max_rank": 15,

    # Percent units: 2.0 means 2%. Prefer lowest rank within this RMSECV increase.
    # Optional metadata column "RMSECV Tolerance (%)" overrides this per property.
    "rmsecv_tolerance_pct": 5.0,

    # Automatically divide the available range into equal-width windows (cm-1).
    # Backward search: 7 windows -> at most 28 evaluated sets per preprocessing.
    # All subsets are catalogued; only the stepwise path is fitted.
    "region_search_n_windows": 7,

    # Savitzky-Golay window for first derivative (must be odd, >= 5)
    "sg_window": 11,
    "sg_polyorder": 2,

    # Manual range filter on reference values (set to None to include all)
    # e.g. exclude samples with OC > 10%:  "ref_max": 10.0
    "ref_min": None,
    "ref_max": None,

    # Maximum fraction of unique calibration samples removed as concentration outliers
    # Strict <= cap: rounded down. Zero disables detection; fewer than 100 samples
    # permit no removal at 1%. All replicates of a removed sample are excluded.
    "outlier_max_pct": 0.01,

    # Performance settings
    # logo_n_jobs controls simultaneous thread workers; their spectral inputs are shared.
    # Use 1 for fully sequential execution, or 2-4 on most laptops/desktops.
    "logo_n_jobs": 4,

    # OPUS reading is independent of modelling; threads avoid process startup costs.
    "spectra_n_jobs": 4,

    # Keep numerical libraries from oversubscribing CPU threads inside each
    # modelling batch. Set to None to leave system defaults unchanged.
    "inner_thread_limit": 1,

    # 0 = quiet rank search, 1 = fold-level progress, 2 = every rank/fold detail
    "verbose": 1,


}


# =============================================================================
# PREPROCESSING FUNCTIONS
# (mirrors the four options in the OPUS Settings tab)
# =============================================================================


def first_deriv(X, window, poly):
    return savgol_filter(X, window_length=window, polyorder=poly, deriv=1, axis=1)


def straight_line_subtraction(X):
    """Remove linear baseline from each spectrum"""
    n = X.shape[1]
    x = np.arange(n, dtype=float)
    slopes = (X[:, -1] - X[:, 0]) / (n - 1)
    baselines = X[:, 0:1] + slopes[:, None] * x[None, :]
    return X - baselines


def snv(X):
    """Standard Normal Variate"""
    mu = X.mean(axis=1, keepdims=True)
    sd = X.std(axis=1, keepdims=True)
    sd[sd == 0] = 1e-10
    return (X - mu) / sd


def msc(X, reference=None):
    """Multiplicative Scatter Correction"""
    if reference is None:
        reference = X.mean(axis=0)
    X = np.asarray(X, dtype=float)
    reference = np.asarray(reference, dtype=float)

    ref_centered = reference - reference.mean()
    denom_ref = np.dot(ref_centered, ref_centered)
    if denom_ref == 0:
        return X.copy()

    x_mean = X.mean(axis=1)
    slopes = ((X - x_mean[:, None]) @ ref_centered) / denom_ref
    intercepts = x_mean - slopes * reference.mean()
    slopes = np.where(slopes == 0, 1e-10, slopes)
    return (X - intercepts[:, None]) / slopes[:, None]

PREPROCESSING_NAMES = (
    "1st Derivative",
    "1st Deriv + SLS",
    "1st Deriv + SNV",
    "1st Deriv + MSC",
)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def normalise_key(s):
    """Convert 'NSSH - 1' or 'NSSH-1' → 'NSSH_1'"""
    s = str(s).strip()
    s = s.replace(" - ", "_").replace("-", "_").replace(" ", "")
    return s.upper()


def extract_file_key(filename):
    """Extract 'NSSH_1' from 'NSSH_1_2_A5.0'"""
    base = os.path.splitext(os.path.basename(filename))[0]
    parts = base.split("_")
    return (parts[0] + "_" + parts[1]).upper() if len(parts) >= 2 else base.upper()


def rmse(y_true, y_pred):
    return np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))


def rpiq_score(y_true, y_pred):
    """
    Ratio of Performance to InterQuartile distance.
    RPIQ = IQR(y_true) / RMSECV
    More robust than RPD for skewed distributions (e.g. P2O5, OC).
    Interpretation mirrors RPD thresholds but shifted:
      < 1.5  = poor
      1.5-2  = fair
      2-3    = good
      > 3    = excellent
    """
    iqr = float(np.percentile(y_true, 75) - np.percentile(y_true, 25))
    return iqr / rmse(y_true, y_pred)

# =============================================================================
# TRANSFORMATION HELPERS
# =============================================================================


def apply_transform(y, method):
    """Apply the chosen transformation to reference values."""
    from scipy.stats import boxcox, yeojohnson as yj
    m = method.lower().strip()
    if m in ("none", ""):
        return y, None
    elif m == "sqrt":
        if np.any(y < 0):
            raise ValueError("sqrt transform requires all reference values >= 0")
        return np.sqrt(y), None
    elif m == "log":
        if np.any(y < 0):
            raise ValueError("log transform requires all reference values >= 0")
        return np.log1p(y), None          # log(y + 1) — safe for zeros
    elif m == "log10":
        if np.any(y < 0):
            raise ValueError("log10 transform requires all reference values >= 0")
        return np.log10(y + 1), None
    elif m == "cbrt":
        return np.cbrt(y), None           # cube root handles negatives naturally
    elif m == "boxcox":
        if np.any(y <= 0):
            raise ValueError("boxcox requires all reference values > 0 (no zeros)")
        y_t, lam = boxcox(y)
        return y_t, lam
    elif m == "yeojohnson":
        y_t, lam = yj(y)
        return y_t, lam
    else:
        raise ValueError(f"Unknown transform '{method}'. "
                         f"Valid options: none, sqrt, log, log10, cbrt, boxcox, yeojohnson")


def back_transform(y_t, method, lam=None):
    """Reverse the transformation back to original units."""
    from scipy.special import inv_boxcox
    m = method.lower().strip()
    if m in ("none", ""):
        return y_t
    elif m == "sqrt":
        return np.clip(y_t, 0, None) ** 2
    elif m == "log":
        return np.expm1(y_t)              # exp(y) - 1  (inverse of log1p)
    elif m == "log10":
        return 10 ** y_t - 1
    elif m == "cbrt":
        return y_t ** 3
    elif m == "boxcox":
        return inv_boxcox(y_t, lam)
    elif m == "yeojohnson":
        values = np.asarray(y_t, dtype=float)
        result = np.empty_like(values)
        positive = values >= 0
        if lam == 0:
            result[positive] = np.expm1(values[positive])
        else:
            result[positive] = np.expm1(np.log1p(lam * values[positive]) / lam)
        if lam == 2:
            result[~positive] = -np.expm1(-values[~positive])
        else:
            power = 2 - lam
            result[~positive] = -np.expm1(np.log1p(-power * values[~positive]) / power)
        return result
    else:
        return y_t


def bias_score(y_true, y_pred):
    return float(np.mean(np.array(y_true) - np.array(y_pred)))


VALID_TRANSFORMS = {"none", "sqrt", "log", "log10", "cbrt", "boxcox", "yeojohnson"}


def safe_name(name):
    """Return a filesystem-safe name for property output folders/files."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name).strip())
    text = text.strip("._-")
    return text or "property"


def parse_bool_metadata(value, default):
    """Parse optional Excel boolean metadata with a default fallback."""
    if pd.isna(value):
        return default
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        if value == 1:
            return True
        if value == 0:
            return False

    text = str(value).strip().lower()
    if text == "":
        return default
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    raise ValueError(
        f"Invalid boolean metadata value '{value}'. "
        "Use TRUE/FALSE, Yes/No, Y/N, 1/0, or leave blank."
    )


def validate_config(cfg: dict, check_paths: bool = False) -> None:
    """Reject invalid settings before loading spectra or launching model searches."""
    for key, minimum in (("max_rank", 1),
                         ("sg_window", 5), ("sg_polyorder", 1)):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
            raise ValueError(f"{key} must be an integer >= {minimum}.")
    if cfg["sg_window"] % 2 != 1 or cfg["sg_polyorder"] >= cfg["sg_window"]:
        raise ValueError("sg_window must be odd and greater than sg_polyorder.")
    for key, include_endpoints in (("outlier_max_pct", True),):
        value = float(cfg[key])
        valid = 0 <= value <= 1 if include_endpoints else 0 < value < 1
        if not valid:
            raise ValueError(f"{key} must be {'between 0 and 1 inclusive' if include_endpoints else 'strictly between 0 and 1'}.")
    for key in ("logo_n_jobs", "spectra_n_jobs"):
        value = cfg.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value == 0:
            raise ValueError(f"{key} must be a nonzero integer.")
    limit = cfg.get("inner_thread_limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, np.integer)) or limit < 1):
        raise ValueError("inner_thread_limit must be a positive integer or None.")
    for low, high in (("wn_min", "wn_max"), ("co2_exclude_min", "co2_exclude_max")):
        if not np.isfinite([cfg[low], cfg[high]]).all() or cfg[low] >= cfg[high]:
            raise ValueError(f"{low} must be finite and less than {high}.")
    for key in ("ref_min", "ref_max"):
        if cfg.get(key) is not None and not np.isfinite(cfg[key]):
            raise ValueError(f"{key} must be finite or None.")
    if cfg.get("ref_min") is not None and cfg.get("ref_max") is not None and cfg["ref_min"] > cfg["ref_max"]:
        raise ValueError("ref_min must not exceed ref_max.")
    validate_tolerance(cfg.get("rmsecv_tolerance_pct", 2.0))
    validate_window_count(cfg.get("region_search_n_windows", 10))
    if check_paths:
        if not os.path.isdir(cfg["spectra_dir"]):
            raise FileNotFoundError(f"Spectra directory does not exist: {cfg['spectra_dir']}")
        if not os.path.isfile(cfg["reference_excel"]):
            raise FileNotFoundError(f"Reference workbook does not exist: {cfg['reference_excel']}")


def validate_reference_frame(frame: pd.DataFrame, cfg: dict) -> None:
    """Allow missing reference values to be skipped; reject malformed nonempty values."""
    required = [cfg["sample_id_col"], cfg["reference_value_col"]]
    if cfg.get("reference_file_col"):
        required.append(cfg["reference_file_col"])
    if cfg.get("group_col"):
        required.append(cfg["group_col"])
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"Reference sheet is missing columns: {sorted(missing)}")
    values = frame[cfg["reference_value_col"]].dropna()
    try:
        numeric = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Nonempty reference values must be numeric.") from exc
    if not np.isfinite(numeric).all():
        raise ValueError("Reference values must be finite.")
    if not cfg.get("group_col"):
        raise ValueError("Nested LOGO requires a treatment group_col.")
    labelled = frame[cfg["reference_value_col"]].notna()
    if frame.loc[labelled, cfg["sample_id_col"]].isna().any():
        raise ValueError("Every nonempty reference value must have a sample ID.")

    usable = labelled & frame[cfg["sample_id_col"]].notna()
    if cfg.get("reference_file_col"):
        usable &= frame[cfg["reference_file_col"]].notna()
    labels = frame.loc[usable, cfg["group_col"]]
    if labels.isna().any() or labels.astype(str).str.strip().eq("").any():
        raise ValueError("Usable reference rows must have a treatment label.")
    pairs = frame.loc[usable, [cfg["sample_id_col"], cfg["group_col"]]].copy()
    pairs[cfg["sample_id_col"]] = pairs[cfg["sample_id_col"]].map(normalise_key)
    if pairs.groupby(cfg["sample_id_col"])[cfg["group_col"]].nunique().gt(1).any():
        raise ValueError("Each unique sample must belong to one treatment.")


def validate_training_data(X: np.ndarray, y: np.ndarray, keys: np.ndarray,
                           group_labels: np.ndarray, cfg: dict) -> None:
    """Check retained rows and every requested outer split before any PLS search."""
    if X.ndim != 2 or len(X) == 0 or not (len(X) == len(y) == len(keys) == len(group_labels)):
        raise ValueError("Retained spectra, references, sample IDs and group labels must have matching nonempty rows.")
    if X.shape[1] < cfg["sg_window"] or not np.isfinite(X).all() or not np.isfinite(y).all():
        raise ValueError("Spectra/references must be finite and the spectrum must fit the derivative window.")
    sample_frame = pd.DataFrame({"key": keys, "group_label": group_labels})
    if sample_frame.groupby("key")["group_label"].nunique().gt(1).any():
        raise ValueError("Each unique sample must belong to one group.")
    method = cfg.get("transform", "none")
    if method not in VALID_TRANSFORMS:
        raise ValueError(f"Unknown response transform: {method}")
    if method == "boxcox" and np.any(y <= 0):
        raise ValueError("Box-Cox requires positive reference values.")
    if method in {"sqrt", "log", "log10"} and np.any(y < 0):
        raise ValueError(f"{method} requires nonnegative reference values.")
    outer_splits = treatment_logo_splits(keys, group_labels, minimum_treatments=3)
    for train, validation in outer_splits:
        cv_splits_for_training(keys[train], group_labels[train], cfg, 0)



def discover_property_sheets(cfg, workbook=None):
    """Find property sheets that contain the required reference columns."""
    excel_path = cfg["reference_excel"]
    if workbook is None:
        with pd.ExcelFile(excel_path) as workbook:
            return discover_property_sheets(cfg, workbook)
    xl = workbook
    skip_sheets = set(cfg.get("skip_sheets", []))
    requested = cfg.get("property_sheets", "auto")

    if requested == "auto":
        candidates = [s for s in xl.sheet_names if s not in skip_sheets]
    elif isinstance(requested, str):
        candidates = [requested]
    else:
        candidates = list(requested)

    required_cols = [cfg["sample_id_col"], cfg["reference_value_col"]]
    if cfg.get("reference_file_col"):
        required_cols.append(cfg["reference_file_col"])
    group_col = cfg.get("group_col")
    if group_col:
        required_cols.append(group_col)

    property_sheets = []
    for sheet in candidates:
        if sheet not in xl.sheet_names:
            raise KeyError(f"Requested sheet '{sheet}' was not found in {excel_path}")

        cols = list(xl.parse(sheet_name=sheet, nrows=0).columns)
        missing = [col for col in required_cols if col not in cols]
        if missing:
            if requested == "auto":
                print(f"  Skipping non-property sheet '{sheet}' — missing columns: {missing}")
                continue
            raise KeyError(f"Sheet '{sheet}' is missing required columns: {missing}")

        property_sheets.append(sheet)

    if not property_sheets:
        raise RuntimeError("No valid property sheets were found in the reference workbook.")

    return property_sheets


def load_property_metadata(cfg, workbook=None):
    """Load per-property units and transforms from the metadata worksheet."""
    excel_path = cfg["reference_excel"]
    metadata_sheet = cfg.get("metadata_sheet", "Property Metadata")
    if workbook is None:
        with pd.ExcelFile(excel_path) as workbook:
            return load_property_metadata(cfg, workbook)
    xl = workbook

    if metadata_sheet not in xl.sheet_names:
        print(f"  Warning: metadata sheet '{metadata_sheet}' was not found; using defaults.")
        return {}

    df = xl.parse(sheet_name=metadata_sheet)
    required_cols = ["Property", "Units", "Transform"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise KeyError(f"Metadata sheet '{metadata_sheet}' is missing columns: {missing}")

    metadata = {}
    for _, row in df.iterrows():
        if pd.isna(row["Property"]):
            continue

        prop = str(row["Property"]).strip()
        if "Field" in df.columns and not pd.isna(row["Field"]):
            field = str(row["Field"]).strip()
            if field:
                prop = f"{field}_{prop}"
        units = "" if pd.isna(row["Units"]) else str(row["Units"]).strip()
        transform = row["Transform"]
        transform = cfg.get("default_transform", "none") if pd.isna(transform) else str(transform).strip().lower()
        exclude_co2 = None
        if "Exclude CO2" in df.columns:
            raw_exclude_co2 = row["Exclude CO2"]
            if not pd.isna(raw_exclude_co2) and str(raw_exclude_co2).strip() != "":
                exclude_co2 = parse_bool_metadata(raw_exclude_co2, cfg.get("exclude_co2", False))

        if transform not in VALID_TRANSFORMS:
            raise ValueError(
                f"Invalid transform '{transform}' for property '{prop}' in metadata sheet. "
                f"Valid options: {sorted(VALID_TRANSFORMS)}"
            )

        raw_tolerance = row.get("RMSECV Tolerance (%)", np.nan)
        tolerance = None if pd.isna(raw_tolerance) or str(raw_tolerance).strip() == "" else validate_tolerance(raw_tolerance)
        metadata[prop] = {"units": units, "transform": transform, "exclude_co2": exclude_co2,
                          "rmsecv_tolerance_pct": tolerance}

    return metadata


def build_property_config(base_cfg, property_sheet, metadata):
    """Create a property-specific config from base CONFIG and workbook metadata."""
    cfg = base_cfg.copy()
    meta = metadata.get(property_sheet, {})
    warnings_list = []

    if not meta:
        warnings_list.append("missing metadata row; used default units/transform")

    units = meta.get("units", cfg.get("default_units", ""))
    transform = meta.get("transform", cfg.get("default_transform", "none"))
    exclude_co2 = meta.get("exclude_co2")
    if exclude_co2 is None:
        exclude_co2 = cfg.get("exclude_co2", False)
    if transform not in VALID_TRANSFORMS:
        raise ValueError(f"Invalid transform '{transform}' for property '{property_sheet}'")

    cfg["reference_sheet"] = property_sheet
    cfg["property_name"] = property_sheet
    cfg["property_safe_name"] = safe_name(property_sheet)
    cfg["units"] = units
    cfg["transform"] = transform
    cfg["exclude_co2"] = bool(exclude_co2)
    tolerance = meta.get("rmsecv_tolerance_pct")
    cfg["rmsecv_tolerance_pct"] = validate_tolerance(
        cfg.get("rmsecv_tolerance_pct", 2.0) if tolerance is None else tolerance)
    cfg["output_dir"] = os.path.join(cfg["output_base_dir"], cfg["property_safe_name"])
    cfg["metadata_warning"] = "; ".join(warnings_list)
    return cfg

# =============================================================================
# SECTION 1 — LOAD SPECTRA
# =============================================================================


def _opus_file_signature(fpath):
    st = os.stat(fpath)
    return {
        "name": os.path.basename(fpath),
        "path": os.path.abspath(fpath),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }


def _read_one_opus_file(fpath):
    try:
        data = opus_read(fpath)

        ab = None
        for key in ['AB', 'IgSm', 'ScSm', 'ScRf', 'Sc']:
            if key in data and hasattr(data[key], '__len__'):
                ab = np.array(data[key], dtype=float)
                break
        if ab is None:
            return None, fpath, "absorbance block not found"

        wn = None
        for pk in ['AB Data Parameter', 'AB_Data_Parameter',
                   'Sc Data Parameter', 'IgSm Data Parameter']:
            if pk in data:
                p = data[pk]
                fxv = float(p['FXV'])
                lxv = float(p['LXV'])
                wn = np.linspace(fxv, lxv, len(ab))
                break
        if wn is None:
            raise ValueError("Wavenumber metadata is missing; cannot align this spectrum reliably.")

        return (os.path.basename(fpath), ab, wn), None, None
    except Exception as e:
        return None, fpath, str(e)


def _spectra_cache_is_valid(cache_pkg, files):
    expected = [_opus_file_signature(f) for f in files]
    return (cache_pkg.get("cache_version") == SPECTRA_CACHE_VERSION
            and cache_pkg.get("file_signatures") == expected)


def validate_wavenumbers(axis: np.ndarray) -> np.ndarray:
    """Return a finite, strictly monotonic 1-D axis (either direction)."""
    axis = np.asarray(axis, dtype=float)
    if axis.ndim != 1 or len(axis) < 2 or not np.isfinite(axis).all():
        raise ValueError("Wavenumbers must contain at least two finite coordinates.")
    differences = np.diff(axis)
    if not (np.all(differences > 0) or np.all(differences < 0)):
        raise ValueError("Wavenumbers must be strictly ascending or descending.")
    return axis


def resample_spectrum(values: np.ndarray, source_axis: np.ndarray,
                      target_axis: np.ndarray) -> np.ndarray:
    """Interpolate a single spectrum; reject extrapolation beyond source coverage."""
    source_axis = validate_wavenumbers(source_axis)
    target_axis = validate_wavenumbers(target_axis)
    values = np.asarray(values, dtype=float)
    if values.shape != source_axis.shape or not np.isfinite(values).all():
        raise ValueError("Spectrum values must be finite and match their wavenumber axis.")
    if target_axis.min() < source_axis.min() or target_axis.max() > source_axis.max():
        raise ValueError("Spectrum does not cover the target wavenumber grid; extrapolation is disabled.")
    if np.array_equal(source_axis, target_axis):
        return values
    if source_axis[0] > source_axis[-1]:
        source_axis, values = source_axis[::-1], values[::-1]
    return np.interp(target_axis, source_axis, values)


def align_spectral_library(raw_spectra: dict, raw_axes: dict) -> tuple:
    """Use the modal-length spectrum's grid within coverage shared by all spectra.

    Each spectrum remains a row. No extrapolation or averaging of replicates occurs.
    The original grid direction is retained for compatibility with existing training.
    """
    from collections import Counter
    raw_axes = {name: validate_wavenumbers(axis) for name, axis in raw_axes.items()}
    modal_length = Counter(map(len, raw_axes.values())).most_common(1)[0][0]
    axis = next(axis for axis in raw_axes.values() if len(axis) == modal_length)
    lower = max(np.min(axis) for axis in raw_axes.values())
    upper = min(np.max(axis) for axis in raw_axes.values())
    common_axis = np.asarray(axis)[(axis >= lower) & (axis <= upper)]
    if len(common_axis) < 2:
        raise ValueError("Spectra have insufficient shared wavenumber coverage.")
    if len(common_axis) != len(axis):
        print(f"  Shared spectral coverage: {common_axis.min():.2f}–{common_axis.max():.2f} cm⁻¹ "
              f"({len(common_axis)} points; endpoints trimmed, no extrapolation)")
    spectra = {}
    for name, values in raw_spectra.items():
        try:
            spectra[name] = resample_spectrum(values, raw_axes[name], common_axis)
        except ValueError as exc:
            raise ValueError(f"Invalid spectral grid for {name}: {exc}") from exc
    return spectra, common_axis


def load_opus_files(spectra_dir, cache_path=None, n_jobs=-1):
    """
    Load all OPUS binary files from a directory using brukeropusreader.
    Uses a shared joblib cache so the full spectral library is parsed once and
    reused for different soil-property sheets.
    """
    if not OPUS_READER:
        raise ImportError(
            "brukeropusreader is not installed.\n"
            "Run:  pip install brukeropusreader\n"
            "Or export your spectra to CSV from OPUS and use load_spectra_csv()."
        )

    patterns = [os.path.join(spectra_dir, f"*.{i}") for i in range(10)]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files))

    if not files:
        raise FileNotFoundError(
            f"No OPUS spectral files found in:\n  {spectra_dir}\n"
            "Check that the path is correct and files have numeric extensions (.0 .1 .2 ...)"
        )

    if cache_path is None:
        cache_path = os.path.join(spectra_dir, "opus_spectra_cache.joblib")

    print(f"  Found {len(files)} OPUS files")

    if os.path.exists(cache_path):
        try:
            cache_pkg = joblib.load(cache_path)
            if _spectra_cache_is_valid(cache_pkg, files):
                print(f"  Loading spectra from cache: {cache_path}", flush=True)
                return cache_pkg["spectra"], cache_pkg["wavenumbers"]
            print("  Spectra cache is stale; rebuilding from OPUS files.", flush=True)
        except Exception as e:
            print(f"  Could not read spectra cache ({e}); rebuilding from OPUS files.", flush=True)

    print(f"  Reading OPUS files in parallel (n_jobs={n_jobs})...", flush=True)
    t0 = time.time()
    results = Parallel(n_jobs=n_jobs, prefer="threads", verbose=0)(
        delayed(_read_one_opus_file)(fpath) for fpath in files
    )

    raw_spectra = {}
    raw_wn = {}
    failed = []
    for payload, failed_path, err in results:
        if payload is None:
            failed.append((failed_path, err))
            continue
        fname, ab, wn = payload
        raw_spectra[fname] = ab
        raw_wn[fname] = wn

    print(f"  Finished reading OPUS files in {fmt_time(time.time() - t0)}: "
          f"{len(raw_spectra)} successful, {len(failed)} failed", flush=True)

    if failed:
        print(f"  Warning: could not read {len(failed)} file(s) — skipped")
        for fpath, err in failed[:10]:
            print(f"    {os.path.basename(fpath)}: {err}")
        if len(failed) > 10:
            print(f"    ... and {len(failed) - 10} more")

    if not raw_spectra:
        raise RuntimeError("No OPUS spectra were successfully loaded.")

    spectra, common_wn = align_spectral_library(raw_spectra, raw_wn)

    print(f"  Successfully loaded: {len(spectra)} spectra")

    cache_pkg = {
        "cache_version": SPECTRA_CACHE_VERSION,
        "spectra_dir": os.path.abspath(spectra_dir),
        "file_signatures": [_opus_file_signature(f) for f in files],
        "spectra": spectra,
        "wavenumbers": common_wn,
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        joblib.dump(cache_pkg, cache_path, compress=3)
        print(f"  Spectra cache saved: {cache_path}", flush=True)
    except Exception as e:
        print(f"  Warning: could not save spectra cache ({e})", flush=True)

    return spectra, common_wn


def load_spectra_csv(csv_path):
    """
    Alternative loader for CSV export from OPUS.
    Expected format:  rows = samples, columns = wavenumbers,
                      first column = file name (index).
    """
    df  = pd.read_csv(csv_path, index_col=0)
    wn  = np.array([float(c) for c in df.columns])
    sp  = {str(idx): row.values.astype(float) for idx, row in df.iterrows()}
    print(f"  Loaded {len(sp)} spectra from CSV")
    return sp, wn


def align_to_reference(spectra_dict, wavenumbers, cfg, reference_frame=None):
    """
    Match spectral file names to reference values.
    Match File Name exactly when configured; use Sample to group replicates.
    Legacy sample-key matching is supported when reference_file_col is None.
    Completely immune to row-drift caused by missing spectra.
    """
    ref_df = (reference_frame.copy() if reference_frame is not None else
              pd.read_excel(cfg["reference_excel"], sheet_name=cfg["reference_sheet"]))
    validate_reference_frame(ref_df, cfg)
    wavenumbers = validate_wavenumbers(wavenumbers)
    sample_col = cfg["sample_id_col"]
    val_col  = cfg["reference_value_col"]
    group_col = cfg.get("group_col")
    if group_col and group_col not in ref_df.columns:
        raise KeyError(
            f"Group column '{group_col}' was not found in the reference sheet."
        )

    file_col = cfg.get("reference_file_col")
    matched_refs, matched_keys, matched_group_labels, spectra_list = [], [], [], []
    unmatched = []
    if file_col:
        # Match each spectral filename to its own reference row, independent of order.
        usable = ref_df.dropna(subset=[sample_col, val_col, file_col] + ([group_col] if group_col else []))
        lookup = {}
        for _, row in usable.iterrows():
            name = str(row[file_col]).strip()
            if name in lookup:
                raise ValueError(f"Duplicate reference filename in {cfg['reference_sheet']}: {name}")
            lookup[name] = (float(row[val_col]), normalise_key(row[sample_col]), str(row[group_col]) if group_col else "")
        for name in sorted(spectra_dict):
            if name not in lookup:
                unmatched.append(name)
                continue
            value, key, group_label = lookup[name]
            matched_refs.append(value)
            matched_keys.append(key)
            matched_group_labels.append(group_label)
            spectra_list.append(spectra_dict[name])
        missing_files = sorted(set(lookup).difference(spectra_dict))
        if missing_files:
            raise ValueError(f"{len(missing_files)} referenced spectra are missing from spectra_dir; examples: {missing_files[:5]}")
    else:
        # Retain the legacy sample-key schema for other workbooks.
        ref_lookup = {}
        for _, row in ref_df.iterrows():
            value = row[val_col]
            group_label = row[group_col] if group_col else ""
            if pd.isna(value) or (group_col and pd.isna(group_label)):
                continue
            ref_lookup.setdefault(normalise_key(row[sample_col]), []).append((float(value), str(group_label)))
        usage = {}
        for name in sorted(spectra_dict):
            key = extract_file_key(name)
            if key not in ref_lookup:
                unmatched.append(name)
                continue
            records = ref_lookup[key]
            count = usage.get(key, 0)
            value, group_label = records[count % len(records)]
            usage[key] = count + 1
            matched_refs.append(value)
            matched_keys.append(key)
            matched_group_labels.append(group_label)
            spectra_list.append(spectra_dict[name])

    if unmatched:
        print(f"\n  WARNING: {len(unmatched)} spectra could not be matched to a reference value:")
        for f in unmatched[:10]:
            print(f"    {f}")
        if len(unmatched) > 10:
            print(f"    … and {len(unmatched)-10} more")

    print(f"  Matched: {len(spectra_list)} spectra  ({len(set(matched_keys))} unique samples)")

    if not spectra_list:
        raise ValueError("No spectra matched usable reference records.")
    X   = np.array(spectra_list, dtype=float)
    y   = np.array(matched_refs, dtype=float)
    kys = np.array(matched_keys)
    group_labels = np.array(matched_group_labels)

    # Apply wavenumber range filter
    mask = (wavenumbers >= cfg["wn_min"]) & (wavenumbers <= cfg["wn_max"])
    if cfg.get("exclude_co2", False):
        co2 = (wavenumbers >= cfg["co2_exclude_min"]) & (wavenumbers <= cfg["co2_exclude_max"])
        mask = mask & ~co2
        print(f"  CO2 region excluded: {cfg['co2_exclude_min']}–{cfg['co2_exclude_max']} cm⁻¹")

    if mask.sum() < cfg["sg_window"]:
        raise ValueError("Retained wavenumber range is too short for the derivative window.")

    print(f"  Wavenumber points after range filter: {mask.sum()} "
          f"({wavenumbers[mask].max():.0f}–{wavenumbers[mask].min():.0f} cm⁻¹)")

    return X[:, mask], y, kys, group_labels, wavenumbers[mask]


# =============================================================================
# SECTION 2 — REMOVE EXTREME REFERENCE VALUES
# =============================================================================


def remove_extreme_values(X, y, keys, group_labels, cfg, out_dir):
    print(f"\n  Reference value statistics before filtering:")
    print(f"    N={len(y)}  min={y.min():.4f}  max={y.max():.4f}  "
          f"mean={y.mean():.4f}  sd={y.std():.4f}")

    # Plot distribution
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(y, bins=30, color='#2a7886', edgecolor='white', linewidth=0.5)
    ax.set_xlabel(f"{cfg['property_name']} ({cfg['units']})")
    ax.set_ylabel("Count")
    ax.set_title("Reference Value Distribution  —  check for extreme outliers before proceeding")
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "01_reference_distribution.png"), dpi=150)
    plt.close()

    include = np.ones(len(y), dtype=bool)
    if cfg.get("ref_min") is not None:
        include &= (y >= cfg["ref_min"])
    if cfg.get("ref_max") is not None:
        include &= (y <= cfg["ref_max"])

    n_excl = (~include).sum()
    if n_excl:
        print(f"  Excluded {n_excl} samples outside user-defined range "
              f"[{cfg.get('ref_min', '–∞')}, {cfg.get('ref_max', '+∞')}]")
    else:
        print("  No extreme value filter applied  "
              "(set 'ref_min'/'ref_max' in CONFIG to exclude ranges)")

    return X[include], y[include], keys[include], group_labels[include]


# =============================================================================
# NESTED LOGO RESAMPLING HELPERS
# =============================================================================


def validate_tolerance(value) -> float:
    """Percent units: enter 2 for 2%, not 0.02 or an Excel percentage cell."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("RMSECV tolerance must be a finite nonnegative percentage.")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("RMSECV tolerance must be numeric; enter 2 for 2%.") from exc
    if not np.isfinite(value) or value < 0:
        raise ValueError("RMSECV tolerance must be finite and nonnegative.")
    return value


def validate_window_count(value) -> int:
    # Enumeration requires 2**N - 1 candidates; prevent accidental unbounded allocation.
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not 1 <= value <= 16:
        raise ValueError("region_search_n_windows must be an integer from 1 to 16; search grows as 2**N - 1.")
    return int(value)


def automatic_region_definitions(cfg: dict, axis: np.ndarray) -> tuple:
    """Enumerate all subsets of nonoverlapping, equal-wavenumber-width windows.

    Window boundaries come from the available axis, not hand-picked soil bands.
    Every retained coordinate belongs to exactly one window. Full range is added
    by prepare_region_config, so the full subset is omitted here to avoid duplicates.
    """
    count = validate_window_count(cfg.get("region_search_n_windows", 10))
    edges = np.linspace(axis.min(), axis.max(), count + 1)
    membership = np.clip(np.searchsorted(edges, axis, side="right") - 1, 0, count - 1)
    windows = []
    for index in range(count):
        points = axis[membership == index]
        if len(points) < 2:
            raise ValueError(f"Automatic window {index + 1} has fewer than two retained coordinates; reduce region_search_n_windows.")
        windows.append({"Window": f"W{index + 1:02d}", "Grid Lower": float(edges[index]),
                        "Grid Upper": float(edges[index + 1]), "Actual Lower": float(points.min()),
                        "Actual Upper": float(points.max()), "Spectral Points": len(points)})
    definitions = {}
    for bits in range(1, (1 << count) - 1):
        chosen = [window for i, window in enumerate(windows) if bits & (1 << i)]
        definitions[" + ".join(window["Window"] for window in chosen)] = [
            (window["Actual Lower"], window["Actual Upper"]) for window in chosen]
    return definitions, windows


def prepare_region_config(cfg: dict, wavenumbers: np.ndarray) -> dict:
    """Prepare immutable feature indices and contiguous intervals on the retained grid.

    Full range is always included. A gap is a skipped column or a spacing greater
    than 1.5 times the median source-grid step (e.g. the removed CO2 band).
    Each retained segment must fit the Savitzky-Golay window.
    """
    axis = validate_wavenumbers(wavenumbers)
    automatic, windows = automatic_region_definitions(cfg, axis)
    definitions = {"Full range": [(cfg["wn_min"], cfg["wn_max"])], **automatic}
    regions = {}
    step = float(np.median(np.abs(np.diff(axis))))
    for name, intervals in definitions.items():
        if not isinstance(name, str) or not name.strip() or not intervals:
            raise ValueError("Each region needs a nonempty name and a list of intervals.")
        mask = np.zeros(len(axis), dtype=bool)
        requested = []
        for interval in intervals:
            if len(interval) != 2 or not np.isfinite(interval).all():
                raise ValueError(f"Invalid interval in region {name!r}: {interval}")
            low, high = sorted(map(float, interval))
            if low == high:
                raise ValueError(f"Region {name!r} contains a zero-width interval.")
            requested.append([low, high])
            mask |= (axis >= low) & (axis <= high)
        indices = np.flatnonzero(mask)
        selected_axis = axis[indices]
        breaks = (np.diff(indices) > 1) | (np.abs(np.diff(selected_axis)) > 1.5 * step)
        segments = np.split(selected_axis, np.flatnonzero(breaks) + 1) if len(indices) else []
        lengths = [len(segment) for segment in segments]
        actual = [[float(segment[0]), float(segment[-1])] for segment in segments]
        description = "; ".join(f"{a:.6f}–{b:.6f}" for a, b in actual) or "No retained points"
        reason = "" if lengths and min(lengths) >= cfg["sg_window"] else "An included interval has fewer points than sg_window."
        regions[name] = {"indices": indices, "segment_lengths": lengths,
                         "intervals": actual, "requested_intervals": requested,
                         "label": description, "error": reason}
    if all(region["error"] for region in regions.values()):
        raise ValueError("No candidate region has sufficiently long spectral intervals.")
    return dict(cfg, _regions=regions, _region_windows=windows, _search_wavenumbers=axis.copy())


def region_metadata(name: str, region: dict) -> dict:
    return {"Region": name, "Regions (cm-1)": region["label"],
            "Spectral Points": len(region["indices"])}


def select_region(X: np.ndarray, cfg: dict, name: str) -> tuple:
    """Select columns before preprocessing; copy only the chosen region's matrix."""
    region = cfg["_regions"][name]
    if region["error"]:
        raise ValueError(region["error"])
    return X[:, region["indices"]], dict(cfg, _segment_lengths=region["segment_lengths"])


def segment_slices(lengths: list, width: int) -> list:
    if not lengths or any(not isinstance(n, (int, np.integer)) or n < 1 for n in lengths) or sum(lengths) != width:
        raise ValueError("Saved interval lengths do not match the spectral matrix.")
    boundaries = np.r_[0, np.cumsum(lengths)]
    return [slice(int(a), int(b)) for a, b in zip(boundaries[:-1], boundaries[1:])]


def spectral_derivative(X: np.ndarray, cfg: dict) -> np.ndarray:
    """Differentiate each included interval independently; never cross a gap."""
    lengths = cfg.get("_segment_lengths", [X.shape[1]])
    segments = segment_slices(lengths, X.shape[1])
    if min(lengths) < cfg["sg_window"]:
        raise ValueError("Every included interval must fit the derivative window.")
    return np.concatenate([first_deriv(X[:, segment], cfg["sg_window"], cfg["sg_polyorder"])
                           for segment in segments], axis=1)


def choose_with_tolerance(frame: pd.DataFrame, error_column: str, tolerance: float) -> tuple:
    """Lowest rank within relative error tolerance, then error/preprocessing/region.

    Zero tolerance admits only exact minimum-error ties. Region width is not an
    additional penalty; it remains visible in the comparison table.
    """
    tolerance = validate_tolerance(tolerance)
    eligible = frame[np.isfinite(frame[error_column]) & (frame[error_column] >= 0)].copy()
    if "Eligible" in eligible:
        eligible = eligible[eligible["Eligible"]]
    if eligible.empty:
        raise RuntimeError("No eligible finite candidate is available for selection.")
    minimum = float(eligible[error_column].min())
    threshold = minimum * (1 + tolerance / 100)
    within = eligible[eligible[error_column] <= threshold]
    best = within.sort_values(["Rank", error_column, "Preprocessing", "Region"]).iloc[0]
    increase = 100 * (float(best[error_column]) / minimum - 1) if minimum > 0 else 0.0
    return best, {"Tolerance (%)": tolerance, "Minimum RMSECV": minimum,
                  "Allowed RMSECV": threshold, "RMSECV Increase (%)": increase}


def build_tolerance_comparison(summary: pd.DataFrame, configured_tolerance: float) -> pd.DataFrame:
    """Selection sensitivity using one run's final-search results, not rerun validation."""
    configured_tolerance = validate_tolerance(configured_tolerance)
    records = []
    for tolerance in sorted({0.0, 1.0, 2.0, 5.0, configured_tolerance}):
        row, decision = choose_with_tolerance(summary, "RMSECV", tolerance)
        records.append({**decision, **row[["Region", "Regions (cm-1)", "Spectral Points",
                                          "Preprocessing", "Rank", "RMSECV"]].to_dict(),
                        "Used for Export": tolerance == configured_tolerance,
                        "Interpretation": "Final calibration CV selection sensitivity; not held-out validation"})
    return pd.DataFrame(records)


def predict_model_bundle(bundle: dict, X: np.ndarray, source_wavenumbers: np.ndarray) -> np.ndarray:
    """Predict external rows using the saved grid and gap-aware preprocessing state.

    Prefer raw, continuous source spectra. Every target interval must be covered;
    interpolation never bridges a gap in the source axis or extrapolates.
    """
    X = np.asarray(X, dtype=float)
    source = validate_wavenumbers(source_wavenumbers)
    target = validate_wavenumbers(bundle["wavenumbers"])
    if X.ndim != 2 or X.shape[1] != len(source) or not np.isfinite(X).all():
        raise ValueError("External matrix must be finite and match the source axis.")
    if np.array_equal(source, target):
        aligned = X
    else:
        if source[0] > source[-1]:
            source, X = source[::-1], X[:, ::-1]
        step = float(np.median(np.diff(source)))
        source_segments = np.split(np.arange(len(source)), np.flatnonzero(np.diff(source) > 1.5 * step) + 1)
        aligned = np.empty((len(X), len(target)))
        for segment in segment_slices(bundle["preprocessing_state"]["segment_lengths"], len(target)):
            target_part = target[segment]
            covering = next((idx for idx in source_segments if source[idx[0]] <= target_part.min()
                             and source[idx[-1]] >= target_part.max()), None)
            if covering is None or len(covering) < 2:
                raise ValueError("External spectra do not continuously cover a selected model interval.")
            aligned[:, segment] = np.vstack([resample_spectrum(row[covering], source[covering], target_part) for row in X])
    matrix = transform_preprocessor(bundle["preprocessing_state"], aligned)
    predictions = back_transform(bundle["pls_model"].predict(matrix).ravel(),
                                 bundle["response_transform"], bundle["response_transform_parameter"])
    if not np.isfinite(predictions).all():
        raise ValueError("External predictions are non-finite after inverse transformation.")
    return predictions


def preprocessor_state(prep_name: str, derivative: np.ndarray, cfg: dict) -> dict:
    """Build serializable state; derivative rows must be training spectra only."""
    if prep_name not in PREPROCESSING_NAMES:
        raise ValueError(f"Unknown preprocessing option: {prep_name}")
    return {"name": prep_name, "window": cfg["sg_window"],
            "polyorder": cfg["sg_polyorder"],
            "segment_lengths": list(cfg.get("_segment_lengths", [derivative.shape[1]])),
            "algorithm": "per_interval_derivative_v1",
            "msc_reference": derivative.mean(axis=0) if prep_name == "1st Deriv + MSC" else None}


def fit_preprocessor(prep_name, X_train, cfg):
    """Fit preprocessing state from calibration rows only."""
    derivative = spectral_derivative(X_train, cfg)
    return preprocessor_state(prep_name, derivative, cfg)


def _postprocess_derivative(prep_name, X_deriv, msc_reference=None, segment_lengths=None):
    if prep_name == "1st Derivative":
        return X_deriv
    if prep_name == "1st Deriv + SLS":
        segments = segment_slices(segment_lengths or [X_deriv.shape[1]], X_deriv.shape[1])
        return np.concatenate([straight_line_subtraction(X_deriv[:, segment]) for segment in segments], axis=1)
    if prep_name == "1st Deriv + SNV":
        return snv(X_deriv)
    if prep_name == "1st Deriv + MSC":
        return msc(X_deriv, reference=msc_reference)
    raise ValueError(f"Unknown preprocessing option: {prep_name}")


def transform_preprocessor(fitted, X):
    prep_name = fitted["name"]
    X_out = spectral_derivative(X, {"sg_window": fitted["window"], "sg_polyorder": fitted["polyorder"],
                                    "_segment_lengths": fitted.get("segment_lengths", [X.shape[1]])})
    return _postprocess_derivative(
        prep_name,
        X_out,
        msc_reference=fitted.get("msc_reference"),
        segment_lengths=fitted.get("segment_lengths"),
    )


def fit_transform_preprocessor(prep_name, X_train, cfg):
    """Return fitted state and transformed (spectra, wavenumbers) matrix."""
    derivative = spectral_derivative(X_train, cfg)
    fitted = preprocessor_state(prep_name, derivative, cfg)
    return fitted, _postprocess_derivative(prep_name, derivative, fitted["msc_reference"], fitted["segment_lengths"])


def grouped_average_frame(y_true, y_pred, groups):
    df = pd.DataFrame({
        "Sample Key": groups,
        "Measured": np.asarray(y_true, dtype=float),
        "Predicted": np.asarray(y_pred, dtype=float),
    })
    return df.groupby("Sample Key", as_index=False).agg({
        "Measured": "mean",
        "Predicted": "mean",
    })


def regression_metrics(y_true, y_pred, reference_iqr=None):
    """Metrics on original-unit sample averages, with reusable reference IQR."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    error = y_true - y_pred
    error_rmse = float(np.sqrt(np.mean(error ** 2)))
    iqr = float(np.subtract(*np.percentile(y_true, [75, 25]))) if reference_iqr is None else reference_iqr
    ratio = iqr / error_rmse if error_rmse else (np.inf if iqr else np.nan)
    return {"R2": float(r2_score(y_true, y_pred)) if len(y_true) >= 2 and np.ptp(y_true) > 0 else np.nan, "RMSE": error_rmse,
            "RPIQ": float(ratio), "Bias": float(error.mean())}


def grouped_metric_state(y_original: np.ndarray, groups: np.ndarray) -> tuple:
    """Cache row-to-sample indices, counts, means and IQR for repeated scoring."""
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    measured = np.bincount(inverse, weights=y_original) / counts
    iqr = float(np.subtract(*np.percentile(measured, [75, 25])))
    return inverse, counts, measured, iqr


def treatment_logo_splits(keys, treatments, minimum_treatments=2):
    """Validated row splits; sample IDs remain the metric/replicate unit."""
    keys, treatments = np.asarray(keys), np.asarray(treatments)
    if len(keys) != len(treatments) or not len(keys):
        raise ValueError("Sample and treatment arrays must have matching nonempty rows.")
    if pd.isna(treatments).any() or any(not str(t).strip() for t in treatments):
        raise ValueError("Every retained sample needs a treatment label.")
    frame = pd.DataFrame({"sample": keys, "treatment": treatments})
    if frame.groupby("sample")["treatment"].nunique().gt(1).any():
        raise ValueError("Each unique sample must belong to one treatment.")
    if len(pd.unique(treatments)) < minimum_treatments:
        raise ValueError(f"At least {minimum_treatments} retained treatments are required.")
    splits = list(LeaveOneGroupOut().split(np.zeros(len(keys)), groups=treatments))
    coverage = np.zeros(len(keys), dtype=int)
    for train, test in splits:
        if len(train) < 2 or len(np.unique(keys[train])) < 2:
            raise ValueError("Every training fold needs at least two unique samples.")
        if set(treatments[train]) & set(treatments[test]) or set(keys[train]) & set(keys[test]):
            raise ValueError("Training and validation must not share treatments or samples.")
        coverage[test] += 1
    if not np.all(coverage == 1):
        raise ValueError("Every row must be held out exactly once.")
    return splits


def cv_splits_for_training(groups, strata, cfg, random_state):
    """Inner leave-one-treatment-out splits; groups are sample identifiers."""
    return treatment_logo_splits(groups, strata)


def build_cv_preprocessing_cache(X, splits, prep_name, cfg, derivative=None):
    """Cache one option's fold matrices; share stateless derivatives across options."""
    if derivative is None:
        derivative = spectral_derivative(X, cfg)
    fold_cache = []
    for train_idx, test_idx in splits:
        train_derivative = derivative[train_idx]
        fitted = preprocessor_state(prep_name, train_derivative, cfg)
        fold_cache.append({
            "train_idx": train_idx, "test_idx": test_idx,
            "X_train_prep": _postprocess_derivative(prep_name, train_derivative, fitted["msc_reference"], fitted["segment_lengths"]),
            "X_test_prep": _postprocess_derivative(prep_name, derivative[test_idx], fitted["msc_reference"], fitted["segment_lengths"]),
        })
    return fold_cache


def build_cv_response_cache(y_original: np.ndarray, splits: list, method: str) -> list:
    """Fit response transforms on each inner training fold, never its held-out rows."""
    return [apply_transform(y_original[train_idx], method) for train_idx, _ in splits]


def grouped_cv_predict_plsr_from_cache(fold_cache, y_t, y_original, groups, rank,
                                      transform_method, lam, response_cache=None,
                                      metric_state=None):
    """Return original-unit CV predictions and sample metrics.

    Legacy y_t/lam arguments are accepted, but inner folds fit their own transforms.
    Fold-transformed predictions cannot share one lambda, so are not returned.
    """
    if response_cache is None:
        response_cache = build_cv_response_cache(
            y_original, [(f["train_idx"], f["test_idx"]) for f in fold_cache], transform_method)
    if metric_state is None:
        metric_state = grouped_metric_state(y_original, groups)
    predictions = np.full(len(y_original), np.nan)
    for fold, (train_response, fold_lambda) in zip(fold_cache, response_cache):
        train_X = fold["X_train_prep"]
        n_comp = min(rank, train_X.shape[0] - 1, train_X.shape[1])
        if n_comp < 1:
            raise ValueError("Insufficient training rows for a PLS component.")
        pls = PLSRegression(n_components=n_comp, scale=False)
        pls.fit(train_X, train_response)
        predictions[fold["test_idx"]] = back_transform(
            pls.predict(fold["X_test_prep"]).ravel(), transform_method, fold_lambda)
    if not np.isfinite(predictions).all():
        raise ValueError("CV predictions are missing or non-finite after inverse transformation.")
    inverse, counts, measured, iqr = metric_state
    predicted = np.bincount(inverse, weights=predictions) / counts
    return predictions, regression_metrics(measured, predicted, iqr)


def grouped_cv_predict_plsr(X, y_t, y_original, groups, strata, prep_name, rank,
                            cfg, transform_method, lam, random_state):
    """Convenience wrapper using the same cached CV implementation as rank search."""
    splits = cv_splits_for_training(groups, strata, cfg, random_state)
    cache = build_cv_preprocessing_cache(X, splits, prep_name, cfg)
    return grouped_cv_predict_plsr_from_cache(
        cache, y_t, y_original, groups, rank, transform_method, lam)


def cv_rank_path(fold_cache, y_original, groups, maximum_rank, method, response_cache):
    """Fit maximum rank once per fold; reconstruct each prefix's regression.

    Degenerate or failed paths fall back to independent fits, preserving valid
    lower ranks. No fitted state is shared between folds or region/prep options.
    """
    from scipy.linalg import pinv
    capacity = min(min(f["X_train_prep"].shape[0] - 1, f["X_train_prep"].shape[1]) for f in fold_cache)
    limit = min(maximum_rank, capacity)
    predictions = np.full((maximum_rank, len(y_original)), np.nan)
    errors = ["" for _ in range(maximum_rank)]
    for rank in range(limit, maximum_rank):
        errors[rank] = f"Rank exceeds the inner-fold capacity ({capacity})."
    for fold, (response, fold_lambda) in zip(fold_cache, response_cache):
        train, test = fold["X_train_prep"], fold["X_test_prep"]
        path = None
        try:
            model = PLSRegression(n_components=limit, scale=False).fit(train, response)
            if not np.all(np.linalg.norm(model.x_weights_, axis=0) > 0):
                raise ValueError("PLS stopped before maximum rank")
            path = model
        except Exception:
            pass
        for index in range(limit):
            rank = index + 1
            try:
                if path is None:
                    pred = PLSRegression(n_components=rank, scale=False).fit(train, response).predict(test).ravel()
                else:
                    weights = path.x_weights_[:, :rank]
                    loadings = path.x_loadings_[:, :rank]
                    coef = weights @ pinv(loadings.T @ weights) @ path.y_loadings_[:, :rank].T
                    pred = ((test - train.mean(axis=0)) @ coef + np.mean(response, axis=0)).ravel()
                pred = back_transform(pred, method, fold_lambda)
                if not np.isfinite(pred).all():
                    raise ValueError("Non-finite inverse-transformed predictions")
                predictions[index, fold["test_idx"]] = pred
            except Exception as exc:
                errors[index] = str(exc)
    inverse, counts, measured, iqr = grouped_metric_state(y_original, groups)
    results = []
    for index, pred in enumerate(predictions):
        if errors[index] or not np.isfinite(pred).all():
            results.append((None, errors[index] or "Missing CV predictions"))
        else:
            averaged = np.bincount(inverse, weights=pred) / counts
            results.append((regression_metrics(measured, averaged, iqr), ""))
    return predictions, results


def optimize_plsr_grouped(X, y_t, y_original, groups, strata, cfg, transform_method, lam, random_state):
    """Separate backward paths per preprocessing; choose by tolerance over all visited sets.

    Each step follows the child's minimum RMSECV across ranks. The final choice
    applies the rank tolerance once to all evaluated successful candidates.
    """
    splits = cv_splits_for_training(groups, strata, cfg, random_state)
    responses = build_cv_response_cache(y_original, splits, transform_method)
    records = []
    windows = tuple(w["Window"] for w in cfg["_region_windows"])
    maximum_rank = int(cfg["max_rank"])
    for prep in PREPROCESSING_NAMES:
        evaluated = {}
        def evaluate(chosen):
            name = "Full range" if len(chosen) == len(windows) else " + ".join(chosen)
            if name in evaluated:
                return evaluated[name]
            region = cfg["_regions"][name]
            try:
                region_X, region_cfg = select_region(X, cfg, name)
                cache = build_cv_preprocessing_cache(region_X, splits, prep, region_cfg)
                _, results = cv_rank_path(cache, y_original, groups, maximum_rank, transform_method, responses)
            except Exception as exc:
                results = [(None, str(exc))] * maximum_rank
            scores = []
            for rank, (metrics, error) in enumerate(results, 1):
                record = {**region_metadata(name, region), "Preprocessing": prep, "Rank": rank,
                          "Windows Retained": len(chosen), "RMSECV": np.nan, "R2_CV": np.nan,
                          "RPIQ_CV": np.nan, "Bias_CV": np.nan, "Status": "Failed", "Error": error}
                if metrics is not None:
                    record.update(RMSECV=metrics["RMSE"], R2_CV=metrics["R2"],
                                  RPIQ_CV=metrics["RPIQ"], Bias_CV=metrics["Bias"], Status="Success")
                    scores.append(metrics["RMSE"])
                records.append(record)
            evaluated[name] = min(scores) if scores else np.inf
            return evaluated[name]
        current = windows
        evaluate(current)
        while len(current) > 1:
            children = [tuple(w for w in current if w != removed) for removed in current]
            ranked = [(evaluate(child), child) for child in children]
            score, current = min(ranked, key=lambda item: (item[0], item[1]))
            if cfg.get("verbose", 1):
                print(f"    {prep} | {len(evaluated)} region sets evaluated | remaining windows {len(current)}", flush=True)
            if not np.isfinite(score):
                break
    frame = pd.DataFrame(records)
    row, decision = choose_with_tolerance(frame, "RMSECV", cfg.get("rmsecv_tolerance_pct", 2.0))
    best = {**row.to_dict(), **decision, "RMSE": float(row["RMSECV"]), "Rank": int(row["Rank"])}
    frame["Within Tolerance"] = np.isfinite(frame["RMSECV"]) & (frame["RMSECV"] <= decision["Allowed RMSECV"])
    frame["Selected"] = False
    frame.loc[row.name, "Selected"] = True
    frame["Tolerance (%)"] = decision["Tolerance (%)"]
    return frame, best


def remove_concentration_outliers_logo(X, y_t, groups, cfg, prep_name, rank):
    """
    Remove concentration outliers from calibration data only.
    Flagging is row-based, but removal is expanded to whole sample IDs to preserve grouping.
    """
    n_samples = len(np.unique(groups))
    fraction = float(cfg["outlier_max_pct"])
    if not 0 <= fraction <= 1:
        raise ValueError("outlier_max_pct must be between 0 and 1.")
    # Decimal avoids a binary rounding artifact at exact integer allowances.
    max_n = int(Decimal(n_samples) * Decimal(str(fraction)))
    if fraction == 0:
        if cfg.get("verbose", 1):
            print("    Outliers: detection disabled; allowed=0; removed=0")
        return np.ones(len(y_t), dtype=bool), []
    fitted, X_prep = fit_transform_preprocessor(prep_name, X, cfg)
    n_comp = min(rank, X_prep.shape[0] - 2, X_prep.shape[1])
    if n_comp < 1:
        return np.ones(len(y_t), dtype=bool), []

    pls = PLSRegression(n_components=n_comp, scale=False)
    pls.fit(X_prep, y_t)
    y_hat = pls.predict(X_prep).ravel()
    resid = y_t - y_hat
    T = pls.x_scores_
    lev = np.sum((T @ np.linalg.pinv(T.T @ T)) * T, axis=1).clip(0, 1)
    mse = np.mean(resid ** 2)
    stud = resid / np.sqrt(mse * (1 - lev + 1e-10)) if mse > 0 else np.zeros_like(resid)

    lev_thr = 3.0 * lev.mean()
    res_thr = 2.5
    row_flagged = (np.abs(stud) > res_thr) | (lev > lev_thr)
    if not row_flagged.any():
        if cfg.get("verbose", 1):
            print(f"    Outlier samples: flagged=0; allowed={max_n}; removed=0")
        return np.ones(len(y_t), dtype=bool), []

    row_score = np.abs(stud) + lev / (lev.mean() + 1e-10)
    flag_df = pd.DataFrame({
        "Sample Key": groups,
        "Flagged": row_flagged,
        "Score": row_score,
    })
    sample_scores = (
        flag_df[flag_df["Flagged"]]
        .groupby("Sample Key")["Score"]
        .max()
        .sort_values(ascending=False)
    )

    removed_samples = list(sample_scores.index[:max_n])
    if cfg.get("verbose", 1):
        print(f"    Outlier samples: flagged={len(sample_scores)}; allowed={max_n}; removed={len(removed_samples)}")
    keep = ~np.isin(groups, removed_samples)
    return keep, removed_samples


def numerical_thread_context(cfg: dict):
    limit = cfg.get("inner_thread_limit", 1)
    return threadpool_limits(limits=int(limit)) if limit is not None and threadpool_limits is not None else nullcontext()


def fit_final_nested_logo_model(X, y_original, groups, wavenumbers, cfg, optimization_df, group_labels):
    """Fit the final bundle under the same numerical thread limit as folds."""
    with numerical_thread_context(cfg):
        return _fit_final_nested_logo_model(X, y_original, groups, wavenumbers, cfg, optimization_df, group_labels)


def _fit_final_nested_logo_model(X, y_original, groups, wavenumbers, cfg, optimization_df, group_labels):
    """Fit and package one final model using all retained calibration samples."""
    if "_regions" not in cfg:
        cfg = prepare_region_config(cfg, wavenumbers)
    transform_method = cfg.get("transform", "none")
    y_t, lam = apply_transform(y_original, transform_method)
    search, best = optimize_plsr_grouped(X, y_t, y_original, groups, group_labels, cfg,
                                       transform_method, lam, int(cfg["random_seed"]))
    initial_X, initial_cfg = select_region(X, cfg, best["Region"])
    keep, removed_samples = remove_concentration_outliers_logo(
        initial_X, y_t, groups, initial_cfg, best["Preprocessing"], best["Rank"])
    y_clean, groups_clean = y_original[keep], groups[keep]
    treatment_logo_splits(groups_clean, group_labels[keep], minimum_treatments=3)
    y_clean_t, lam = apply_transform(y_clean, transform_method)
    initial_search = search.assign(Phase="Initial calibration search")
    if removed_samples:
        search, best = optimize_plsr_grouped(X[keep], y_clean_t, y_clean, groups_clean,
            group_labels[keep], cfg, transform_method, lam, int(cfg["random_seed"]))
    selection_summary = search.assign(Phase="Final calibration search", **{
        "Selection Scope": "Internal CV on final calibration data; not held-out validation"})
    calibration_search = (pd.concat([initial_search, selection_summary], ignore_index=True)
                          if removed_samples else selection_summary.copy())
    X_clean, region_cfg = select_region(X[keep], cfg, best["Region"])
    selected_region = cfg["_regions"][best["Region"]]
    selected_wavenumbers = np.asarray(wavenumbers)[selected_region["indices"]]
    fitted_prep, X_clean_prep = fit_transform_preprocessor(
        best["Preprocessing"], X_clean, region_cfg
    )
    n_comp = min(best["Rank"], X_clean_prep.shape[0] - 1, X_clean_prep.shape[1])
    if n_comp < 1:
        raise RuntimeError("The selected PLS rank is invalid for the final calibration data.")
    pls = PLSRegression(n_components=n_comp, scale=False)
    pls.fit(X_clean_prep, y_clean_t)

    model_bundle = {
        "preprocessing_state": fitted_prep,
        "preprocessing": fitted_prep,
        "pls_model": pls,
        "model": pls,
        "selected_preprocessing": best["Preprocessing"],
        "selected_rank": int(best["Rank"]),
        "requested_rank": int(best["Rank"]),
        "fitted_rank": int(n_comp),
        "selected_calibration_rmsecv": best["RMSECV"],
        "final_model_selection_rule": "lowest rank within internal RMSECV tolerance in a separate final calibration search; ties by error/preprocessing/region",
        "rmsecv_tolerance_pct": cfg.get("rmsecv_tolerance_pct", 2.0),
        "minimum_calibration_rmsecv": best["Minimum RMSECV"],
        "actual_rmsecv_increase_pct": best["RMSECV Increase (%)"],
        "selected_region": best["Region"],
        "region_search_n_windows": cfg.get("region_search_n_windows", 10),
        "region_search_windows": cfg["_region_windows"],
        "region_search_rule": "backward stepwise path per preprocessing over automatically generated windows",
        "selected_regions_cm1": selected_region["intervals"],
        "regions_label": selected_region["label"],
        "requested_regions_cm1": selected_region["requested_intervals"],
        "bundle_version": 3,
        "calibration_search_results": calibration_search,
        "validation_scope": "Held-out Nested LOGO performance of the complete selection procedure",
        "prediction_helper": "predict_model_bundle in this region-aware module",
        "wavenumbers": selected_wavenumbers.copy(),
        "exclude_co2": bool(cfg.get("exclude_co2", False)),
        "co2_exclude_min": cfg.get("co2_exclude_min"),
        "co2_exclude_max": cfg.get("co2_exclude_max"),
        "response_transform": transform_method,
        "response_transform_parameter": lam,
        "property_name": cfg["property_name"],
        "units": cfg["units"],
        "training_sample_count": int(len(np.unique(groups_clean))),
        "training_spectrum_count": int(len(X_clean)),
        "removed_sample_ids": list(removed_samples),
        "validation_method": "nested_treatment_logo",
        "outer_fold_count": int(len(np.unique(group_labels))),
        "inner_validation_method": "leave_one_treatment_out",
        "treatment_column": cfg["group_col"],
        "training_treatments": sorted(map(str, np.unique(group_labels[keep]))),
        "calibration_scope": "all retained calibration samples",
    }
    return model_bundle, best, removed_samples, selection_summary


def run_one_nested_logo_fold(fold_num, X, y_original, keys, group_labels, cfg, base_seed, split):
    with numerical_thread_context(cfg):
        return _run_one_nested_logo_fold(fold_num, X, y_original, keys, group_labels, cfg, base_seed, split)


def _run_one_nested_logo_fold(fold_num, X, y_original, keys, group_labels, cfg, base_seed, split):
    fold_t0 = time.time()
    random_state = base_seed + fold_num - 1
    transform_method = cfg.get("transform", "none")
    verbose = int(cfg.get("verbose", 1))

    train_mask, val_mask = split
    held_out = str(group_labels[val_mask][0])
    train_keys, val_keys = set(keys[train_mask]), set(keys[val_mask])

    X_train, y_train = X[train_mask], y_original[train_mask]
    keys_train, group_labels_train = keys[train_mask], group_labels[train_mask]
    X_val, y_val = X[val_mask], y_original[val_mask]
    keys_val = keys[val_mask]

    y_train_t, lam = apply_transform(y_train, transform_method)

    if verbose >= 1:
        print(f"\n  Outer fold {fold_num}, held-out treatment {held_out} — "
              f"calibration samples={len(train_keys)}, validation samples={len(val_keys)}")

    initial_opt_t0 = time.time()
    pre_results, pre_best = optimize_plsr_grouped(
        X_train, y_train_t, y_train, keys_train, group_labels_train,
        cfg, transform_method, lam, random_state,
    )
    initial_opt_seconds = time.time() - initial_opt_t0

    outlier_t0 = time.time()
    outlier_X, outlier_cfg = select_region(X_train, cfg, pre_best["Region"])
    keep_train, removed_samples = remove_concentration_outliers_logo(
        outlier_X, y_train_t, keys_train, outlier_cfg,
        pre_best["Preprocessing"], int(pre_best["Rank"]),
    )
    outlier_detection_seconds = time.time() - outlier_t0
    outlier_reopt_seconds = 0.0

    if removed_samples:
        if verbose >= 1:
            print(f"    Removed {len(removed_samples)} calibration outlier sample(s); re-optimizing.")
        X_train_clean = X_train[keep_train]
        y_train_clean = y_train[keep_train]
        keys_train_clean = keys_train[keep_train]
        group_labels_train_clean = group_labels_train[keep_train]
        y_train_clean_t, lam = apply_transform(y_train_clean, transform_method)
        outlier_reopt_t0 = time.time()
        final_results, final_best = optimize_plsr_grouped(
            X_train_clean, y_train_clean_t, y_train_clean,
            keys_train_clean, group_labels_train_clean, cfg, transform_method, lam, random_state,
        )
        outlier_reopt_seconds = time.time() - outlier_reopt_t0
    else:
        X_train_clean = X_train
        y_train_clean = y_train
        keys_train_clean = keys_train
        group_labels_train_clean = group_labels_train
        y_train_clean_t = y_train_t
        final_results = pre_results
        final_best = pre_best

    final_fit_t0 = time.time()
    selected_X, selected_cfg = select_region(X_train_clean, cfg, final_best["Region"])
    fitted_prep, X_train_prep = fit_transform_preprocessor(final_best["Preprocessing"], selected_X, selected_cfg)
    n_comp = min(int(final_best["Rank"]), X_train_prep.shape[0] - 1, X_train_prep.shape[1])
    pls = PLSRegression(n_components=n_comp, scale=False)
    pls.fit(X_train_prep, y_train_clean_t)

    selected_val, _ = select_region(X_val, cfg, final_best["Region"])
    X_val_prep = transform_preprocessor(fitted_prep, selected_val)
    y_val_pred_t = pls.predict(X_val_prep).ravel()
    y_val_pred = back_transform(y_val_pred_t, transform_method, lam)
    if not np.isfinite(y_val_pred).all():
        raise ValueError("Validation predictions are non-finite after inverse transformation.")

    val_avg = grouped_average_frame(y_val, y_val_pred, keys_val)
    metrics = regression_metrics(val_avg["Measured"], val_avg["Predicted"])
    val_avg.insert(0, "Held-out Treatment", held_out)
    val_avg.insert(0, "Outer Fold", fold_num)
    final_fit_seconds = time.time() - final_fit_t0
    fold_seconds = time.time() - fold_t0

    fold_record = {
        "Outer Fold": fold_num,
        "Held-out Treatment": held_out,
        "Inner Folds": len(np.unique(group_labels_train_clean)),
        "Removed Sample IDs": "; ".join(map(str, removed_samples)),
        "Calibration Samples": len(np.unique(keys_train_clean)),
        "Validation Samples": len(np.unique(keys_val)),
        "Calibration Spectra": len(X_train_clean),
        "Validation Spectra": len(X_val),
        "Selected Region": final_best["Region"],
        "Regions (cm-1)": final_best["Regions (cm-1)"],
        "Spectral Points": final_best["Spectral Points"],
        "Tolerance (%)": cfg.get("rmsecv_tolerance_pct", 2.0),
        "Selected Internal RMSECV": final_best["RMSECV"],
        "Minimum Internal RMSECV": final_best["Minimum RMSECV"],
        "RMSECV Increase (%)": final_best["RMSECV Increase (%)"],
        "Selected Preprocessing": final_best["Preprocessing"],
        "Selected Rank": int(final_best["Rank"]),
        "Fitted Rank": int(n_comp),
        "Outlier Samples Removed": len(removed_samples),
        "R2 Validation": metrics["R2"],
        "RMSE Validation": metrics["RMSE"],
        "RPIQ Validation": metrics["RPIQ"],
        "Bias Validation": metrics["Bias"],
        "Initial Optimization Seconds": round(initial_opt_seconds, 2),
        "Outlier Detection Seconds": round(outlier_detection_seconds, 2),
        "Outlier Reoptimization Seconds": round(outlier_reopt_seconds, 2),
        "Final Fit Validation Seconds": round(final_fit_seconds, 2),
        "Outer Fold Seconds": round(fold_seconds, 2),
    }

    if verbose >= 1:
        print(f"    Validation: R2={metrics['R2']:.4f} "
              f"RMSE={metrics['RMSE']:.4f} RPIQ={metrics['RPIQ']:.2f} "
              f"elapsed={fmt_time(fold_seconds)}")
    final_results = final_results.assign(Phase="Final search")
    if removed_samples:
        initial_results = pre_results.assign(Phase="Initial search")
        final_results = pd.concat([initial_results, final_results], ignore_index=True)
    return fold_record, val_avg, final_results.assign(**{"Outer Fold": fold_num, "Held-out Treatment": held_out})


# =============================================================================
# MAIN PIPELINE
# =============================================================================


def fmt_time(seconds):
    """Format seconds into a readable string."""
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    if h:    return f"{h}h {m}m {s}s"
    elif m:  return f"{m}m {s}s"
    else:    return f"{s}s"


def timed_section(title, pipeline_t0, section_num, total_sections):
    """Print a section header with elapsed pipeline time."""
    elapsed = time.time() - pipeline_t0
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  [{section_num}/{total_sections}]  {title}")
    print(f"  Pipeline elapsed: {fmt_time(elapsed)}")
    print(bar)
    return time.time()   # returns section start time


def summarize_fold_metrics(fold_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize the distribution of validation metrics across held-out treatments."""
    metric_cols = ["R2 Validation", "RMSE Validation", "RPIQ Validation", "Bias Validation"]
    summary_records = []
    for col in metric_cols:
        vals = fold_df[col].dropna().astype(float)
        summary_records.append({
            "Metric": col,
            "Mean": vals.mean(),
            "SD": vals.std(ddof=1),
            "Median": vals.median(),
            "Min": vals.min(),
            "Max": vals.max(),
        })
    return pd.DataFrame(summary_records)


def save_nested_logo_plots(fold_df, prediction_df, cfg, out_dir, pdf_path):
    """Write PDF and PNG plots independently of workbook/model serialization."""
    prop, units = cfg["property_name"], cfg["units"]
    with PdfPages(pdf_path) as pdf:
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        for ax, col, label in zip(
            axes,
            ["R2 Validation", "RMSE Validation", "RPIQ Validation"],
            ["Validation R²", f"Validation RMSE ({units})", "Validation RPIQ"],
        ):
            ax.boxplot(fold_df[col].dropna(), patch_artist=True,
                       boxprops=dict(facecolor="#b8d8ba", color="#355c3a"),
                       medianprops=dict(color="#1d3320", linewidth=1.5))
            ax.set_title(label)
            ax.set_xticks([])
            ax.grid(True, axis="y", alpha=0.25)
        fig.suptitle(f"{prop} — {len(fold_df)} outer treatment folds")
        plt.tight_layout()
        pdf.savefig(fig)
        plt.savefig(os.path.join(out_dir, "LOGO_metric_boxplots.png"), dpi=150)
        plt.close()

        fig, ax = plt.subplots(figsize=(7, 7))
        ax.scatter(prediction_df["Measured"], prediction_df["Predicted"], alpha=0.35, s=18)
        lims = [
            min(prediction_df["Measured"].min(), prediction_df["Predicted"].min()) * 0.97,
            max(prediction_df["Measured"].max(), prediction_df["Predicted"].max()) * 1.03,
        ]
        ax.plot(lims, lims, "k--", lw=1)
        ax.set_xlim(lims)
        ax.set_ylim(lims)
        ax.set_xlabel(f"Measured {prop} ({units})")
        ax.set_ylabel(f"Validation predicted {prop} ({units})")
        ax.set_title(f"{prop} — pooled validation predictions across held-out treatments")
        ax.grid(True, alpha=0.25)
        plt.tight_layout()
        pdf.savefig(fig)
        plt.savefig(os.path.join(out_dir, "LOGO_pooled_predicted_vs_measured.png"), dpi=150)
        plt.close()

        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        for ax, col, label in zip(
            axes,
            ["R2 Validation", "RMSE Validation", "RPIQ Validation"],
            ["Validation R²", f"Validation RMSE ({units})", "Validation RPIQ"],
        ):
            ax.hist(fold_df[col].dropna(), bins=12, color="#4f86c6", edgecolor="white")
            ax.set_title(label)
            ax.grid(True, axis="y", alpha=0.25)
        fig.suptitle(f"{prop} — Nested LOGO metric distributions")
        plt.tight_layout()
        pdf.savefig(fig)
        plt.savefig(os.path.join(out_dir, "LOGO_metric_histograms.png"), dpi=150)
        plt.close()


def write_excel_table(writer, frame: pd.DataFrame, sheet_name: str,
                      max_data_rows: int = 1_048_575) -> None:
    """Split large search tables over numbered sheets, preserving every candidate."""
    if max_data_rows < 1:
        raise ValueError("max_data_rows must be positive.")
    for part, start in enumerate(range(0, max(len(frame), 1), max_data_rows), start=1):
        suffix = "" if part == 1 else f" {part}"
        name = sheet_name[:31 - len(suffix)] + suffix
        frame.iloc[start:start + max_data_rows].to_excel(writer, sheet_name=name, index=False)


def save_nested_logo_results(
    fold_df,
    prediction_df,
    optimization_df,
    cfg,
    out_dir,
    model_bundle=None,
    final_model_selection=None,
    tolerance_comparison=None,
):
    os.makedirs(out_dir, exist_ok=True)
    prop = cfg["property_name"]
    prop_file = cfg.get("property_safe_name", safe_name(prop))
    units = cfg["units"]
    excel_path = os.path.join(out_dir, f"PLSR_Nested_LOGO_{prop_file}_Results.xlsx")
    pdf_path = os.path.join(out_dir, f"PLSR_Nested_LOGO_{prop_file}_Plots.pdf")
    model_path = os.path.join(out_dir, f"PLSR_Nested_LOGO_{prop_file}_Model.joblib")

    pooled = regression_metrics(prediction_df["Measured"], prediction_df["Predicted"])
    summary_df = pd.DataFrame([{"Metric": name, "Value": value,
        "Scope": "Pooled outer predictions; one prediction per sample"}
        for name, value in pooled.items()])
    fold_summary = summarize_fold_metrics(fold_df)

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        fold_summary.to_excel(writer, sheet_name="Fold Descriptive Summary", index=False)
        if model_bundle is not None:
            write_excel_table(writer, model_bundle["calibration_search_results"], "Calibration Search")
        fold_df.to_excel(writer, sheet_name="Outer Fold Results", index=False)
        prediction_df.to_excel(writer, sheet_name="Validation Predictions", index=False)
        write_excel_table(writer, optimization_df, "Optimization Results")
        if final_model_selection is not None:
            write_excel_table(writer, final_model_selection, "Final Model Selection")
        if tolerance_comparison is not None:
            tolerance_comparison.to_excel(writer, sheet_name="Tolerance Comparison", index=False)
        if "_regions" in cfg:
            catalog = pd.DataFrame([{**region_metadata(name, region),
                                     "Requested Intervals": str(region["requested_intervals"]),
                                     "Status": "Invalid" if region["error"] else "Catalogued (may not be evaluated)", "Error": region["error"]}
                                    for name, region in cfg["_regions"].items()])
            write_excel_table(writer, catalog, "Region Candidates")
            pd.DataFrame(cfg["_region_windows"]).to_excel(writer, sheet_name="Region Windows", index=False)

    if model_bundle is not None:
        joblib.dump(model_bundle, model_path, compress=3)

    save_nested_logo_plots(fold_df, prediction_df, cfg, out_dir, pdf_path)

    print(f"  Excel results saved to: {excel_path}")
    print(f"  Plots saved to: {pdf_path}")
    if model_bundle is not None:
        print(f"  Final model bundle saved to: {model_path}")
    return summary_df, excel_path, pdf_path, model_path


def save_batch_summary(batch_records, cfg):
    os.makedirs(cfg["output_base_dir"], exist_ok=True)
    out_path = os.path.join(cfg["output_base_dir"], "Batch_Modeling_Summary.xlsx")
    pd.DataFrame(batch_records).to_excel(out_path, index=False)
    print(f"\n  Batch summary saved to: {out_path}")
    return out_path


def run_nested_logo_folds(X, y, keys, group_labels, cfg):
    """Run folds with one process-wide BLAS limit; all shared inputs are read-only.

    Threads avoid copying the spectral library or depending on process semaphores.
    Workers call the internal fold function so threadpool limits are not nested
    concurrently and restored in an unpredictable order.
    """
    splits = treatment_logo_splits(keys, group_labels, minimum_treatments=3)
    workers = int(cfg.get("logo_n_jobs", 1))
    seed = int(cfg.get("random_seed", 42))
    with numerical_thread_context(cfg):
        if workers == 1:
            return [_run_one_nested_logo_fold(i, X, y, keys, group_labels, cfg, seed, split) for i, split in enumerate(splits, 1)]
        if cfg.get("verbose", 1):
            print(f"  Running Nested LOGO folds with {workers} thread workers")
        return Parallel(n_jobs=workers, prefer="threads", require="sharedmem",
                        verbose=5 if cfg.get("verbose", 1) >= 2 else 0)(
            delayed(_run_one_nested_logo_fold)(i, X, y, keys, group_labels, cfg, seed, split)
            for i, split in enumerate(splits, 1)
        )


def run_property_pipeline(cfg, spectra_dict, wavenumbers, reference_frame=None):
    validate_config(cfg)
    pipeline_t0 = time.time()
    TOTAL_SECTIONS = 5
    profile = {}

    out_dir = cfg["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    n_cores = os.cpu_count() or 1
    print("=" * 60)
    print("  SOIL MIR PLSR / NESTED LOGO VALIDATION PIPELINE")
    print("=" * 60)
    print(f"  Property  : {cfg['property_name']} ({cfg['units']})")
    print(f"  Transform : {cfg['transform']}")
    print(f"  Reference : {cfg['reference_excel']}")
    print(f"  Sheet     : {cfg['reference_sheet']}")
    print(f"  Output    : {out_dir}")
    print("  Validation: nested treatment LOGO; one outer fold per treatment")
    print(f"  Treatments: {cfg['group_col']}  |  split unit: treatment; metric unit: sample ID")
    print(f"  CPU cores : {n_cores}")
    if cfg.get("metadata_warning"):
        print(f"  Metadata  : {cfg['metadata_warning']}")

    # -------------------------------------------------------------------------
    sec_t0 = timed_section("SECTION 1 — ALIGN DATA", pipeline_t0, 1, TOTAL_SECTIONS)
    X, y, keys, group_labels, wavenumbers = align_to_reference(
        spectra_dict, wavenumbers, cfg, reference_frame)
    cfg = prepare_region_config(cfg, wavenumbers)
    print(f"  Automatic windows: {cfg['region_search_n_windows']}; catalogued combinations: {len(cfg['_regions'])}; search: backward stepwise; RMSECV tolerance: {cfg.get('rmsecv_tolerance_pct', 2.0):g}%")
    print(f"  Unique matched samples: {len(np.unique(keys))}")
    print(f"  Group labels: {', '.join(map(str, sorted(pd.unique(group_labels))))}")
    profile["Align Seconds"] = time.time() - sec_t0
    print(f"  Section 1 done in {fmt_time(profile['Align Seconds'])}")

    # -------------------------------------------------------------------------
    sec_t0 = timed_section("SECTION 2 — OPTIONAL EXTREME VALUE REMOVAL", pipeline_t0, 2, TOTAL_SECTIONS)
    X, y, keys, group_labels = remove_extreme_values(X, y, keys, group_labels, cfg, out_dir)
    profile["Extreme Filter Seconds"] = time.time() - sec_t0
    print(f"  Section 2 done in {fmt_time(profile['Extreme Filter Seconds'])}")

    # -------------------------------------------------------------------------
    sec_t0 = timed_section("SECTION 3 — NESTED TREATMENT LOGO VALIDATION", pipeline_t0, 3, TOTAL_SECTIONS)
    validate_training_data(X, y, keys, group_labels, cfg)
    results = run_nested_logo_folds(X, y, keys, group_labels, cfg)

    results = sorted(results, key=lambda item: item[0]["Outer Fold"])
    fold_records = [rec for rec, _, _ in results]
    prediction_frames = [pred_df for _, pred_df, _ in results]
    optimization_frames = [opt_df for _, _, opt_df in results]

    fold_df = pd.DataFrame(fold_records)
    prediction_df = pd.concat(prediction_frames, ignore_index=True)
    if prediction_df["Sample Key"].duplicated().any() or set(prediction_df["Sample Key"]) != set(keys):
        raise ValueError("Outer predictions must cover every retained sample exactly once.")
    optimization_df = pd.concat(optimization_frames, ignore_index=True)
    profile["Nested LOGO Seconds"] = time.time() - sec_t0
    print(f"  Section 3 done in {fmt_time(profile['Nested LOGO Seconds'])}")

    timing_cols = [
        "Initial Optimization Seconds",
        "Outlier Detection Seconds",
        "Outlier Reoptimization Seconds",
        "Final Fit Validation Seconds",
        "Outer Fold Seconds",
    ]
    print("\n  === TIMING PROFILE ===")
    for col in timing_cols:
        vals = fold_df[col].dropna().astype(float)
        total = vals.sum()
        mean = vals.mean()
        profile[col.replace(" Seconds", " Total Seconds")] = total
        print(f"  {col:<35} total={fmt_time(total):>10}  mean={fmt_time(mean)}")

    # -------------------------------------------------------------------------
    sec_t0 = timed_section("SECTION 4 — FIT FINAL CALIBRATED MODEL", pipeline_t0, 4, TOTAL_SECTIONS)
    final_model_bundle, final_model_settings, final_removed_samples, final_selection_summary = (
        fit_final_nested_logo_model(X, y, keys, wavenumbers, cfg, optimization_df, group_labels)
    )
    tolerance_comparison = build_tolerance_comparison(final_selection_summary, cfg.get("rmsecv_tolerance_pct", 2.0))
    profile["Final Model Fit Seconds"] = time.time() - sec_t0
    print(f"  Final model settings: {final_model_settings['Region']} | {final_model_settings['Regions (cm-1)']} | {final_model_settings['Preprocessing']} "
          f"Rank {final_model_settings['Rank']} "
          f"calibration RMSECV={final_model_settings['RMSECV']:.4f}")
    print(f"  Final whole-sample outliers removed: {len(final_removed_samples)}")
    print(f"  Section 4 done in {fmt_time(profile['Final Model Fit Seconds'])}")

    # -------------------------------------------------------------------------
    sec_t0 = timed_section("SECTION 5 — SAVE NESTED LOGO RESULTS AND MODEL", pipeline_t0, 5, TOTAL_SECTIONS)
    summary_df, excel_path, pdf_path, model_path = save_nested_logo_results(
        fold_df,
        prediction_df,
        optimization_df,
        cfg,
        out_dir,
        model_bundle=final_model_bundle,
        final_model_selection=final_selection_summary,
        tolerance_comparison=tolerance_comparison,
    )
    profile["Export Seconds"] = time.time() - sec_t0
    print(f"  Section 5 done in {fmt_time(profile['Export Seconds'])}")

    print("\n  === NESTED LOGO VALIDATION SUMMARY ===")
    print(summary_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    elapsed = time.time() - pipeline_t0
    print("\n" + "="*60)
    print("  PROPERTY PIPELINE COMPLETE")
    print("="*60)
    print(f"\n  All outputs saved to: {out_dir}")
    print(f"  Excel summary: {excel_path}")
    print(f"  Plot report  : {pdf_path}")
    print(f"  Final model  : {model_path}")

    return {
        "fold_df": fold_df,
        "prediction_df": prediction_df,
        "summary_df": summary_df,
        "optimization_df": optimization_df,
        "final_selection_summary": final_selection_summary,
        "tolerance_comparison": tolerance_comparison,
        "excel_path": excel_path,
        "pdf_path": pdf_path,
        "model_path": model_path,
        "model_bundle": final_model_bundle,
        "final_model_settings": final_model_settings,
        "final_removed_samples": final_removed_samples,
        "elapsed_seconds": elapsed,
        "profile": profile,
    }


def main():
    base_cfg = CONFIG.copy()
    validate_config(base_cfg, check_paths=True)
    with pd.ExcelFile(base_cfg["reference_excel"]) as workbook:
        return run_batch(base_cfg, workbook)


def run_batch(base_cfg, workbook):
    """Coordinate properties; keep the workbook in the parent process."""
    batch_t0 = time.time()
    os.makedirs(base_cfg["output_base_dir"], exist_ok=True)

    print("=" * 60)
    print("  SOIL MIR PLSR / BATCH NESTED LOGO VALIDATION")
    print("=" * 60)
    print(f"  Spectra   : {base_cfg['spectra_dir']}")
    print(f"  Reference : {base_cfg['reference_excel']}")
    print(f"  Output    : {base_cfg['output_base_dir']}")
    print("  Validation: nested treatment LOGO; fold counts derived from each property")

    metadata = load_property_metadata(base_cfg, workbook)
    if base_cfg.get("run_all_properties", False):
        property_sheets = discover_property_sheets(base_cfg, workbook)
    else:
        property_sheets = [base_cfg["reference_sheet"]]

    reference_frames = {sheet: workbook.parse(sheet_name=sheet) for sheet in property_sheets}
    for frame in reference_frames.values():
        validate_reference_frame(frame, base_cfg)

    print("\n  Loading spectra once for all properties ...")
    spectra_dict, wavenumbers = load_opus_files(
        base_cfg["spectra_dir"], base_cfg.get("spectra_cache"), base_cfg.get("spectra_n_jobs", 4)
    )

    print(f"\n  Properties to model ({len(property_sheets)}): {', '.join(property_sheets)}")

    batch_records = []
    for i, property_sheet in enumerate(property_sheets, start=1):
        property_t0 = time.time()
        cfg = build_property_config(base_cfg, property_sheet, metadata)
        print("\n" + "#" * 72)
        print(f"  PROPERTY {i}/{len(property_sheets)}: {property_sheet}")
        print("#" * 72)

        record = {
            "Property": property_sheet,
            "Units": cfg["units"],
            "Transform": cfg["transform"],
            "Exclude CO2": cfg.get("exclude_co2", False),
            "Tolerance (%)": cfg.get("rmsecv_tolerance_pct", 2.0),
            "Status": "Failed",
            "Elapsed Seconds": None,
            "Elapsed": None,
            "Output Folder": cfg["output_dir"],
            "Excel Path": "",
            "PDF Path": "",
            "Model Path": "",
            "Metadata Warning": cfg.get("metadata_warning", ""),
            "Align Seconds": None,
            "Extreme Filter Seconds": None,
            "Nested LOGO Seconds": None,
            "Export Seconds": None,
            "Initial Optimization Total Seconds": None,
            "Outlier Detection Total Seconds": None,
            "Outlier Reoptimization Total Seconds": None,
            "Final Fit Validation Total Seconds": None,
            "Outer Fold Total Seconds": None,
            "Error": "",
        }

        try:
            result = run_property_pipeline(cfg, spectra_dict, wavenumbers, reference_frames[property_sheet])
            elapsed = result["elapsed_seconds"]
            record.update({
                "Status": "Success",
                "Elapsed Seconds": round(elapsed, 2),
                "Elapsed": fmt_time(elapsed),
                "Excel Path": result["excel_path"],
                "PDF Path": result["pdf_path"],
                "Model Path": result["model_path"],
                "Selected Region": result["final_model_settings"]["Region"],
                "Regions (cm-1)": result["final_model_settings"]["Regions (cm-1)"],
                "Selected Rank": result["final_model_settings"]["Rank"],
            })
            for _, metric in result["summary_df"].iterrows():
                record[f"Pooled Outer {metric['Metric']}"] = metric["Value"]
            for key, value in result.get("profile", {}).items():
                record[key] = round(value, 2)
        except Exception as e:
            elapsed = time.time() - property_t0
            record.update({
                "Elapsed Seconds": round(elapsed, 2),
                "Elapsed": fmt_time(elapsed),
                "Error": traceback.format_exc(),
            })
            print(f"\n  Property '{property_sheet}' failed:")
            print(record["Error"])
            if not base_cfg.get("continue_on_property_error", True):
                batch_records.append(record)
                save_batch_summary(batch_records, base_cfg)
                raise

        batch_records.append(record)
        save_batch_summary(batch_records, base_cfg)

    total_elapsed = time.time() - batch_t0
    print("\n" + "=" * 60)
    print("  BATCH PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Properties attempted : {len(batch_records)}")
    print(f"  Successful           : {sum(r['Status'] == 'Success' for r in batch_records)}")
    print(f"  Failed               : {sum(r['Status'] != 'Success' for r in batch_records)}")
    print(f"  Total elapsed        : {fmt_time(total_elapsed)}")
    print(f"  Output folder        : {base_cfg['output_base_dir']}")

    return pd.DataFrame(batch_records)


# =============================================================================
# Run only when executed directly; importing exposes reusable modelling helpers.
# =============================================================================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n*** ERROR ***\n{traceback.format_exc()}")
        sys.exit(1)
