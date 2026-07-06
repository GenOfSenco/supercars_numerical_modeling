@echo off
echo Aerogen v2 — Diffuser Design Lab
cd /d "%~dp0"
python -m aerogen
if errorlevel 1 (
    echo [ERROR] Failed to start. Install: pip install numpy scipy gmsh
    pause
)
