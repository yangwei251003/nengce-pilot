"""Publication boundary regressions, with no real provider or private data access."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.v3 import data, provider, provider_profiles


class OpenSourceBoundaryTests(unittest.TestCase):
    def test_builtin_model_needs_explicit_credential_file(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'read_text') as read:
            with self.assertRaisesRegex(ValueError, 'NENGCE_CREDENTIAL_FILE'):
                provider.credential()
            read.assert_not_called()

    def test_default_profile_namespace_is_distinct(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=Path(tempfile.gettempdir())):
            self.assertIn('NengcePilotOpenSource', provider_profiles.store_path().parts)

    def test_catalog_marks_missing_original_without_rewriting_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root/'catalog'/'sample'
            folder.mkdir(parents=True)
            original = {'dataset_id':'sample','provenance':{'raw_files':[{'path':'missing.csv','sha256':'unavailable'}]}}
            text = json.dumps(original)
            (folder/'metadata.json').write_text(text, encoding='utf-8')
            with patch.object(data,'CATALOG',root/'catalog'), patch.object(data,'UPLOADS',root/'private-imports'):
                result = data.list_datasets()[0]
            self.assertFalse(result['runtime_ready'])
            self.assertEqual(result['runtime_missing'],['missing.csv'])
            self.assertEqual((folder/'metadata.json').read_text(encoding='utf-8'),text)


if __name__ == '__main__':
    unittest.main()
