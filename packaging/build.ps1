# Builds the program and the installer: dist\PTMail-Setup-<version>.exe
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"

Push-Location $root
try {
    $version = & $python -c "import ptmail; print(ptmail.__version__)"
    & $python -m PyInstaller packaging\ptmail.spec --noconfirm --distpath dist --workpath build
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    & $iscc "/DAppVersion=$version" packaging\ptmail.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Write-Output "Gotowe: dist\PTMail-Setup-$version.exe"
}
finally {
    Pop-Location
}
