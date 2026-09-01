import unittest

from core.models import Listing
from core.normalizer import normalize_many, normalize_one


class TestNormalizer(unittest.TestCase):
    def test_maps_capacidad_to_ambientes(self):
        raw = {
            "url": "https://example.com/1",
            "sitio_origen": "zonaprop",
            "precio": 100000,
            "moneda": "ARS",
            "capacidad": 2,
            "ubicacion": "Palermo",
        }
        listing = normalize_one(raw)
        self.assertIsInstance(listing, Listing)
        self.assertEqual(listing.ambientes, 2.0)

    def test_uses_sitio_origen_fallback_when_missing_in_raw(self):
        raw = {"url": "https://example.com/2"}
        listing = normalize_one(raw, sitio_origen="zonaprop")
        self.assertEqual(listing.sitio_origen, "zonaprop")

    def test_discards_raw_without_url(self):
        raw = {"sitio_origen": "zonaprop", "precio": 1000}
        self.assertIsNone(normalize_one(raw))

    def test_discards_non_dict_raw(self):
        self.assertIsNone(normalize_one("no es un dict"))

    def test_normalize_many_skips_invalid_entries(self):
        raws = [
            {"url": "https://example.com/1", "sitio_origen": "zonaprop"},
            {"sitio_origen": "zonaprop"},  # sin url, se descarta
            {"url": "https://example.com/2", "sitio_origen": "zonaprop", "capacidad": 3},
        ]
        listings = normalize_many(raws)
        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[1].ambientes, 3.0)


if __name__ == "__main__":
    unittest.main()
