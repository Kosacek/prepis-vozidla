$NAS = "\\192.168.1.18\Petr\PrepisVozidla"

Write-Host "Deploying to NAS..."
Copy-Item -Path "dist\PrepisVozidla\PrepisVozidla.exe" -Destination "$NAS\PrepisVozidla.exe" -Force
Copy-Item -Path "dist\PrepisVozidla\_internal\*" -Destination "$NAS\_internal\" -Recurse -Force
Copy-Item -Path ".env" -Destination "$NAS\_internal\.env" -Force
Copy-Item -Path "VERSION" -Destination "$NAS\_internal\VERSION" -Force
Write-Host "Done."
