import json
import tempfile
import unittest
from pathlib import Path

from core.dedup import Deduplicator
from core.models import Listing


def _listing(url):
    return Listing(url=url, sitio_origen="zonaprop")


class TestDeduplicator(unittest.TestCase):
    def test_filters_intra_batch_duplicates(self):
        dedup = Deduplicator(storage_path=None)
        listings = [_listing("https://example.com/1"), _listing("https://example.com/1")]
        self.assertEqual(len(dedup.filter_new(listings)), 1)

    def test_persists_between_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "vistos.json"

            primero = Deduplicator(storage_path=storage)
            nuevas = primero.filter_new([_listing("https://example.com/1")])
            self.assertEqual(len(nuevas), 1)

            segundo = Deduplicator(storage_path=storage)
            nuevas_segunda_corrida = segundo.filter_new(
                [_listing("https://example.com/1"), _listing("https://example.com/2")]
            )
            self.assertEqual(len(nuevas_segunda_corrida), 1)
            self.assertEqual(nuevas_segunda_corrida[0].url, "https://example.com/2")

    def test_corrupt_storage_file_starts_empty_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "vistos.json"
            storage.write_text("esto no es json valido", encoding="utf-8")

            dedup = Deduplicator(storage_path=storage)
            nuevas = dedup.filter_new([_listing("https://example.com/1")])
            self.assertEqual(len(nuevas), 1)

    def test_reset_clears_in_memory_state_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "vistos.json"
            dedup = Deduplicator(storage_path=storage)
            dedup.filter_new([_listing("https://example.com/1")])
            dedup.reset()
            self.assertEqual(len(dedup.filter_new([_listing("https://example.com/1")])), 1)
            data = json.loads(storage.read_text(encoding="utf-8"))
            self.assertIn("https://example.com/1", data)


if __name__ == "__main__":
    unittest.main()
