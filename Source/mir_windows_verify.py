"""Opt-in release verification. Inputs are read-only; outputs must be a new folder."""
import argparse
import json
import platform
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import mir_cleanup_session as engine
import soil_mir_data_cleanup as core


def run(app, argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-windows', action='store_true')
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--verification-output', type=Path, required=True)
    parser.add_argument('--properties', nargs='+', default=['202_STC', '202_STN'])
    args = parser.parse_args(argv)
    output = args.verification_output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'passed': False, 'platform': platform.platform(),
              'python': sys.version, 'frozen': bool(getattr(sys, 'frozen', False)),
              'properties': {}, 'clean_machine_test': 'not performed'}
    started = time.monotonic()
    window = None

    def save(message):
        report['progress'] = message
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        engine.atomic_json(output / 'verification.json', report)
        print(message, flush=True)
        app.processEvents()

    try:
        source = args.data.resolve() / 'reference' / 'reference_value_ZL_trt.xlsx'
        spectra = args.data.resolve() / 'spectra' / 'Complete'
        inputs = [source] + sorted(p for p in spectra.rglob('*') if p.is_file())
        before = {str(p): core.fingerprint(p) for p in inputs}
        report['spectra_files'] = len(inputs) - 1
        book = pd.read_excel(source, sheet_name=None)
        report['discovered_property_sheets'] = len(core.select_properties(book, 'all'))
        candidates = core.select_properties(book, args.properties)
        report['requested_properties'] = candidates
        report['invalid_property_sheets'] = {}
        mod = core.backend()
        with pd.ExcelFile(source) as workbook:
            metadata = core.metadata_for_properties(mod.load_property_metadata(mod.CONFIG, workbook), candidates)
        props = []
        for prop in candidates:
            try:
                frame = core.validate_frame(book[prop])
                cfg = mod.build_property_config(mod.CONFIG, prop, metadata)
                if cfg['metadata_warning']:
                    raise ValueError(cfg['metadata_warning'])
                mod.apply_transform(frame['Reference Value'].to_numpy(float), cfg['transform'])
                missing = [name for name in frame['File Name'] if not (spectra / name).is_file()]
                if missing:
                    raise ValueError(f'Missing spectra: {missing[:10]}')
            except ValueError as exc:
                report['invalid_property_sheets'][prop] = {
                    'reason': str(exc),
                    'missing_required_cells': {k: int(v) for k, v in book[prop][core.COLS].isna().sum().items()}}
                continue
            props.append(prop)
            report['properties'][prop] = {'records': len(frame), 'samples': int(frame.Sample.nunique())}
        if not props:
            raise ValueError('No valid property sheets to test')
        save(f'Input validation complete; preparing {len(props)} valid property sheets')
        session = engine.Session.create(source, spectra, output / 'session avec espaces é', props)
        from mir_cleanup_app import Window
        window = Window()
        window.bind(session)
        window.show()
        app.processEvents()
        for index, prop in enumerate(props):
            save(f'Reviewing {prop} ({index + 1}/{len(props)})')
            frame = session.frame(prop)
            session.decide(prop, 'PCA', [frame.iloc[0]['File Name']], 'spectral_quality', 'spectrum', 'Windows verification é')
            session.refit_pca(prop)
            session.finish_pca(prop)
            session.calculate(prop, 'A')
            state = session.state['properties'][prop]
            first_a = state['diagnostics']['A']['rows'][0]
            session.decide(prop, 'A', [first_a['File Name']], 'concentration', 'sample')
            session.finish_half(prop, 'A')
            session.calculate(prop, 'B')
            first_b = state['diagnostics']['B']['rows'][0]
            assert first_a['Preprocessing'] == first_b['Preprocessing']
            assert first_a['Selection Rank'] == first_b['Selection Rank']
            assert not session.excluded(prop, 'A').intersection(state['diagnostics']['B']['validation_files'])
            session.decide(prop, 'B', [first_b['File Name']], 'concentration', 'spectrum')
            session.finish_half(prop, 'B')
            report['properties'][prop].update(
                excluded=len(session.excluded(prop)),
                preprocessing=first_a['Preprocessing'], selection_rank=first_a['Selection Rank'],
                finished=True)
            save(f'Completed {prop}')
        session = engine.Session.load(session.folder)
        # A moved Mac session retains prepared spectra; only the workbook needs relinking.
        session.state['source'] = '/Users/mac/MIR/original.xlsx'
        session.save('Simulate relocation from Mac')
        session.relocate_source(source)
        session.export_review(output / 'review.xlsx')
        session.import_review(output / 'review.xlsx')
        window.bind(session)
        for stage in ['PCA', 'A', 'B']:
            window.stage.setCurrentText(stage)
            window.refresh()
            app.processEvents()
            window.grab().save(str(output / f'app-{stage}.png'))
        save('Exporting and checking retained workbook values')
        destination = session.export(output / 'export')
        engine.verify_export(source, destination / 'reference_cleaned.xlsx',
                             {prop: session.excluded(prop) for prop in props})
        for path in inputs:
            if core.fingerprint(path) != before[str(path)]:
                raise AssertionError(f'Input changed: {path}')
        report.update(passed=True, original_inputs_unchanged=True,
                      session_relocation_passed=True, excel_review_roundtrip_passed=True,
                      session_folder=str(session.folder), export_folder=str(destination))
        save('All supplied-data workflow checks passed')
        return 0
    except Exception:
        report['error'] = traceback.format_exc()
        save('Verification failed')
        (output / 'verification-error.txt').write_text(report['error'], encoding='utf-8')
        return 1
    finally:
        if window is not None:
            window.close()
        app.processEvents()
