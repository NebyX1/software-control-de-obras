param(
    [string]$OutputDir = ''
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if ([string]::IsNullOrEmpty($OutputDir)) { $OutputDir = Join-Path $root 'backups' }

$files = @('-f', 'docker-compose.yml', '-f', 'docker-compose.local.yml')
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dir = Join-Path $OutputDir $stamp
New-Item -ItemType Directory -Force -Path $dir | Out-Null

# El volcado se genera dentro del contenedor: las credenciales no salen a la línea de comandos del host.
docker compose @files exec -T db sh -c 'mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" --single-transaction --routines --triggers "$MARIADB_DATABASE" > /tmp/cc-backup.sql'
if ($LASTEXITCODE -ne 0) { Write-Error 'Falló el volcado de la base de datos.'; exit 1 }
docker compose @files cp 'db:/tmp/cc-backup.sql' (Join-Path $dir 'database.sql')
docker compose @files exec -T db sh -c 'rm -f /tmp/cc-backup.sql'
if ($LASTEXITCODE -ne 0) { Write-Error 'No se pudo copiar el volcado.'; exit 1 }

# Documentos subidos (volumen compra-clara_documents).
docker run --rm -v 'compra-clara_documents:/src:ro' -v "${dir}:/dst" --entrypoint sh compra-clara-backend:local -c 'tar czf /dst/documents.tgz -C /src .'
if ($LASTEXITCODE -ne 0) { Write-Error 'Falló el respaldo de documentos.'; exit 1 }

Write-Output "Respaldo creado en: $dir"
Write-Output '  database.sql   (volcado MariaDB)'
Write-Output '  documents.tgz  (archivos subidos)'
Write-Output 'Las contraseñas no se guardan en el respaldo. Guardá .env por separado y en un lugar seguro.'
