"""Disposable staged-session and desktop regression tests."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import mir_cleanup_session as e
import soil_mir_data_cleanup as c


def fixture(folder):
    folder=Path(folder);folder.mkdir(exist_ok=True)
    rng=np.random.default_rng(41)
    f=pd.DataFrame([{'Sample':f'S{i:02}', 'File Name':f'S{i:02}_{j}.0','Reference Value':float((i+2)**2), 'Group':str(i%4)} for i in range(16) for j in range(3)])
    X=rng.normal(size=(48,45))+np.sqrt(f['Reference Value'].to_numpy())[:,None]*np.sin(np.linspace(0,6,45))[None,:]
    source=folder/'original.xlsx'
    with pd.ExcelWriter(source) as w:
        f.to_excel(w,sheet_name='P',index=False)
        pd.DataFrame({'value':[.1,1.234567890123456,'unchanged']}).to_excel(w,sheet_name='Metadata',index=False)
    np.savez_compressed(folder/'x.npz',X=X,axis=np.linspace(600,4000,45))
    p={'frame':e.records(f),'config':{'transform':'sqrt','units':'g/kg','exclude_co2':False,'sg_window':5,'sg_polyorder':2,'_segment_lengths':[45]},
       'matrix':'x.npz','matrix_sha256':c.fingerprint(folder/'x.npz'),'decisions':{},'pca':None,'pca_round':0,'pca_dirty':True,'pca_done':False,
       'halves':{},'diagnostics':{},'finished':{'A':False,'B':False},'archive':[]}
    s=e.Session(folder,{'version':1,'source':str(source),'source_sha256':c.fingerprint(source),'properties':{'P':p},'history':[],'limit':'disable','percent':1.,'spectra_sha256':{}})
    s.refit_pca('P');return s


class StagedTests(unittest.TestCase):
    def test_sequence_refit_invalidation_and_export(self):
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);p=s.state['properties']['P']
            before=np.array([r['scores'] for r in p['pca']['rows']])
            s.decide('P','PCA',['S00_0.0'],'spectral_quality','spectrum')
            with self.assertRaisesRegex(ValueError,'Refit PCA'):s.finish_pca('P')
            np.testing.assert_array_equal(before,np.array([r['scores'] for r in p['pca']['rows']]))
            s.refit_pca('P');self.assertEqual(len(p['pca']['rows']),47)
            s.finish_pca('P');self.assertEqual(set(p['halves'].values()),{'A','B'})
            with self.assertRaisesRegex(ValueError,'Finish A'):s.calculate('P','B')
            s.calculate('P','A');r=p['diagnostics']['A']['rows'][0]
            for row in p['diagnostics']['A']['rows']:
                self.assertAlmostEqual(row['Transformed Reference'],np.sqrt(row['Reference Value']))
                self.assertAlmostEqual(row['Calibration Prediction'],max(0,row['Transformed Prediction'])**2,places=7)
            s.decide('P','A',[r['File Name']],'concentration','sample');s.finish_half('P','A');s.calculate('P','B')
            self.assertFalse(s.excluded('P','A') & set(p['diagnostics']['B']['validation_files']))
            s.finish_half('P','B');dest=s.export(Path(temp)/'export')
            original=pd.read_excel(s.state['source'],sheet_name=None);clean=pd.read_excel(dest/'reference_cleaned.xlsx',sheet_name=None)
            expected=original['P'][~original['P']['File Name'].isin(s.excluded('P'))].reset_index(drop=True)
            pd.testing.assert_frame_equal(clean['P'],expected,check_exact=True)
            pd.testing.assert_frame_equal(clean['Metadata'],original['Metadata'],check_exact=True)
            with zipfile.ZipFile(s.state['source']) as a,zipfile.ZipFile(dest/'reference_cleaned.xlsx') as b:
                self.assertEqual(a.read('xl/worksheets/sheet2.xml'),b.read('xl/worksheets/sheet2.xml'))
            self.assertEqual(json.loads((dest/'reference_cleaned.cleanup.json').read_text())['concentration_limit'],'disable')
            loaded=e.Session.load(temp);self.assertTrue(loaded.state['properties']['P']['finished']['B'])
            s.decide('P','A',[r['File Name']],'concentration','sample',restore=True)
            self.assertNotIn('B',p['diagnostics']);self.assertFalse(p['finished']['B'])
            with self.assertRaisesRegex(ValueError,'finish both'):s.export(Path(temp)/'bad')

    def test_b_reuses_a_and_legacy_session_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);s.finish_pca('P');s.calculate('P','A');s.finish_half('P','A');s.calculate('P','B')
            p=s.state['properties']['P'];a=p['diagnostics']['A']['rows'][0];b=p['diagnostics']['B']['rows'][0]
            self.assertEqual((a['Preprocessing'],a['Selection Rank']),(b['Preprocessing'],b['Selection Rank']))
            self.assertEqual(b['Diagnostic Rank'],15)
            self.assertEqual(len(p['diagnostics']['B']['search']),1)
            s.decide('P','B',[b['File Name']],'','sample');s.finish_half('P','B')
            decisions=copy.deepcopy(p['decisions'])
            p['diagnostics']['B'].pop('selection_source');s.save('simulate older version')
            loaded=e.Session.load(temp);p=loaded.state['properties']['P']
            self.assertNotIn('B',p['diagnostics']);self.assertEqual(p['decisions'],decisions)
            self.assertFalse(p['finished']['B']);loaded.calculate('P','B')
            self.assertEqual(p['diagnostics']['B']['selection_source'],'A')
            f=loaded.frame('P');X=np.outer(np.arange(len(f)),np.arange(45));train=np.arange(len(f))<24
            with self.assertRaisesRegex(ValueError,"cannot support A's selected rank"):
                c.diagnose_half(X,f,train,~train,p['config'],'B',(a['Preprocessing'],15))

    def test_optional_reason_excel_and_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);s.decide('P','PCA',['S00_0.0'],'','spectrum')
            self.assertEqual(s.state['properties']['P']['decisions']['S00_0.0']['reason'],'')
            s.refit_pca('P');s.finish_pca('P');s.calculate('P','A')
            row=s.state['properties']['P']['diagnostics']['A']['rows'][0]
            s.set_limit(True,1)
            with self.assertRaisesRegex(ValueError,'allowance'):s.decide('P','A',[row['File Name']],'','sample')
            s.set_limit(False,1)
            s.decide('P','A',[row['File Name']],'','spectrum')
            self.assertEqual(s.excluded('P','A'),{row['File Name']})
            s.decide('P','A',[row['File Name']],'','spectrum',restore=True)
            path=Path(temp)/'review.xlsx';s.export_review(path)
            review=pd.read_excel(path,sheet_name='Review').fillna('')
            review.loc[review['File Name'].eq(row['File Name']),'Confirm']='YES'
            review.to_excel(path,sheet_name='Review',index=False);s.import_review(path)
            self.assertEqual(s.state['properties']['P']['decisions'][row['File Name']]['reason'],'')
            expected=set(s.frame('P').loc[s.frame('P').Sample.eq(row['Sample']),'File Name'])-s.excluded('P','PCA')
            self.assertEqual(s.excluded('P','A'),expected)

    def test_tabs_filter_sort_and_deselect(self):
        from mir_cleanup_app import Window,W,QtCore
        from types import SimpleNamespace
        from matplotlib.backend_bases import MouseEvent
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);w=Window();w.bind(s);w.show();app.processEvents()
            self.assertEqual([w.tabs.tabText(i) for i in range(w.tabs.count())],['Plot','Data sheet','Full dataset (A + B)'])
            from unittest.mock import patch
            with patch.object(W.QInputDialog,'getText',return_value=('s01',True)):
                w.table.horizontalHeader().sectionDoubleClicked.emit(0)
            self.assertEqual(len(w.visible),3)
            w.set_filter('File Name','_1.0');self.assertEqual(len(w.visible),1)
            w.table.selectRow(0);self.assertEqual(w.selected,{'S01_1.0'})
            w.clear_selection();self.assertFalse(w.selected);self.assertFalse(w.table.selectedItems())
            w.clear_filters();self.assertEqual(len(w.visible),48)
            w.table.sortItems(3,QtCore.Qt.DescendingOrder)
            values=[w.table.item(i,3).data(QtCore.Qt.DisplayRole) for i in range(w.table.rowCount())]
            self.assertEqual(values,sorted(values,reverse=True))
            filename=w.table.item(0,1).text()
            with patch.object(w,'populate',wraps=w.populate) as populate:
                w.table.selectRow(0);populate.assert_not_called()
            self.assertEqual(w.selected,{filename})
            from PySide6.QtTest import QTest
            w.canvas.setFocus();QTest.keyClick(w.canvas,QtCore.Qt.Key_Escape);self.assertFalse(w.selected)
            event=SimpleNamespace(artist=w.artist,ind=[0]);w.pick(event);self.assertEqual(len(w.selected),1)
            w.pick(SimpleNamespace(artist=w.artist,ind=[0]));self.assertFalse(w.selected)
            w.selected={w.visible[0]['File Name']};w.draw();w.canvas.draw()
            pos=w.ax.transAxes.transform((.99,.99));click=MouseEvent('button_press_event',w.canvas,*pos,button=1)
            w.plot_click(click);self.assertFalse(w.selected)
            w.tabs.setCurrentIndex(1);self.assertEqual(w.tabs.currentWidget(),w.table.parentWidget())
            w.close()

    def test_excel_namespaces_and_stn_export(self):
        from lxml import etree as XML
        source=Path(__file__).resolve().parents[2]/'data/reference/reference_value_ZL_trt.xlsx'
        if not source.exists():self.skipTest('Real workbook unavailable')
        f=pd.read_excel(source,sheet_name='202_STN');files=set(f['File Name'].iloc[:4])
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'clean.xlsx';e.export_workbook_exact(source,dest,{'202_STN':files})
            e.verify_export(source,dest,{'202_STN':files})
            with zipfile.ZipFile(source) as z,zipfile.ZipFile(dest) as out:
                altered=[name for name in z.namelist() if z.read(name)!=out.read(name)]
                self.assertEqual(len(altered),1)
                original=XML.fromstring(z.read(altered[0]));changed=XML.fromstring(out.read(altered[0]))
                self.assertEqual(original.nsmap,changed.nsmap)
                for prefix in changed.get('{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable','').split():
                    self.assertIn(prefix,changed.nsmap)
            self.assertEqual(len(pd.read_excel(dest,sheet_name='202_STN')),len(f)-4)
            with self.assertRaisesRegex(ValueError,'filenames not found'):
                e.export_workbook_exact(source,Path(temp)/'bad.xlsx',{'202_STN':{'missing-file'}})

    def test_metrics_spectrum_exclusions_and_combined(self):
        m=e.calibration_metrics([1,2,3,4],[1,2,3,3])
        self.assertAlmostEqual(m['R2'],.8);self.assertAlmostEqual(m['RMSE'],.5)
        self.assertAlmostEqual(m['RPD'],np.sqrt(5/3)/.5);self.assertAlmostEqual(m['RPIQ'],3.)
        self.assertIsNone(e.calibration_metrics([1],[1])['RPD'])
        self.assertIsNone(e.calibration_metrics([2,2],[1,1])['R2'])
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);s.finish_pca('P');s.calculate('P','A');p=s.state['properties']['P'];r=p['diagnostics']['A']['rows'][0]
            s.decide('P','A',[r['File Name']],'concentration','spectrum');self.assertEqual(s.excluded('P','A'),{r['File Name']})
            s.finish_half('P','A');s.calculate('P','B')
            self.assertNotIn(r['File Name'],p['diagnostics']['B']['validation_files'])
            siblings=set(s.frame('P').loc[s.frame('P').Sample.eq(r['Sample']),'File Name'])-{r['File Name']}
            self.assertTrue(siblings<=set(p['diagnostics']['B']['validation_files']))
            rows=e.combined_rows(s,'P');self.assertEqual(len(rows),48);self.assertEqual(set(x['Half'] for x in rows),{'A','B'})
            self.assertEqual(sum(x['Status']=='Excluded' for x in rows),1)
            path=Path(temp)/'review.xlsx';s.export_review(path);s.import_review(path)
            self.assertEqual(s.excluded('P','A'),{r['File Name']})
            s.finish_half('P','B');dest=s.export(Path(temp)/'clean')
            self.assertEqual(len(pd.read_excel(dest/'reference_cleaned.xlsx',sheet_name='P')),47)
            self.assertIn('last_export',s.state)
            s.decide('P','B',[p['diagnostics']['B']['rows'][0]['File Name']],'','spectrum')
            self.assertNotIn('last_export',s.state)

    def test_plot_controls_metrics_legends_and_toggle(self):
        from mir_cleanup_app import Window,W
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);w=Window();w.bind(s);w.show();app.processEvents()
            mask=np.arange(len(w.visible))<2;w.toggle_points(mask);first=set(w.selected)
            second=np.arange(len(w.visible))==3;w.toggle_points(second);self.assertEqual(len(w.selected),3)
            w.toggle_points(mask);self.assertEqual(len(w.selected),1);self.assertFalse(w.selected & first)
            w.ax.set_xlim(-100,100)
            limits=w.ax.get_xlim();w.toggle_points(second);self.assertEqual(w.ax.get_xlim(),limits)
            for mode in range(3):
                w.colour.setCurrentIndex(mode);w.draw();self.assertIsNotNone(w.ax.get_legend())
                self.assertEqual(w.colorbar is not None,mode==2)
            s.finish_pca('P');s.calculate('P','A');w.stage.setCurrentText('A')
            self.assertTrue(w.unit.isEnabled());w.unit.setCurrentText('spectrum');self.assertEqual(w.unit.currentText(),'spectrum')
            self.assertTrue(any('RPIQ' in t.get_text() for t in w.ax.texts));self.assertEqual(w.full_table.rowCount(),48)
            w.full_search.setText('Excluded');self.assertEqual(w.full_table.rowCount(),0)
            w.close()

    def test_magnifier_rectangle_directions(self):
        from mir_cleanup_app import Window,W
        from matplotlib.backend_bases import MouseEvent
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            w=Window();w.bind(fixture(temp));w.show();app.processEvents();w.canvas.draw()
            self.assertFalse(any(b.text() in ['Zoom in','Zoom out'] for b in w.findChildren(W.QPushButton)))
            w.select_mode.setCurrentIndex(1);self.assertIsNotNone(w.rect)
            selected={w.visible[0]['File Name']};w.selected=selected.copy()
            for direction in ['in','out']:
                w.toolbar.direction_actions[direction].trigger();self.assertIsNone(w.rect)
                self.assertEqual(w.toolbar.mode.name,'ZOOM')
                before=np.ptp(w.ax.get_xlim())
                start=w.ax.transAxes.transform((.25,.25));end=w.ax.transAxes.transform((.75,.75))
                for name,point in [('button_press_event',start),('motion_notify_event',end),('button_release_event',end)]:
                    w.canvas.callbacks.process(name,MouseEvent(name,w.canvas,*point,button=1))
                app.processEvents();w.canvas.draw()
                after=np.ptp(w.ax.get_xlim())
                if direction=='in':self.assertLess(after,before)
                else:self.assertGreater(after,before)
                self.assertEqual(w.selected,selected)
            w.toolbar.back();app.processEvents()
            self.assertLess(np.ptp(w.ax.get_xlim()),after)
            w.toolbar.zoom();self.assertIsNotNone(w.rect)
            self.assertIsNotNone(w.toolbar.zoom_button.menu())
            w.close()

    def test_saved_values_keep_full_float_precision(self):
        value=1.2345678901234567
        self.assertEqual(e.records(pd.DataFrame({'value':[value]}))[0]['value'],value)

    def test_limits_import_resume_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);s.finish_pca('P');s.calculate('P','A');p=s.state['properties']['P'];row=p['diagnostics']['A']['rows'][0]
            s.set_limit(True,1)
            with self.assertRaisesRegex(ValueError,'allowance'):s.decide('P','A',[row['File Name']],'concentration','sample')
            s.set_limit(True,6.25);s.decide('P','A',[row['File Name']],'concentration','sample')
            path=Path(temp)/'review.xlsx';s.export_review(path);s.import_review(path)
            self.assertEqual(len({d['sample'] for d in p['decisions'].values()}),1)
            wrong=Path(temp)/'wrong.xlsx';wrong.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'fingerprint'):s.relocate_source(wrong)
            (Path(temp)/'x.npz').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'verification'):e.Session.load(temp)

    def test_rank_and_pca_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp)
            for name in ['S00_0.0','S01_0.0']:
                s.decide('P','PCA',[name],'spectral_quality','spectrum');s.refit_pca('P')
            with self.assertRaisesRegex(ValueError,'Three PCA'):s.decide('P','PCA',['S02_0.0'],'spectral_quality','spectrum')
            f=s.frame('P');X=np.outer(np.arange(len(f)),np.arange(45));train=np.arange(len(f))<24
            cfg=s.state['properties']['P']['config'];diag,search=c.diagnose_half(X,f,train,~train,cfg,'A')
            self.assertLess(diag['Diagnostic Rank'].iloc[0],15)

    def test_background_workbook_and_window_callbacks(self):
        from mir_cleanup_app import Setup,Window,W,QtCore
        from PySide6.QtTest import QTest
        import time
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            session=fixture(temp);d=Setup();d.source.setText(session.state['source']);d.load_properties()
            deadline=time.monotonic()+10
            while d.reader is not None and time.monotonic()<deadline:QTest.qWait(10)
            self.assertIsNone(d.reader);self.assertEqual(d.property_checks[0].text(),'P');d.close()
            w=Window();threads=[]
            def completed(value):
                threads.append(QtCore.QThread.currentThread()==app.thread());w.bind(value)
            w.run(lambda:session,completed)
            deadline=time.monotonic()+10
            while w.worker is not None and time.monotonic()<deadline:QTest.qWait(10)
            self.assertIsNone(w.worker);self.assertEqual(threads,[True]);w.close()

    def test_desktop_axes_and_decision_selection(self):
        from mir_cleanup_app import Window,W
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            s=fixture(temp);w=Window();w.bind(s)
            for x in range(w.xpc.count()):
                for y in range(w.ypc.count()):
                    w.xpc.blockSignals(True);w.ypc.blockSignals(True);w.xpc.setCurrentIndex(x);w.ypc.setCurrentIndex(y)
                    w.xpc.blockSignals(False);w.ypc.blockSignals(False);w.draw()
                    np.testing.assert_allclose(w.xy,[[r['scores'][x],r['scores'][y]] for r in s.state['properties']['P']['pca']['rows']])
            w.table.selectRow(0);self.assertEqual(len(w.selected),1)
            s.finish_pca('P');s.calculate('P','A');w.stage.setCurrentText('A');w.refresh()
            for scale in [0,1]:
                w.scale.setCurrentIndex(scale);w.draw();r=w.visible[0]
                self.assertAlmostEqual(w.xy[0,0],r['Transformed Reference' if scale==0 else 'Reference Value'])
            w.checkpoint();s.decide('P','A',[w.visible[0]['File Name']],'concentration','sample');w.undo();self.assertFalse(s.excluded('P'))
            w.figure.savefig(Path(temp)/'ui.png');w.close();app.processEvents()

if __name__=='__main__':unittest.main()
