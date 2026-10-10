"""Estaciones de la región que transmiten en abierto (generado por tools/estaciones_region.py).

Foto del 2026-10-10 04:29 UTC: canal vertical con dato de hace menos de 10 min en
el SeedLink de EarthScope o de GEOFON. No editar a mano: regenerar.
Rectángulo: norte 23.631, sur -7.29, este -61.992, oeste -104.883.
"""

# Estación -> (red, ubicación, canal vertical, lat, lon)
REGIONAL_STATIONS = {
    "PAPH1": ("AY", "", "HHZ", 18.5622, -72.2969),  # Port Au Prince, OU, HT
    "BCIP": ("CU", "00", "BHZ", 9.1665, -79.8373),  # Isla Barro Colorado, Panama
    "GRTK": ("CU", "00", "BHZ", 21.5115, -71.1342),  # Grand Turk, Turks and Caicos Islands
    "GTBY": ("CU", "00", "HHZ", 19.9268, -75.1108),  # Guantanamo Bay, Cuba
    "MTDJ": ("CU", "00", "BHZ", 18.2261, -77.5345),  # Mount Denham, Jamaica
    "SDDR": ("CU", "00", "HHZ", 18.9821, -71.2878),  # Presa de Sabenta, Dominican Republic
    "TGUH": ("CU", "00", "HHZ", 14.057, -87.273),  # Tegucigalpa, Honduras
    "CAMR": ("CW", "00", "HHZ", 23.0617, -81.3709),  # Camariocas, Cardenas, Matanzas
    "MASC": ("CW", "00", "HHZ", 20.1755, -74.2312),  # Maisi,Guantanamo,Cuba
    "CBCY": ("CY", "01", "HHZ", 19.738, -79.7583),  # The Bluff, Cayman Brac, Cayman Islands
    "FSCY": ("CY", "01", "HHZ", 19.3129, -81.1835),  # Frank Sound, Grand Cayman, Cayman Islands
    "SDD": ("DR", "", "BHZ", 18.4632, -69.9169),  # Santo Domingo, DR
    "ANTS": ("EC", "", "HHZ", -0.4973, -78.1704),  # OVANTI_S
    "ARNL": ("EC", "", "HHZ", -3.5478, -80.067),  # RENSIG, RENAC
    "CHSH": ("EC", "", "HHZ", -1.4938, -78.8693),  # OVCHIM_S
    "COHC": ("EC", "", "HHZ", -2.4661, -79.2574),  # RENSIG, RENAC
    "PULU": ("EC", "", "HHZ", 0.0218, -78.5022),  # OVPULU_S
    "SLOR": ("EC", "", "HHZ", -0.7298, -78.4967),  # TEMP - COTO
    "TULM": ("EC", "", "HHZ", 0.7161, -77.7869),  # RENSIG
    "VCES": ("EC", "", "HHZ", -0.7999, -78.3944),  # RENSIG
    "HDC": ("G", "00", "BHZ", 10.002, -84.1114),  # Heredia, Costa Rica
    "UNM": ("G", "00", "BHZ", 19.3297, -99.1781),  # Unam - Mexico, Mexico
    "BOAB": ("GE", "", "HHZ", 12.4493, -85.6659),  # INETER/GEOFON Station Boaco, Nicaragua
    "JTS": ("II", "00", "BHZ", 10.2908, -84.9525),  # Las Juntas de Abangares, Costa Rica
    "TEIG": ("IU", "00", "BHZ", 20.2262, -88.2763),  # Tepich, Yucatan, Mexico
    "GWJB": ("JM", "00", "HHZ", 18.0742, -76.728),  # Greenwich, St.Andrew, Jamaica
    "HOJB": ("JM", "00", "HHZ", 18.0048, -76.7491),  # UWI Mona, St. Andrew, Jamaica
    "LGMB": ("JM", "00", "HHZ", 17.9963, -76.7259),  # Long Mountain
    "PCJB": ("JM", "00", "HHZ", 17.7412, -77.1573),  # Portland Cottage, Clarendon Jamaica
    "PMBJB": ("JM", "00", "HHZ", 18.4886, -77.9148),  # Paradise Montego Bay
    "STHB": ("JM", "00", "HHZ", 18.0772, -76.8097),  # Stoney Hill, St. Andrew Jamaica
    "YHJB": ("JM", "00", "HHZ", 17.8905, -76.4904),  # Yallahs, St. Thomas, Jamaica
    "LOBH": ("LO", "00", "EHZ", 17.862, -71.6387),  # Bahia de las Aguilas, Pedernales
    "LOCA": ("LO", "00", "EHZ", 19.477, -70.8529),  # La Canela, Santiago
    "LOLU": ("LO", "00", "EHZ", 19.9101, -71.0021),  # Luperon, Puerto Plata
    "LOMC": ("LO", "00", "EHZ", 19.8436, -71.651),  # Monte Cristi
    "LONA2": ("LO", "00", "EHZ", 19.3801, -69.8649),  # Toro Cenizo, Nagua
    "LONE3": ("LO", "00", "EHZ", 18.6047, -71.4587),  # El Aguacate, Bahoruco
    "LOPU": ("LO", "00", "EHZ", 19.2903, -70.5452),  # Pueblo Viejo, La Vega
    "LORA": ("LO", "00", "EHZ", 19.6498, -71.3716),  # Ranchadero, Monte Cristi
    "LOSA": ("LO", "00", "EHZ", 19.1858, -69.2717),  # Samana
    "LOTA": ("LO", "00", "EHZ", 19.535, -70.5789),  # Tamboril, Santiago
    "LOVI": ("LO", "00", "EHZ", 17.7983, -71.3678),  # El Caujil, Oviedo
    "OLV1": ("MC", "", "BHZ", 16.7504, -62.2279),  # Olveston, Montserrat
    "TRNT": ("MC", "", "BHZ", 16.7642, -62.1633),  # Trants Estate, Montserrat
    "CCIG": ("MX", "", "BHZ", 16.2818, -92.1368),  # COMITAN
    "MOIG": ("MX", "", "BHZ", 19.6467, -101.2273),  # Morelia, Mich, MX
    "TLIG": ("MX", "", "BHZ", 17.5627, -98.5665),  # TLAPA
    "ZAIG": ("MX", "", "BHZ", 22.7692, -102.5671),  # ZACATECAS
    "SEUS": ("NA", "", "HHZ", 17.4928, -62.9814),  # St Eustatius, Netherlands Antilles Seismic Netwo
    "HERN": ("NU", "00", "EHZ", 12.6093, -86.831),  # Volcan Telica, Leon, Nicaragua
    "MASN": ("NU", "00", "EHZ", 11.9889, -86.1577),  # Volcan Masaya, Masaya, Nicaragua
    "SIUN": ("NU", "10", "HHZ", 13.7162, -84.7735),  # Universidad URACAN, Siuna, Nicaragua
    "CAO2": ("OV", "", "ENZ", 9.688, -85.107),  # no, Puntarenas
    "LAFE": ("OV", "", "HHZ", 9.8072, -84.9103),  # Finca La Fe,Paquera, Puntarenas
    "VAVL": ("OV", "", "HHZ", 10.4373, -84.7091),  # VAVL, Volcan Arenal, Volcano Lodge
    "VPCC": ("OV", "", "HHZ", 10.2681, -84.2046),  # Nueva Cinchona, Volcan Poas
    "VRBA": ("OV", "", "HHZ", 10.8664, -85.326),  # Volcan Rincon de la Vieja, Sensoria,Buenos Aires
    "ACPR": ("PR", "00", "HHZ", 12.5057, -70.0011),  # International School of Aruba UNESCO
    "AGPR": ("PR", "00", "HHZ", 18.4675, -67.1112),  # Aguadilla PR
    "AOPR": ("PR", "00", "HHZ", 18.3466, -66.754),  # Observatorio Arecibo PR
    "BRR1": ("PR", "", "HNZ", 18.1893, -66.3044),  # Barranquitas Fire Station
    "CELP": ("PR", "00", "HHZ", 18.0749, -66.5792),  # CELP
    "CG01": ("PR", "", "HNZ", 18.2268, -66.0409),  # Emergency management office, Caguas
    "CLS1": ("PR", "", "HNZ", 18.3417, -66.4681),  # Ciales Fire Station
    "COM1": ("PR", "", "HNZ", 18.0774, -66.3685),  # Coamo Fire Station
    "CRPR": ("PR", "00", "HHZ", 18.0064, -67.1096),  # CRPR
    "CUPR": ("PR", "00", "HHZ", 18.3075, -65.2826),  # CUPR
    "ECPR": ("PR", "00", "HHZ", 18.3188, -66.3629),  # ECPR
    "FAPR": ("PR", "00", "HHZ", 18.2166, -65.6566),  # Fundacion de Amor
    "GBPR": ("PR", "00", "HHZ", 17.9751, -66.8793),  # Bosque Seco Guanica
    "GCPR": ("PR", "00", "HHZ", 18.3091, -66.0837),  # GCPR
    "GNC1": ("PR", "", "HNZ", 17.9722, -66.9086),  # Guanica OMME
    "GY01": ("PR", "", "HNZ", 18.3579, -66.1159),  # Guaynabo Fire Station
    "GYN1": ("PR", "", "HNZ", 18.02, -66.7915),  # Guayanilla Fire Station
    "HM01": ("PR", "", "HNZ", 18.154, -65.8277),  # Humacao Fire Station
    "ICMP": ("PR", "00", "HHZ", 17.8863, -66.5271),  # ICMP
    "IGPR": ("PR", "00", "HHZ", 17.9655, -66.1069),  # IGPR
    "ISPR": ("PR", "00", "HNZ", 18.0846, -67.049),  # Universidad Interamaricana de San German
    "LSP": ("PR", "00", "HHZ", 18.1757, -67.0858),  # Cerro Las Mesas
    "MLPR": ("PR", "00", "HHZ", 17.9694, -67.0442),  # MLPR
    "MNB1": ("PR", "", "HNZ", 18.005, -65.9015),  # Maunabo Fire Station
    "NGB1": ("PR", "", "HNZ", 18.2133, -65.7414),  # Naguabo Fire Station
    "OBIP": ("PR", "00", "HHZ", 18.0428, -66.6062),  # OBIP
    "PCDR": ("PR", "", "BHZ", 18.5145, -68.381),  # PCDR
    "PDPR": ("PR", "00", "HHZ", 18.0181, -66.0222),  # PDPR
    "PRSN": ("PR", "00", "HHZ", 18.2175, -67.1447),  # PRSN
    "QBPR": ("PR", "00", "HNZ", 18.4772, -66.9388),  # QBPR
    "ROPR": ("PR", "00", "HNZ", 18.3376, -67.2499),  # ROPR
    "SMDR": ("PR", "", "BHZ", 19.2898, -69.1882),  # SMDR
    "SNS1": ("PR", "", "HNZ", 18.336, -66.9945),  # San Sebastian Fire Station
    "TA02": ("PR", "", "HNZ", 18.3295, -66.0164),  # Carraizo Dam Free Field
    "TBVI": ("PR", "00", "HHZ", 18.4202, -64.6203),  # TBVI
    "UUPR": ("PR", "00", "HHZ", 18.2528, -66.7202),  # UUPR
    "ZCPR": ("PR", "00", "HNZ", 18.2542, -65.6405),  # Zona Ceiba Puerto Rico
    "ARTIL": ("SV", "00", "HHZ", 13.8374, -89.3651),  # Artilleria
    "CEDA": ("SV", "", "HHZ", 13.8028, -89.3949),  # Z
    "JAYA": ("SV", "", "HHZ", 13.6542, -89.4489),  # Z
    "MTO3": ("SV", "", "HHZ", 14.3989, -89.3606),  # Montecristo
    "NUBE": ("SV", "", "HHZ", 13.9022, -89.7799),  # Z
    "PACA": ("SV", "", "HHZ", 13.469, -88.3233),  # Cerro El Pacayal, El Salvador
    "PAVA": ("SV", "", "HHZ", 13.713, -88.9371),  # Z
    "RBDL": ("SV", "", "HHZ", 14.113, -89.6827),  # El Robledal
    "SBLS": ("SV", "", "HHZ", 13.8393, -89.623),  # San Blas
    "SNET": ("SV", "", "HHZ", 13.6868, -89.2315),  # Montecristo, El Salvador
    "VSM2": ("SV", "00", "HHZ", 13.4424, -88.2733),  # Volcan de San Miguel
    "DRK0": ("TC", "", "HHZ", 9.2624, -83.2454),  # Durika
    "ELI1": ("TC", "", "EHZ", 10.645, -85.5528),  # Earth Liberia
    "LCR2": ("TC", "", "HHZ", 9.7415, -84.0053),  # Finca La Lucha San Jose
    "MARA": ("TC", "", "HHZ", 10.0195, -85.4255),  # Maravilla
    "PIRO": ("TC", "", "HHZ", 8.4109, -83.3195),  # PIRO, Osa Puntarenas
    "QUEP": ("TC", "", "EHZ", 9.431, -84.164),  # Quepos
    "TCS1": ("TC", "", "HHZ", 10.0421, -84.2998),  # Tacares, Grecia, Alajuela
    "TEXA": ("TC", "", "HHZ", 10.383, -84.618),  # Soltis Center
    "UPAL": ("TC", "", "EHZ", 10.8972, -85.0123),  # Upala
    "CADR": ("ZC", "", "BHZ", 19.667, -69.9398),  # Cabo Frances, DR
    "JIDR": ("ZC", "", "BHZ", 18.4914, -71.8642),  # Jimani, DR
    "SODR": ("ZC", "", "BHZ", 19.7524, -70.5763),  # Sosua, DR
}

