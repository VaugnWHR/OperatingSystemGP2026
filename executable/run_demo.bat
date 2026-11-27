@echo off
cd /d "%~dp0"
echo === RCOS demo 1: basic scenario (report only) ===
rcos_simulator.exe --quiet
echo.
echo === RCOS demo 2: CPU scheduler comparison ===
rcos_simulator.exe --compare-schedulers
echo.
echo === RCOS demo 3: memory fragmentation fixed by compaction ===
rcos_simulator.exe --scenario fragmentation --compact --quiet
echo.
pause
