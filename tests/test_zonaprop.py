import unittest

from sites.zonaprop import ZonapropScraper


class DummyResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class DummySession:
    def __init__(self, text):
        self.text = text

    def get(self, url):
        return DummyResponse(self.text)


class TestZonapropScraper(unittest.TestCase):
    def test_fetch_listings_handles_json_with_closing_brace_in_string(self):
        html = '''
        <script>
        window.__PRELOADED_STATE__ = {"listStore":{"listPostings":[{"url":"/prop/1","title":"foo }; bar","priceOperationTypes":[{"prices":[{"amount":123,"currency":"USD"}]}],"postingLocation":{"location":{"name":"Palermo"},"postingGeolocation":{"geolocation":{"latitude":-34.6,"longitude":-58.4}}},"mainFeatures":{"CFT1":{"value":"2"}}}],"paging":{"totalPages":1}}};
        </script>
        '''
        scraper = ZonapropScraper(DummySession(html), "https://www.zonaprop.com.ar/alquiler/palermo.html")
        listings = scraper.fetch_listings()
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["title"], "foo }; bar")

    def test_parse_listing_handles_empty_lists_safely(self):
        scraper = ZonapropScraper(DummySession(""), "https://www.zonaprop.com.ar/alquiler/palermo.html")
        parsed = scraper.parse_listing({
            "url": "/prop/2",
            "postingLocation": {
                "location": {"name": "Belgrano"},
                "postingGeolocation": {"geolocation": {"latitude": -34.6, "longitude": -58.4}},
            },
            "mainFeatures": {"CFT1": {"value": "3"}},
            "priceOperationTypes": [],
            "expenses": {},
        })
        self.assertEqual(parsed["precio"], 0)
        self.assertEqual(parsed["moneda"], "ARS")
        self.assertEqual(parsed["ubicacion"], "Belgrano")


if __name__ == "__main__":
    unittest.main()
