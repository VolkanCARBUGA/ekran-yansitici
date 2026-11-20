# ==============================================================================
# Ekran Yansitici - Windows oturum acilisinda otomatik baslatma kurulumu
#   * app\ klasorunu %LOCALAPPDATA%\EkranYansitici altina kopyalar
#   * Sanal ortam (venv) olusturup bagimliliklari kurar
#   * Baslangic (Startup) klasorune gizli calisan bir .vbs baslatici koyar
#     (sunucu coker/kapanirsa 3 sn sonra yeniden baslatilir)
# Kaldirmak icin: OTOMATIK_BASLATMA_KUR.bat --kaldir
# Not: Dosya bilerek ASCII tutuldu (Windows PowerShell 5.1 BOM'suz UTF-8'i bozuk okur).
# ==============================================================================
param([switch]$Kaldir)
$ErrorActionPreference = 'Stop'

$Src        = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:LOCALAPPDATA 'EkranYansitici'
$LogDir     = Join-Path $InstallDir 'logs'
$Vbs        = Join-Path ([Environment]::GetFolderPath('Startup')) 'EkranYansitici.vbs'

function Stop-Server {
    Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and
        ($_.CommandLine -like "*$InstallDir*" -or $_.CommandLine -like '*EkranYansitici.vbs*')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Find-Python {
    $candidates = @(
        @{ Exe = 'py';      Args = @('-3') },
        @{ Exe = 'python';  Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $ok = & $c.Exe @($c.Args + @('-c', 'import sys; print(sys.version_info[:2] >= (3, 10))')) 2>$null
            if ($ok -eq 'True') { return $c }
        } catch {}
    }
    return $null
}

Stop-Server
Start-Sleep -Milliseconds 500

if ($Kaldir) {
    Remove-Item $Vbs -Force -ErrorAction SilentlyContinue
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'Otomatik baslatma kaldirildi.'
    exit 0
}

$py = Find-Python
if (-not $py) {
    Write-Host 'HATA: Python 3.10+ bulunamadi. https://www.python.org/downloads/ adresinden kurun'
    Write-Host '      (kurulumda "Add python.exe to PATH" kutusunu isaretleyin).'
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir, $LogDir | Out-Null
robocopy $Src $InstallDir /MIR /XD venv __pycache__ logs /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Dosya kopyalama basarisiz (robocopy kodu $LASTEXITCODE)" }

$VenvPy = Join-Path $InstallDir 'venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    Write-Host 'Sanal ortam olusturuluyor...'
    & $py.Exe @($py.Args + @('-m', 'venv', (Join-Path $InstallDir 'venv')))
}
& $VenvPy -m pip install -q --disable-pip-version-check -r (Join-Path $InstallDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Bagimliliklar kurulamadi (pip install).' }

$ServerPy = Join-Path $InstallDir 'server.py'
$Log      = Join-Path $LogDir 'server.log'
$vbsContent = @"
' Ekran Yansitici - gizli baslatici (coker/kapanirsa 3 sn sonra yeniden baslatir)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "$InstallDir"
Do
    sh.Run "cmd /c """"$VenvPy"" ""$ServerPy"" > ""$Log"" 2>&1""", 0, True
    WScript.Sleep 3000
Loop
"@
# UTF-16 (BOM'lu): kullanici adinda Turkce karakter olsa da WSH dogru okur
Set-Content -Path $Vbs -Value $vbsContent -Encoding Unicode

Start-Process wscript.exe -ArgumentList "`"$Vbs`""
Start-Sleep -Seconds 4

Write-Host '=========================================================='
Write-Host 'OTOMATIK BASLATMA KURULDU VE SU AN AKTIF!'
Write-Host '----------------------------------------------------------'
Write-Host "Kurulum dizini : $InstallDir"
Write-Host "Baslatici      : $Vbs"
Write-Host "Log            : $Log"
Write-Host '=========================================================='
if (Test-Path $Log) { Get-Content $Log -Tail 12 }
