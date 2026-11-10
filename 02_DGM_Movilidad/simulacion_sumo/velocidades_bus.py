"""
Velocidad comercial de buses y tranvia a partir de las salidas de 09_buses.py.

Importante: en el modo mesoscopico, el largo de recorrido que informa SUMO en tripinfo (routeLength) es ~29 % mayor
que la suma de los largos de las calles de la ruta (verificado: L5 Ida 11.8 km de calles, routeLength 15.3 km). Aqui
el largo se calcula con las calles de la ruta, y la velocidad = largo / duracion del viaje.

Tambien marca las rutas sospechosas: las que dentro del area piloto miden mas que la linea completa (la reparacion de
saltos o el ajuste a la red dio un rodeo). Se excluyen de las medianas.

Uso como modulo: velocidades(carpeta, net) -> DataFrame por ruta.
Uso como script: py simulacion_sumo/velocidades_bus.py  (recalcula velocidad_lineas.csv y resumen_escenario.csv
de todas las carpetas de simulacion_sumo/buses/)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import sys
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
B, E = 7 * 3600, 8 * 3600


def velocidades(carpeta, net):
    carpeta = Path(carpeta)
    largo = {r.id: sum(net.getEdge(e).getLength() for e in r.edges.split()) / 1000
             for r in sumolib.xml.parse(str(carpeta / "buses.rou.xml"), "route")}
    cob = pd.read_csv(carpeta / "cobertura_lineas.csv")
    cob["ruta"] = "L" + cob.id_ld.str.replace("|", "_").str.replace(" ", "_")
    cob = cob.set_index("ruta")
    t = pd.DataFrame([{"id": v.id, "tipo": v.vType, "salida": float(v.depart), "llegada": float(v.arrival),
                       "duracion": float(v.duration)}
                      for v in sumolib.xml.parse(str(carpeta / "viajes.xml"), "tripinfo")
                      if v.vType in ("bus", "tranvia")])
    t["ruta"] = t.id.str.rsplit(".", n=1).str[0]
    t = t[(t.salida >= B) & (t.salida < E)]
    t["terminado"] = t.llegada > 0
    v = t[t.terminado].groupby("ruta").agg(viajes=("id", "size"), min_sim=("duracion", lambda s: s.mean() / 60))
    v["km"] = v.index.map(largo)
    v["kmh_sim"] = v.km / (v.min_sim / 60)
    v["no_terminaron"] = t[~t.terminado].groupby("ruta").size().reindex(v.index).fillna(0).astype(int)
    v = v.join(cob[["linea", "sentido", "modo", "km_total"]])
    v["linename"] = v.linea
    v["sospechosa"] = v.km > 1.15 * v.km_total
    return v.round(2), t


if __name__ == "__main__":
    import red_buses  # noqa: F401  (solo para comprobar el entorno)
    nets = {}
    for carpeta in sorted((SIM / "buses").iterdir()):
        if not (carpeta / "viajes.xml").exists() or not (carpeta / "resumen_escenario.csv").exists():
            continue
        n = ("cuenca_piloto_v3b_menos_carril.net.xml" if "menoscarril" in carpeta.name else
             "cuenca_piloto_v3_carril_bus.net.xml" if "carrilbus" in carpeta.name else "cuenca_piloto_v2.net.xml")
        if n not in nets:
            nets[n] = sumolib.net.readNet(str(SIM / "red" / n))
        v, t = velocidades(carpeta, nets[n])
        prog = pd.read_csv(carpeta / "velocidad_lineas.csv", index_col=0)
        if "kmh_programada" in prog:
            v = v.join(prog[["kmh_programada"]])
        v.to_csv(carpeta / "velocidad_lineas.csv", encoding="utf-8-sig")
        r = pd.read_csv(carpeta / "resumen_escenario.csv")
        bus = v[(v.modo == "bus") & ~v.sospechosa]
        tb = t[t.tipo == "bus"].merge(v[["km"]], left_on="ruta", right_index=True)
        tb = tb[tb.terminado & ~tb.ruta.isin(v.index[v.sospechosa])]
        r["bus_kmh_mediana"] = round(bus.kmh_sim.median(), 1)
        r["bus_kmh_flota"] = round(tb.km.sum() / (tb.duracion.sum() / 3600), 1)
        tr = v[v.modo == "tranvia"]
        r["tranvia_kmh"] = round(tr.kmh_sim.mean(), 1)
        r.to_csv(carpeta / "resumen_escenario.csv", index=False)
        print(f"{carpeta.name:40s} bus mediana {r.bus_kmh_mediana[0]:5.1f}  flota {r.bus_kmh_flota[0]:5.1f}  "
              f"tranvia {r.tranvia_kmh[0]:5.1f} km/h  (rutas sospechosas excluidas: {int(v.sospechosa.sum())})")
