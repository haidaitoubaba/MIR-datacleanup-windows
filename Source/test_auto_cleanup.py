import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import mir_cleanup_auto as auto
import mir_cleanup_session as engine
from test_mir_cleanup_app import fixture

class AutoCleanupTests(unittest.TestCase):
    def test_batch_matches_manual_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as root:
            source=fixture(Path(root)/'input'); original=copy.deepcopy(source.state)
            manual=fixture(Path(root)/'manual'); manual.finish_pca('P')
            for half in ('A','B'):
                manual.calculate('P',half)
                rows=manual.state['properties']['P']['diagnostics'][half]['rows']
                files=[r['File Name'] for r in rows if r.get('Concentration Candidate')]
                if files: manual.decide('P',half,files,'concentration','sample','test')
                manual.finish_half('P',half)
            result=auto.run(source)
            self.assertEqual(source.state,original)
            self.assertEqual(result.excluded('P'),manual.excluded('P'))
            self.assertTrue(result.state['properties']['P']['finished']['B'])
            self.assertEqual(auto.readiness(result),[])
            self.assertEqual(engine.Session.load(result.folder).excluded('P'),result.excluded('P'))
    def test_failure_rollback_and_skip(self):
        with tempfile.TemporaryDirectory() as root:
            source=fixture(Path(root)/'input'); before=copy.deepcopy(source.state['properties']['P'])
            with patch.object(engine.Session,'calculate',side_effect=ValueError('rank unavailable')):
                result=auto.run(source)
            self.assertEqual(result.state['properties']['P'],before)
            self.assertEqual(result.state['auto_cleanup']['results'][0]['status'],'failed')
            self.assertTrue(auto.readiness(result))
            source.state['properties']['P']['finished']['A']=True; source.save('Existing review')
            self.assertEqual(auto.run(source).state['auto_cleanup']['results'][0]['status'],'skipped')
    def test_recover_interrupted_property(self):
        with tempfile.TemporaryDirectory() as root:
            source=fixture(Path(root)/'input'); before=copy.deepcopy(source.state['properties']['P'])
            source.state['_auto_checkpoint']={'property':'P','state':before,'history_length':len(source.state['history'])}
            source.state['properties']['P']['pca_done']=True; source.save('Interrupted')
            loaded=engine.Session.load(source.folder)
            self.assertEqual(loaded.state['properties']['P'],before)
            self.assertNotIn('_auto_checkpoint',loaded.state)

if __name__=='__main__': unittest.main()

class AutoGuiTests(unittest.TestCase):
    def test_button_runs_and_binds_copy(self):
        import time
        from mir_cleanup_app import Window, W
        app=W.QApplication.instance() or W.QApplication([])
        with tempfile.TemporaryDirectory() as root:
            source=fixture(Path(root)/'input'); w=Window(); w.bind(source); w.show()
            with patch.object(W.QMessageBox,'question',return_value=W.QMessageBox.Yes), patch.object(W.QMessageBox,'exec',return_value=0):
                w.auto_clean()
                deadline=time.monotonic()+90
                while w.worker is not None and time.monotonic()<deadline:
                    app.processEvents(); time.sleep(.02)
                self.assertIsNone(w.worker)
                self.assertNotEqual(w.session.folder,source.folder)
                self.assertTrue(w.session.state['properties']['P']['finished']['B'])
                self.assertTrue(w.centralWidget().isEnabled())
            w.close()

class AutoBoundaryTests(unittest.TestCase):
    def test_stop_after_current_property(self):
        import threading
        with tempfile.TemporaryDirectory() as root:
            source=fixture(Path(root)/'input'); source.state['properties']['Q']=copy.deepcopy(source.state['properties']['P']);source.save('add property')
            flag=threading.Event()
            def progress(i,n,prop,stage):
                if prop=='P' and stage=='A':flag.set()
            result=auto.run(source,progress,flag.is_set)
            self.assertTrue(result.state['properties']['P']['finished']['B'])
            self.assertFalse(result.state['properties']['Q']['finished']['B'])
            self.assertTrue(result.state['auto_cleanup']['stopped'])
            self.assertTrue(auto.readiness(result))
    def test_limit_failure_continues_next_property(self):
        with tempfile.TemporaryDirectory() as root:
            source=fixture(Path(root)/'input');source.state['properties']['Q']=copy.deepcopy(source.state['properties']['P']);source.set_limit(True,0)
            original_calculate=engine.Session.calculate
            def calculate(session,prop,half):
                original_calculate(session,prop,half)
                if prop=='P' and half=='A': session.state['properties'][prop]['diagnostics'][half]['rows'][0]['Concentration Candidate']=True
                if prop=='Q':
                    for row in session.state['properties'][prop]['diagnostics'][half]['rows']:row['Concentration Candidate']=False
            with patch.object(engine.Session,'calculate',calculate):result=auto.run(source)
            statuses=[r['status'] for r in result.state['auto_cleanup']['results']]
            self.assertEqual(statuses,['failed','completed'])
            self.assertFalse(result.state['properties']['P']['pca_done'])
            self.assertTrue(result.state['properties']['Q']['finished']['B'])
