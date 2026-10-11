$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$repositoryRoot = Split-Path -Parent $projectRoot
$outputApk = Join-Path $projectRoot "app\build\outputs\apk\debug\app-debug.apk"
$bundledApk = Join-Path $repositoryRoot "server\assets\apps\niko-was-here.apk"

$androidSdk = if ($env:ANDROID_HOME) {
    $env:ANDROID_HOME
} else {
    Join-Path $env:LOCALAPPDATA "Android\Sdk"
}

$androidStudioJdk = "C:\Program Files\Android\Android Studio\jbr"
if (-not $env:JAVA_HOME -and (Test-Path -LiteralPath $androidStudioJdk)) {
    $env:JAVA_HOME = $androidStudioJdk
}

if (-not (Test-Path -LiteralPath $androidSdk)) {
    throw "Android SDK not found at $androidSdk"
}

if (-not $env:JAVA_HOME -or -not (Test-Path -LiteralPath $env:JAVA_HOME)) {
    throw "A JDK 17 or newer is required. Set JAVA_HOME and try again."
}

$env:ANDROID_HOME = $androidSdk
$env:ANDROID_SDK_ROOT = $androidSdk

Push-Location $projectRoot
try {
    & ".\gradlew.bat" --no-daemon assembleDebug
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $bundledApk) | Out-Null
Copy-Item -LiteralPath $outputApk -Destination $bundledApk -Force

Write-Host "Built:   $outputApk"
Write-Host "Bundled: $bundledApk"
