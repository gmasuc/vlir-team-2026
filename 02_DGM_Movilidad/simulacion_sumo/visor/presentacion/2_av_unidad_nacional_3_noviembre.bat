@echo off
rem Av. Unidad Nacional, 12 de Abril y 3 de Noviembre
rem Situacion actual, modelo calibrado. Avanza solo hasta las 7:30 y se detiene. Luego subir Delay (p. ej. 50) y pulsar Play.
cd /d "%~dp0.."
start "" "C:\Users\pedri\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c actual_calibrado.sumocfg --gui-settings-file presentacion\vista_2_av_unidad_nacional_3_noviembre.xml --breakpoints 27000 --start

