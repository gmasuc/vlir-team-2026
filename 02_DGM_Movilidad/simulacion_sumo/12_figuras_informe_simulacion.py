"""
Figuras y tablas del informe de la simulacion (analisis/informe/informe_simulacion_escenarios.md).

s1  Calibracion: autos contados vs simulados por acceso (equilibrio, calibrada, calibrada con reruteo)
s2  Mapa: red piloto, corredores de 40+ buses/h con carril exclusivo (escenario 2) y tranvia
s3  Escenario 1: velocidad de cada linea con frecuencias de la capa vs del contrato (fluido y hora pico)
s4  Escenario 2: minutos que ahorraria cada linea con carril exclusivo (rango minimo-maximo)

Uso:  py simulacion_sumo/12_figuras_informe_simulacion.py
Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sumo  # noqa: E402

sys.path.append(os.path.join(sumo.SUMO_HOME, "tools"))
import sumolib  # noqa: E402

SIM = Path(__file__).resolve().parent
FIG = SIM.parent / "analisis" / "informe" / "figuras"
FIG.mkdir(parents=True, exist_ok=True)
BUSES = SIM / "buses"
CAL = SIM / "calibracion" / "ambos_v2"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

# ----------------------------------------------------------------------------- s1 calibracion
acc = pd.read_csv(CAL / "comparacion_accesos.csv")
if (CAL / "reruteo_aristas.xml").exists():
    v = {e.id: float(e.entered or 0) for iv in sumolib.xml.parse(str(CAL / "reruteo_aristas.xml"), "interval")
         for e in iv.edge or []}
    acc["reruteo"] = acc.arista.map(v).fillna(0)
paneles = [("equilibrio", "Sin calibrar"), ("final", "Calibrada"), ("reruteo", "Calibrada + cambio de ruta")]
paneles = [p for p in paneles if p[0] in acc]
fig, axs = plt.subplots(1, len(paneles), figsize=(4.2 * len(paneles), 4.2), sharex=True, sharey=True)
filas = []
for ax, (col, tit) in zip(np.atleast_1d(axs), paneles):
    r = np.corrcoef(acc.contados, acc[col])[0, 1]
    err = (100 * (acc[col] - acc.contados).abs() / acc.contados).median()
    filas.append({"demanda": tit, "correlacion": round(r, 2), "error_medio_%": round(err),
                  "simulados_vs_contados_%": round(100 * acc[col].sum() / acc.contados.sum())})
    ax.scatter(acc.contados, acc[col], s=22, color="#2F6FC0", alpha=.8)
    m = max(acc.contados.max(), acc[col].max()) * 1.05
    ax.plot([0, m], [0, m], color="grey", lw=1, ls="--")
    ax.set_title(f"{tit}\nr = {r:.2f} · error típico {err:.0f} %")
    ax.set_xlabel("autos contados por hora (2023)")
np.atleast_1d(axs)[0].set_ylabel("autos simulados por hora")
fig.tight_layout()
fig.savefig(FIG / "s1_calibracion_conteos.png", dpi=150)
pd.DataFrame(filas).to_csv(FIG / "s1_calibracion_tabla.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(filas).to_string(index=False))

# ----------------------------------------------------------------------------- s2 mapa
net = sumolib.net.readNet(str(SIM / "red" / "cuenca_piloto_v2.net.xml"))
corr = pd.read_csv(SIM / "red" / "carriles_bus_v3.csv")
fig, ax = plt.subplots(figsize=(9, 7))
for e in net.getEdges():
    if e.getFunction() == "internal":
        continue
    s = np.array(e.getShape())
    if e.getType() == "railway.tram":
        ax.plot(s[:, 0], s[:, 1], color="#2E7D5B", lw=2.2, zorder=3)
    elif e.allows("passenger"):
        ax.plot(s[:, 0], s[:, 1], color="#D9DDD8", lw=.4, zorder=1)
for eid in corr.arista:
    s = np.array(net.getEdge(eid).getShape())
    ax.plot(s[:, 0], s[:, 1], color="#C0392B", lw=2.4, zorder=4)
ax.plot([], [], color="#C0392B", lw=2.4, label=f"Carril exclusivo de bus (escenario 2): {corr.largo_m.sum() / 1000:.1f} km")
ax.plot([], [], color="#2E7D5B", lw=2.2, label="Tranvía (vía propia)")
ax.legend(loc="lower right", frameon=False)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("Corredores con 40 buses por hora o más")
fig.tight_layout()
fig.savefig(FIG / "s2_mapa_corredores.png", dpi=150)

# ----------------------------------------------------------------------------- s3 escenario 1
def vel(carpeta):
    v = pd.read_csv(BUSES / carpeta / "velocidad_lineas.csv", index_col=0)
    return v[(v.linename != "RUTA TRANVIA") & ~v.sospechosa]


fig, axs = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
for ax, (d, tit) in zip(axs, [("equilibrio", "Tráfico fluido"), ("calibrada", "Hora pico (autos calibrados)")]):
    a, b = vel(f"{d}_bahia_reruteo"), vel(f"{d}_contrato_bahia_reruteo")
    t = a[["kmh_sim"]].join(b[["kmh_sim"]], rsuffix="_c", how="inner")
    ax.scatter(t.kmh_sim, t.kmh_sim_c, s=20, color="#2F6FC0")
    m = max(t.max().max(), 1) * 1.05
    ax.plot([0, m], [0, m], color="grey", lw=1, ls="--")
    ax.set_title(f"{tit}\nmediana: {a.kmh_sim.median():.1f} → {b.kmh_sim.median():.1f} km/h")
    ax.set_xlabel("velocidad del bus con frecuencias actuales (km/h)")
axs[0].set_ylabel("velocidad con frecuencias del contrato (km/h)")
fig.suptitle("Escenario 1: cada punto es una línea en un sentido (bajo la diagonal = más lenta con el contrato)")
fig.tight_layout()
fig.savefig(FIG / "s3_escenario1_velocidades.png", dpi=150)

# ----------------------------------------------------------------------------- s4 escenario 2
f2 = BUSES / "escenario2_carril_bus.csv"
if f2.exists():
    e2 = pd.read_csv(f2)
    x = e2[(e2.demanda == "calibrada") & (e2.ahorro_max_min > 0.5)].copy()
    x["etiqueta"] = "L" + x.linea.astype(str) + " " + x.sentido
    x = x.sort_values("ahorro_max_min")
    fig, ax = plt.subplots(figsize=(8, max(3, .28 * len(x))))
    ax.barh(x.etiqueta, x.ahorro_max_min, color="#F2C4BE", label="máximo (desaparece toda la demora)")
    ax.barh(x.etiqueta, x.ahorro_min_min, color="#C0392B", label="mínimo (desaparece la espera en cola)")
    ax.set_xlabel("minutos ahorrados por viaje en hora pico")
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Escenario 2: ahorro de tiempo por línea con carril exclusivo")
    fig.tight_layout()
    fig.savefig(FIG / "s4_escenario2_ahorro.png", dpi=150)
print("figuras en", FIG)
