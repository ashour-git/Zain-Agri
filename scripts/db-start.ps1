<#
.SYNOPSIS
    Start the local ZAIN AGRI PostgreSQL cluster (no Docker, no admin rights).

.DESCRIPTION
    Uses the installed PostgreSQL 17 binaries but a separate data directory
    under %LOCALAPPDATA%\zain-agri\pgdata on port 5433, so it never touches an
    existing PostgreSQL installation or its data.
#>
param(
    [int]$Port = 5433
)

$ErrorActionPreference = "Stop"

$pgBin = "C:\Program Files\PostgreSQL\17\bin"
$dataDir = Join-Path $env:LOCALAPPDATA "zain-agri\pgdata"

if (-not (Test-Path "$pgBin\postgres.exe")) {
    throw "PostgreSQL 17 not found at $pgBin"
}

if (-not (Test-Path "$dataDir\PG_VERSION")) {
    Write-Host "Initializing cluster at $dataDir"
    New-Item -ItemType Directory -Force -Path (Split-Path $dataDir) | Out-Null
    & "$pgBin\initdb.exe" -D $dataDir -U zain --auth=trust --encoding=UTF8 --locale=C | Out-Null
    Add-Content -Path "$dataDir\postgresql.conf" -Value @"

# zain-agri development settings
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_min_messages = warning
"@
}

function Test-Port {
    param([int]$P)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        return $client.ConnectAsync("127.0.0.1", $P).Wait(1000)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (Test-Port -P $Port) {
    Write-Host "PostgreSQL already listening on port $Port"
    return
}

Write-Host "Starting PostgreSQL on port $Port"
Start-Process -FilePath "$pgBin\postgres.exe" `
    -ArgumentList @("-D", "`"$dataDir`"", "-p", "$Port") `
    -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Port -P $Port) {
        Write-Host "Ready on 127.0.0.1:$Port (data: $dataDir)"
        return
    }
}

throw "PostgreSQL did not become ready. See $dataDir\log"
