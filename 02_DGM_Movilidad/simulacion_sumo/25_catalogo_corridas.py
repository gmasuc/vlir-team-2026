"""
Catálogo de todas las corridas de la simulación, para el informe técnico (anexo A).

Para cada corrida del registro (19_registro_simulaciones.py → registro_simulaciones.xlsx):
  - decodifica las opciones de 09_buses.py que lleva el nombre de su carpeta y las traduce a lo que cambian en el modelo
    (archivo de entrada o parámetro de SUMO);
  - busca la corrida de referencia: la corrida anterior (por etapa y fecha) con la que comparte más opciones;
  - indica qué opción se agregó o se quitó frente a esa referencia, es decir, el parámetro que se cambió;
  - adjunta los indicadores de la corrida (bus, auto, atrapados, conteos, tiempos de viaje).

Uso:  py simulacion_sumo/25_catalogo_corridas.py
Salida: analisis/informe/anexo_A_catalogo_corridas.md y simulacion_sumo/catalogo_corridas.csv
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import re
from pathlib import Path

import pandas as pd

SIM = Path(__file__).resolve().parent
INF = SIM.parent / "analisis" / "informe"

# opción en el nombre de la carpeta -> (qué cambia en el modelo, parámetro o archivo)
OPCIONES = {
    "equilibrio": ("Demanda de equilibrio sin calibrar (86 123 vehículos)", "06_asignacion_congestion.py, duaIterate 10 iteraciones"),
    "calibrada": ("Demanda calibrada con los conteos 2023 (90 378 vehículos)", "07_calibracion_conteos.py → demanda_final.rou.xml"),
    "contrato": ("Intervalos de los contratos de operación (370 → 438 buses/h)", "flow period = 3600 / buses_h del contrato"),
    "bahia": ("Paradas de bus fuera de la calzada", "`<stop parking=\"true\">`"),
    "menoscarril": ("Un carril menos para autos en 306 tramos de corredores (14.4 km)", "red v3b; v3bs con semáforos SCATS (10_carriles_bus.py, 13_semaforos_scats.py menos_carril)"),
    "2b": ("El carril menos solo en Av. de las Américas y Av. 24 de Mayo (82 tramos, 4.8 km)", "red v3bs_2b"),
    "reruteo": ("Autos que recalculan su ruta cada 5 min", "--device.rerouting.probability 1 --device.rerouting.period 300 --device.rerouting.adaptation-steps 18"),
    "scats": ("Semáforos de SCATS (176 programas; 38 semáforos agregados a la red)", "red v2s + semaforos_scats.add.xml (13_semaforos_scats.py)"),
    "scats_v1": ("Primera versión de los programas de SCATS (prioridad del tranvía con tiempos estándar)", "semaforos_scats v1"),
    "v2_error": ("Segunda versión (fase más larga asignada al riel)", "semaforos_scats v2"),
    "centro": ("Centro Histórico: un carril menos y paradas en el carril (328 tramos)", "red v2sc_centro (16_centro_realista.py)"),
    "centro_paradas": ("Centro Histórico: paradas en el carril", "sin parking en 328 tramos"),
    "centro_parqueo": ("Centro Histórico: un carril menos", "red v2sc_centro"),
    "cap55": ("Centro: 55 % de la capacidad", "meso_centro_cap55.add.xml"),
    "cap70": ("Centro: 70 % de la capacidad", "meso_centro_cap70.add.xml"),
    "cap85": ("Centro: 85 % de la capacidad", "meso_centro_cap85.add.xml"),
    "tlsflow": ("Semáforos que limitan el flujo + 100 % de la espera en rojo", "--meso-tls-flow-penalty 1 --meso-tls-penalty 1"),
    "tlsflow_solo": ("Semáforos que limitan el flujo, sin espera en rojo", "--meso-tls-flow-penalty 1"),
    "tlsflow_p25": ("Semáforos que limitan el flujo + 25 % de la espera en rojo", "--meso-tls-flow-penalty 1 --meso-tls-penalty 0.25"),
    "tlsflow_p50": ("Semáforos que limitan el flujo + 50 % de la espera en rojo", "--meso-tls-flow-penalty 1 --meso-tls-penalty 0.5"),
    "vel": ("Velocidades máximas de la jerarquía vial oficial (17 981 tramos)", "red v2s_vel (18_velocidades_oficiales.py)"),
    "minor10": ("10 s de demora en la vía secundaria de cruces sin semáforo", "--meso-minor-penalty 10"),
    "minor20": ("20 s de demora en la vía secundaria de cruces sin semáforo", "--meso-minor-penalty 20"),
    "jc": ("Cruces que controlan el paso (prioridad y semáforos)", "--meso-junction-control"),
    "coord": ("Semáforos de SCATS coordinados (84 desfases, ciclo común por grupo)", "semaforos_scats_coord.add.xml (24_coordinacion_scats.py)"),
    "fases": ("Fases de SCATS por calle en 43 semáforos", "semaforos_scats_coord_fases.add.xml (24_coordinacion_scats.py fases)"),
    "sinvueltas": ("Recorridos sin vueltas a la manzana ausentes de la traza oficial (52 recorridos)", "09_buses.py quitar_vueltas"),
    "seed2": ("Semilla aleatoria 2", "--seed 2"), "seed3": ("Semilla aleatoria 3", "--seed 3"),
    "seed4": ("Semilla aleatoria 4", "--seed 4"), "seed5": ("Semilla aleatoria 5", "--seed 5"),
    "dem90": ("Demanda de autos −10 %", "demanda_final_dem90.rou.xml"),
    "dem110": ("Demanda de autos +10 %", "demanda_final_dem110.rou.xml"),
    "sin2carriles": ("Red sin el paso de 1 376 tramos de avenida a 2 carriles", "red v1s_vel"),
}
# opciones compuestas primero, para que "tlsflow_p25" no se lea como "tlsflow"
ORDEN = sorted(OPCIONES, key=len, reverse=True)
DEFECTO_TLS = "--meso-tls-penalty 1 (por defecto)"


def opciones(nombre):
    resto, out = "_" + nombre + "_", []
    for o in ORDEN:
        if f"_{o}_" in resto:
            out.append(o)
            resto = resto.replace(f"_{o}_", "_", 1)
    sobra = [x for x in resto.strip("_").split("_") if x]
    out = set(out)
    if "2b" in out:                          # el carril focalizado es una variante del carril menos
        out.discard("menoscarril")
    return out, sobra


r = pd.read_excel(SIM / "registro_simulaciones.xlsx")
r["n_etapa"] = r.etapa.str.extract(r"^(\d+)").astype(float)
r = r.sort_values(["n_etapa", "fecha"]).reset_index(drop=True)
r["opciones"], r["sin_decodificar"] = zip(*r.corrida.map(opciones))

filas = []
for i, x in r.iterrows():
    ref, mejor = None, None
    for j in range(i):
        y = r.loc[j]
        d = len(x.opciones ^ y.opciones)
        if mejor is None or d < mejor or (d == mejor and len(x.opciones & y.opciones) > len(x.opciones & ref.opciones)):
            ref, mejor = y, d
    if ref is None:
        cambio = "primera corrida"
        parametro = "; ".join(OPCIONES[o][1] for o in sorted(x.opciones))
    else:
        mas, menos = sorted(x.opciones - ref.opciones), sorted(ref.opciones - x.opciones)
        cambio = "; ".join([f"+ {OPCIONES[o][0]}" for o in mas] + [f"− {OPCIONES[o][0]}" for o in menos]) or "repetición"
        parametro = "; ".join([OPCIONES[o][1] for o in mas] + [f"sin: {OPCIONES[o][1]}" for o in menos])
        # cambiar la regla de los semáforos implica volver a la regla por defecto
        if not any(o.startswith("tlsflow") or o == "jc" for o in x.opciones) and any(
                o.startswith("tlsflow") or o == "jc" for o in menos):
            parametro += f"; {DEFECTO_TLS}"
    filas.append({"n": i + 1, "fecha": x.fecha, "etapa": x.etapa, "corrida": x.corrida,
                  "referencia": "—" if ref is None else ref.corrida, "cambio": cambio, "parametro_o_archivo": parametro,
                  "proposito": x.proposito, "estado": x.estado, "decision": x.decision_y_por_que,
                  "bus_kmh": x.bus_kmh_mediana, "auto_min": x.auto_viaje_min, "atrapados_9_30": x.autos_atrapados_9_30,
                  "conteos_r": x.conteos_r, "conteos_volumen_%": x["conteos_volumen_%"],
                  "conteos_GEH<5_%": x["conteos_GEH<5_%"], "google_%": x["tiempos_viaje_modelo/google_%"],
                  "google_en_rango_%": x["tiempos_viaje_dentro_rango_%"],
                  "sin_decodificar": " ".join(x.sin_decodificar)})
c = pd.DataFrame(filas)
c.to_csv(SIM / "catalogo_corridas.csv", index=False, encoding="utf-8-sig")
if c.sin_decodificar.str.len().gt(0).any():
    print("opciones sin decodificar:", c[c.sin_decodificar.str.len() > 0][["corrida", "sin_decodificar"]].to_string())


def f(v, d=1):
    return "—" if pd.isna(v) else (f"{v:.{d}f}" if isinstance(v, float) and d else f"{v:.0f}")


L = ["# Anexo A. Catálogo de las corridas de simulación", "",
     "Generado por `simulacion_sumo/25_catalogo_corridas.py` a partir de `registro_simulaciones.xlsx`. No editar a mano.", "",
     f"**{len(c)} corridas.** Cada fila indica el cambio frente a la corrida de referencia: la corrida anterior (por "
     "etapa y fecha) con la que comparte más opciones. «+» = opción agregada, «−» = opción quitada. La columna "
     "*Parámetro o archivo* dice qué opción de SUMO o qué archivo de entrada corresponde a ese cambio. Las opciones "
     "comunes a todas las corridas (modo mesoscópico, 6:00–9:30, 10 s por parada de bus, 30 s de tranvía, "
     "`--time-to-teleport 300`) están en la sección 5 del informe técnico.", "",
     "Indicadores de los vehículos que salen de 7:00 a 8:00. Bus = mediana de las líneas (km/h); Auto = viaje medio "
     "(min); Atrap. = vehículos en la red a las 9:30; r, Vol. y GEH = ajuste a los 38 accesos contados (2023); "
     "Google = tiempo del modelo frente a Google Maps en 20 trayectos y % de trayectos dentro de su rango. "
     "— = no calculado (las corridas previas a la etapa 4 no guardaron los volúmenes por calle).", ""]
for etapa, g in c.groupby("etapa", sort=False):
    L += [f"## {etapa}", "",
          "| # | Corrida | Cambio frente a la referencia | Parámetro o archivo | Bus | Auto | Atrap. | r | Vol. | GEH<5 | Google | En rango | Estado |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, x in g.iterrows():
        ref = "" if x.referencia == "—" else f"<br>*ref.: `{x.referencia}`*"
        L.append(f"| {x.n} | `{x.corrida}`{ref} | {x.cambio} | {x.parametro_o_archivo} | {f(x.bus_kmh)} | {f(x.auto_min)} | "
                 f"{f(x.atrapados_9_30, 0)} | {f(x.conteos_r, 2)} | {f(x['conteos_volumen_%'], 0)} | "
                 f"{f(x['conteos_GEH<5_%'], 0)} | {f(x['google_%'], 0)} | {f(x['google_en_rango_%'], 0)} | {x.estado} |")
    L.append("")
    L += ["**Propósito y decisión de cada corrida:**", ""]
    for x in g.itertuples():
        if isinstance(x.decision, str) and x.decision:
            L.append(f"- `{x.corrida}` — {x.proposito}. {x.decision}")
    L.append("")
(INF / "anexo_A_catalogo_corridas.md").write_text("\n".join(L), encoding="utf-8")
print(f"{len(c)} corridas -> {INF / 'anexo_A_catalogo_corridas.md'}")
