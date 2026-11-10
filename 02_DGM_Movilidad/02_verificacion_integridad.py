"""
Verificacion de integridad: recalcula las cifras del EDA desde los archivos originales por una via
independiente y las contrasta con fuentes externas (portal Cuenca en Datos, informe Producto 1).
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import glob
import io
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import openpyxl
import pandas as pd
import pyogrio
import requests

BASE = Path(__file__).parent
GIS = BASE / "datos" / "GIS_Transporte"
ZIP = BASE / "datos_originales" / "Transporte público.zip"
OK, MAL, OJO = "OK  ", "FALLA", "OJO "
res = []


def check(nombre, estado, detalle):
    res.append((estado, nombre, detalle))
    print(f"[{estado}] {nombre}: {detalle}")


def minutos(s):
    t = s.astype(str).str.strip()
    t = t.where(t.str.count(":") >= 2, t + ":00")      # hh:mm -> hh:mm:00 (el tranvia ya viene con segundos)
    return pd.to_timedelta(t, errors="coerce").dt.total_seconds() / 60


print("=" * 100, "\n1. ARCHIVOS: lo descomprimido es identico al zip original")
z = zipfile.ZipFile(ZIP)
dif = []
for i in z.infolist():
    n = i.filename if i.flag_bits & 0x800 else i.filename.encode("cp437").decode("utf-8", "replace")
    if n.endswith("/"):
        continue
    local = BASE / "datos" / n.replace("GIS Transporte", "GIS_Transporte")
    if not local.exists() or local.read_bytes() != z.read(i):
        dif.append(n)
check("Archivos extraidos == zip", OK if not dif else MAL, f"{len(z.infolist())} archivos, diferencias: {dif or 'ninguna'}")

print("=" * 100, "\n2. LECTURA INDEPENDIENTE (pyogrio sin geopandas) y conteos")
for capa, esperado in [("Lineas", 173), ("paradas", 1635), ("rutas_lines", 163)]:
    info = pyogrio.read_info(GIS / f"{capa}.shp")
    check(f"Registros {capa}", OK if info["features"] == esperado else MAL,
          f"{info['features']} (EDA: {esperado}) | CRS {info['crs']} | codificacion {info['encoding']}")
car = [pyogrio.read_info(f)["features"] for f in sorted(glob.glob(str(GIS / "02_Paradas Caracterizacion_*.shp")))]
check("Registros caracterizacion", OJO, f"{sum(car)} en archivos; EDA usa 914 porque 1 registro no tiene geometria")

print("=" * 100, "\n3. LINEAS: supuestos del EDA")
L = gpd.read_file(GIS / "Lineas.shp")
op = L[L["sentido"].isin(["Ida", "Retorno"]) & ~L["name"].str.upper().str.startswith("ALARGUE", na=False)].copy()
check("Cada linea tiene exactamente Ida y Retorno", OK if (op.groupby("linename").size() == 2).all() else MAL,
      op.groupby("linename").size().value_counts().to_dict())

for c in ["tiempo_rec", "intervalo_", "interval_1", "interval_2", "inicio_ope", "fin_operac"]:
    crudo = op[c].astype(str).str.strip()
    malos = crudo[minutos(op[c]).isna() & op[c].notna()]
    check(f"Formato hh:mm en {c}", OK if malos.empty else MAL, f"no convertibles: {malos.tolist() or 'ninguno'}")

# el EDA toma el intervalo de la PRIMERA fila de cada linea: ¿ida y retorno tienen el mismo?
for c in ["intervalo_", "interval_1", "interval_2"]:
    distintos = op.groupby("linename")[c].nunique()
    d = distintos[distintos > 1]
    check(f"Ida y retorno con igual {c}", OK if d.empty else OJO, f"lineas con valores distintos: {d.index.tolist() or 'ninguna'}")

lg = (op.length / 1000).round(2)
lc = pd.to_numeric(op["length"].str.replace("km", ""), errors="coerce").round(2)
check("Campo length == longitud geometrica", OK if (abs(lg - lc) < 0.5).mean() > 0.9 else OJO,
      f"diferencia mediana {abs(lg - lc).median():.2f} km, max {abs(lg - lc).max():.2f} km")
check("Flota total (ida + retorno)", OK, f"{op['flota'].sum():.0f} buses")

print("=" * 100, "\n4. LINEAS vs PORTAL CUENCA EN DATOS (rutas 2025, fuente independiente)")
url = ("https://cuencaendatos.cuenca.gob.ec/dataset/f15c8808-0d12-4f97-bfd4-3b2f85ea84d1/resource/"
       "e55af215-4648-4e3b-84c9-d7e929435008/download/gadcuenca_rutastransporte_2025marzo1.csv")
try:
    portal = pd.read_csv(io.BytesIO(requests.get(url, timeout=60).content), sep=None, engine="python",
                         encoding="latin-1")
    portal["LINEA"] = portal["LINEA"].astype(str).str.strip()
    lineas_shp = set(op["linename"]) - {"RUTA TRANVIA"}
    lineas_portal = set(portal["LINEA"])
    check("Mismas lineas en shp y portal", OK if lineas_shp == lineas_portal else OJO,
          f"solo shp: {sorted(lineas_shp - lineas_portal)} | solo portal: {sorted(lineas_portal - lineas_shp)}")
    p = portal.groupby("LINEA")[["LUNES_VIERNES_INTERVALO", "SABADOS_INTERVALO", "DOMINGOS_INTERVALO"]].first()
    s = op.groupby("linename")[["intervalo_", "interval_1", "interval_2"]].first()
    j = s.join(p, how="inner")
    for a, b, dia in [("intervalo_", "LUNES_VIERNES_INTERVALO", "lun-vie"), ("interval_1", "SABADOS_INTERVALO", "sabado"),
                      ("interval_2", "DOMINGOS_INTERVALO", "domingo")]:
        d = (minutos(j[a]) - minutos(j[b])).fillna(0)
        check(f"Intervalo {dia} shp == portal", OK if (d == 0).all() else OJO,
              f"{(d == 0).sum()}/{len(d)} iguales; distintas: " + ", ".join(f"L{k} ({j.loc[k, a]} vs {j.loc[k, b]})" for k in d[d != 0].index))
except Exception as e:
    check("Portal", OJO, f"no se pudo descargar: {e}")

print("=" * 100, "\n5. LINEAS vs INFORME PRODUCTO 1 (Tabla 6: salidas por dia lun-vie por operadora)")
op["salidas"] = ((minutos(op["fin_operac"]) - minutos(op["inicio_ope"])) / minutos(op["intervalo_"].replace("00:00", np.nan))).fillna(0) + 1
calc = op[op["linename"] != "RUTA TRANVIA"].groupby("empresa")["salidas"].sum().round(0)
informe = {"COMTUBANOSA": 435, "CUENCANA": 1014, "LANCOMTRI": 731, "RICAURTESA": 462, "TOMEBAMBA": 1378,
           "UNCOMETRO": 508, "URBA10": 409}   # Banos = COMTUBANOSA; Urbadiez = URBA10; SIT no aparece (plan de contingencia 603)
comp = pd.DataFrame({"calculado": calc, "informe": pd.Series(informe)})
comp["dif_%"] = (100 * (comp["calculado"] / comp["informe"] - 1)).round(0)
print(comp.to_string())
check("Salidas lun-vie vs informe", OK if comp["dif_%"].abs().dropna().max() <= 20 else OJO,
      f"total calculado {calc.sum():.0f} vs informe 5 540 (incluye plan de contingencia 603)")
check("Flota vs informe", OK if abs(op["flota"].sum() - 475) / 475 < 0.05 else OJO,
      f"{op['flota'].sum():.0f} vs ~475 del informe (consorcio SIR, 475 unidades)")

print("=" * 100, "\n6. PARADAS")
P = gpd.read_file(GIS / "paradas.shp")
npts = P.geometry.apply(lambda g: len(g.geoms))
check("Cada MultiPoint tiene 1 punto (explode no duplica)", OK if (npts == 1).all() else MAL, npts.value_counts().to_dict())
lcols = [c for c in P.columns if c.startswith("l")]
vals = pd.unique(P[lcols].values.ravel())
check("Columnas de linea solo con 0/1", OK if set(pd.Series(vals).dropna()) <= {0, 1} else MAL,
      f"valores: {sorted(pd.Series(vals).dropna().unique())}, nulos: {int(P[lcols].isna().sum().sum())}")
check("IDs de parada unicos", OK if P["id2"].is_unique else OJO, f"duplicados: {int(P['id2'].duplicated().sum())}")
xy = P.geometry.apply(lambda g: (round(g.geoms[0].x), round(g.geoms[0].y)))
check("Sin paradas en la misma coordenada", OK if not xy.duplicated().any() else OJO, f"duplicadas: {int(xy.duplicated().sum())}")
freq_lineas = {"l" + k.lower() for k in op["linename"] if k != "RUTA TRANVIA"}
sin_freq = [c for c in lcols if c not in freq_lineas and (P[c] == 1).any()]
afect = int((P[sin_freq] == 1).any(axis=1).sum())
check("Buses/hora por parada completo", OJO if sin_freq else OK,
      f"columnas con paradas pero sin frecuencia conocida: {sin_freq} -> {afect} paradas pueden estar SUBESTIMADAS")
tope = P.assign(n=(P[lcols] == 1).sum(axis=1)).sort_values("n", ascending=False).iloc[0]
check("Parada con mas lineas", OK, f"{tope['nombres']} con {tope['n']} lineas")

print("=" * 100, "\n7. CARACTERIZACION")
C = pd.concat([gpd.read_file(f) for f in sorted(glob.glob(str(GIS / "02_Paradas Caracterizacion_*.shp")))], ignore_index=True)
check("Columna 'Señal Ver' leida con tilde correcta", OK if "Señal Ver" in C.columns else MAL, [c for c in C.columns if "al Ver" in c])
for c in ["CATEGORIA", "Caseta", "Asientos", "Techo", "Basurero", "Pasos Peat", "Bahia de e"]:
    print(f"    {c}: {C[c].value_counts(dropna=False).to_dict()}")
check("Valores SI/NO sin variantes raras", OJO, "revisar arriba: 'Techo' tiene 1 'BUENO' y algunas columnas tienen nulos (se cuentan como NO)")
pcoord = C.dropna(subset=["geometry"])
d = np.hypot(pcoord.geometry.x - pcoord["Longitud"].astype(float), pcoord.geometry.y - pcoord["Latitud"].astype(float))
check("Geometria == columnas Latitud/Longitud", OK if (d < 1e-4).mean() > 0.99 else OJO, f"{(d < 1e-4).mean():.1%} coinciden")

print("=" * 100, "\n8. MATRIZ OD: lectura cruda celda por celda con openpyxl")
wb = openpyxl.load_workbook(BASE / "datos" / "matriz_OD_65zonas.xlsx", data_only=True)
ws = wb.active
filas = list(ws.iter_rows(values_only=True))
cab = filas[0][1:]
nombres = [f[0] for f in filas[1:]]
M = np.array([f[1:] for f in filas[1:]], dtype=float)
od = pd.read_excel(BASE / "datos" / "matriz_OD_65zonas.xlsx", index_col=0)
check("pandas == lectura cruda", OK if np.allclose(M, od.values) and list(cab) == list(od.columns) else MAL, f"{M.shape}")
check("Filas y columnas con las mismas zonas, en el mismo orden", OK if list(cab) == nombres else MAL, "")
check("Sin valores negativos ni vacios", OK if (M >= 0).all() and not np.isnan(M).any() else MAL, "")
check("Cada fila suma 1", OK if np.allclose(M.sum(1), 1) else MAL, f"rango {M.sum(1).min():.6f} a {M.sum(1).max():.6f}")
check("Zonas con nombre unico", OK if len(set(nombres)) == len(nombres) else MAL, "")
corte = nombres.index("Baños 1")
check("Corte urbano/rural", OJO, f"{corte} urbanas / {len(nombres) - corte} rurales; 'Guzho' (pos. {nombres.index('Guzho')}) quedo como urbana: confirmar")
check("Viajes internos (mediana)", OK, f"{np.median(np.diag(M)):.1%}")
check("Bloques urbano/rural", OK, f"urbano->urbano {M[:corte, :corte].sum(1).mean():.0%}, rural->urbano {M[corte:, :corte].sum(1).mean():.0%}")

print("=" * 100, "\nRESUMEN")
r = pd.DataFrame(res, columns=["estado", "chequeo", "detalle"])
print(r["estado"].value_counts().to_string())
r.to_csv(BASE / "analisis" / "01_exploracion" / "verificacion_integridad.csv", index=False, encoding="utf-8-sig")
