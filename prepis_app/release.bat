@echo off
if "%1"=="" (
    echo Usage: release.bat 1.2.0
    echo This will create a GitHub release tagged v1.2.0
    exit /b 1
)

echo Building with PyInstaller...
pyinstaller prepis_vozidla.spec --noconfirm

echo Creating zip...
cd dist
if exist PrepisVozidla.zip del PrepisVozidla.zip
powershell -Command "Compress-Archive -Path 'PrepisVozidla' -DestinationPath 'PrepisVozidla.zip'"
cd ..

echo Creating GitHub release v%1...
gh release create "v%1" "dist/PrepisVozidla.zip" --title "v%1" --notes "Release v%1"

echo Done! Release v%1 published.
