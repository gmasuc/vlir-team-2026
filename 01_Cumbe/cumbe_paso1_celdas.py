# Ejecucion paso a paso en VS Code (Run Cell / Shift+Enter)
# Requiere cumbe_paso1_mapa_preliminar.py en la MISMA carpeta.
# Autor: Pedro Luzuriaga Orellana - Universidad de Cuenca

# %% 0. Importar funciones
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from shapely.ops import unary_union

import cumbe_paso1_mapa_preliminar as p

# %% 1. Limite  -> verifica que el poligono sea Cumbe y no un rectangulo
limite = p.obtener_limite()
limite_utm = limite.to_crs(p.CRS_UTM).geometry.iloc[0]
print(limite.geom_type.iloc[0], limite.total_bounds)
limite.plot(edgecolor="black", facecolor="none"); plt.title("Limite"); plt.show()

# %% 2. DEM  -> verifica rango de elevaciones (Cumbe ~2500-3500 m aprox.)
area_dem = limite.to_crs(p.CRS_UTM).buffer(p.BUFFER_M)
bounds_4326 = tuple(area_dem.to_crs("EPSG:4326").total_bounds)
ruta_dem = p.OUT / "dem_utm.tif"
if not ruta_dem.exists() or not p.dem_cubre(ruta_dem, area_dem.total_bounds):
    p.descargar_dem(bounds_4326, ruta_dem)
with rasterio.open(ruta_dem) as d:
    z = d.read(1).astype(float); z[z == d.nodata] = np.nan
    print("Elevacion min/max:", np.nanmin(z), np.nanmax(z), "| resolucion:", d.res)
plt.imshow(z, cmap="terrain"); plt.colorbar(label="m"); plt.title("DEM"); plt.show()

# %% 3. Cauces y cuenca  -> compara con rios conocidos (IGM / Google Earth)
# Si la cuenca no es la del rio Cumbe: p.SALIDA_CUENCA = (lon, lat) y vuelve a ejecutar esta celda
# Si hay demasiados/pocos cauces: cambia p.UMBRAL_CAUCE y vuelve a ejecutar esta celda
cauces, cuenca = p.extraer_hidrologia(ruta_dem, limite_utm)
ax = cauces.plot(lw=0.5, color="tab:blue")
limite.to_crs(p.CRS_UTM).boundary.plot(ax=ax, color="black")
p.gpd.GeoSeries([cuenca], crs=p.CRS_UTM).boundary.plot(ax=ax, color="tab:blue", ls="--")
plt.title("Cauces, parroquia (negro) y cuenca (azul punteado)"); plt.show()

# %% 4. Vias OSM (parroquia + cuenca)  -> revisa tipos y cuantas tienen dato de superficie
area_utm = unary_union([limite_utm, cuenca])
area_4326 = p.gpd.GeoSeries([area_utm], crs=p.CRS_UTM).to_crs("EPSG:4326").iloc[0]
vias = p.obtener_vias(area_4326, area_utm)
print(vias["highway"].value_counts())
for c in ["surface", "tracktype"]:
    if c in vias.columns:
        print(vias[c].value_counts(dropna=False))
vias.plot(); plt.title("Vias OSM"); plt.show()

# %% 5. Tramos de 100 m
tramos = p.segmentar(vias)
print(len(tramos), "tramos |", round(tramos["largo_m"].sum() / 1000, 1), "km")

# %% 6. Pendiente y elevacion  -> pendientes > 30 % suelen ser ruido del DEM
tramos = p.pendiente_y_elevacion(tramos, ruta_dem)
print(tramos["pendiente_pct"].describe())
tramos["pendiente_pct"].hist(bins=40); plt.title("Pendiente (%)"); plt.show()

# %% 7. Distancia a cauce y cruces
tramos = p.relacion_cauce(tramos, cauces)
print(tramos["dist_cauce_m"].describe())
print("Tramos que cruzan un cauce:", int(tramos["cruce_cauce"].sum()))

# %% 8. Cobertura y lluvia  -> la lluvia casi no variara entre tramos (pixel ~5 km)
tramos = p.cobertura_y_lluvia(tramos)
print(tramos["cobertura"].value_counts(dropna=False))
print(tramos["lluvia_anual_mm"].describe())

# %% 9. Clasificacion y salidas
tramos = p.clasificar(tramos, limite_utm, cuenca)
print(tramos["posible_lastre"].value_counts())
print(tramos[["en_parroquia", "en_cuenca"]].value_counts())
p.guardar(limite, cuenca, cauces, tramos)
tramos.head(10)
