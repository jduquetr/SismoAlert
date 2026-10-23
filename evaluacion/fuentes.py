"""De dónde sale la señal archivada: la red CM del SGC y el resto de EarthScope.

EarthScope solo guarda las componentes horizontales de las estaciones CM desde 2026 (antes,
casi nada); el servicio FDSN del SGC (sismo.sgc.gov.co:8080) tiene su archivo completo con
la respuesta de los sensores. Las redes IU y EC están en EarthScope. Si el SGC no tiene un
dato CM, se intenta en EarthScope.
"""
import sys

from obspy import Stream
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoDataException

SGC = "http://sismo.sgc.gov.co:8080"


class ClienteMixto:
    def __init__(self, timeout=180):
        self.sgc = Client(SGC, timeout=timeout, _discover_services=False, service_mappings={
            "dataselect": SGC + "/fdsnws/dataselect/1", "station": SGC + "/fdsnws/station/1"})
        self.earthscope = Client("EARTHSCOPE", timeout=timeout)

    def _bulk(self, client, bulk):
        if not bulk:
            return Stream()
        try:
            return client.get_waveforms_bulk(bulk)
        except FDSNNoDataException:
            return Stream()

    def get_waveforms_bulk(self, bulk):
        cm = [b for b in bulk if b[0] == "CM"]
        st = self._bulk(self.sgc, cm) if cm else Stream()
        con = {tr.stats.station for tr in st}
        resto = [b for b in bulk if b[0] != "CM" or b[1] not in con]
        return st + self._bulk(self.earthscope, resto)

    def get_stations(self, network, **kw):
        clientes = (self.sgc, self.earthscope) if network == "CM" else (self.earthscope,)
        inv = None
        for c in clientes:
            try:
                i = c.get_stations(network=network, **kw)
                inv = i if inv is None else inv + i
            except Exception as err:
                print(f"  {network}.{kw.get('station')}: {type(err).__name__}", file=sys.stderr)
        if inv is None:
            raise FDSNNoDataException(f"sin inventario para {network}.{kw.get('station')}")
        return inv
