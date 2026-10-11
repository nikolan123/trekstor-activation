[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Serial,

    [switch]$Reboot,

    [switch]$NoLaunchSetup
)

# This script is repository-wide and can be run from any working directory.
$ErrorActionPreference = "Stop"

$vendorPackage = "com.taphier.customizer"
$vendorActivity = "$vendorPackage/$vendorPackage.WaitForCustomizerActivity"
$nikoPackage = "de.readerportal.nikowashere"

function Invoke-Adb {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [switch]$AllowFailure
    )

    $output = & adb -s $script:Serial @Arguments 2>&1
    $exitCode = $LASTEXITCODE

    if ($output) {
        $output | Write-Host
    }

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "adb failed with exit code ${exitCode}: adb -s $script:Serial $($Arguments -join ' ')"
    }

    return $output
}

function Invoke-RootShell {
    param(
        [Parameter(Mandatory)]
        [string]$Command,

        [switch]$AllowFailure
    )

    return Invoke-Adb -Arguments @("shell", "su", "-c", $Command) -AllowFailure:$AllowFailure
}

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    throw "adb was not found in PATH."
}

if (-not $Serial) {
    $connected = @(
        & adb devices |
            Select-Object -Skip 1 |
            Where-Object { $_ -match '^([^\s]+)\s+device\s*$' } |
            ForEach-Object { $Matches[1] }
    )

    if ($connected.Count -eq 0) {
        throw "No authorized ADB device is connected."
    }

    if ($connected.Count -gt 1) {
        throw "More than one ADB device is connected. Run again with -Serial <serial>."
    }

    $Serial = $connected[0]
}

$script:Serial = $Serial

$state = (& adb -s $Serial get-state 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $state -ne "device") {
    throw "ADB device '$Serial' is not ready (state: '$state')."
}

$model = (Invoke-Adb -Arguments @("shell", "getprop", "ro.product.model") | Out-String).Trim()
$vendorPath = (Invoke-Adb -Arguments @("shell", "pm", "path", $vendorPackage) | Out-String).Trim()
$rootIdentity = (Invoke-RootShell -Command "id" | Out-String).Trim()

if (-not $vendorPath.StartsWith("package:")) {
    throw "'$vendorPackage' is not installed; refusing to treat this as a TrekStor customizer tablet."
}

if ($rootIdentity -notmatch 'uid=0\(root\)') {
    throw "Root access through 'su -c' is required."
}

$target = "$model ($Serial)"
Write-Host "Target: $target"

if (-not $PSCmdlet.ShouldProcess(
    $target,
    "remove Niko Was Here, delete the downloaded manual, restore the firmware wallpaper, and reset vendor setup"
)) {
    return
}

Write-Host "`n[1/5] Stopping vendor customization..."
Invoke-RootShell -Command "am force-stop $vendorPackage" | Out-Null

Write-Host "[2/5] Uninstalling Niko Was Here..."
$nikoPath = (Invoke-Adb -Arguments @("shell", "pm", "path", $nikoPackage) -AllowFailure | Out-String).Trim()
if ($nikoPath.StartsWith("package:")) {
    Invoke-RootShell -Command "pm uninstall $nikoPackage" | Out-Null
} else {
    Write-Host "Not installed; nothing to remove."
}

Write-Host "[3/5] Deleting downloaded manual files..."
# Send one escaped command directly to Android's shell. Passing paths with
# spaces through an additional `su -c` layer splits "User Manual.pdf" on this
# old su implementation.
Invoke-Adb -Arguments @(
    "shell",
    "rm -f /sdcard/User\ Manual.pdf /sdcard/manual.pdf /sdcard/Download/User\ Manual.pdf /sdcard/Download/manual.pdf"
) | Out-Null

Write-Host "[4/5] Restoring the firmware wallpaper..."
# Keep one recoverable copy of a custom static wallpaper when one exists.
$wallpaperBackupCreated = $false
$wallpaperListing = (& adb -s $Serial shell su -c "ls /data/system/users/0/wallpaper" 2>$null | Out-String).Trim()
if ($wallpaperListing -eq "/data/system/users/0/wallpaper") {
    Invoke-RootShell -Command "cp -f /data/system/users/0/wallpaper /sdcard/wallpaper-before-reset" | Out-Null
    $wallpaperBackupCreated = $true
}

$wallpaperInfoListing = (& adb -s $Serial shell su -c "ls /data/system/users/0/wallpaper_info.xml" 2>$null | Out-String).Trim()
if ($wallpaperInfoListing -eq "/data/system/users/0/wallpaper_info.xml") {
    Invoke-RootShell -Command "cp -f /data/system/users/0/wallpaper_info.xml /sdcard/wallpaper_info-before-reset.xml" | Out-Null
}

Invoke-RootShell -Command "rm -f /data/system/users/0/wallpaper /data/system/users/0/wallpaper_info.xml" | Out-Null

Write-Host "[5/5] Resetting TrekStor vendor setup..."
Invoke-RootShell -Command "pm clear $vendorPackage" | Out-Null
Invoke-RootShell -Command "pm enable $vendorActivity" | Out-Null
Invoke-RootShell -Command "settings put global device_provisioned 0" | Out-Null
Invoke-RootShell -Command "settings put secure user_setup_complete 0" | Out-Null

if ($Reboot) {
    Write-Host "Rebooting to reload the firmware wallpaper..."
    Invoke-Adb -Arguments @("reboot") | Out-Null

    Write-Host "Waiting for ADB..."
    & adb -s $Serial wait-for-device
    if ($LASTEXITCODE -ne 0) {
        throw "The tablet did not return to ADB after reboot."
    }

    $deadline = (Get-Date).AddSeconds(90)
    do {
        $bootCompleted = (& adb -s $Serial shell getprop sys.boot_completed 2>$null | Out-String).Trim()
        if ($bootCompleted -eq "1") {
            break
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    if ($bootCompleted -ne "1") {
        throw "ADB returned, but Android did not finish booting within 90 seconds."
    }
} else {
    Write-Host "Skipping reboot"
}

if (-not $NoLaunchSetup) {
    Invoke-Adb -Arguments @(
        "shell", "su", "-c",
        "am start -a android.intent.action.MAIN -c android.intent.category.HOME -n $vendorActivity"
    ) | Out-Null
}

$deviceProvisioned = (Invoke-Adb -Arguments @("shell", "settings", "get", "global", "device_provisioned") | Out-String).Trim()
$userSetupComplete = (Invoke-Adb -Arguments @("shell", "settings", "get", "secure", "user_setup_complete") | Out-String).Trim()

Write-Host "`nReset complete."
Write-Host "device_provisioned=$deviceProvisioned"
Write-Host "user_setup_complete=$userSetupComplete"
if (-not $NoLaunchSetup) {
    Write-Host "Vendor setup launched."
} elseif ($Reboot) {
    Write-Host "Vendor setup may launch automatically during boot."
} else {
    Write-Host "Vendor setup is reset but was not launched."
}
if ($wallpaperBackupCreated) {
    Write-Host "Previous wallpaper backup: /sdcard/wallpaper-before-reset"
}
