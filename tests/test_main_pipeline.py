import unittest
from unittest.mock import MagicMock

import main
from core.currency import CotizacionDolar
from core.models import Listing


def _cotizador_ars():
    """CotizacionDolar real: para montos en ARS pasa el valor directo
    sin pegarle a la red, así que no hace falta mockear nada."""
    return CotizacionDolar(session=MagicMock())


def _listing(**kwargs):
    defaults = dict(url="https://example.com/1", sitio_origen="zonaprop")
    defaults.update(kwargs)
    return Listing(**defaults)


CRITERIOS_CAPACIDAD = {
    "capacidad": {"ambientes_a_personas": {2: 2, 3: 4}},
    "precio_por_persona": {"moneda": "ARS", "maximo": 600000},
}


class TestCumpleCapacidadYPrecio(unittest.TestCase):
    def test_sin_mapeo_configurado_no_filtra(self):
        listing = _listing(ambientes=1, precio=999999999)
        self.assertTrue(main.cumple_capacidad_y_precio(listing, {}, MagicMock()))

    def test_ambientes_fuera_del_mapeo_se_descarta(self):
        listing = _listing(ambientes=1, precio=100)
        self.assertFalse(
            main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, MagicMock())
        )

    def test_2_ambientes_dentro_del_tope_pasa(self):
        listing = _listing(ambientes=2, precio=1_200_000, moneda="ARS")
        self.assertTrue(
            main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, _cotizador_ars())
        )

    def test_2_ambientes_supera_el_tope_se_descarta(self):
        listing = _listing(ambientes=2, precio=1_200_001, moneda="ARS")
        self.assertFalse(
            main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, _cotizador_ars())
        )

    def test_3_ambientes_usa_el_tope_de_4_personas(self):
        listing = _listing(ambientes=3, precio=2_400_000, moneda="ARS")
        self.assertTrue(
            main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, _cotizador_ars())
        )
        listing_caro = _listing(ambientes=3, precio=2_400_001, moneda="ARS")
        self.assertFalse(
            main.cumple_capacidad_y_precio(listing_caro, CRITERIOS_CAPACIDAD, _cotizador_ars())
        )

    def test_convierte_usd_a_ars_antes_de_comparar(self):
        cotizador = MagicMock()
        cotizador.a_ars.return_value = 1_200_000
        listing = _listing(ambientes=2, precio=1000, moneda="USD")
        self.assertTrue(main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, cotizador))
        cotizador.a_ars.assert_called_once_with(1000, "USD")

    def test_sin_precio_se_descarta(self):
        listing = _listing(ambientes=2, precio=None)
        self.assertFalse(
            main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, MagicMock())
        )

    def test_conversion_fallida_se_descarta(self):
        cotizador = MagicMock()
        cotizador.a_ars.return_value = None
        listing = _listing(ambientes=2, precio=1000, moneda="USD")
        self.assertFalse(main.cumple_capacidad_y_precio(listing, CRITERIOS_CAPACIDAD, cotizador))


UNI = (-34.44644, -58.529835)

CRITERIOS_UBICACION = {
    "transporte": {
        "radio_caminata_uni_km": 1.5,
        "combis": {"radio_metros": 600},
        "tren_costa": {"radio_metros": 700},
        "tren_mitre": {"radio_metros": 700},
        "colectivo": {"radio_metros": 400},
    }
}


class TestClasificarUbicacion(unittest.TestCase):
    def test_caminando_si_esta_dentro_del_radio(self):
        listing = _listing(lat=UNI[0] + 0.001, lon=UNI[1])  # ~100m
        geocoder = MagicMock()
        poi_finder = MagicMock()
        nivel, etiqueta = main.clasificar_ubicacion(
            listing, CRITERIOS_UBICACION, UNI, [], [], [], geocoder, poi_finder
        )
        self.assertEqual(nivel, main.NIVEL_CAMINANDO)
        self.assertEqual(etiqueta, "Caminando a la universidad")
        poi_finder.existe_cerca.assert_not_called()

    def test_combi_tiene_prioridad_sobre_tren_y_colectivo(self):
        lejos_de_la_uni = (-34.30, -58.60)
        combi = (-34.30, -58.601)  # ~100m del listing
        listing = _listing(lat=lejos_de_la_uni[0], lon=lejos_de_la_uni[1])
        poi_finder = MagicMock()
        poi_finder.existe_cerca.return_value = True  # habría colectivo, pero combi debe ganar
        nivel, etiqueta = main.clasificar_ubicacion(
            listing,
            CRITERIOS_UBICACION,
            UNI,
            [combi],
            [combi],  # tren_costa también cerca, pero combi debe ganar igual
            [],
            MagicMock(),
            poi_finder,
        )
        self.assertEqual(nivel, main.NIVEL_COMBI)

    def test_tren_costa_antes_que_tren_mitre(self):
        lejos_de_la_uni = (-34.30, -58.60)
        tren = (-34.30, -58.601)
        listing = _listing(lat=lejos_de_la_uni[0], lon=lejos_de_la_uni[1])
        nivel, _ = main.clasificar_ubicacion(
            listing, CRITERIOS_UBICACION, UNI, [], [tren], [tren], MagicMock(), MagicMock()
        )
        self.assertEqual(nivel, main.NIVEL_TREN_COSTA)

    def test_colectivo_solo_si_no_hay_nada_mejor(self):
        lejos_de_la_uni = (-34.30, -58.60)
        listing = _listing(lat=lejos_de_la_uni[0], lon=lejos_de_la_uni[1])
        poi_finder = MagicMock()
        poi_finder.existe_cerca.return_value = True
        nivel, etiqueta = main.clasificar_ubicacion(
            listing, CRITERIOS_UBICACION, UNI, [], [], [], MagicMock(), poi_finder
        )
        self.assertEqual(nivel, main.NIVEL_COLECTIVO)
        self.assertEqual(etiqueta, "Colectivo")

    def test_sin_nada_cerca(self):
        lejos_de_la_uni = (-34.30, -58.60)
        listing = _listing(lat=lejos_de_la_uni[0], lon=lejos_de_la_uni[1])
        poi_finder = MagicMock()
        poi_finder.existe_cerca.return_value = False
        nivel, etiqueta = main.clasificar_ubicacion(
            listing, CRITERIOS_UBICACION, UNI, [], [], [], MagicMock(), poi_finder
        )
        self.assertEqual(nivel, main.NIVEL_SIN_TRANSPORTE)
        self.assertEqual(etiqueta, "Sin transporte cercano")

    def test_sin_coordenadas_geocodifica(self):
        listing = _listing(lat=None, lon=None, ubicacion="Algún lugar")
        geocoder = MagicMock()
        geocoder.geocode.return_value = UNI
        nivel, _ = main.clasificar_ubicacion(
            listing, CRITERIOS_UBICACION, UNI, [], [], [], geocoder, MagicMock()
        )
        geocoder.geocode.assert_called_once_with("Algún lugar")
        self.assertEqual(nivel, main.NIVEL_CAMINANDO)


if __name__ == "__main__":
    unittest.main()
