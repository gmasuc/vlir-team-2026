"""
Corrige el trazado del tranvia en la capa de lineas de la DGM.

Problema: en Lineas.shp el trazado de Ida mide 2.9 km (incompleto) y el de Retorno 13.4 km
(2.4 km dibujados dos veces, en 28 pedazos). Ningun tramo se aparta del recorrido real.
Solucion: usar la geometria de OpenStreetMap (relaciones 9562447 y 9562448), conservando los
datos operativos de la DGM (intervalos, flota, horarios), y construir las 27 paradas ordenadas.

Entradas (descargadas de Overpass, ver datos/derivados/osm_*.json)
Salidas:  datos/derivados/Lineas_corregido.gpkg   (capa de lineas con el tranvia corregido)
          datos/derivados/tranvia_corregido.gpkg  (capas 'trazado' y 'paradas')
Los archivos originales de la DGM no se modifican.
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, substring

BASE = Path(__file__).parent
DER = BASE / "datos" / "derivados"
CRS = 32717

# ----------------------------------------------------------------------------- trazado OSM
rel = json.loads((DER / "osm_tranvia_raw.json").read_text(encoding="utf-8"))
calles = json.loads((DER / "osm_calles.json").read_text(encoding="utf-8"))
gcalle = gpd.GeoDataFrame([{"calle": w["tags"]["name"], "geometry": LineString([(p["lon"], p["lat"]) for p in w["geometry"]])}
                           for w in calles], crs=4326).to_crs(CRS).dissolve("calle").geometry
trazos = []
for e in rel:
    ways = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in e["members"]
            if m["type"] == "way" and m.get("role", "") == "" and "geometry" in m]
    g = gpd.GeoSeries([linemerge(ways)], crs=4326).to_crs(CRS).iloc[0]
    assert g.geom_type == "LineString", "el trazado OSM no es continuo"
    if g.coords[0][1] > g.coords[-1][1]:          # orientar de sur a norte
        g = LineString(g.coords[::-1])
    lamar = g.intersection(gcalle["Mariscal Lamar"].buffer(25)).length
    gcol = g.intersection(gcalle["Gran Colombia"].buffer(25)).length
    trazos.append({"osm_relacion": e["id"], "osm_nombre": e["tags"]["name"], "geom_sn": g, "lamar": lamar, "gcol": gcol})

# convencion DGM: Ida = Control Sur -> Parque Industrial (norte, por Mariscal Lamar)
norte = max(trazos, key=lambda t: t["lamar"])
sur = max(trazos, key=lambda t: t["gcol"])
assert norte is not sur
sentidos = {"Ida": (norte, norte["geom_sn"]), "Retorno": (sur, LineString(sur["geom_sn"].coords[::-1]))}

# ----------------------------------------------------------------------------- paradas
ns = json.loads((DER / "osm_paradas.json").read_text(encoding="utf-8"))
P = gpd.GeoDataFrame([{"osm_node": n["id"], "nombre_osm": n.get("tags", {}).get("name"),
                       "geometry": Point(n["lon"], n["lat"])} for n in ns], crs=4326).to_crs(CRS)
P = P[P["nombre_osm"].str.startswith("Tranvía - Nº", na=False)].copy()
P["numero"] = P["nombre_osm"].str.extract(r"Nº\s*0?(\d+[ns]?)")[0]
P["nombre"] = P["nombre_osm"].str.replace(r"^Tranvía - Nº\s*\S+\s*-\s*", "", regex=True)
P["tramo"] = P["numero"].map(lambda x: "norte (Mariscal Lamar)" if x.endswith("n")
                             else "sur (Gran Colombia)" if x.endswith("s") else "compartido")

filas = []
for sentido, (t, geom) in sentidos.items():
    sufijo_excluido = "s" if sentido == "Ida" else "n"
    cand = P[~P["numero"].str.endswith(sufijo_excluido)].copy()
    cand["dist_via_m"] = cand.distance(geom)
    cand = cand.sort_values("dist_via_m").drop_duplicates("numero")   # un nodo por parada: el mas cercano a esta via
    cand["km"] = cand.geometry.apply(geom.project) / 1000
    cand = cand.sort_values("km")
    cand["sentido"] = sentido
    cand["orden"] = range(1, len(cand) + 1)
    filas.append(cand)
paradas = pd.concat(filas, ignore_index=True)
paradas = gpd.GeoDataFrame(paradas, geometry="geometry", crs=CRS)
paradas["km"] = paradas["km"].round(2)
paradas["dist_via_m"] = paradas["dist_via_m"].round(1)

# ----------------------------------------------------------------------------- lineas corregidas
L = gpd.read_file(BASE / "datos" / "GIS_Transporte" / "Lineas.shp")
L["correccion"] = None
for sentido, (t, geom) in sentidos.items():
    i = L.index[(L["linename"] == "RUTA TRANVIA") & (L["sentido"] == sentido)]
    assert len(i) == 1
    L.loc[i, "geometry"] = gpd.GeoSeries([geom], crs=CRS).values
    L.loc[i, "length"] = f"{geom.length / 1000:.3f}km"
    L.loc[i, "correccion"] = f"geometria de OSM relacion {t['osm_relacion']} ({t['osm_nombre']})"
# alargues de las lineas 1 y 3 mal etiquetados como Ida/Retorno
mal = L["name"].str.upper().str.startswith("ALARGUE", na=False) & L["sentido"].isin(["Ida", "Retorno"])
L.loc[mal, "correccion"] = "alargue etiquetado como " + L.loc[mal, "sentido"] + " en el original"
L.loc[mal, "sentido"] = "ALARGUE " + L.loc[mal, "sentido"].str.upper() + " " + L.loc[mal, "name"].str.extract(
    r"ALARGUE (?:IDA|RETORNO) (.*)", flags=re.I)[0].fillna("")

L.to_file(DER / "Lineas_corregido.gpkg", layer="lineas", driver="GPKG")
traz = L[L["linename"] == "RUTA TRANVIA"][["sentido", "ruta", "tiempo_rec", "flota", "inicio_ope", "fin_operac",
                                         "intervalo_", "interval_1", "interval_2", "correccion", "geometry"]].copy()
traz["km"] = (traz.length / 1000).round(2)
traz.to_file(DER / "tranvia_corregido.gpkg", layer="trazado", driver="GPKG")
paradas[["sentido", "orden", "numero", "nombre", "tramo", "km", "dist_via_m", "osm_node", "geometry"]].to_file(
    DER / "tranvia_corregido.gpkg", layer="paradas", driver="GPKG")

# ----------------------------------------------------------------------------- reporte
print(traz.drop(columns="geometry").to_string())
for s in ["Ida", "Retorno"]:
    d = paradas[paradas["sentido"] == s]
    print(f"\n{s}: {len(d)} paradas | max distancia a la via {d['dist_via_m'].max()} m")
    print("  " + " -> ".join(f"{r.numero} {r.nombre} ({r.km})" for r in d.itertuples()))
print("\nEstaciones unicas:", paradas["numero"].nunique())
print("Alargues re-etiquetados:", int(mal.sum()))
