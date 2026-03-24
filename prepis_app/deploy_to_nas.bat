@echo off
echo Deploying to NAS...

set NAS=\\192.168.1.18\Petr\PrepisVozidla

REM Copy exe and _internal only — never touch data\ (firmy.xlsx, plne_moce, scans)
powershell -Command "Copy-Item -Path 'dist\PrepisVozidla\PrepisVozidla.exe' -Destination '%NAS%\PrepisVozidla.exe' -Force"
powershell -Command "Copy-Item -Path 'dist\PrepisVozidla\_internal\*' -Destination '%NAS%\_internal\' -Recurse -Force"
powershell -Command "Copy-Item -Path '.env' -Destination '%NAS%\_internal\.env' -Force"

echo Done.
pause
