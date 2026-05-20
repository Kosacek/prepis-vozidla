@echo off
robocopy "D:\Claude Code\prepis_vozidla_app\prepis_app\dist\PrepisVozidla" "\\192.168.1.18\Petr\PrepisVozidla" /E /IS /IT > "D:\Claude Code\prepis_vozidla_app\prepis_app\deploy_output.txt" 2>&1
copy /Y "D:\Claude Code\prepis_vozidla_app\prepis_app\.env" "\\192.168.1.18\Petr\PrepisVozidla\_internal\.env" >> "D:\Claude Code\prepis_vozidla_app\prepis_app\deploy_output.txt" 2>&1
echo VERSION: >> "D:\Claude Code\prepis_vozidla_app\prepis_app\deploy_output.txt"
type "\\192.168.1.18\Petr\PrepisVozidla\_internal\VERSION" >> "D:\Claude Code\prepis_vozidla_app\prepis_app\deploy_output.txt" 2>&1
