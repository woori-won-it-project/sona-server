# Local DB (docker postgres) -> dumps/sona.dump
# Usage (repo root): .\scripts\db-dump.ps1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$ComposeFile = Join-Path $Root 'infra/docker-compose.yml'
$OutFile = Join-Path $Root 'dumps/sona.dump'

if (-not (Test-Path $EnvFile)) { throw '.env not found. Copy .env.example to .env first.' }
$EnvVars = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $EnvVars[$Matches[1]] = $Matches[2].Trim() }
}
$Db = if ($EnvVars['POSTGRES_DB']) { $EnvVars['POSTGRES_DB'] } else { 'sona' }
$User = if ($EnvVars['POSTGRES_USER']) { $EnvVars['POSTGRES_USER'] } else { 'sona' }

$Container = docker compose -f $ComposeFile --env-file $EnvFile ps -q postgres
if (-not $Container) { throw 'postgres container is not running. Run docker compose up -d first.' }

docker exec $Container pg_dump -U $User -d $Db -Fc -f /tmp/sona.dump
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }

New-Item -ItemType Directory -Force (Split-Path -Parent $OutFile) | Out-Null
docker cp "${Container}:/tmp/sona.dump" $OutFile
if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }
docker exec $Container rm -f /tmp/sona.dump

Write-Host "Dump created: $OutFile ($((Get-Item $OutFile).Length) bytes)"
