"""
Validación independiente de la calibración de la simulación (funciones que usa validacion_independiente.ipynb).

La configuración «vel_oficial + tlsflow_p25» se eligió comparando varias corridas con los conteos de autos de 2023 en
38 accesos (17 intersecciones) y con la velocidad programada del bus. Por eso esos conteos no sirven, solos, para decir
que el modelo es bueno. Aquí se evalúa con pruebas que no se usaron para elegir:
  1. validación cruzada por intersección: se elige la configuración con 16 intersecciones y se evalúa en la que quedó
     fuera, una por una (cada intersección se predice sin haber participado en la elección);
  2. volúmenes de hora pico de las intersecciones conflictivas (KML de la DGM), nunca usados en el modelo;
  3. buses contados en 2023 en los mismos accesos (la clase BUSES de los conteos), nunca usados en la calibración;
  4. velocidad simulada de cada línea frente a su velocidad programada (la elección usó solo la mediana).

Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sumo

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
BASE = SIM.parent
BUSES = SIM / "buses"
CONFIGS = {   # nombre corto -> carpeta de la corrida (misma demanda, paradas y semáforos SCATS)
    "base": "calibrada_bahia_reruteo_scats",
    "flujo + demora 100 %": "calibrada_bahia_reruteo_scats_tlsflow",
    "flujo + demora 50 %": "calibrada_bahia_reruteo_scats_tlsflow_p50",
    "flujo + demora 25 %": "calibrada_bahia_reruteo_scats_tlsflow_p25",
    "flujo sin demora": "calibrada_bahia_reruteo_scats_tlsflow_solo",
    "vel. oficial + flujo + demora 50 %": "calibrada_bahia_reruteo_scats_vel_tlsflow_p50",
    "vel. oficial + flujo + demora 25 %": "calibrada_bahia_reruteo_scats_vel_tlsflow_p25",
    "vel. oficial + flujo sin demora": "calibrada_bahia_reruteo_scats_vel_tlsflow_solo",
}
ELEGIDA = "vel. oficial + flujo + demora 25 %"


def geh(sim, obs):
    """estadístico GEH de cada par (valores bajo 5 se consideran un buen ajuste en hora pico)."""
    sim, obs = np.asarray(sim, float), np.asarray(obs, float)
    return np.sqrt(2 * (sim - obs) ** 2 / np.clip(sim + obs, 1, None))


def volumenes_por_arista(carpeta):
    """vehículos que entran a cada tramo de calle entre 7:00 y 8:00 (todas las clases)."""
    ent = {}
    for iv in sumolib.xml.parse(str(BUSES / carpeta / "aristas_todos.xml"), "interval"):
        for e in iv.edge or []:
            ent[e.id] = ent.get(e.id, 0) + float(e.entered or 0)
    return ent


def tabla_accesos():
    """38 accesos contados de autos (7:00-8:00) con el volumen simulado en cada configuración."""
    acc = pd.read_csv(SIM / "calibracion" / "ambos_v2" / "comparacion_accesos.csv")[
        ["arista", "interseccion", "acceso", "contados"]]
    for nombre, carpeta in CONFIGS.items():
        acc[nombre] = acc.arista.map(volumenes_por_arista(carpeta)).fillna(0)
    return acc


def indicadores(sim, obs):
    sim, obs = np.asarray(sim, float), np.asarray(obs, float)
    return {"r": np.corrcoef(sim, obs)[0, 1], "error_tipico_%": np.median(100 * np.abs(sim - obs) / obs),
            "volumen_%": 100 * sim.sum() / obs.sum(), "GEH<5_%": 100 * (geh(sim, obs) < 5).mean()}


def validacion_cruzada(acc, criterio="r"):
    """deja fuera una intersección por vez: elige la configuración con las otras 16 (la de mejor `criterio`) y guarda
    su volumen simulado en los accesos de la intersección que quedó fuera."""
    filas = []
    for inter in acc.interseccion.unique():
        ent, prueba = acc[acc.interseccion != inter], acc[acc.interseccion == inter]
        puntajes = {c: indicadores(ent[c], ent.contados)[criterio] for c in CONFIGS}
        elegida = max(puntajes, key=puntajes.get)
        for i, r in prueba.iterrows():
            filas.append({"interseccion": inter, "acceso": r.acceso, "contados": r.contados,
                          "elegida_sin_ella": elegida, "sim_elegida": r[elegida], "sim_base": r["base"]})
    return pd.DataFrame(filas)


def conflictivas(radio=60):
    """volumen simulado que entra a cada intersección conflictiva (KML de la DGM) frente a su volumen de hora pico."""
    c = pd.read_csv(BASE / "datos" / "scats" / "intersecciones_conflictivas.csv")
    c = c[c.vehiculos_hora_pico.notna()].copy()
    net = sumolib.net.readNet(str(SIM / "red" / "cuenca_piloto_v2s.net.xml"))
    nodos = [n for n in net.getNodes() if n.getType() not in ("dead_end", "internal")]
    entradas = []
    for r in c.itertuples():
        x, y = net.convertLonLat2XY(r.lon, r.lat)
        grupo = {n.getID() for n in nodos if np.hypot(n.getCoord()[0] - x, n.getCoord()[1] - y) < radio}
        entradas.append({e.getID() for n in nodos if n.getID() in grupo for e in n.getIncoming()
                         if e.getFromNode().getID() not in grupo})
    for nombre, carpeta in CONFIGS.items():
        v = volumenes_por_arista(carpeta)
        c[nombre] = [sum(v.get(e, 0) for e in ent) for ent in entradas]
    return c


def buses_accesos():
    """buses por hora contados en 2023 (clase BUSES) y simulados en los mismos accesos, por configuración."""
    t = None
    for nombre, carpeta in CONFIGS.items():
        b = pd.read_csv(BUSES / carpeta / "buses_accesos.csv").rename(columns={"simulados": nombre})
        t = b if t is None else t.merge(b[["interseccion", "acceso", nombre]], on=["interseccion", "acceso"])
    return t


def velocidad_lineas():
    """velocidad simulada de cada recorrido frente a la programada (sin rutas con rodeos), por configuración."""
    t = None
    for nombre, carpeta in CONFIGS.items():
        v = pd.read_csv(BUSES / carpeta / "velocidad_lineas.csv")
        v = v[(v.modo == "bus") & ~v.sospechosa][["ruta", "kmh_programada", "kmh_sim"]].rename(
            columns={"kmh_sim": nombre})
        t = v if t is None else t.merge(v[["ruta", nombre]], on="ruta")
    return t
