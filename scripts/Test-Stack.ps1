param(
    [int]$Port = 8080
)

$ErrorActionPreference = 'Continue'
$base = "http://127.0.0.1:$Port"
$failures = 0

$services = @('db', 'migrate', 'backend', 'worker', 'web')
foreach ($svc in $services) {
    $name = "compra-clara-$svc-1"
    $status = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $name 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Output "[FAIL] contenedor $name no existe"
        $failures++
        continue
    }
    $ok = ($status -eq 'healthy') -or ($status -eq 'running') -or ($status -eq 'exited' -and $svc -eq 'migrate')
    if ($ok) { Write-Output "[ OK ] $name estado=$status" } else { Write-Output "[FAIL] $name estado=$status"; $failures++ }
}

$checks = @(
    @{ Name = 'Web /healthz'; Path = '/healthz' },
    @{ Name = 'API live'; Path = '/api/v1/health/live' },
    @{ Name = 'API ready'; Path = '/api/v1/health/ready' },
    @{ Name = 'SPA (ruta profunda)'; Path = '/compras/SC-2026-0001' }
)
foreach ($check in $checks) {
    try {
        $resp = Invoke-WebRequest -Uri ($base + $check.Path) -UseBasicParsing -TimeoutSec 10
        if ($resp.StatusCode -eq 200) {
            Write-Output "[ OK ] $($check.Name) HTTP 200"
        } else {
            Write-Output "[FAIL] $($check.Name) HTTP $($resp.StatusCode)"
            $failures++
        }
    } catch {
        Write-Output "[FAIL] $($check.Name): $($_.Exception.Message)"
        $failures++
    }
}

if ($failures -gt 0) {
    Write-Output "Verificación con $failures falla(s)."
    exit 1
}
Write-Output 'Verificación de stack: todo OK.'
