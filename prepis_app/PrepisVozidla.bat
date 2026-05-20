@echo off
set LOCAL=%TEMP%\PrepisVozidla
set NAS=%~dp0

robocopy "%NAS%_internal" "%LOCAL%\_internal" /E /NFL /NDL /NJH /NJS /NP >nul 2>&1
copy /Y "%NAS%PrepisVozidla.exe" "%LOCAL%\PrepisVozidla.exe" >nul 2>&1

start "" "%LOCAL%\PrepisVozidla.exe"
