"""
Asignacion con congestion (equilibrio de rutas) de la demanda de autos de la hora pico, con duaIterate de SUMO
en modo mesoscopico, y comparacion con los conteos vehiculares 2023 en cada iteracion.

En cada iteracion se simula la hora pico; los vehiculos que encontraron congestion prueban rutas alternativas
en la siguiente. Al final las rutas se reparten como lo haria la gente: nadie gana cambiando de ruta.

Uso:  py simulacion_sumo/06_asignacion_congestion.py [escenario] [iteraciones]
Entrada: simulacion_sumo/demanda/<escenario>/viajes.trips.xml (de 05_demanda_autos.py)
Salida:  simulacion_sumo/asignacion/<escenario>/ (rutas de equilibrio, volumenes, comparacion_iteraciones.csv)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))
import red_buses as rb  # noqa: E402

SIM = BASE / "simulacion_sumo"
ESC = sys.argv[1] if len(sys.argv) > 1 else "ambos"
ITER = int(sys.argv[2]) if len(sys.argv) > 2 else 10
OUT = SIM / "asignacion" / ESC
OUT.mkdir(parents=True, exist_ok=True)
NET = SIM / "red" / "cuenca_piloto.net.xml"
TRIPS = SIM / "demanda" / ESC / "viajes.trips.xml"
HORA = 7
AGG = 900                                   # segundos por intervalo de medicion

# ----------------------------------------------------------------------------- 1. solo viajes con ruta posible
# (~2 % de los viajes empiezan o terminan en calles desconectadas; duaIterate se detiene ante ellos)
con_ruta = {v.id for v in sumolib.xml.parse_fast(str(SIM / "demanda" / ESC / "rutas.rou.xml"), "vehicle", ["id"])}
VALIDOS = OUT / "viajes_validos.trips.xml"
SOLO_COMPARAR = len(sys.argv) > 3 and sys.argv[3] == "comparar"     # p. ej.: ... ambos 10 comparar
if not SOLO_COMPARAR:
    with open(TRIPS, encoding="utf-8") as fi, open(VALIDOS, "w", encoding="utf-8") as fo:
        for linea in fi:
            m = re.search(r'<trip id="([^"]+)"', linea)
            if m is None or m.group(1) in con_ruta:
                fo.write(linea)
print(f"viajes con ruta posible: {len(con_ruta):,}", flush=True)

# ----------------------------------------------------------------------------- 2. duaIterate (mesoscopico)
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
cmd = [sys.executable, os.path.join(sumo.SUMO_HOME, "tools", "assign", "duaIterate.py"),
       "-n", str(NET), "-t", str(VALIDOS), "-l", str(ITER), "-m",          # -m: mesoscopico
       "-b", str(HORA * 3600), "-e", str((HORA + 2) * 3600), "-a", str(AGG),
       "--time-to-teleport", "300", "-w", "--clean-alt",
       "duarouter--routing-threads", "4", "sumo--meso-tls-penalty", "1", "sumo--threads", "4"]
if not SOLO_COMPARAR:
    print("ejecutando duaIterate:", ITER, "iteraciones en", OUT, flush=True)
    with open(OUT / "duaIterate.log", "w") as log:
        r = subprocess.run(cmd, cwd=OUT, env=env, stdout=log, stderr=subprocess.STDOUT)
    print("duaIterate termino con codigo", r.returncode, flush=True)

# ----------------------------------------------------------------------------- 2. intersecciones contadas -> aristas de entrada
net = sumolib.net.readNet(str(NET))
c = pd.read_csv(glob.glob(str(BASE / "datos" / "portal" / "gadcuenca_conteovehicular*.csv"))[0], sep=None, engine="python", encoding="latin-1")
c.columns = [x.strip() for x in c.columns]
c["livianos"] = c[[x for x in c.columns if x.upper().startswith("LIVIANOS")]].apply(pd.to_numeric, errors="coerce").sum(axis=1)
c["hora"] = pd.to_numeric(c["HORA INICIO"].astype(str).str.extract(r"(\d{1,2})\s*:")[0], errors="coerce")
obs = c[c.hora == HORA].groupby(c.DIRECCION.str.strip())["livianos"].sum()
calles = gpd.read_file(BASE / "datos" / "derivados" / "red_calles_osm.gpkg")
puntos = {}
for nombre in obs.index:
    p = rb.ubicar_interseccion(nombre, calles)
    if p is None:
        continue
    lon, lat = gpd.GeoSeries([p], crs=32717).to_crs(4326).iloc[0].coords[0]
    x, y = net.convertLonLat2XY(lon, lat)
    nodos = [n for n in net.getNodes() if np.hypot(n.getCoord()[0] - x, n.getCoord()[1] - y) < 40]
    ent = {e.getID() for n in nodos for e in n.getIncoming() if e.getFunction() != "internal"}
    puntos[nombre] = ent - {e.getID() for n in nodos for e in n.getOutgoing()}

# ----------------------------------------------------------------------------- 3. volumenes por iteracion vs conteos
def volumenes(archivo):
    """vehiculos que entran a cada arista entre las 7:00 y las 8:00 (edgedata de la iteracion)."""
    v = {}
    for iv in sumolib.xml.parse(sumolib.openz(archivo), "interval"):     # duaIterate los guarda comprimidos
        if HORA * 3600 <= float(iv.begin) < (HORA + 1) * 3600:
            for e in iv.edge or []:
                v[e.id] = v.get(e.id, 0) + float(e.entered or 0)
    return pd.Series(v, dtype=float)

filas, ultimo = [], None
for f in sorted(glob.glob(str(OUT / "[0-9][0-9][0-9]" / f"dump_{AGG}*.xml*"))):     # 000/dump_900.0.xml.gz, 001/...
    it = int(Path(f).parent.name)
    try:
        vol = volumenes(f)
    except (EOFError, OSError):
        print(f"iteracion {it}: archivo incompleto (todavia se esta simulando), se omite")
        continue
    sim = pd.Series({k: vol.reindex(list(e)).fillna(0).sum() for k, e in puntos.items()})
    o = obs.reindex(sim.index)
    ok = o > 50
    filas.append({"iteracion": it, "suma_contados": o[ok].sum(), "suma_simulados": sim[ok].sum(),
                  "razon": sim[ok].sum() / o[ok].sum(), "correlacion": np.corrcoef(o[ok], sim[ok])[0, 1],
                  "error_medio_%": (100 * (sim[ok] - o[ok]).abs() / o[ok]).median()})
    ultimo = pd.DataFrame({"contados_livianos_h": o, "simulados_h": sim.round(0)})
it_df = pd.DataFrame(filas).round(2)
it_df.to_csv(OUT / "comparacion_iteraciones.csv", index=False)
print(it_df.to_string(index=False))
if ultimo is not None:
    ultimo["razon"] = (ultimo.simulados_h / ultimo.contados_livianos_h).round(2)
    ultimo.to_csv(OUT / "comparacion_conteos_final.csv", encoding="utf-8-sig")
    print("\nultima iteracion:\n" + ultimo.to_string())
