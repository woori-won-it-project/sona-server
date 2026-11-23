# dumps/sona.dump -> Local DB (docker postgres)
# Usage (repo root): .\scripts\db-restore.ps1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$ComposeFile = Join-Path $Root 'infra/docker-compose.yml'
$DumpFile = Join-Path $Root 'dumps/sona.dump'

if (-not (Test-Path $EnvFile)) { throw '.env not found. Copy .env.example to .env first.' }
if (-not (Test-Path $DumpFile)) { throw "Dump file not found: $DumpFile" }
$EnvVars = @{}
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $EnvVars[$Matches[1]] = $Matches[2].Trim() }
}
$Db = if ($EnvVars['POSTGRES_DB']) { $EnvVars['POSTGRES_DB'] } else { 'sona' }
$User = if ($EnvVars['POSTGRES_USER']) { $EnvVars['POSTGRES_USER'] } else { 'sona' }

$Container = docker compose -f $ComposeFile --env-file $EnvFile ps -q postgres
if (-not $Container) { throw 'postgres container is not running. Run docker compose up -d first.' }

docker cp $DumpFile "${Container}:/tmp/sona.dump"
if ($LASTEXITCODE -ne 0) { throw 'docker cp failed.' }

docker exec $Container pg_restore -U $User -d $Db --clean --if-exists --no-owner /tmp/sona.dump
$RestoreExit = $LASTEXITCODE
docker exec $Container rm -f /tmp/sona.dump
if ($RestoreExit -ne 0) { throw "pg_restore failed (exit $RestoreExit)." }

Write-Host "Restored $DumpFile into database '$Db'."
