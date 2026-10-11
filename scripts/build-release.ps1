[CmdletBinding()]
param(
    [switch]$Docker,
    [string]$Image = "trekstore:latest"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $repositoryRoot "dist"
$bundleRoot = Join-Path $distRoot "trekstore-server"
$bundleZip = Join-Path $distRoot "trekstore-server.zip"
$appBuildScript = Join-Path $repositoryRoot "nikowashere_src\build.ps1"
$pdfScript = Join-Path $repositoryRoot "nikowashere_pdf\md2pdf.py"
$serverRoot = Join-Path $repositoryRoot "server"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found in PATH. Install uv and try again."
}

Write-Host "[1/4] Building Niko Was Here APK..."
& $appBuildScript

Write-Host "[2/4] Building manual PDF..."
& uv run $pdfScript
if ($LASTEXITCODE -ne 0) {
    throw "PDF build failed with exit code $LASTEXITCODE"
}

Write-Host "[3/4] Building tablet customization package..."
Push-Location $repositoryRoot
try {
    & uv run python -c "from server.main import build_custom_zip; build_custom_zip()"
    if ($LASTEXITCODE -ne 0) {
        throw "Package build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

$requiredArtifacts = @(
    (Join-Path $serverRoot "assets\apps\niko-was-here.apk"),
    (Join-Path $serverRoot "assets\manual.pdf"),
    (Join-Path $serverRoot "custom.zip")
)

foreach ($artifact in $requiredArtifacts) {
    if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
        throw "Expected build artifact was not created: $artifact"
    }
}

Write-Host "[4/4] Creating deployable server bundle..."
New-Item -ItemType Directory -Force -Path $distRoot | Out-Null

$expectedBundleRoot = [IO.Path]::GetFullPath((Join-Path $distRoot "trekstore-server"))
if ([IO.Path]::GetFullPath($bundleRoot) -ne $expectedBundleRoot) {
    throw "Unexpected bundle path: $bundleRoot"
}
if (Test-Path -LiteralPath $bundleRoot) {
    [IO.Directory]::Delete($bundleRoot, $true)
}

New-Item -ItemType Directory -Path $bundleRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $repositoryRoot "Dockerfile.runtime") -Destination (Join-Path $bundleRoot "Dockerfile")
Copy-Item -LiteralPath (Join-Path $repositoryRoot "pyproject.toml") -Destination $bundleRoot
Copy-Item -LiteralPath (Join-Path $repositoryRoot "uv.lock") -Destination $bundleRoot
Copy-Item -LiteralPath $serverRoot -Destination $bundleRoot -Recurse

Get-ChildItem -LiteralPath $bundleRoot -Recurse -Force -Directory |
    Where-Object Name -eq "__pycache__" |
    Sort-Object FullName -Descending |
    ForEach-Object { [IO.Directory]::Delete($_.FullName, $true) }

$bundledData = Join-Path $bundleRoot "server\data"
if (Test-Path -LiteralPath $bundledData) {
    [IO.Directory]::Delete($bundledData, $true)
}

Compress-Archive -Path (Join-Path $bundleRoot "*") -DestinationPath $bundleZip -Force

$hash = (Get-FileHash -LiteralPath $bundleZip -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Bundle: $bundleZip"
Write-Host "SHA256: $hash"

if ($Docker) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker was requested but the docker command was not found."
    }

    Write-Host "Building Docker image: $Image"
    & docker build --tag $Image $repositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed with exit code $LASTEXITCODE"
    }
    Write-Host "Image:  $Image"
}
