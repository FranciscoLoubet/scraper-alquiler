import unittest
from unittest.mock import MagicMock

from core.puntos_referencia import resolver_puntos


class TestResolverPuntos(unittest.TestCase):
    def test_lat_lon_hardcodeados_no_geocodifican(self):
        geocoder = MagicMock()
        resueltos = resolver_puntos([{"nombre": "x", "lat": -34.5, "lon": -58.5}], geocoder)
        self.assertEqual(resueltos, [(-34.5, -58.5)])
        geocoder.geocode.assert_not_called()

    def test_geocodifica_cuando_no_hay_lat_lon(self):
        geocoder = MagicMock()
        geocoder.geocode.return_value = (-34.5, -58.5)
        resueltos = resolver_puntos([{"nombre": "x", "direccion": "algun lugar"}], geocoder)
        self.assertEqual(resueltos, [(-34.5, -58.5)])
        geocoder.geocode.assert_called_once_with("algun lugar")

    def test_omite_puntos_que_no_se_pudieron_geocodificar(self):
        geocoder = MagicMock()
        geocoder.geocode.side_effect = [None, (-34.5, -58.5)]
        puntos = [
            {"nombre": "a", "direccion": "no existe"},
            {"nombre": "b", "direccion": "si existe"},
        ]
        self.assertEqual(resolver_puntos(puntos, geocoder), [(-34.5, -58.5)])

    def test_omite_puntos_sin_direccion_ni_lat_lon(self):
        geocoder = MagicMock()
        self.assertEqual(resolver_puntos([{"nombre": "x"}], geocoder), [])
        geocoder.geocode.assert_not_called()

    def test_lista_vacia(self):
        self.assertEqual(resolver_puntos([], MagicMock()), [])


if __name__ == "__main__":
    unittest.main()
