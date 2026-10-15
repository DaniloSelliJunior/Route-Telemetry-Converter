@echo off
REM Gera RouteTelemetryConverter.exe (pasta dist\)
pip install -r requirements.txt
flet pack app.py --name RouteTelemetryConverter ^
  --add-data "motec_lib;motec_lib" ^
  --add-data "assets;assets" ^
  --pyinstaller-build-args="--paths=motec_lib" ^
  --pyinstaller-build-args="--hidden-import=data_log" ^
  --pyinstaller-build-args="--hidden-import=motec_log" ^
  --pyinstaller-build-args="--hidden-import=ldparser.ldparser"
echo Pronto: dist\RouteTelemetryConverter.exe
