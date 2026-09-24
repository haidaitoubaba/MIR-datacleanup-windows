"""Windows paths, UTF-8 sessions and resource availability regressions."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mir_cleanup_session as engine
import soil_mir_data_cleanup as core
from test_mir_cleanup_app import fixture


class PortabilityTests(unittest.TestCase):
    def test_unicode_paths_session_relocation_and_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'MIR données 测试 avec espaces'
            session = fixture(root)
            session.state['note'] = 'Révision 测试'
            session.save('Saved Unicode comment')
            # Also accept valid UTF-8 JSON written without ASCII escaping.
            path = root / 'session.json'
            path.write_text(json.dumps(session.state, ensure_ascii=False), encoding='utf-8')
            session = engine.Session.load(root)
            self.assertEqual(session.state['note'], 'Révision 测试')
            old_source = Path(session.state['source'])
            new_source = root / 'référence déplacée.xlsx'
            shutil.copyfile(old_source, new_source)
            session.state['source'] = '/Users/old/MIR/original.xlsx'
            session.relocate_source(new_source)
            session.finish_pca('P')
            session.calculate('P', 'A'); session.finish_half('P', 'A')
            session.calculate('P', 'B'); session.finish_half('P', 'B')
            destination = session.export(root / 'résultat exporté')
            engine.verify_export(new_source, destination / 'reference_cleaned.xlsx', {'P': set()})
            html = (destination / 'PCA_viewer.html').read_text(encoding='utf-8')
            self.assertNotIn('/*PLOTLY_BUNDLE*/', html)
            self.assertIn('Plotly', html)
            self.assertEqual(core.fingerprint(old_source), core.fingerprint(new_source))

    def test_failed_atomic_save_preserves_previous_session(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'session.json'
            engine.atomic_json(path, {'value': 'original'})
            with patch.object(engine.os, 'replace', side_effect=PermissionError('File is locked')):
                with self.assertRaises(PermissionError):
                    engine.atomic_json(path, {'value': 'new'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'value': 'original'})


if __name__ == '__main__':
    unittest.main()
