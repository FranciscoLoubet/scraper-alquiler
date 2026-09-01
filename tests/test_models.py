import unittest

from core.models import Listing


class TestListing(unittest.TestCase):
    def test_requires_url_and_sitio_origen(self):
        with self.assertRaises(ValueError):
            Listing(url="", sitio_origen="zonaprop")
        with self.assertRaises(ValueError):
            Listing(url="https://example.com/1", sitio_origen="")

    def test_coerces_invalid_numeric_fields_to_default(self):
        listing = Listing(
            url="https://example.com/1",
            sitio_origen="zonaprop",
            expensas="no-numerico",
        )
        self.assertEqual(listing.expensas, 0.0)

    def test_precio_invalid_becomes_none_not_zero(self):
        listing = Listing(url="https://example.com/1", sitio_origen="zonaprop", precio="n/a")
        self.assertIsNone(listing.precio)

    def test_dedup_key_normalizes_trailing_slash_and_case(self):
        a = Listing(url="HTTPS://Example.com/Prop/1/", sitio_origen="zonaprop")
        b = Listing(url="https://example.com/prop/1", sitio_origen="zonaprop")
        self.assertEqual(a.dedup_key, b.dedup_key)

    def test_from_dict_ignores_unknown_keys(self):
        listing = Listing.from_dict(
            {"url": "https://example.com/1", "sitio_origen": "zonaprop", "campo_random": 123}
        )
        self.assertEqual(listing.url, "https://example.com/1")

    def test_to_row_matches_headers_order(self):
        listing = Listing(url="https://example.com/1", sitio_origen="zonaprop")
        self.assertEqual(len(listing.to_row()), len(Listing.HEADERS))


if __name__ == "__main__":
    unittest.main()
