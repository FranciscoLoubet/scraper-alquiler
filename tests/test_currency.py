import unittest
from unittest.mock import MagicMock

from core.currency import CotizacionDolar


def _session_devolviendo(payload):
    session = MagicMock()
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session


class TestCotizacionDolar(unittest.TestCase):
    def test_ars_pasa_directo_sin_pedir_cotizacion(self):
        session = MagicMock()
        cotizador = CotizacionDolar(session=session)
        self.assertEqual(cotizador.a_ars(100000, "ARS"), 100000)
        session.get.assert_not_called()

    def test_usd_se_convierte_con_la_cotizacion_de_venta(self):
        session = _session_devolviendo({"compra": 1000, "venta": 1050})
        cotizador = CotizacionDolar(session=session)
        self.assertEqual(cotizador.a_ars(1000, "USD"), 1_050_000)

    def test_cotizacion_se_cachea_entre_llamadas(self):
        session = _session_devolviendo({"compra": 1000, "venta": 1050})
        cotizador = CotizacionDolar(session=session)
        cotizador.a_ars(100, "USD")
        cotizador.a_ars(200, "USD")
        session.get.assert_called_once()

    def test_moneda_desconocida_devuelve_none(self):
        cotizador = CotizacionDolar(session=MagicMock())
        self.assertIsNone(cotizador.a_ars(100, "EUR"))

    def test_falla_de_red_devuelve_none(self):
        session = MagicMock()
        session.get.side_effect = RuntimeError("timeout")
        cotizador = CotizacionDolar(session=session)
        self.assertIsNone(cotizador.a_ars(100, "USD"))

    def test_moneda_vacia_se_trata_como_ars(self):
        cotizador = CotizacionDolar(session=MagicMock())
        self.assertEqual(cotizador.a_ars(500, ""), 500)


if __name__ == "__main__":
    unittest.main()
