"""
Figuras de la bitácora de simulaciones (analisis/informe/bitacora_simulaciones.md).

Entrada: registro_simulaciones.csv (19_registro_simulaciones.py), robustez/robustez.csv (21_robustez.py), conteos por
         acceso (calibracion/ambos_v2/comparacion_accesos.csv) y tiempos de Google (20_tiempos_viaje.py).
Salida:  analisis/informe/figuras/bitacora/b1..b7_*.png

Uso:  py simulacion_sumo/23_figuras_bitacora.py
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import importlib
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SIM = Path(__file__).resolve().parent
sys.path.append(str(SIM))
sys.path.append(str(SIM.parent))
import validacion_independiente as vi  # noqa: E402
tv = importlib.import_module("20_tiempos_viaje")

OUT = SIM.parent / "analisis" / "informe" / "figuras" / "bitacora"
OUT.mkdir(parents=True, exist_ok=True)

# paleta de referencia (modo claro): tres colores categóricos, gris para el resto
AZUL, NARANJA, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRIS, GRIS_CLARO, TINTA, TINTA2, FONDO = "#9a9893", "#d9d8d3", "#0b0b0b", "#52514e", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": GRIS_CLARO,
                     "axes.labelcolor": TINTA2, "xtick.color": TINTA2, "ytick.color": TINTA2,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": "#ecebe7", "grid.linewidth": 0.8, "figure.facecolor": FONDO,
                     "axes.facecolor": FONDO, "axes.titlesize": 10.5, "axes.titleweight": "bold",
                     "axes.titlecolor": TINTA, "axes.titlelocation": "left"})

reg = pd.read_csv(SIM / "registro_simulaciones.csv")
reg = reg.set_index("corrida")
BASE_SCATS = "calibrada_bahia_reruteo_scats"
JC = "calibrada_bahia_reruteo_scats_vel_jc"
P25 = "calibrada_bahia_reruteo_scats_vel_tlsflow_p25"
COORD = "calibrada_bahia_reruteo_scats_vel_coord_jc"
FINAL = "calibrada_bahia_reruteo_scats_vel_coord_fases_sinvueltas_jc"     # modelo calibrado (30-10-2026)


def guardar(fig, nombre):
    fig.savefig(OUT / nombre, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("figura:", OUT / nombre)


# ----------------------------------------------------------------------------- b1. evolución del modelo
pasos = [("E3\nsemáforos\ngenéricos", "calibrada_bahia_reruteo"), ("E4\nSCATS", BASE_SCATS),
         ("E6\nflujo\n+25 %", "calibrada_bahia_reruteo_scats_tlsflow_p25"), ("E7\nvel. oficial\n+ flujo", P25),
         ("E9\ncruces que\ncontrolan", JC), ("E12\ncoordina-\ndos", COORD),
         ("E13\nfases y\nrecorridos", FINAL)]
x = np.arange(len(pasos))
paneles = [("bus_kmh_mediana", "Velocidad del bus (km/h)", 22.0, "observada 22.0"),
           ("conteos_r", "Ajuste a conteos (r)", 1.0, "ideal 1"),
           ("tiempos_viaje_modelo/google_%", "Tiempo de viaje / Google (%)", 100, "ideal 100 %")]
fig, axs = plt.subplots(1, 3, figsize=(14, 3.8))
for ax, (col, titulo, ref, ref_txt) in zip(axs, paneles):
    y = [reg.loc[c, col] if c in reg.index else np.nan for _, c in pasos]
    ax.axhline(ref, color=GRIS, lw=1, ls="--")
    ax.annotate(ref_txt, (0.6, ref), textcoords="offset points", xytext=(0, -3), color=TINTA2, fontsize=8,
                va="top", ha="center")
    ax.plot(x, y, color=AZUL, lw=2, marker="o", ms=7, mec=FONDO, mew=1.5)
    for xi, yi in zip(x, y):
        if not np.isnan(yi):
            ax.annotate(f"{yi:g}", (xi, yi), textcoords="offset points", xytext=(0, 8), ha="center",
                        fontsize=8.5, color=TINTA)
    ax.plot(x[-1], y[-1], marker="o", ms=11, color=AZUL, mec=TINTA, mew=1.2)
    ax.set_xticks(x, [p for p, _ in pasos], fontsize=7.5)
    ax.set_title(titulo)
    lo = np.nanmin(y + [ref])
    hi = np.nanmax(y + [ref])
    ax.set_ylim(lo - 0.15 * (hi - lo) - 0.01, hi + 0.25 * (hi - lo) + 0.01)
axs[1].text(0, axs[1].get_ylim()[0] + 0.02, "sin medir", fontsize=7.5, color=TINTA2, ha="center")
axs[2].text(0, axs[2].get_ylim()[0] + 2, "sin medir", fontsize=7.5, color=TINTA2, ha="center")
fig.suptitle("Cómo cambió el modelo de la situación actual en cada etapa (punto grande = modelo calibrado actual)",
             x=0.01, ha="left", fontsize=11, color=TINTA)
fig.tight_layout()
guardar(fig, "b1_evolucion_modelo.png")

# ----------------------------------------------------------------------------- b2. conteos frente a tiempos de viaje
sit = reg[reg.index.str.match(r"^calibrada_bahia_reruteo_scats") & reg["conteos_r"].notna()
          & ~reg.estado.isin(["robustez"])].copy()
etiquetas = {BASE_SCATS: "SCATS (E4)", "calibrada_bahia_reruteo_scats_centro": "centro −1 carril (E5)",
             "calibrada_bahia_reruteo_scats_centro_parqueo": "centro parqueo (E5)",
             "calibrada_bahia_reruteo_scats_tlsflow_solo": "flujo 0 % (E6)",
             "calibrada_bahia_reruteo_scats_tlsflow": "flujo 100 % (E6)",
             "calibrada_bahia_reruteo_scats_tlsflow_p25": "flujo 25 % (E6)",
             "calibrada_bahia_reruteo_scats_tlsflow_p50": "flujo 50 % (E6)",
             "calibrada_bahia_reruteo_scats_vel_tlsflow_solo": "vel. oficial + flujo 0 % (E7)",
             "calibrada_bahia_reruteo_scats_vel_tlsflow_p50": "vel. oficial + flujo 50 % (E7)",
             P25: "vel. oficial + flujo 25 % (E7)",
             "calibrada_bahia_reruteo_scats_vel_minor10_tlsflow_p25": "+10 s en cruces (E9)",
             "calibrada_bahia_reruteo_scats_vel_minor20_tlsflow_p25": "+20 s en cruces (E9)", JC: "cruces que controlan (E9)",
             COORD: "coordinados (E12)", FINAL: "modelo calibrado (E13)"}
DESPLAZA = {BASE_SCATS: (-12, -13), "calibrada_bahia_reruteo_scats_vel_tlsflow_solo": (7, 2),
            "calibrada_bahia_reruteo_scats_tlsflow_p25": (-82, -3), "calibrada_bahia_reruteo_scats_tlsflow_solo": (-70, -3),
            "calibrada_bahia_reruteo_scats_tlsflow_p50": (-30, -13),
            "calibrada_bahia_reruteo_scats_vel_minor10_tlsflow_p25": (-20, -14),
            "calibrada_bahia_reruteo_scats_vel_tlsflow_p50": (7, -10), JC: (8, 6), COORD: (-88, 12),
            FINAL: (8, -14)}
CLAVE = {BASE_SCATS, P25, JC, COORD, FINAL, "calibrada_bahia_reruteo_scats_vel_minor20_tlsflow_p25", "calibrada_bahia_reruteo_scats_centro",
         "calibrada_bahia_reruteo_scats_tlsflow"}
fig, ax = plt.subplots(figsize=(8.2, 5.2))
ax.add_patch(plt.Rectangle((60, 0.75), 50, 0.15, color="#eaf2fc", zorder=0))
ax.text(108, 0.895, "zona buscada: tiempos cercanos\na Google y buen ajuste a conteos", fontsize=8, color=TINTA2,
        ha="right", va="top")
for c, r in sit.iterrows():
    bloqueo = r.autos_atrapados_9_30 > 300
    color = AZUL if c == FINAL else NARANJA if c == P25 else GRIS
    ax.scatter(r["tiempos_viaje_modelo/google_%"], r.conteos_r, s=110 if c in (FINAL, P25) else 55,
               marker="X" if bloqueo else "o", color=color, edgecolor=FONDO, linewidth=1.2, zorder=5 if c == FINAL else 3)
    if c in CLAVE:
        ax.annotate(etiquetas[c], (r["tiempos_viaje_modelo/google_%"], r.conteos_r), textcoords="offset points",
                    xytext=DESPLAZA.get(c, (7, -3)), fontsize=8, color=TINTA if c in (FINAL, P25) else TINTA2,
                    fontweight="bold" if c in (FINAL, P25) else "normal")
ax.scatter([], [], marker="X", color=GRIS, s=55, label="red bloqueada (más de 300 vehículos atrapados)")
ax.scatter([], [], marker="o", color=GRIS, s=55, label="sin bloqueo (sin etiqueta: otras variantes de las etapas 5 a 7)")
ax.legend(loc="lower left", fontsize=8, frameon=False)
ax.set_xlim(30, 110)
ax.set_ylim(0.5, 0.9)
ax.set_xlabel("Tiempo de viaje del modelo frente a Google Maps (%)  →  más realista")
ax.set_ylabel("Ajuste a los conteos 2023 (r)  →  mejor")
ax.set_title("Mejorar los conteos acortaba los viajes; el modelo calibrado busca el equilibrio")
guardar(fig, "b2_conteos_vs_tiempos.png")

# ----------------------------------------------------------------------------- b3. vehículos atrapados (alarma de bloqueo)
act = reg[~reg.estado.isin(["robustez", "exploratoria"]) & ~reg.index.str.contains("contrato|menoscarril")].copy()
act["n_etapa"] = act.etapa.str.extract(r"^(\d+)")[0].astype(int)
act = act.sort_values(["n_etapa", "fecha"])
nombres = {"equilibrio": "E1 demanda sin calibrar, paradas en la calle", "equilibrio_bahia": "E1 + bahía",
           "equilibrio_bahia_reruteo": "E1 + cambio de ruta", "calibrada": "E2 calibrada, paradas en la calle",
           "calibrada_bahia": "E2 calibrada + bahía (sin cambio de ruta)",
           "calibrada_bahia_reruteo": "E3 + cambio de ruta (semáforos genéricos)",
           "calibrada_bahia_reruteo_scats_v1": "E4 SCATS versión 1", "calibrada_bahia_reruteo_scats_v2_error": "E4 SCATS versión 2",
           BASE_SCATS: "E4 SCATS corregido", **{k: v for k, v in etiquetas.items() if k != BASE_SCATS},
           "calibrada_bahia_reruteo_scats_centro_paradas": "paradas en el carril (E5)",
           "calibrada_bahia_reruteo_scats_cap85": "capacidad 85 % (E5)", "calibrada_bahia_reruteo_scats_cap70": "capacidad 70 % (E5)",
           "calibrada_bahia_reruteo_scats_cap55": "capacidad 55 % (E5)",
           "calibrada_bahia_reruteo_scats_tlsflow_p50": "flujo 50 % (E6)",
           "calibrada_bahia_reruteo_scats_vel_tlsflow_solo": "vel. oficial + flujo 0 % (E7)",
           "calibrada_bahia_reruteo_scats_vel_tlsflow_p50": "vel. oficial + flujo 50 % (E7)"}
act["nombre"] = [nombres.get(c, c) for c in act.index]
fig, ax = plt.subplots(figsize=(8.2, 7))
y = np.arange(len(act))[::-1]
v = act.autos_atrapados_9_30.clip(lower=1)
col = [AZUL if c == FINAL else NARANJA if a > 300 else GRIS for c, a in zip(act.index, act.autos_atrapados_9_30)]
ax.hlines(y, 1, v, color=GRIS_CLARO, lw=1.5)
ax.scatter(v, y, color=col, s=45, zorder=3, edgecolor=FONDO, linewidth=1)
for yi, vi_, n in zip(y, act.autos_atrapados_9_30, act.nombre):
    ax.text(vi_ * 1.15, yi, f"{vi_:,.0f}".replace(",", " "), va="center", fontsize=7.5, color=TINTA2)
ax.axvline(300, color=GRIS, ls="--", lw=1)
ax.text(320, y[0] + 0.5, "más de 300: red bloqueada", fontsize=8, color=TINTA2)
ax.set_xscale("log")
ax.set_yticks(y, act.nombre, fontsize=7.8)
ax.set_xlim(8, 40000)
ax.set_ylim(-0.8, len(act) + 0.4)
ax.set_xlabel("Vehículos que siguen en la calle a las 9:30 (escala logarítmica)")
ax.set_title("Vehículos atrapados en cada prueba de la situación actual, por etapa")
ax.grid(axis="y", visible=False)
guardar(fig, "b3_atrapados.png")

# ----------------------------------------------------------------------------- b4. conteos por acceso
acc = pd.read_csv(SIM / "calibracion" / "ambos_v2" / "comparacion_accesos.csv")[["arista", "interseccion", "contados"]]
fig, axs = plt.subplots(1, 2, figsize=(10, 4.6), sharex=True, sharey=True)
for ax, (carpeta, titulo, color) in zip(axs, [(BASE_SCATS, "Semáforos SCATS (etapa 4)", GRIS),
                                             (JC, "Cruces que controlan el paso (etapa 9)", AZUL)]):
    sim = acc.arista.map(vi.volumenes_por_arista(carpeta)).fillna(0)
    ind = vi.indicadores(sim, acc.contados)
    lim = max(acc.contados.max(), sim.max()) * 1.05
    ax.plot([0, lim], [0, lim], color=GRIS, lw=1, ls="--")
    ax.fill_between([0, lim], [0, lim * 0.7], [0, lim * 1.3], color="#eaf2fc", zorder=0)
    ax.scatter(acc.contados, sim, s=35, color=color, edgecolor=FONDO, linewidth=1, zorder=3)
    ax.set_title(titulo)
    ax.text(0.03, 0.97, f"r = {ind['r']:.2f}\nerror típico = {ind['error_tipico_%']:.0f} %\n"
                        f"volumen = {ind['volumen_%']:.0f} %\nGEH < 5 = {ind['GEH<5_%']:.0f} %",
            transform=ax.transAxes, va="top", fontsize=8.5, color=TINTA)
    ax.set_xlabel("Contados en 2023 (vehículos de 7:00 a 8:00)")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
axs[0].set_ylabel("Simulados (vehículos de 7:00 a 8:00)")
fig.suptitle("Los 38 accesos contados: cada punto es un acceso; la diagonal es el acuerdo perfecto, la banda ±30 %",
             x=0.01, ha="left", fontsize=11, color=TINTA)
fig.tight_layout()
guardar(fig, "b4_conteos_por_acceso.png")

# ----------------------------------------------------------------------------- b5. tiempos de viaje frente a Google
g = tv.google()
mods = {c: tv.tiempos_trayectos(c).set_index("n").min_modelo for c in (BASE_SCATS, JC)}
fig, ax = plt.subplots(figsize=(10, 4.4))
n = g.n.values
ax.vlines(n, g.google_min_minimo, g.google_min_maximo, color="#b7d3f6", lw=9, zorder=1)
ax.scatter(n, mods[BASE_SCATS].reindex(n), color=GRIS, s=40, zorder=3, label="semáforos SCATS (etapa 4)",
           edgecolor=FONDO, linewidth=1)
ax.scatter(n, mods[JC].reindex(n), color=AZUL, s=48, zorder=4, label="cruces que controlan el paso (etapa 9)",
           edgecolor=FONDO, linewidth=1)
ax.plot([], [], color="#b7d3f6", lw=9, label="rango de Google Maps (mínimo a máximo)")
for i in n:
    if i % 2 == 0:
        ax.axvspan(i - 0.5, i + 0.5, color="#f3f2ee", zorder=0)
etq = [f"{i}\n{tv.TRAYECTOS[i - 1][0]}→{tv.TRAYECTOS[i - 1][1]}" for i in n]
ax.set_xticks(n, etq, fontsize=7.5)
ax.set_xlim(0.4, len(n) + 0.6)
ax.set_ylabel("Minutos en auto (salida 7:30)")
ax.set_title("Los 20 trayectos: fondo gris = trayectos pares, que no se usaron para elegir el modelo (comprobación)")
ax.legend(loc="upper right", fontsize=8, frameon=False)
guardar(fig, "b5_tiempos_google.png")

# ----------------------------------------------------------------------------- b6. escenarios en cada versión del modelo
versiones = [  # (nombre, actual, contrato, carril 14.4 km, carril focalizado)
    ("E1 demanda sin calibrar", "equilibrio_bahia_reruteo", "equilibrio_contrato_bahia_reruteo",
     "equilibrio_bahia_menoscarril_reruteo", None),
    ("E3 semáforos genéricos", "calibrada_bahia_reruteo", "calibrada_contrato_bahia_reruteo",
     "calibrada_bahia_menoscarril_reruteo", None),
    ("E4 semáforos SCATS", BASE_SCATS, "calibrada_contrato_bahia_reruteo_scats",
     "calibrada_bahia_menoscarril_reruteo_scats", "calibrada_bahia_menoscarril_reruteo_scats_2b"),
    ("E8 vel. oficial + flujo", P25, "calibrada_contrato_bahia_reruteo_scats_vel_tlsflow_p25",
     "calibrada_bahia_menoscarril_reruteo_scats_vel_tlsflow_p25", "calibrada_bahia_menoscarril_reruteo_scats_2b_vel_tlsflow_p25"),
    ("E10 modelo calibrado", JC, "calibrada_contrato_bahia_reruteo_scats_vel_jc",
     "calibrada_bahia_menoscarril_reruteo_scats_vel_jc", "calibrada_bahia_menoscarril_reruteo_scats_2b_vel_jc"),
]
rob = pd.read_csv(SIM / "robustez" / "robustez.csv")
esc = [("Frecuencias de contrato", 2, "costo_auto_contrato_min"), ("Carril bus en 14.4 km", 3, "costo_auto_carril_14km_min"),
       ("Carril focalizado (Américas y 24 de Mayo)", 4, "costo_auto_carril_focalizado_min")]
fig, axs = plt.subplots(1, 3, figsize=(12, 3.4), sharey=True, sharex=True)
yv = np.arange(len(versiones))[::-1]
for ax, (titulo, k, col) in zip(axs, esc):
    for yi, v in zip(yv, versiones):
        if v[k] is None:
            ax.text(0.05, yi, "no evaluado", va="center", fontsize=7.5, color=TINTA2)
            continue
        costo = reg.loc[v[k], "auto_viaje_min"] - reg.loc[v[1], "auto_viaje_min"]
        ax.scatter(costo, yi, color=AZUL if v[0].startswith("E10") else GRIS, s=50, zorder=3, edgecolor=FONDO)
        ax.text(costo, yi + 0.28, f"{costo:+.1f}", ha="center", fontsize=8, color=TINTA)
    lo, hi = rob[col].min(), rob[col].max()
    ax.hlines(-1, lo, hi, color=NARANJA, lw=4)
    ax.text((lo + hi) / 2, -0.72, f"{lo:+.1f} a {hi:+.1f}", ha="center", fontsize=8, color=TINTA)
    ax.axvline(0, color=GRIS, lw=1)
    ax.set_title(titulo, fontsize=9.5)
    ax.set_xlabel("Minutos más por viaje en auto")
axs[0].set_yticks(list(yv) + [-1], [v[0] for v in versiones] + ["Prueba de robustez (rango)"], fontsize=8)
axs[0].set_xlim(-0.7, 4.6)
axs[0].set_ylim(-1.6, len(versiones) - 0.4)
for ax in axs:
    ax.grid(axis="y", visible=False)
fig.suptitle("Costo para el auto de cada escenario en cada versión del modelo: los valores cambian, el orden no",
             x=0.01, ha="left", fontsize=11, color=TINTA)
fig.tight_layout()
guardar(fig, "b6_escenarios_por_version.png")

# ----------------------------------------------------------------------------- b7. robustez por variante
rob = rob[rob.variante != "sin avenidas a 2 carriles"]
fig, ax = plt.subplots(figsize=(9, 3.8))
yr = np.arange(len(rob))[::-1]
for (titulo, _, col), color, mk in zip(esc, [GRIS, NARANJA, AZUL], ["s", "o", "D"]):
    ax.scatter(rob[col], yr, color=color, marker=mk, s=45, zorder=3, edgecolor=FONDO, label=titulo)
ax.axvline(1, color=GRIS, ls="--", lw=1)
ax.text(1.05, yr[0] + 0.3, "1 minuto", fontsize=8, color=TINTA2)
ax.set_yticks(yr, rob.variante, fontsize=8)
ax.set_xlabel("Minutos más por viaje en auto frente a la situación actual de la misma variante")
ax.set_title("Prueba de robustez: en las 8 variantes, el carril en toda la red es siempre el más costoso")
ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.18), ncol=3, fontsize=8, frameon=False)
ax.grid(axis="y", visible=False)
guardar(fig, "b7_robustez.png")

# ----------------------------------------------------------------------------- b8. mapa de velocidad del bus (22_mapa_velocidad_bus.py)
mapa = SIM / "buses" / FINAL / "mapa_velocidad_bus.png"
if mapa.exists():
    import shutil
    shutil.copy(mapa, OUT / "b8_mapa_velocidad_bus.png")
    print("figura:", OUT / "b8_mapa_velocidad_bus.png")

# ----------------------------------------------------------------------------- b9. velocidad del bus por línea frente a la observada
e0 = pd.read_csv(SIM.parent / "datos" / "derivados" / "escenario0_lineas_lv.csv")
e0 = e0[e0.tipo == "Normal"].assign(linea=lambda d: d.linea.astype(str).str.upper()).set_index("linea")
fig, axs = plt.subplots(1, 2, figsize=(10, 4.6), sharex=True, sharey=True)
for ax, (carpeta, titulo, color) in zip(axs, [(JC, "Etapa 9 (antes de calibrar el bus)", GRIS),
                                             (FINAL, "Modelo calibrado (etapa 13)", AZUL)]):
    v = pd.read_csv(SIM / "buses" / carpeta / "velocidad_lineas.csv")
    v = v[(v.modo == "bus") & ~v.sospechosa].assign(linea=lambda d: d.linea.astype(str).str.upper())
    g = v.groupby("linea").kmh_sim.mean().to_frame().join(e0.vo_pico, how="inner")
    ax.plot([8, 32], [8, 32], color=GRIS, lw=1, ls="--")
    ax.fill_between([8, 32], [8 * 0.8, 32 * 0.8], [8 * 1.2, 32 * 1.2], color="#eaf2fc", zorder=0)
    ax.scatter(g.vo_pico, g.kmh_sim, s=38, color=color, edgecolor=FONDO, linewidth=1, zorder=3)
    for lin, rr in g.iterrows():
        if lin in ("4", "7", "100", "15", "50"):
            ax.annotate(f"línea {lin}", (rr.vo_pico, rr.kmh_sim), textcoords="offset points", xytext=(5, -3),
                        fontsize=7.5, color=TINTA2)
    ax.text(0.03, 0.97, f"{len(g)} líneas\nmodelo ÷ observado (mediana) = {(g.kmh_sim / g.vo_pico).median():.0%}",
            transform=ax.transAxes, va="top", fontsize=8.5, color=TINTA)
    ax.set_title(titulo)
    ax.set_xlabel("Velocidad observada en hora pico, Escenario 0 (km/h)")
    ax.set_xlim(8, 32)
    ax.set_ylim(8, 32)
axs[0].set_ylabel("Velocidad del bus en el modelo (km/h)")
fig.suptitle("Velocidad del bus por línea: cada punto es una línea; la diagonal es el acuerdo perfecto, la banda ±20 %",
             x=0.01, ha="left", fontsize=11, color=TINTA)
fig.tight_layout()
guardar(fig, "b9_bus_modelo_vs_observado.png")
