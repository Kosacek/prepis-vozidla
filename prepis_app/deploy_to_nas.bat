@echo off
echo Deploying to NAS...

set NAS=\\192.168.1.18\Petr\PrepisVozidla

REM Copy exe and _internal only — never touch data\ (firmy.xlsx, plne_moce, scans)
xcopy /Y /Q "dist\PrepisVozidla\PrepisVozidla.exe" "%NAS%\"
xcopy /Y /Q /E "dist\PrepisVozidla\_internal\*" "%NAS%\_internal\"

echo Done.
pause
