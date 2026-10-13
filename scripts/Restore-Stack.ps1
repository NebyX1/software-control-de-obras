param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [string]$TargetDatabase = '',
    [switch]$RestoreDocuments,
    [switch]$Confirm
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$files = @('-f', 'docker-compose.yml', '-f', 'docker-compose.local.yml')
$sqlFile = Join-Path $BackupDir 'database.sql'
if (-not (Test-Path $sqlFile)) { Write-Error "No se encontró $sqlFile"; exit 1 }

# Sin -TargetDatabase se restaura sobre la base activa, y eso exige -Confirm.
$overwriteActive = [string]::IsNullOrEmpty($TargetDatabase)
if ($overwriteActive -and -not $Confirm) {
    Write-Error 'Restaurar sobre la base activa borra los datos actuales. Repetí con -Confirm, o indicá -TargetDatabase para probar en una base separada.'
    exit 1
}

docker compose @files cp $sqlFile 'db:/tmp/cc-restore.sql'
if ($LASTEXITCODE -ne 0) { Write-Error 'No se pudo copiar el volcado al contenedor.'; exit 1 }

if ($overwriteActive) {
    docker compose @files exec -T db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" "$MARIADB_DATABASE" < /tmp/cc-restore.sql'
} else {
    if ($TargetDatabase -notmatch '^[A-Za-z0-9_]+$') { Write-Error 'Nombre de base inválido.'; exit 1 }
    # $TargetDatabase fue validado con regex arriba; el SQL llega por stdin para no pelear con comillas.
    "CREATE DATABASE IF NOT EXISTS $TargetDatabase CHARACTER SET utf8mb4;" | docker compose @files exec -T db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD"'
    if ($LASTEXITCODE -ne 0) { docker compose @files exec -T db sh -c 'rm -f /tmp/cc-restore.sql' | Out-Null; Write-Error 'No se pudo crear la base de destino.'; exit 1 }
    $cmd = 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" ' + $TargetDatabase + ' < /tmp/cc-restore.sql'
    docker compose @files exec -T db sh -c $cmd
}
$restoreExit = $LASTEXITCODE
docker compose @files exec -T db sh -c 'rm -f /tmp/cc-restore.sql'
if ($restoreExit -ne 0) { Write-Error 'Falló la restauración de la base de datos.'; exit 1 }
Write-Output 'Base de datos restaurada.'

if ($RestoreDocuments) {
    if (-not $Confirm) { Write-Error 'Restaurar documentos requiere -Confirm.'; exit 1 }
    $tgz = Join-Path $BackupDir 'documents.tgz'
    if (-not (Test-Path $tgz)) { Write-Error "No se encontró $tgz"; exit 1 }
    docker run --rm -v 'compra-clara_documents:/dst' -v "${BackupDir}:/src:ro" --entrypoint sh compra-clara-backend:local -c 'tar xzf /src/documents.tgz -C /dst'
    if ($LASTEXITCODE -ne 0) { Write-Error 'Falló la restauración de documentos.'; exit 1 }
    Write-Output 'Documentos restaurados.'
}
