import unittest

from core.filters import FilterConfig, apply_filters
from core.models import Listing


def _listing(**kwargs):
    defaults = dict(url="https://example.com/1", sitio_origen="zonaprop", precio=200000)
    defaults.update(kwargs)
    return Listing(**defaults)


class TestApplyFilters(unittest.TestCase):
    def test_no_filters_returns_everything(self):
        listings = [_listing(url="https://example.com/1"), _listing(url="https://example.com/2")]
        config = FilterConfig(precio_min=None, precio_max=None)
        self.assertEqual(len(apply_filters(listings, config)), 2)

    def test_precio_min_excludes_below_threshold(self):
        listings = [_listing(precio=100), _listing(precio=500000)]
        config = FilterConfig(precio_min=100000, precio_max=None)
        resultado = apply_filters(listings, config)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].precio, 500000)

    def test_listing_without_precio_excluded_when_price_filter_active(self):
        listings = [_listing(precio=None)]
        config = FilterConfig(precio_min=100000, precio_max=None)
        self.assertEqual(apply_filters(listings, config), [])

    def test_amueblado_filter(self):
        listings = [_listing(amueblado=True), _listing(amueblado=False), _listing(amueblado=None)]
        config = FilterConfig(precio_min=None, amueblado=True)
        resultado = apply_filters(listings, config)
        self.assertEqual(len(resultado), 1)
        self.assertTrue(resultado[0].amueblado)


if __name__ == "__main__":
    unittest.main()
