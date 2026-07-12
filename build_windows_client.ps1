$Bold       = "$([char]27)[1m"
$BoldReset  = "$([char]27)[22m"

$Red        = "$([char]27)[31m"
$Green      = "$([char]27)[32m"
$Yellow     = "$([char]27)[33m"
$Blue       = "$([char]27)[34m"
$Purple     = "$([char]27)[35m"
$LightBlue  = "$([char]27)[36m"
$White      = "$([char]27)[37m"
$Grey       = "$([char]27)[30m"

Clear-Host
Write-Host ""
Write-Host "${Bold}${White}########## ${Red}Apollo${Grey}Explorer Windows Client - Release 1.5 ${White}###########"
Write-Host ""
Write-Host "${Bold}${White}0. Checking Prerequisites${Grey}${BoldReset}"

# build log artifacts
$ArtifactsPath = Join-Path $PSScriptRoot "artifacts"
New-Item -ItemType Directory -Path $ArtifactsPath -Force | Out-Null
$LogErrorsPath = Join-Path $ArtifactsPath "log_errors.txt"
$LogWarningsPath = Join-Path $ArtifactsPath "log_warnings.txt"
$LogSuccessPath = Join-Path $ArtifactsPath "log_success.txt"

# clear or create build log artifacts
if (Test-Path $LogErrorsPath) {
    Clear-Content -Path $LogErrorsPath -Force
} else {
    New-Item -ItemType File -Path $LogErrorsPath -Force | Out-Null
}
if (Test-Path $LogWarningsPath) {
    Clear-Content -Path $LogWarningsPath -Force
} else {
    New-Item -ItemType File -Path $LogWarningsPath -Force | Out-Null
}
if (Test-Path $LogSuccessPath) {
    Clear-Content -Path $LogSuccessPath -Force
} else {
    New-Item -ItemType File -Path $LogSuccessPath -Force | Out-Null
}

# local installer
$QtInstallerPath = Join-Path $ArtifactsPath "qt-online-installer-windows-x64-online.exe"
$QT6InstallPath = Join-Path $ArtifactsPath "Qt6"
New-Item -ItemType Directory -Path $QT6InstallPath -Force | Out-Null
$QT6CommandPath =  Join-Path $QT6InstallPath "6.11.1\mingw_64\bin"
$env:Path += ";"
$env:Path += $QT6CommandPath
$QT6ToolsPath = Join-Path $QT6InstallPath "Tools\mingw1310_64\bin"
$env:Path += ";"
$env:Path += $QT6ToolsPath

try {
    Get-Command "qmake" -ErrorAction Stop | Out-Null
    Write-Host "* QT6 FrameWork found"
} catch {
    $Answer = Read-Host "* No QT6 FrameWork found, do you want to install QT6? (y/n) "
    $Answer = $Answer.Trim().ToLower()
    if($Answer -eq "n") {exit}
    Write-Host ""
    Write-Host ""
    Write-Host "* Installing QT6 FrameWork (qt6.11.1-essentials-dev) to $QT6InstallPath"
    Invoke-WebRequest "https://download.qt.io/official_releases/online_installers/qt-online-installer-windows-x64-online.exe" -OutFile $QtInstallerPath
    & $QtInstallerPath `
        --root $QT6InstallPath `
        --accept-licenses `
        --accept-obligations `
        --default-answer `
        --confirm-command `
        install qt6.11.1-essentials-dev `
        1>>$LogSuccessPath `
        2>>$LogErrorsPath

    if ($LASTEXITCODE -ne 0) {
        Write-Host "${Bold}${Red}* ERROR Qt installer failed with exit code $LASTEXITCODE${Grey}${BoldReset}"
        Write-Host "${Bold}${Yellow}* Check $LogErrorsPath and $LogSuccessPath for details.${Grey}${BoldReset}"
        exit 1
    }

    try {
        Get-Command "qmake" -ErrorAction Stop | Out-Null
        Write-Host "* QT6 FrameWork successfully installed"

        if (Test-Path $QtInstallerPath) {
            Remove-Item -Force $QtInstallerPath
        }
    } catch {
        Write-Host "${Bold}${Red}* ERROR Installing QT6. qmake was not found after installation.${Grey}${BoldReset}"
        Write-Host "${Bold}${Yellow}* Build cannot continue without qmake, mingw32-make.exe, and windeployqt.exe.${Grey}${BoldReset}"
        Write-Host "${Bold}${Yellow}* Expected Qt install path: $QT6InstallPath${Grey}${BoldReset}"
        exit 1
    }
}

$RequiredCommands = @(
    "qmake",
    "mingw32-make.exe",
    "windeployqt.exe"
)

foreach ($Command in $RequiredCommands) {
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
    } catch {
        Write-Host "${Bold}${Red}* ERROR Missing required command: $Command${Grey}${BoldReset}"
        Write-Host "${Bold}${Yellow}* Check that Qt 6.11.1 MinGW paths are installed and added to PATH.${Grey}${BoldReset}"
        Write-Host "${Bold}${Yellow}* Expected Qt bin path: $QT6CommandPath${Grey}${BoldReset}"
        Write-Host "${Bold}${Yellow}* Expected MinGW tools path: $QT6ToolsPath${Grey}${BoldReset}"
        exit 1
    }
}

Write-Host "${Bold}${White}1. Clean House${Grey}${BoldReset}"
if (Test-Path ".\Makefile") {
    mingw32-make.exe distclean 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
}
Remove-Item -Recurse -Force .\acp\debug\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\acp\release\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\ApolloExplorerPC\debug\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\ApolloExplorerPC\release\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\AmigaIconReader\debug\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\AmigaIconReader\release\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\ApolloExplorer-Windows -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item .\ApolloExplorerPC\ApolloExplorer_resource.rc -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath

Write-Host "${Bold}${White}2. Create Windows Project${Grey}${BoldReset}"
qmake -recursive -config release  1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath

Write-Host "${Bold}${White}3. Make Windows Project${Grey}${BoldReset}"
mingw32-make.exe -j8 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath

$ErrorCheck = Select-String -Path $LogErrorsPath -Pattern "\berror\b"

if ($null -ne $ErrorCheck)
{
    Write-Host "${Bold}${Red}Error(s) found, check $LogErrorsPath${Grey}${BoldReset}"
} else {
    Write-Host "${Bold}${White}4. Install Windows Project${Grey}${BoldReset}"
    mkdir ApolloExplorer-Windows >>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
    Move-Item .\acp\release\acp.exe .\ApolloExplorer-Windows\acp.exe -Force 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
    Move-Item .\ApolloExplorerPC\release\ApolloExplorer.exe .\ApolloExplorer-Windows\ApolloExplorer.exe -Force 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
    windeployqt.exe --release .\ApolloExplorer-Windows\ApolloExplorer.exe 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
}

Write-Host "${Bold}${White}5. Clean Windows Project${Grey}${BoldReset}"
Remove-Item -Recurse -Force .\acp\debug\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\acp\release\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\ApolloExplorerPC\debug\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\ApolloExplorerPC\release\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\AmigaIconReader\debug\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item -Recurse -Force .\AmigaIconReader\release\ -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
Remove-Item .\ApolloExplorerPC\ApolloExplorer_resource.rc -ErrorAction SilentlyContinue 1>>$LogSuccessPath 2>>$LogErrorsPath 3>>$LogWarningsPath
