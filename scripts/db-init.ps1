<#
.SYNOPSIS
    Create the development roles/databases and apply migrations.

.DESCRIPTION
    Idempotent. Requires scripts/db-start.ps1 to have been run.
    After this completes the API can connect with the DATABASE_URL in .env.
#>
param(
    [int]$Port = 5433
)

$ErrorActionPreference = "Stop"

$root = Split-Path $PSScriptRoot -Parent
$pgBin = "C:\Program Files\PostgreSQL\17\bin"
$psql = "$pgBin\psql.exe"

& "$PSScriptRoot\db-start.ps1" -Port $Port

Write-Host "Creating runtime role"
& $psql -h 127.0.0.1 -p $Port -U zain -d postgres -v ON_ERROR_STOP=1 `
    -f (Join-Path $root "infrastructure\db\init-roles.sql") | Out-Null

foreach ($db in @("zain_agri", "zain_agri_test")) {
    $exists = & $psql -h 127.0.0.1 -p $Port -U zain -d postgres -tAc `
        "SELECT 1 FROM pg_database WHERE datname = '$db'"
    if ($exists -ne "1") {
        Write-Host "Creating database $db"
        & "$pgBin\createdb.exe" -h 127.0.0.1 -p $Port -U zain $db
    }
}

Write-Host "Applying migrations"
Push-Location (Join-Path $root "apps\api")
try {
    & uv run alembic upgrade head
} finally {
    Pop-Location
}

foreach ($db in @("zain_agri", "zain_agri_test")) {
    Write-Host "Granting runtime privileges on $db"
    & $psql -h 127.0.0.1 -p $Port -U zain -d $db -v ON_ERROR_STOP=1 `
        -f (Join-Path $root "infrastructure\db\grants.sql") | Out-Null
}

Write-Host "Database ready."
