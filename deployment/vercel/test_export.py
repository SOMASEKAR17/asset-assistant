import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('export_static', Path(__file__).resolve().parents[1] / 'export_static.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExportBoundaries(unittest.TestCase):
    def test_container_paths_are_remapped_but_traversal_is_rejected(self):
        scratch = Path(__file__).resolve().parents[1] / '.preview'
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            root = Path(folder) / 'library'
            root.mkdir()
            sample = root / 'sample.mp4'
            sample.write_bytes(b'test')
            (root.parent / 'private.mp4').write_bytes(b'private')
            self.assertEqual(module.mapped_file('/library/sample.mp4', root, '/library'), sample.resolve())
            with self.assertRaises(ValueError):
                module.mapped_file('/library/../private.mp4', root, '/library')
            with self.assertRaises(ValueError):
                module.mapped_file('/library/missing.mp4', root, '/library')

    def test_tags_exclude_nested_metadata(self):
        self.assertEqual(module.tags('["sunset", {"secret":"not a tag"}, 5]'), ['sunset'])
        self.assertEqual(module.tags('{"path":"private"}'), [])


if __name__ == '__main__':
    unittest.main()
