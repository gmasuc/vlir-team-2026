@echo off
rem Abre la situacion actual (semaforos reales) en la zona y la hora que se elijan.
rem La simulacion corre rapido hasta esa hora y se detiene; luego subir Delay (p. ej. 50) y pulsar Play.
rem Horas posibles: de 06:45 a 09:30 (hora pico de autos: 07:00 a 08:00).
cd /d "%~dp0.."
echo.
echo  Zonas: 1 Redondel Jose Peralta    2 Unidad Nacional    3 Terminal Terrestre
echo         4 Parque Calderon           5 Feria Libre        6 Pumapungo
echo         7 Redondel Miraflores       0 ciudad completa
echo.
set /p ZONA=Zona (0-7):
set /p HORA=Hora a ver, formato HH:MM (por ejemplo 07:45):
for /f "tokens=1,2 delims=:" %%a in ("%HORA%") do (set HH=%%a& set MM=%%b)
if "%HH:~0,1%"=="0" set HH=%HH:~1%
if "%MM:~0,1%"=="0" set MM=%MM:~1%
set /a SEG=HH*3600+MM*60
if %SEG% LSS 24300 set SEG=24300
if %SEG% GTR 34200 set SEG=34200
set VISTA=vista.xml
for %%f in (presentacion\vista_%ZONA%_*.xml) do set VISTA=%%f
echo Abriendo zona %ZONA%, se detiene a las %HORA% (segundo %SEG%)...
start "" "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Lib\site-packages\sumo\bin\sumo-gui.exe" -c actual_calibrado.sumocfg --gui-settings-file %VISTA% --breakpoints %SEG% --start
