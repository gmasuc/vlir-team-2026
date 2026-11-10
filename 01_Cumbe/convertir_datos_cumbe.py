"""
Convierte a GeoTIFF comprimido (sin perder datos) los rásters útiles de cumbe_exportado:
  - el modelo de elevación de 0.5 m (CUMBE_MDT_AK-002.tif, 3.7 GB sin comprimir);
  - las capas de hidrología en formato ArcInfo grid (cauces y cuenca a 0.5 m).
Después compara bloque a bloque el original con la copia: deben ser idénticos.

Ya se ejecutó el 14-10-2026 (ver datos/conversion.log): todas las copias resultaron idénticas y luego se borraron los
originales grandes (CUMBE_MDT_AK-002.tif y la carpeta Hidrologia). Se conserva como registro de lo que se hizo.

Uso:  py 01_Cumbe/convertir_datos_cumbe.py
Salida: 01_Cumbe/datos/mdt_cumbe_05m.tif, 01_Cumbe/datos/hidrologia_05m/*.tif, 01_Cumbe/datos/conversion.log
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

BASE = Path(__file__).resolve().parent
ORIG = BASE / "datos_originales" / "cumbe_exportado"
OUT = BASE / "datos"
(OUT / "hidrologia_05m").mkdir(parents=True, exist_ok=True)
LOG = open(OUT / "conversion.log", "w", encoding="utf-8")

TRABAJOS = [(ORIG / "CUMBE_MDT_AK-002.tif", OUT / "mdt_cumbe_05m.tif", 3)]          # predictor 3: flotantes
for g in ["con15k", "con50k", "con250k", "cuenca1", "stlink15k", "stlink50k"]:
    TRABAJOS.append((ORIG / "Hidrologia" / g, OUT / "hidrologia_05m" / f"{g}.tif", 2))  # predictor 2: enteros


def log(t):
    print(t, flush=True)
    LOG.write(t + "\n")
    LOG.flush()


def bloques(s, alto=1024):
    for fila in range(0, s.height, alto):
        yield Window(0, fila, s.width, min(alto, s.height - fila))


for src_p, dst_p, pred in TRABAJOS:
    with rasterio.open(src_p) as s:
        perfil = s.profile.copy()
        perfil.update(driver="GTiff", compress="deflate", predictor=pred, tiled=True, blockxsize=512,
                      blockysize=512, BIGTIFF="IF_SAFER")
        with rasterio.open(dst_p, "w", **perfil) as d:
            for w in bloques(s):
                d.write(s.read(1, window=w), 1, window=w)
    # verificación bloque a bloque
    iguales = True
    with rasterio.open(src_p) as a, rasterio.open(dst_p) as b:
        for w in bloques(a):
            x, y = a.read(1, window=w), b.read(1, window=w)
            if not np.array_equal(x, y, equal_nan=np.issubdtype(x.dtype, np.floating)):
                iguales = False
                break
    tam_o = sum(f.stat().st_size for f in (src_p.rglob("*") if src_p.is_dir() else [src_p]) if f.is_file())
    log(f"{src_p.name}: {tam_o / 1e6:,.0f} MB -> {dst_p.stat().st_size / 1e6:,.0f} MB | identico: {iguales}")
log("FIN")
