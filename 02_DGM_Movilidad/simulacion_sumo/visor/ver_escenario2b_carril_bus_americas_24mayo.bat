@echo off
rem Escenario 2b: carril exclusivo de bus solo en la Av. de las Americas y la Av. 24 de Mayo (4.8 km), con semaforos reales
rem Pulsar el boton verde (Play). Rueda del raton = zoom. Autos en amarillo, buses en rojo, tranvia en verde.
cd /d "%~dp0"
start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c escenario2b_carril_bus_americas_24mayo.sumocfg
