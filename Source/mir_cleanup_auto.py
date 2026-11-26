"""Batch cleanup for isolated session copies."""
import copy
from datetime import datetime
from pathlib import Path
import shutil

import mir_cleanup_session as engine


def already_reviewed(p):
    def has_ab(obj):
        return bool(set(obj.get('diagnostics', {})) & {'A', 'B'} or
                    any(x.get('stage') in ('A', 'B') for x in obj.get('decisions', {}).values()))
    return has_ab(p) or any(p.get('finished', {}).values()) or any(has_ab(a) for a in p.get('archive', []))


def recover(session):
    checkpoint = session.state.pop('_auto_checkpoint', None)
    if checkpoint:
        session.state['properties'][checkpoint['property']] = checkpoint['state']
        session.state['history'] = session.state['history'][:checkpoint['history_length']]
        generated = checkpoint.get('generated_pca')
        if generated:
            (session.folder / Path(generated).name).unlink(missing_ok=True)
        session.save('Recovered interrupted automatic cleanup')


def readiness(session):
    issues = []
    for prop, p in session.state['properties'].items():
        if not p['finished']['B']:
            issues.append(f'{prop}: finish both calibration reviews')
        try:
            session.validate_limit(prop)
        except ValueError as exc:
            issues.append(str(exc))
    try:
        if engine.core.fingerprint(Path(session.state['source'])) != session.state['source_sha256']:
            issues.append('Source workbook differs from the original.')
    except OSError as exc:
        issues.append(f'Source workbook unavailable: {exc}')
    return issues


def run(source, progress=lambda *a: None, stopped=lambda: False):
    dest = source.folder.parent / ('auto_cleanup_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    shutil.copytree(source.folder, dest)
    session = engine.Session.load(dest)
    session.state.pop('last_export', None)
    session.state['auto_cleanup'] = {'results': [], 'stopped': False, 'in_progress': True}
    session.save('Automatic cleanup copy created')
    results = []
    try:
        for index, (prop, p) in enumerate(session.state['properties'].items(), 1):
            if stopped():
                break
            if already_reviewed(p):
                progress(index, len(session.state['properties']), prop, 'Skipped')
                results.append({'property': prop, 'status': 'skipped'})
                session.state['auto_cleanup']['results'] = copy.deepcopy(results)
                continue
            generated = f'PCA_property_{index-1}_fit_{p["pca_round"]+1}.html' if p['pca_dirty'] else None
            if generated and (dest / generated).exists():
                generated = None
            checkpoint = {'property': prop, 'state': copy.deepcopy(p), 'history_length': len(session.state['history']),
                          'generated_pca': generated}
            session.state['_auto_checkpoint'] = checkpoint
            session.save(f'{prop}: automatic cleanup started')
            try:
                progress(index, len(session.state['properties']), prop, 'PCA')
                session.refit_pca(prop)
                session.finish_pca(prop)
                counts = {}
                for half in ('A', 'B'):
                    progress(index, len(session.state['properties']), prop, half)
                    session.calculate(prop, half)
                    rows = p['diagnostics'][half]['rows']
                    candidates = [r['File Name'] for r in rows if r.get('Concentration Candidate')]
                    samples = sorted({str(r['Sample']) for r in rows if r.get('Concentration Candidate')})
                    before = session.excluded(prop)
                    if candidates:
                        session.decide(prop, half, candidates, 'concentration', 'sample',
                                       'Automatic cleanup; candidate spectra: ' + ', '.join(candidates))
                    counts[half] = {'candidate_spectra': len(candidates), 'samples': len(samples),
                                    'excluded_spectra': len(session.excluded(prop) - before)}
                    session.finish_half(prop, half)
                session.state.pop('_auto_checkpoint', None)
                results.append({'property': prop, 'status': 'completed', 'counts': counts})
                session.state['auto_cleanup']['results'] = copy.deepcopy(results)
                session.save(f'{prop}: automatic cleanup completed')
            except (ValueError, ArithmeticError) as exc:
                recover(session)
                results.append({'property': prop, 'status': 'failed', 'error': str(exc)})
                session.state['auto_cleanup']['results'] = copy.deepcopy(results)
                session.save(f'{prop}: automatic cleanup failed')
        session.state['auto_cleanup'] = {'results': results, 'stopped': stopped(), 'in_progress': False}
        session.save('Automatic cleanup finished')
        return session
    except Exception as exc:
        recover(session)
        raise RuntimeError(f'Automatic cleanup stopped. Session copy: {dest}\n{exc}') from exc
