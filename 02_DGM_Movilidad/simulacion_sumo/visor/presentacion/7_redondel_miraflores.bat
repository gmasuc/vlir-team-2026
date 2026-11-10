@echo off
rem Redondel Miraflores: Av. de las Americas y Del Silban (uno de los puntos mas lentos del bus)
rem Situacion actual, modelo calibrado. Avanza solo hasta las 7:30 y se detiene. Luego subir Delay (p. ej. 50) y pulsar Play.
cd /d "%~dp0.."
start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c actual_calibrado.sumocfg --gui-settings-file presentacion\vista_7_redondel_miraflores.xml --breakpoints 27000 --start