# Las que no salen del SeedLink de EarthScope (el de config.SEEDLINK_SERVER)
REGIONAL_SERVERS = {
}

# Estaciones a menos de 150 km entre sí (o de una principal) valen por una
REGIONAL_GROUPS = {
    "AGPR": "QBPR",
    "ANTS": "ecuador",
    "AOPR": "QBPR",
    "ARTIL": "MTO3",
    "BOAB": "HERN",
    "BRR1": "QBPR",
    "CADR": "LOLU",
    "CAO2": "LCR2",
    "CEDA": "MTO3",
    "CELP": "QBPR",
    "CG01": "QBPR",
    "CHSH": "ecuador",
    "CLS1": "QBPR",
    "COM1": "QBPR",
    "CRPR": "QBPR",
    "CUPR": "TBVI",
    "DRK0": "LCR2",
    "ECPR": "QBPR",
    "ELI1": "UPAL",
    "FAPR": "TBVI",
    "GBPR": "QBPR",
    "GCPR": "QBPR",
    "GNC1": "QBPR",
    "GTBY": "MASC",
    "GWJB": "PMBJB",
    "GY01": "QBPR",
    "GYN1": "QBPR",
    "HDC": "UPAL",
    "HERN": "HERN",
    "HM01": "QBPR",
    "HOJB": "PMBJB",
    "ICMP": "QBPR",
    "IGPR": "QBPR",
    "ISPR": "QBPR",
    "JAYA": "MTO3",
    "JIDR": "LONE3",
    "JTS": "UPAL",
    "LAFE": "UPAL",
    "LCR2": "LCR2",
    "LGMB": "PMBJB",
    "LOBH": "LONE3",
    "LOCA": "LOLU",
    "LOLU": "LOLU",
    "LOMC": "LOLU",
    "LONA2": "LOLU",
    "LONE3": "LONE3",
    "LOPU": "LOLU",
    "LORA": "LOLU",
    "LOSA": "SMDR",
    "LOTA": "LOLU",
    "LOVI": "LONE3",
    "LSP": "QBPR",
    "MARA": "UPAL",
    "MASC": "MASC",
    "MASN": "HERN",
    "MLPR": "QBPR",
    "MNB1": "QBPR",
    "MTDJ": "PMBJB",
    "MTO3": "MTO3",
    "NGB1": "TBVI",
    "NUBE": "MTO3",
    "OBIP": "QBPR",
    "OLV1": "SEUS",
    "PACA": "TGUH",
    "PAPH1": "LONE3",
    "PAVA": "MTO3",
    "PCDR": "SMDR",
    "PCJB": "YHJB",
    "PDPR": "QBPR",
    "PMBJB": "PMBJB",
    "PRSN": "QBPR",
    "PULU": "ecuador",
    "QBPR": "QBPR",
    "QUEP": "LCR2",
    "RBDL": "MTO3",
    "ROPR": "QBPR",
    "SBLS": "MTO3",
    "SDD": "SMDR",
    "SDDR": "LOLU",
    "SEUS": "SEUS",
    "SLOR": "ecuador",
    "SMDR": "SMDR",
    "SNET": "MTO3",
    "SNS1": "QBPR",
    "SODR": "LOLU",
    "STHB": "PMBJB",
    "TA02": "QBPR",
    "TBVI": "TBVI",
    "TCS1": "UPAL",
    "TEXA": "UPAL",
    "TGUH": "TGUH",
    "TRNT": "SEUS",
    "TULM": "ecuador",
    "UPAL": "UPAL",
    "UUPR": "QBPR",
    "VAVL": "UPAL",
    "VCES": "ecuador",
    "VPCC": "UPAL",
    "VRBA": "UPAL",
    "VSM2": "TGUH",
    "YHJB": "YHJB",
    "ZCPR": "TBVI",
}
