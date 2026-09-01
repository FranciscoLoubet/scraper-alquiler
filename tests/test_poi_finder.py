import unittest
from unittest.mock import MagicMock

from core.poi_finder import POIFinder, haversine_km


class TestHaversine(unittest.TestCase):
    def test_same_point_is_zero(self):
        self.assertAlmostEqual(haversine_km(-34.6, -58.4, -34.6, -58.4), 0.0, places=6)

    def test_known_distance_caba_to_tigre_is_roughly_correct(self):
        # Obelisco (-34.6037, -58.3816) a Tigre centro (-34.4264, -58.5796),
        # ~27km en línea recta.
        distancia = haversine_km(-34.6037, -58.3816, -34.4264, -58.5796)
        self.assertGreater(distancia, 20)
        self.assertLess(distancia, 35)


class TestPOIFinderQuery(unittest.TestCase):
    def test_build_query_unknown_type_raises(self):
        finder = POIFinder(session=MagicMock())
        with self.assertRaises(ValueError):
            finder._build_query("aeropuerto", -34.6, -58.4, 500)

    def test_build_query_includes_all_tags_for_type(self):
        finder = POIFinder(session=MagicMock())
        query = finder._build_query("supermercado", -34.6, -58.4, 500)
        self.assertIn('node["shop"="supermarket"]', query)
        self.assertIn('node["shop"="convenience"]', query)
        self.assertIn("around:500,-34.6,-58.4", query)


class TestPOIFinderExisteCerca(unittest.TestCase):
    def _session_devolviendo(self, payload):
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        session.post.return_value = response
        return session

    def test_true_when_elements_present(self):
        session = self._session_devolviendo({"elements": [{"type": "node", "id": 1}]})
        finder = POIFinder(session=session)
        finder._throttle = lambda: None
        self.assertTrue(finder.existe_cerca("gimnasio", -34.6, -58.4, 500))

    def test_false_when_no_elements(self):
        session = self._session_devolviendo({"elements": []})
        finder = POIFinder(session=session)
        finder._throttle = lambda: None
        self.assertFalse(finder.existe_cerca("gimnasio", -34.6, -58.4, 500))

    def test_result_is_cached(self):
        session = self._session_devolviendo({"elements": [{"type": "node", "id": 1}]})
        finder = POIFinder(session=session)
        finder._throttle = lambda: None
        finder.existe_cerca("gimnasio", -34.6, -58.4, 500)
        finder.existe_cerca("gimnasio", -34.6, -58.4, 500)
        self.assertEqual(session.post.call_count, 1)

    def test_fails_open_on_request_error(self):
        session = MagicMock()
        session.post.side_effect = RuntimeError("timeout")
        finder = POIFinder(session=session)
        finder._throttle = lambda: None
        self.assertTrue(finder.existe_cerca("gimnasio", -34.6, -58.4, 500))


if __name__ == "__main__":
    unittest.main()
