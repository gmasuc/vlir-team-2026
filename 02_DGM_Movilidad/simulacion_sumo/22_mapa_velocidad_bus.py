"""
Mapa de la velocidad de los buses calle por calle en la hora pico (7:00-8:00), para ver dónde va lento y dónde rápido.

Entrada: buses/<corrida>/buses_aristas.xml (por tramo: distancia recorrida y tiempo de los buses, 7:00-8:00), la red de
         la corrida (nombre de la calle y velocidad máxima) y las zonas OD 2025 (para marcar el Centro Histórico).
Proceso: velocidad del bus en cada tramo = distancia recorrida por los buses / tiempo que pasaron en él. En modo
         mesoscópico el tiempo registrado del tramo (sampledSeconds) no incluye la espera al final de la cola ni la
         detención en las paradas; se suman la espera (waitingTime) y 10 s por parada de cada bus (buses.rou.xml), así
         el total coincide con el tiempo de viaje de los buses. Se resume por calle y por zona.
Salida:  buses/<corrida>/mapa_velocidad_bus.html (mapa interactivo: color = velocidad, grosor = buses por hora; al pasar
         el mouse muestra calle, velocidad y buses) y velocidad_bus_por_calle.csv; resumen en pantalla.

Uso:  py simulacion_sumo/22_mapa_velocidad_bus.py [corrida]      (por defecto, el modelo calibrado)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import sumo
from shapely.geometry import Point

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
corrida = sys.argv[1] if len(sys.argv) > 1 else "calibrada_bahia_reruteo_scats_vel_jc"
C = SIM / "buses" / corrida
log = (C / "buses_aristas.xml").read_text(encoding="utf-8")
red = log.split('net-file value="')[1].split('"')[0]
net = sumolib.net.readNet(red)

centro = gpd.read_file(BASE / "datos" / "zonas" / "zonas_od_2025.gpkg")
centro = centro[centro.Zona.str.contains("Centro Historico", case=False)].to_crs(4326).geometry.union_all()

# detención en paradas por tramo: 10 s por parada y por bus de cada recorrido (buses por hora = 3600 / período)
parada_tramo = {b.id: b.lane.rsplit("_", 1)[0] for b in sumolib.xml.parse(str(C / "paradas.add.xml"), "busStop")}
periodo = {f.route: float(f.period) for f in sumolib.xml.parse(str(C / "buses.rou.xml"), "flow")}
detencion = {}
for ruta in sumolib.xml.parse(str(C / "buses.rou.xml"), "route"):
    for st in ruta.stop or []:
        tramo = parada_tramo.get(st.busStop)
        if tramo and ruta.id in periodo:
            detencion[tramo] = detencion.get(tramo, 0) + float(st.duration) * 3600 / periodo[ruta.id]

filas = []
for iv in sumolib.xml.parse(str(C / "buses_aristas.xml"), "interval"):
    for e in iv.edge or []:
        if e.id.startswith(":") or float(e.sampledSeconds) <= 0:
            continue
        E = net.getEdge(e.id)
        x, y = E.getShape()[len(E.getShape()) // 2]
        filas.append({"arista": e.id, "calle": E.getName() or "(sin nombre)", "m": E.getLength(),
                      "buses_hora": int(float(e.left)), "dist": float(e.distance),
                      "seg": float(e.sampledSeconds) + float(e.waitingTime) + detencion.get(e.id, 0),
                      "espera_s": float(e.waitingTime), "limite_kmh": round(E.getSpeed() * 3.6),
                      "centro": centro.contains(Point(net.convertXY2LonLat(x, y))),
                      "forma": [list(reversed(net.convertXY2LonLat(px, py))) for px, py in E.getShape()]})
t = pd.DataFrame(filas)
t["kmh"] = (t.dist / t.seg * 3.6).round(1)
t = t[t.buses_hora > 0]
print(f"horas-bus en los tramos (7:00-8:00): {t.seg.sum() / 3600:.0f}; velocidad media de toda la red: "
      f"{t.dist.sum() / t.seg.sum() * 3.6:.1f} km/h")


def resumen(g):
    return pd.Series({"km": g.m.sum() / 1000, "buses_hora": g.buses_hora.max(),
                      "kmh": g.dist.sum() / g.seg.sum() * 3.6})


zona = t.groupby("centro").apply(resumen, include_groups=False).rename(index={True: "Centro Histórico", False: "fuera del centro"})
limite = t.groupby("limite_kmh").apply(resumen, include_groups=False)
calles = t.groupby("calle").apply(resumen, include_groups=False)
calles = calles[(calles.km >= 1) & (calles.buses_hora >= 20)].sort_values("kmh").round(1)
calles.to_csv(C / "velocidad_bus_por_calle.csv", encoding="utf-8-sig")

print(f"corrida: {corrida}\nvelocidad del bus por zona (km/h, 7:00-8:00):\n{zona.round(1).to_string()}")
print(f"\npor velocidad máxima de la calle:\n{limite.round(1).to_string()}")
print(f"\ncalles con al menos 1 km y 20 buses por hora, de la más lenta a la más rápida:\n{calles.to_string()}")

# ----------------------------------------------------------------------------- mapa
COLORES = [(10, "#b2182b", "menos de 10"), (15, "#ef8a62", "10 a 15"), (20, "#fddb6d", "15 a 20"),
           (30, "#91cf60", "20 a 30"), (999, "#1a9850", "30 o más")]
geo = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in r.forma]},
     "properties": {"calle": r.calle, "kmh": r.kmh, "buses": r.buses_hora, "limite": r.limite_kmh,
                    "color": next(c for v, c, _ in COLORES if r.kmh < v)}}
    for r in t.sort_values("buses_hora").itertuples()]}
leyenda = "".join(f'<div><span style="background:{c}"></span>{n} km/h</div>' for _, c, n in COLORES)
z = zona.round(1)
html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Velocidad del bus</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>html,body,#m{{height:100%;margin:0;font-family:system-ui,sans-serif}}
.caja{{background:#fff;padding:10px 12px;border-radius:6px;box-shadow:0 1px 4px #0004;font-size:13px;line-height:1.5;max-width:300px}}
.caja span{{display:inline-block;width:22px;height:6px;margin-right:6px;vertical-align:middle}}</style></head>
<body><div id="m"></div><script>
const d={json.dumps(geo)};
const m=L.map('m');
L.tileLayer('https://{{s}}.basemap.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap, © CARTO'}}).addTo(m);
const capa=L.geoJSON(d,{{style:f=>({{color:f.properties.color,weight:1.5+Math.sqrt(f.properties.buses)*0.9,opacity:0.9}}),
 onEachFeature:(f,l)=>l.bindTooltip(`<b>${{f.properties.calle}}</b><br>bus: ${{f.properties.kmh}} km/h<br>`+
  `${{f.properties.buses}} buses por hora<br>velocidad máxima: ${{f.properties.limite}} km/h`)}}).addTo(m);
m.fitBounds(capa.getBounds());
const c=L.control({{position:'topright'}});
c.onAdd=()=>{{const e=L.DomUtil.create('div','caja');e.innerHTML=
 `<b>Velocidad del bus, 7:00–8:00</b><br>Modelo calibrado (simulación)<br>{leyenda}`+
 `<div style="margin-top:6px">Grosor = buses por hora</div>`+
 `<div style="margin-top:6px">Centro Histórico: <b>{z.loc['Centro Histórico','kmh']} km/h</b><br>`+
 `Fuera del centro: <b>{z.loc['fuera del centro','kmh']} km/h</b></div>`+
 `<div style="margin-top:6px;color:#555">Incluye semáforos, colas y paradas.</div>`;return e}};
c.addTo(m);
</script></body></html>"""
(C / "mapa_velocidad_bus.html").write_text(html, encoding="utf-8")
print(f"\nmapa: {C / 'mapa_velocidad_bus.html'}")

