@echo off
echo Deploying to NAS...
robocopy "D:\Claude Code\prepis_vozidla_app\prepis_app\dist\PrepisVozidla" "\\192.168.1.18\Petr\PrepisVozidla" /E /IS /IT
echo.
echo Copying .env...
copy /Y "D:\Claude Code\prepis_vozidla_app\prepis_app\.env" "\\192.168.1.18\Petr\PrepisVozidla\_internal\.env"
echo.
echo Verifying VERSION on NAS:
type "\\192.168.1.18\Petr\PrepisVozidla\_internal\VERSION"
echo.
echo Done.
pause
