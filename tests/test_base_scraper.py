import logging
import unittest

from sites.base import Scraper


class DummyScraper(Scraper):
    def fetch_listings(self):
        return [{"url": "https://example.com/1"}, {"url": "https://example.com/2"}]

    def parse_listing(self, raw):
        if raw["url"].endswith("1"):
            raise ValueError("boom")
        return {"url": raw["url"]}


class BrokenFetchScraper(Scraper):
    def fetch_listings(self):
        raise RuntimeError("fetch exploded")

    def parse_listing(self, raw):
        return raw


class TestScraper(unittest.TestCase):
    def test_session_default_is_none_not_string(self):
        scraper = DummyScraper()
        self.assertIsNone(scraper.session)

    def test_run_logs_failures_and_continues(self):
        scraper = DummyScraper()
        with self.assertLogs("sites.base", level="ERROR") as captured:
            result = scraper.run()
        self.assertEqual(len(result), 1)
        self.assertIn("https://example.com/1", "\n".join(captured.output))

    def test_run_handles_fetch_listings_exception(self):
        scraper = BrokenFetchScraper()
        with self.assertLogs("sites.base", level="ERROR") as captured:
            result = scraper.run()
        self.assertEqual(result, [])
        self.assertIn("fetch exploded", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
