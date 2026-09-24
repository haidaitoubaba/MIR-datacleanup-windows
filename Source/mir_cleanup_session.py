"""Portable staged cleanup sessions; no executable objects in saved sessions."""
from __future__ import annotations
import copy
import json
import os
import re
import shutil
import tempfile
import zipfile
import posixpath
import xml.etree.ElementTree as ET
from lxml import etree as XML
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from threadpoolctl import threadpool_limits
import soil_mir_data_cleanup as core


def records(frame):
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient='records')


def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)


def workbook_properties(path):
    sheets = pd.read_excel(path, sheet_name=None)
    return core.select_properties(sheets, 'all')


class Session:
    def __init__(self, folder, state):
        self.folder = Path(folder)
        self.state = state

    @classmethod
    def create(cls, source, spectra_dir, folder, properties):
        source, spectra_dir, folder = Path(source), Path(spectra_dir), Path(folder)
        if folder.exists():
            raise ValueError('Choose a new session folder; existing sessions are not overwritten.')
        sheets = pd.read_excel(source, sheet_name=None)
        props = core.select_properties(sheets, properties)
        mod = core.backend()
        with pd.ExcelFile(source) as book:
            metadata = core.metadata_for_properties(mod.load_property_metadata(mod.CONFIG, book), props)
        frames, configs = {}, {}
        for prop in props:
            frames[prop] = core.validate_frame(sheets[prop])
            cfg = mod.build_property_config(mod.CONFIG, prop, metadata)
            if cfg['metadata_warning']:
                raise ValueError(f'{prop}: {cfg["metadata_warning"]}')
            mod.apply_transform(frames[prop]['Reference Value'].to_numpy(float), cfg['transform'])
            configs[prop] = cfg
        folder.mkdir(parents=True)
        try:
            spectra, axis = mod.load_opus_files(str(spectra_dir), cache_path=str(folder / 'spectra_cache.joblib'), n_jobs=1)
            state = {'version': 1, 'source': str(source.resolve()), 'source_sha256': core.fingerprint(source),
                     'spectra_dir': str(spectra_dir.resolve()), 'properties': {}, 'history': [],
                     'limit': 'disable', 'percent': 1.0, 'created': datetime.now(timezone.utc).isoformat(),
                     'spectra_sha256': {}}
            for i, prop in enumerate(props):
                frame, cfg = frames[prop], configs[prop]
                files = frame['File Name'].tolist()
                missing = [f for f in files if f not in spectra]
                if missing:
                    raise ValueError(f'{prop}: missing spectra: {missing[:10]}')
                for name in files:
                    state['spectra_sha256'][name] = core.fingerprint(spectra_dir / name)
                mask = (axis >= 600) & (axis <= 4000)
                if cfg.get('exclude_co2'):
                    mask &= ~((axis >= 2300) & (axis <= 2400))
                a = axis[mask]
                breaks = np.flatnonzero(np.abs(np.diff(a)) > 1.5 * np.median(np.abs(np.diff(axis)))) + 1
                config = {k: cfg[k] for k in ['transform', 'units', 'exclude_co2', 'sg_window', 'sg_polyorder']}
                config['_segment_lengths'] = [len(s) for s in np.split(a, breaks)]
                name = f'spectra_{i}.npz'
                np.savez_compressed(folder / name, X=np.array([spectra[f] for f in files])[:, mask], axis=a)
                state['properties'][prop] = {'frame': records(frame), 'config': config, 'matrix': name,
                    'matrix_sha256': core.fingerprint(folder / name), 'decisions': {}, 'pca': None,
                    'pca_round': 0, 'pca_dirty': True, 'pca_done': False, 'halves': {},
                    'diagnostics': {}, 'finished': {'A': False, 'B': False}, 'archive': []}
            session = cls(folder, state)
            for prop in props:
                session.refit_pca(prop)
            session.save('Created session')
            (folder / 'spectra_cache.joblib').unlink(missing_ok=True)
            return session
        except Exception:
            # Only this newly created session directory is removed.
            shutil.rmtree(folder)
            raise

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        state = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        if state.get('version') != 1:
            raise ValueError('Unsupported session version.')
        for p in state['properties'].values():
            path = folder / p['matrix']
            if path.parent.resolve() != folder.resolve() or core.fingerprint(path) != p['matrix_sha256']:
                raise ValueError('Saved session spectra failed verification.')
        session = cls(folder, state)
        changed = False
        for p in state['properties'].values():
            if 'B' in p['diagnostics'] and p['diagnostics']['B'].get('selection_source') != 'A':
                session.archive(p, 'Previous independently optimized B; decisions preserved')
                p['diagnostics'].pop('B')
                p['finished']['B'] = False
                changed = True
        if changed:
            session.save('Updated B workflow: recalculate B using A settings; existing decisions preserved')
        return session

    def save(self, action):
        if not action.startswith('Exported '):
            self.state.pop('last_export', None)
        self.state['history'].append({'time': datetime.now(timezone.utc).isoformat(), 'action': action})
        atomic_json(self.folder / 'session.json', self.state)

    def frame(self, prop):
        return pd.DataFrame(self.state['properties'][prop]['frame'])

    def excluded(self, prop, stage=None):
        p = self.state['properties'][prop]
        return {f for f, d in p['decisions'].items() if stage is None or d['stage'] == stage}

    def archive(self, p, label):
        p['archive'].append({'label': label, 'pca': copy.deepcopy(p['pca']),
                             'diagnostics': copy.deepcopy(p['diagnostics']),
                             'decisions': copy.deepcopy(p['decisions']), 'halves': copy.deepcopy(p['halves'])})

    def validate_limit(self, prop, decisions=None):
        p = self.state['properties'][prop]
        decisions = p['decisions'] if decisions is None else decisions
        percent = Decimal(str(self.state['percent']))
        if not percent.is_finite() or not 0 <= percent <= 100:
            raise ValueError('Percentage must be between 0 and 100.')
        if self.state['limit'] not in ['enable', 'disable']:
            raise ValueError('Invalid limit setting.')
        samples = {d['sample'] for d in decisions.values() if d['stage'] in ('A', 'B') or d['reason'] == 'concentration'}
        cap = int(Decimal(self.frame(prop).Sample.nunique()) * percent / 100)
        if self.state['limit'] == 'enable' and len(samples) > cap:
            raise ValueError(f'{prop}: {len(samples)} concentration samples exceed the allowance of {cap} ({percent}%).')

    def set_limit(self, enabled, percent):
        old = self.state['limit'], self.state['percent']
        self.state['limit'], self.state['percent'] = ('enable' if enabled else 'disable'), float(percent)
        try:
            for prop in self.state['properties']:
                self.validate_limit(prop)
        except Exception:
            self.state['limit'], self.state['percent'] = old
            raise
        self.save('Updated concentration limit')

    def decide(self, prop, stage, files, reason, unit, comment='', restore=False):
        p = self.state['properties'][prop]; frame = self.frame(prop)
        files = set(files)
        if not files or not files <= set(frame['File Name']):
            raise ValueError('Select valid records first.')
        if stage not in ('PCA', 'A', 'B'):
            raise ValueError('Invalid review stage.')
        reason = str(reason or '').strip().lower()
        if reason not in {'', 'redundancy', 'spectral_quality', 'range', 'concentration'}:
            raise ValueError('Unknown exclusion reason.')
        if unit not in ('sample', 'spectrum'):
            raise ValueError('Unit must be spectrum or sample.')
        if stage == 'PCA' and reason == 'concentration':
            raise ValueError('Use calibration review for concentration exclusions.')
        if stage != 'PCA':
            if stage not in p['diagnostics']:
                raise ValueError('Calculate this half before reviewing it.')
            allowed = {r['File Name'] for r in p['diagnostics'][stage]['rows']}
            if not files <= allowed:
                raise ValueError('Select records in the displayed calibration half.')
        if unit == 'sample':
            samples = set(frame.loc[frame['File Name'].isin(files), 'Sample'])
            files = set(frame.loc[frame.Sample.isin(samples), 'File Name'])
        # A later decision cannot erase an earlier PCA exclusion.
        if stage != 'PCA':
            files -= self.excluded(prop, 'PCA')
        decisions = copy.deepcopy(p['decisions'])
        lookup = frame.set_index('File Name')
        for f in files:
            if restore:
                if f in decisions and decisions[f]['stage'] != stage:
                    raise ValueError('Restore records in the stage where they were excluded.')
                decisions.pop(f, None)
            else:
                decisions[f] = {'sample': str(lookup.loc[f, 'Sample']), 'reason': reason,
                                'unit': unit, 'stage': stage, 'comment': comment}
        if decisions == p['decisions']:
            return
        if stage == 'PCA' and p['pca_round'] >= 3:
            raise ValueError('Three PCA rounds have been used. Start a new session to revise PCA exclusions.')
        self.validate_limit(prop, decisions)
        self.archive(p, f'Before {stage} decision change')
        if stage == 'PCA':
            decisions = {f: d for f, d in decisions.items() if d['stage'] == 'PCA'}
            p.update(pca_dirty=True, pca_done=False, halves={}, diagnostics={}, finished={'A': False, 'B': False})
        elif stage == 'A':
            decisions = {f: d for f, d in decisions.items() if d['stage'] != 'B'}
            p['diagnostics'].pop('B', None)
            p['finished'] = {'A': False, 'B': False}
        else:
            p['finished']['B'] = False
        p['decisions'] = decisions
        self.save(f'{prop}: updated {stage} decisions')

    def refit_pca(self, prop):
        p = self.state['properties'][prop]
        if not p['pca_dirty']:
            return
        if p['pca_round'] >= 3:
            raise ValueError('Maximum three PCA fits per session.')
        frame = self.frame(prop)
        keep = ~frame['File Name'].isin(self.excluded(prop, 'PCA'))
        X = np.load(self.folder / p['matrix'])['X'][keep]
        with threadpool_limits(limits=1):
            model, scores, variance = core.fit_pca(X)
        rows = records(frame.loc[keep]); distances = cdist(scores, scores)
        np.fill_diagonal(distances, np.inf)
        for i, row in enumerate(rows):
            j = int(np.argmin(distances[i]))
            row.update(scores=scores[i].tolist(), **{'Nearest File': rows[j]['File Name'],
                'Nearest Distance': float(distances[i,j]), 'Same Sample Neighbour': row['Sample'] == rows[j]['Sample']})
        if p['pca']:
            self.archive(p, 'Previous PCA basis')
        p['pca_round'] += 1
        p['pca'] = {'variance': variance.tolist(), 'rows': rows, 'round': p['pca_round']}
        p['pca_dirty'] = False
        self.save(f'{prop}: PCA fit {p["pca_round"]}')
        index = list(self.state['properties']).index(prop)
        core.render_viewer({prop: self.payload()[prop]}, self.folder / f'PCA_property_{index}_fit_{p["pca_round"]}.html')

    def finish_pca(self, prop):
        p = self.state['properties'][prop]
        if p['pca_dirty']:
            raise ValueError('Refit PCA before finishing this review.')
        if p['pca_done']:
            return
        rows = pd.DataFrame(p['pca']['rows'])
        avg = pd.DataFrame(rows.scores.tolist()).assign(Sample=rows.Sample).groupby('Sample', sort=True).mean()
        if len(avg) < 4:
            raise ValueError('At least four retained samples are needed for the two halves.')
        chosen = core.kennard_stone(avg.to_numpy(), len(avg)//2)
        a = set(avg.index[chosen])
        p['halves'] = {s: ('A' if s in a else 'B') for s in avg.index}
        p['pca_done'] = True
        self.save(f'{prop}: finished PCA and assigned halves')

    def calculate(self, prop, half):
        p = self.state['properties'][prop]
        if not p['pca_done'] or p['pca_dirty']:
            raise ValueError('Finish PCA review first.')
        if half == 'B' and not p['finished']['A']:
            raise ValueError('Finish A review before calculating B.')
        if half in p['diagnostics']:
            return  # Deliberately no same-half refit in v1.
        frame = self.frame(prop)
        base = ~frame['File Name'].isin(self.excluded(prop, 'PCA'))
        train = base & frame.Sample.map(p['halves']).eq(half)
        test = base & ~train
        if half == 'B':
            test &= ~frame['File Name'].isin(self.excluded(prop, 'A'))
        X = np.load(self.folder / p['matrix'])['X']
        fixed = None
        if half == 'B':
            a = p['diagnostics']['A']['rows'][0]
            fixed = (a['Preprocessing'], int(a['Selection Rank']))
        with threadpool_limits(limits=1):
            diag, search = core.diagnose_half(X, frame, train.to_numpy(), test.to_numpy(), p['config'], half, fixed_selection=fixed)
        if search.empty or 'Calibration Prediction' not in diag:
            raise ValueError('Calibration diagnosis unavailable: constant response or insufficient spectral rank.')
        result = frame.loc[train].join(diag)
        if not np.isfinite(result[['Calibration Prediction', 'Transformed Prediction', 'Studentised Residual']].to_numpy(float)).all():
            raise ValueError('Non-finite diagnostic result; review inputs.')
        p['diagnostics'][half] = {'rows': records(result), 'search': records(search),
                                  'validation_files': frame.loc[test, 'File Name'].tolist(),
                                  'selection_source': 'A' if half == 'B' else 'optimized on B'}
        self.save(f'{prop}: calculated half {half}')

    def finish_half(self, prop, half):
        p = self.state['properties'][prop]
        if half not in p['diagnostics'] or (half == 'B' and not p['finished']['A']):
            raise ValueError('Calculate and review the preceding stages first.')
        self.validate_limit(prop)
        p['finished'][half] = True
        self.save(f'{prop}: finished half {half}')

    def review_frame(self):
        parts = []
        for prop, p in self.state['properties'].items():
            f = self.frame(prop).assign(Property=prop, Confirm='', Reason='', Unit='spectrum', Comment='', Stage='PCA')
            for i, row in f.iterrows():
                d = p['decisions'].get(row['File Name'])
                if d:
                    f.loc[i, ['Confirm','Reason','Unit','Comment','Stage']] = ['YES',d['reason'],d['unit'],d['comment'],d['stage']]
                elif p['pca_done']:
                    f.loc[i,'Stage'] = p['halves'].get(row.Sample, 'PCA')
            f.loc[f.Stage.isin(['A','B']) & f.Confirm.ne('YES'), 'Unit'] = 'sample'
            parts.append(f)
        return pd.concat(parts, ignore_index=True)

    def export_review(self, path):
        with pd.ExcelWriter(path) as writer:
            self.review_frame().to_excel(writer, sheet_name='Review', index=False)
            for half in ['A','B']:
                rows = [dict(r,Property=prop) for prop,p in self.state['properties'].items()
                        for r in p['diagnostics'].get(half,{}).get('rows',[])]
                pd.DataFrame(rows).to_excel(writer, sheet_name=f'Calibration {half}', index=False)
            pd.DataFrame({'Instructions':['Edit Confirm, Reason, Unit, Comment only. Do not change Stage or record identities.',
                'Save Excel, then import in the app. Changed A decisions invalidate B.',
                'YES excludes; blank/NO restores a previously confirmed record. Reason is optional. Unit may be spectrum or sample in every stage.']}).to_excel(writer,sheet_name='Read Me',index=False)

    def import_review(self, path):
        r = pd.read_excel(path, sheet_name='Review').fillna('')
        expected = self.review_frame().fillna('')
        keys = ['Property','File Name']
        if r.duplicated(keys).any() or set(map(tuple,r[keys].values)) != set(map(tuple,expected[keys].values)):
            raise ValueError('Review must contain each session record exactly once.')
        core.confirmed_rows(r.assign(Reason=r.Reason.replace({'': 'spectral_quality', 'concentration': 'spectral_quality'})))
        old = copy.deepcopy(self.state)
        try:
            expected = expected.set_index(keys)
            for _, row in r.iterrows():
                base = expected.loc[(row.Property,row['File Name'])]
                if row.Sample != base.Sample or row.Stage != base.Stage:
                    raise ValueError('Review identities/stages changed; export a fresh review.')
            # Reject contradictory sample YES and explicit NO before applying.
            for prop in self.state['properties']:
                pr = r[r.Property == prop]
                no = set(pr.loc[pr.Confirm.astype(str).str.lower().eq('no'),'File Name'])
                for _,row in core.confirmed_rows(pr.assign(Reason=pr.Reason.replace({'': 'spectral_quality', 'concentration': 'spectral_quality'}))).iterrows():
                    if row.Unit == 'sample' and no & set(pr.loc[pr.Sample == row.Sample,'File Name']):
                        raise ValueError('Conflicting sample exclusion and NO decision.')
            changes = []
            for _,row in r.iterrows():
                base = expected.loc[(row.Property,row['File Name'])]
                yes = str(row.Confirm).strip().lower() == 'yes'
                if yes != (base.Confirm == 'YES') or (yes and any(str(row[c]).strip().lower()!=str(base[c]).strip().lower() for c in ['Reason','Unit','Comment'])):
                    changes.append(row)
            # Do not silently reapply stale B decisions from the same import.
            changed_stages = {(r.Property,r.Stage) for r in changes}
            if any((p,'PCA') in changed_stages and any((p,h) in changed_stages for h in ['A','B']) or
                   (p,'A') in changed_stages and (p,'B') in changed_stages for p in self.state['properties']):
                raise ValueError('Import one dependent stage at a time; earlier-stage changes invalidate later results.')
            for row in changes:
                self.decide(row.Property,row.Stage,[row['File Name']],str(row.Reason).strip().lower(),
                            str(row.Unit).lower() or 'spectrum',str(row.Comment),restore=str(row.Confirm).strip().lower()!='yes')
        except Exception:
            self.state = old
            atomic_json(self.folder/'session.json',old)
            raise
        self.save('Imported Excel review')

    def relocate_source(self, path):
        if core.fingerprint(path) != self.state['source_sha256']:
            raise ValueError('Selected workbook does not match the original input fingerprint.')
        self.state['source'] = str(Path(path).resolve())
        self.save('Relocated source workbook')

    def payload(self):
        result = {}
        for prop,p in self.state['properties'].items():
            if p['pca'] is None:
                continue
            rows=[]
            for r in p['pca']['rows']:
                excluded = r['File Name'] in p['decisions']
                rows.append({'sample':r['Sample'],'file':r['File Name'],'group':r['Group'],
                    'value':r['Reference Value'],'scores':r['scores'], 'status':'confirmed excluded' if excluded else 'retained',
                    'excluded':excluded,'nearest':r['Nearest File'],'distance':r['Nearest Distance']})
            result[prop]={'variance':p['pca']['variance'],'records':rows,
                          'basis':f'PCA fit {p["pca_round"]}; excludes earlier PCA removals; no refit after calibration exclusions'}
        return result

    def export(self, destination):
        destination=Path(destination)
        if destination.exists():
            raise ValueError('Choose a new output folder.')
        for prop,p in self.state['properties'].items():
            if not p['finished']['B']:
                raise ValueError(f'{prop}: finish both calibration reviews before exporting.')
            self.validate_limit(prop)
        source=Path(self.state['source'])
        if core.fingerprint(source)!=self.state['source_sha256']:
            raise ValueError('Source workbook differs from the session input; relocate the original file.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='.mir-export-',dir=destination.parent))
        try:
            book=stage/'reference_cleaned.xlsx'
            export_workbook_exact(source,book,{p:self.excluded(p) for p in self.state['properties']})
            verify_export(source, book, {p:self.excluded(p) for p in self.state['properties']})
            audit=self.review_frame();audit=audit[audit.Confirm=='YES'].rename(columns={'Reason':'Reasons'})
            audit.to_csv(stage/'confirmed_audit.csv',index=False)
            self.export_review(stage/'review.xlsx')
            payload=self.payload();core.render_viewer(payload,stage/'PCA_viewer.html');core.export_figures(payload,stage)
            export_diagnostic_figures(self,stage)
            provenance={'source':str(source),'source_sha256':self.state['source_sha256'],
                'properties':list(self.state['properties']), 'cleaned_sha256':core.fingerprint(book),
                'confirmed_exclusions':records(audit), 'concentration_limit':self.state['limit'],
                'concentration_limit_percent':self.state['percent'], 'settings':{p:v['config'] for p,v in self.state['properties'].items()},
                'method':'Sequential PCA review, A calibration review, B reuses A preprocessing and selection rank, evaluated on retained A; rank-15 calibration diagnostics where feasible; SOP-inspired Python diagnostics',
                'evaluation':'Performance on the precleaned dataset; not independent validation of cleanup.'}
            atomic_json(book.with_suffix('.cleanup.json'),provenance)
            atomic_json(stage/'session_audit.json',self.state)
            core.historical_comparison(pd.read_excel(source,sheet_name=None),list(self.state['properties']),
                                      {p:self.excluded(p) for p in self.state['properties']}).to_csv(stage/'historical_comparison.csv',index=False)
            os.rename(stage,destination)
        except Exception:
            shutil.rmtree(stage)
            raise
        self.state['last_export'] = str(destination.resolve())
        self.save(f'Exported {destination}')
        return destination



def calibration_metrics(measured, predicted):
    """Metrics on the displayed spectra, in the displayed response scale."""
    y=np.asarray(measured,dtype=float);pred=np.asarray(predicted,dtype=float)
    if len(y)==0 or len(y)!=len(pred) or not np.isfinite(y).all() or not np.isfinite(pred).all():
        return {k:None for k in ['R2','RMSE','RPD','RPIQ']}
    rmse=float(np.sqrt(np.mean((y-pred)**2)));sst=float(np.sum((y-y.mean())**2))
    return {'R2':float(1-np.sum((y-pred)**2)/sst) if len(y)>1 and sst>0 else None,
            'RMSE':rmse,'RPD':float(np.std(y,ddof=1)/rmse) if len(y)>1 and rmse>0 else None,
            'RPIQ':float((np.percentile(y,75)-np.percentile(y,25))/rmse) if rmse>0 else None}


def metric_label(measured,predicted):
    m=calibration_metrics(measured,predicted)
    return 'Calibration · displayed spectra (n='+str(len(measured))+')\n'+'  |  '.join(
        ('R²' if k=='R2' else k)+' = '+(f'{v:.4g}' if v is not None else 'N/A') for k,v in m.items())


def combined_rows(session,prop):
    p=session.state['properties'][prop]
    diagnostics={r['File Name']:r for h in ['A','B'] for r in p['diagnostics'].get(h,{}).get('rows',[])}
    rows=[]
    for original in p['frame']:
        row=dict(original);row.update(diagnostics.get(row['File Name'],{}))
        decision=p['decisions'].get(row['File Name'],{})
        row.update(Half=p['halves'].get(row['Sample'],'Not assigned'),
                   Status='Excluded' if decision else 'Retained',
                   Reason=decision.get('reason',''),Unit=decision.get('unit',''),
                   **{'Exclusion Stage':decision.get('stage','')})
        rows.append(row)
    return rows


def verify_export(source,destination,excluded):
    before=pd.read_excel(source,sheet_name=None);after=pd.read_excel(destination,sheet_name=None)
    if list(before)!=list(after):raise ValueError('Export verification failed: worksheet names changed.')
    for prop,frame in before.items():
        expected=frame.loc[~frame['File Name'].isin(excluded[prop])].reset_index(drop=True) if excluded.get(prop) else frame
        try:pd.testing.assert_frame_equal(after[prop],expected,check_exact=True,check_dtype=False)
        except AssertionError as exc:raise ValueError(f'Export verification failed for {prop}; no output was published.') from exc


def export_workbook_exact(source, destination, excluded):
    """Edit only affected sheet XML; retain original cell values and other ZIP members."""
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    relns='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    with zipfile.ZipFile(source) as z:
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        frames=pd.read_excel(source,sheet_name=None)
        patches={}
        for prop, files in excluded.items():
            if prop not in frames:raise ValueError(f'Export sheet missing: {prop}')
            unknown=set(files)-set(frames[prop]['File Name'])
            if unknown:raise ValueError(f'{prop}: exclusion filenames not found in source: {sorted(unknown)[:5]}')
        for sheet in wb.find('m:sheets',ns):
            prop=sheet.attrib['name']
            if not excluded.get(prop):continue
            target=rels[sheet.attrib[relns]]
            path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            root=XML.fromstring(z.read(path));data=root.find('m:sheetData',ns)
            if root.findall('.//m:f',ns):
                raise ValueError(f'{prop}: formulas in an affected sheet require manual review before row deletion.')
            # Dataframe row 0 corresponds to Excel row 2, including interior blank rows.
            removed={i+2 for i,f in enumerate(frames[prop]['File Name']) if f in excluded[prop]}
            for row in list(data):
                old=int(row.attrib['r'])
                if old in removed:
                    data.remove(row);continue
                new=old-sum(r<old for r in removed)
                row.attrib['r']=str(new)
                for cell in row:
                    if 'r' in cell.attrib:cell.attrib['r']=re.sub(r'\d+$',str(new),cell.attrib['r'])
            for tag in ['dimension','autoFilter']:
                node=root.find('m:'+tag,ns)
                if node is not None and 'ref' in node.attrib:
                    node.attrib['ref']=re.sub(r'(\d+)$',lambda m:str(max(1,int(m[1])-len(removed))),node.attrib['ref'])
            patches[path]=XML.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():out.writestr(info,patches.get(info.filename,z.read(info.filename)))


def export_diagnostic_figures(session, folder):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_pdf import PdfPages
    with PdfPages(Path(folder)/'Calibration_report.pdf') as pdf:
        for i,(prop,p) in enumerate(session.state['properties'].items()):
            for half,d in p['diagnostics'].items():
                for transformed in [True,False]:
                    fig=Figure(figsize=(8,6));ax=fig.subplots()
                    rows=d['rows'];x=np.array([r['Transformed Reference' if transformed else 'Reference Value'] for r in rows])
                    y=np.array([r['Transformed Prediction' if transformed else 'Calibration Prediction'] for r in rows])
                    colors=['#b43f42' if r['File Name'] in p['decisions'] else '#238798' for r in rows]
                    ax.scatter(x,y,c=colors,s=18)
                    lo,hi=min(x.min(),y.min()),max(x.max(),y.max());ax.plot([lo,hi],[lo,hi],'k--',lw=1,label='1:1 line')
                    for label,color in [('Retained','#238798'),('Excluded','#b43f42')]:ax.scatter([],[],c=color,label=label)
                    ax.legend(loc='lower right',fontsize=8)
                    ax.text(.02,.98,metric_label(x,y),transform=ax.transAxes,va='top',fontsize=8,bbox=dict(facecolor='white',alpha=.9))
                    scale=p['config']['transform']+' scale' if transformed else p['config']['units']
                    ax.set(xlabel=f'Measured ({scale})',ylabel=f'Calibration fit ({scale})',
                        title=f'{prop} · Half {half} · rank {int(rows[0]["Diagnostic Rank"])}\n{rows[0]["Preprocessing"]}')
                    fig.tight_layout();pdf.savefig(fig);fig.savefig(Path(folder)/f'property_{i}_{half}_{"modelled" if transformed else "original"}.png',dpi=160)
