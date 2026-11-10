"""
Tiempos estimados de parada a parada para cada línea (y el tranvía), según la simulación de la hora pico.

1. Corre la situación actual con semáforos reales (los mismos archivos de buses/calibrada_bahia_reruteo_scats y la
   misma configuración de 09_buses.py, por lo que el resultado es idéntico) agregando --stop-output: la hora en que
   cada bus llega a cada parada y sale de ella. Si el archivo ya existe, no vuelve a correr (usar "rehacer" para forzar).
2. Para los buses que salen entre 7:00 y 8:00, por línea y sentido, y por cada par de paradas consecutivas:
   distancia por las calles, minutos de viaje (de la salida de una parada a la llegada a la siguiente, sin la detención),
   velocidad del tramo y minutos acumulados desde la primera parada. Se usa la mediana entre buses (no la media), para
   que un bus atrapado una vez no distorsione el tramo.

Límites: solo el tramo de cada línea dentro del área piloto; una parada por calle y línea (09_buses.py); la detención en
cada parada es fija (10 s bus, 30 s tranvía), así que lo que varía es el viaje entre paradas (tráfico y semáforos).
En el modo mesoscópico el bus avanza calle por calle, no metro a metro: en tramos cortos (< 200 m) la velocidad del tramo
es imprecisa (puede salir por encima del límite); los minutos acumulados y los tramos largos sí son confiables.
Paradas: las del recorrido publicado por el GAD (CSV de abril de 2026), ver 09_buses.py; columna origen_paradas.

Uso:  py simulacion_sumo/15_tiempos_parada_a_parada.py [rehacer]
Salida: buses/tiempos_parada_a_parada/tramos.csv (un tramo por fila), resumen_lineas.csv y
        tiempos_parada_a_parada.xlsx (una hoja por línea y sentido)
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
RUN = SIM / "buses" / "calibrada_bahia_reruteo_scats"
OUT = SIM / "buses" / "tiempos_parada_a_parada"
NET = SIM / "red" / "cuenca_piloto_v2s.net.xml"
AUTOS = SIM / "calibracion" / "ambos_v2" / "demanda_final.rou.xml"
SALIDA = OUT / "paradas_salida.xml"
B, E = 7 * 3600, 8 * 3600
env = dict(os.environ, SUMO_HOME=sumo.SUMO_HOME)
OUT.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------- 1. simular con registro de paradas
if not SALIDA.exists() or "rehacer" in sys.argv:
    if os.name == "nt":                   # no suspender la computadora mientras corre
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    cmd = [str(Path(sumo.SUMO_HOME) / "bin" / "sumo"), "-n", str(NET), "-r", f"{RUN / 'buses.rou.xml'},{AUTOS}",
           "-a", ",".join(map(str, [SIM / "red" / "semaforos_scats.add.xml", RUN / "tranvia_prioridad.add.xml",
                                    RUN / "paradas.add.xml"])),
           "--mesosim", "--meso-tls-penalty", "1", "--device.rerouting.probability", "1",
           "--device.rerouting.period", "300", "--device.rerouting.adaptation-steps", "18", "-b", "21600",
           "-e", "34200", "--time-to-teleport", "300", "--ignore-route-errors", "--no-step-log", "--threads", "4",
           "--tripinfo-output", "viajes.xml", "--tripinfo-output.write-unfinished", "--stop-output", SALIDA.name,
           "--duration-log.statistics"]
    print("simulando la hora pico con registro de paradas (~30 min)...", flush=True)
    with open(OUT / "sumo.log", "w") as log:
        if subprocess.run(cmd, cwd=OUT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
            sys.exit(f"falló sumo (ver {OUT / 'sumo.log'})")

# ----------------------------------------------------------------------------- 2. tiempos entre paradas
net = sumolib.net.readNet(str(NET))
nombre = {s.get("id"): s.get("name") for s in ET.parse(RUN / "paradas.add.xml").getroot().iter("busStop")}
pos_stop = {s.id: (s.lane.rsplit("_", 1)[0], float(s.startPos)) for s in sumolib.xml.parse(str(RUN / "paradas.add.xml"), "busStop")}
rutas, orden = {}, {}
for r in sumolib.xml.parse(str(RUN / "buses.rou.xml"), "route"):
    rutas[r.id] = r.edges.split()
    orden[r.id] = [s.busStop for s in (r.stop or [])]
flujos = {f.id: (f.route, f.type) for f in sumolib.xml.parse(str(RUN / "buses.rou.xml"), "flow")}


def distancia(edges, a, b):
    """metros por la ruta desde la parada a hasta la parada b."""
    (ea, pa), (eb, pb) = pos_stop[a], pos_stop[b]
    ia = edges.index(ea)
    ib = edges.index(eb, ia)
    if ia == ib:
        return pb - pa
    m = net.getEdge(ea).getLength() - pa
    m += sum(net.getEdge(e).getLength() for e in edges[ia + 1:ib])
    return m + pb


paradas = pd.DataFrame([{"vehiculo": s.id, "parada": s.busStop, "llega": float(s.started), "sale": float(s.ended)}
                        for s in sumolib.xml.parse(str(SALIDA), "stopinfo") if s.busStop])
paradas["flujo"] = paradas.vehiculo.str.rsplit(".", n=1).str[0]
salida_bus = paradas.groupby("vehiculo").llega.min()
paradas = paradas[paradas.vehiculo.map(salida_bus).between(B, E, inclusive="left")]

filas = []
for (flujo, veh), g in paradas.sort_values("llega").groupby(["flujo", "vehiculo"]):
    g = g.reset_index(drop=True)
    for i in range(len(g) - 1):
        filas.append({"ruta": flujo, "vehiculo": veh, "desde": g.parada[i], "hasta": g.parada[i + 1],
                      "min_viaje": (g.llega[i + 1] - g.sale[i]) / 60, "min_detencion": (g.sale[i] - g.llega[i]) / 60})
viajes = pd.DataFrame(filas)
tramos = []
for ruta, g in viajes.groupby("ruta"):
    edges = rutas[flujos[ruta][0]]
    secuencia = orden[flujos[ruta][0]]
    acum = 0.0
    for k, (a, b) in enumerate(zip(secuencia, secuencia[1:]), 1):
        x = g[(g.desde == a) & (g.hasta == b)]
        if x.empty:
            continue
        try:
            m = distancia(edges, a, b)
        except ValueError:
            m = float("nan")
        mv = x.min_viaje.median()
        acum += mv + x.min_detencion.median()
        tramos.append({"ruta": ruta, "linea": ruta[1:].rsplit("_", 1)[0], "sentido": ruta.rsplit("_", 1)[1],
                       "tramo": k, "desde": nombre.get(a, a), "hasta": nombre.get(b, b), "metros": round(m),
                       "min_viaje": round(mv, 2), "kmh": round(m / 1000 / (mv / 60), 1) if mv > 0 else None,
                       "min_acumulado": round(acum, 1), "buses_medidos": len(x),
                       "min_viaje_p90": round(x.min_viaje.quantile(0.9), 2)})
t = pd.DataFrame(tramos)
t["linea"] = t.linea.replace({"RUTA_TRANVIA": "Tranvía"})
t.to_csv(OUT / "tramos.csv", index=False, encoding="utf-8-sig")

res = t.groupby(["linea", "sentido"]).agg(paradas=("tramo", lambda s: len(s) + 1), km=("metros", lambda s: round(s.sum() / 1000, 1)),
                                          min_total=("min_acumulado", "max"), tramo_mas_lento=("kmh", "min")).reset_index()
res["kmh_promedio"] = (res.km / (res.min_total / 60)).round(1)
cob = pd.read_csv(RUN / "cobertura_lineas.csv")
if "origen_paradas" in cob:                           # de dónde salen las paradas de cada línea (09_buses.py)
    cob["linea"] = cob.linea.astype(str).replace({"RUTA TRANVIA": "Tranvía"})
    res = res.merge(cob[["linea", "sentido", "origen_paradas"]], on=["linea", "sentido"], how="left")
res.to_csv(OUT / "resumen_lineas.csv", index=False, encoding="utf-8-sig")

with pd.ExcelWriter(OUT / "tiempos_parada_a_parada.xlsx") as xl:
    res.to_excel(xl, sheet_name="Resumen", index=False)
    for (lin, sen), g in t.groupby(["linea", "sentido"], sort=False):
        g.drop(columns=["ruta", "linea", "sentido"]).to_excel(xl, sheet_name=f"{lin} {sen}"[:31], index=False)
print(f"{t.ruta.nunique()} recorridos, {len(t)} tramos entre paradas")
print(res.to_string(index=False))
