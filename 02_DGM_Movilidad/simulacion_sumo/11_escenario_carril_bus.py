"""
Escenario 2: carril exclusivo para el bus en los corredores de 40 buses/h o mas (10_carriles_bus.py).

El modelo mesoscopico tiene una sola cola por calle, asi que el carril exclusivo no se puede simular directamente
(y el modo microscopico se traba con esta red de OSM). Se estima en dos partes:

1. Ganancia para el bus, con la corrida actual (09_buses.py ... capa bahia reruteo). En cada tramo de corredor, la simulacion
   da el tiempo que pierden los buses frente a circular a velocidad libre (timeLoss) y el tiempo detenidos en cola
   (waitingTime). Con carril exclusivo:
     - ganancia minima: desaparece el tiempo detenido en cola;
     - ganancia maxima: desaparece toda la demora (incluye la de los semaforos, que en realidad se mantiene).
   Por linea se suma la demora media por bus de los tramos de corredor que recorre.
2. Costo para los autos: corrida con un carril menos en los corredores (09_buses.py ... capa bahia reruteo
   menos_carril), comparada con la actual. En ambas los autos pueden cambiar de ruta durante el viaje.

Uso:  py simulacion_sumo/11_escenario_carril_bus.py [scats]
      Con "scats" compara las corridas con semaforos reales (solo demanda calibrada). Con "scats 2b", el escenario 2b
      (carril exclusivo solo en la Av. de las Americas y la Av. 24 de Mayo; salidas escenario2b_*).
Salida: simulacion_sumo/buses/escenario2_carril_bus[_scats].csv (por linea) y escenario2_resumen[_scats].csv
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
BUSES = SIM / "buses"
VAR = "_2b" if "2b" in sys.argv else ""
# Con "candidata": corridas con velocidades oficiales + semáforos que limitan el flujo (calibración del 22-10-2026)
# "candidata_jc": velocidades oficiales + cruces que controlan el paso (validación con tiempos de viaje, 23-10-2026)
CAND = "_vel_jc" if "candidata_jc" in sys.argv else "_vel_tlsflow_p25" if "candidata" in sys.argv else ""
corr = set(pd.read_csv(SIM / "red" / f"carriles_bus_v3{VAR}.csv").arista)

SCATS = "scats" in sys.argv
SUF = "_scats" if SCATS else ""
DEMANDAS = ["calibrada"] if SCATS else ["equilibrio", "calibrada"]
resumen, por_linea = [], []
for demanda in DEMANDAS:
    base = BUSES / f"{demanda}_bahia_reruteo{SUF}{CAND}"            # ambas con reruteo de autos durante el viaje
    esc = BUSES / f"{demanda}_bahia_menoscarril_reruteo{SUF}{VAR}{CAND}"
    # demora por bus en cada tramo de corredor (7:00-8:00)
    dem = {}
    for iv in sumolib.xml.parse(str(base / "buses_aristas.xml"), "interval"):
        for e in iv.edge or []:
            pasan = float(e.left or 0)
            if e.id in corr and pasan > 0:
                dem[e.id] = (float(e.timeLoss or 0) / pasan, float(e.waitingTime or 0) / pasan, pasan)
    horas_max = sum(t * n for t, _, n in dem.values()) / 3600
    horas_min = sum(w * n for _, w, n in dem.values()) / 3600
    # por linea
    vel = pd.read_csv(base / "velocidad_lineas.csv", index_col=0)
    rutas = {r.id: r.edges.split() for r in sumolib.xml.parse(str(base / "buses.rou.xml"), "route")}
    for rid, fila in vel[(vel.linename != "RUTA TRANVIA") & ~vel.sospechosa].iterrows():   # sin rutas con rodeos
        ed = [e for e in rutas.get(rid, []) if e in dem]
        g_max = sum(dem[e][0] for e in ed) / 60
        g_min = sum(dem[e][1] for e in ed) / 60
        por_linea.append({"demanda": demanda, "ruta": rid, "linea": fila.linename, "sentido": fila.sentido,
                          "km": fila.km, "tramos_corredor": len(ed),
                          "min_actual": round(fila.min_sim, 1), "ahorro_min_min": round(g_min, 1),
                          "ahorro_max_min": round(g_max, 1), "kmh_actual": fila.kmh_sim,
                          "kmh_con_carril_min": round(fila.km / ((fila.min_sim - g_min) / 60), 1),
                          "kmh_con_carril_max": round(fila.km / ((fila.min_sim - g_max) / 60), 1)})
    a = pd.read_csv(base / "resumen_escenario.csv").iloc[0]
    b = pd.read_csv(esc / "resumen_escenario.csv").iloc[0] if (esc / "resumen_escenario.csv").exists() else None
    resumen.append({"demanda": demanda, "tramos_corredor_con_buses": len(dem),
                    "horas_bus_ahorradas_por_hora_min": round(horas_min, 1),
                    "horas_bus_ahorradas_por_hora_max": round(horas_max, 1),
                    "auto_viaje_min_actual": a.auto_viaje_min,
                    "auto_viaje_min_con_carril": None if b is None else b.auto_viaje_min,
                    "autos_terminan_%_actual": a["autos_terminan_%"],
                    "autos_terminan_%_con_carril": None if b is None else b["autos_terminan_%"],
                    "en_calle_final_actual": a.en_calle_9_30,
                    "en_calle_final_con_carril": None if b is None else b.en_calle_9_30})

pl = pd.DataFrame(por_linea)
pl.to_csv(BUSES / f"escenario{VAR[1:] or 2}_carril_bus{SUF}{CAND}.csv", index=False, encoding="utf-8-sig")
rs = pd.DataFrame(resumen)
rs.to_csv(BUSES / f"escenario{VAR[1:] or 2}_resumen{SUF}{CAND}.csv", index=False, encoding="utf-8-sig")
print(rs.T.to_string())
for d in DEMANDAS:
    x = pl[pl.demanda == d]
    print(f"\n{d}: velocidad mediana actual {x.kmh_actual.median():.1f} km/h -> con carril "
          f"{x.kmh_con_carril_min.median():.1f} a {x.kmh_con_carril_max.median():.1f} km/h")
    print(x.sort_values("ahorro_max_min", ascending=False).head(10)[
        ["linea", "sentido", "min_actual", "ahorro_min_min", "ahorro_max_min", "kmh_actual",
         "kmh_con_carril_min", "kmh_con_carril_max"]].to_string(index=False))