# ----------------------------------------------------------------------------- figura estática (para informes)
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

AZULES = ["#0d366b", "#1c5cab", "#3987e5", "#6da7ec", "#b7d3f6"]      # más oscuro = más lento
fig, ax = plt.subplots(figsize=(9, 7.5))
fondo = [[(lon, lat) for lat, lon in [list(reversed(net.convertXY2LonLat(px, py))) for px, py in e.getShape()]]
         for e in net.getEdges() if e.getFunction() != "internal" and e.allows("passenger")]
ax.add_collection(LineCollection(fondo, colors="#e4e3de", linewidths=0.4, zorder=1))
clase = pd.cut(t.kmh, [0] + [v for v, _, _ in COLORES], right=False, labels=False)
for i, ((_, _, n), color) in enumerate(zip(COLORES, AZULES)):
    s = t[clase == i]
    ax.add_collection(LineCollection([[(p[1], p[0]) for p in f] for f in s.forma], colors=color,
                                     linewidths=0.8 + np.sqrt(s.buses_hora.values) * 0.35, zorder=2,
                                     label=f"{n} km/h"))
ax.autoscale()
ax.set_aspect(1 / np.cos(np.radians(-2.9)))
ax.set_axis_off()
ax.legend(title="Velocidad del bus, 7:00–8:00\n(grosor = buses por hora)", loc="lower right", fontsize=8,
          title_fontsize=8.5, frameon=False)
ax.set_title(f"Velocidad del bus por calle en la hora pico. Centro Histórico: {z.loc['Centro Histórico', 'kmh']} km/h; "
             f"fuera del centro: {z.loc['fuera del centro', 'kmh']} km/h", fontsize=10.5, loc="left", fontweight="bold")
fig.savefig(C / "mapa_velocidad_bus.png", dpi=170, bbox_inches="tight", facecolor="#fcfcfb")
print(f"figura: {C / 'mapa_velocidad_bus.png'}")
