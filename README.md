# Compra Clara Lavalleja

Sistema de compras públicas por expediente: solicitud, cotizaciones, evaluación, adjudicación, orden de compra, recepción, facturación y pagos, con auditoría y control de roles.

Stack: Flask + SQLAlchemy (backend, gunicorn), worker en segundo plano, MariaDB 11.4, frontend React/Vite servido por nginx, todo orquestado con Docker Compose.

## Estado actual

| Estado | Qué aplica |
|---|---|
| Verificado localmente en Docker Desktop | Stack completo (db, migrate, backend, worker, web, mailpit), login con captcha y 2FA, navegación por rol, 83 pruebas de backend, build del frontend, respaldo y restauración, persistencia tras reinicio. |
| Preparado para Coolify | Dockerfiles, `docker-compose.yml` sin puertos publicados, variables documentadas. Ver [docs/DESPLIEGUE_COOLIFY.md](docs/DESPLIEGUE_COOLIFY.md). |
| Pendiente de validación institucional | Despliegue remoto, SMTP institucional, almacenamiento de documentos definitivo, IA en vivo (ver [docs/IA.md](docs/IA.md)), y datos reales. No se desplegó nada remoto. |

## Requisitos

- Windows con Docker Desktop (Compose v2 o superior).
- PowerShell 5 o superior.
- Puerto `127.0.0.1:8080` libre (se puede cambiar con `LOCAL_HTTP_PORT`).

## Puesta en marcha desde cero

Todos los comandos se ejecutan desde la raíz del repositorio.

```powershell
# 1. Crear .env privado con secretos generados (no se sobrescribe si ya existe)
.\scripts\Initialize-Environment.ps1

# 2. Levantar el stack (agregar -WithMail para Mailpit, el buzón local de pruebas)
.\scripts\Start-Stack.ps1 -WithMail

# 3. Verificar salud de contenedores y rutas públicas
.\scripts\Test-Stack.ps1

# 4. Crear el primer administrador (pide la contraseña sin eco)
docker compose -f docker-compose.yml -f docker-compose.local.yml exec backend flask --app wsgi create-admin --username admin --email admin@example.org --full-name "Administrador"
```

Luego abrir http://localhost:8080 e iniciar sesión. El código 2FA llega por correo: con `-WithMail` se puede leer en http://127.0.0.1:8025 (Mailpit).

`.env` contiene secretos y está excluido de git. No copiarlo a chats, tickets ni logs. `Initialize-Environment.ps1 -Force` regenera todos los secretos y **invalida** la base existente.

## Scripts

| Script | Función |
|---|---|
| `scripts\Initialize-Environment.ps1` | Crea `.env` con secretos aleatorios. |
| `scripts\Start-Stack.ps1 [-WithMail]` | Construye y levanta el stack (`up -d --build`). Idempotente. |
| `scripts\Test-Stack.ps1 [-Port 8080]` | Verifica contenedores y endpoints (`/healthz`, `/api/v1/health/live|ready`, SPA). Sale con 1 si algo falla. |
| `scripts\Run-Tests.ps1 [-SkipBackend] [-SkipFrontend]` | Pruebas de backend (pytest) y build del frontend. |
| `scripts\Backup-Stack.ps1` | Respaldo en `backups\<fecha>\`: volcado MariaDB y archivo de documentos. |
| `scripts\Restore-Stack.ps1` | Restaura un respaldo. Ver [docs/OPERACION_BACKUP.md](docs/OPERACION_BACKUP.md). |

Nunca usar `docker compose down -v`: borra los volúmenes de datos.

## Datos de demostración (opcional, solo local)

Las semillas demo están bloqueadas por defecto (`ALLOW_DEMO_SEED=false`). Para cargarlas en el entorno local, poner `ALLOW_DEMO_SEED=true` en `.env`, reiniciar el backend y ejecutar `flask --app wsgi seed-demo --confirm`. Carga 8 proveedores, 11 usuarios por rol y 5 expedientes parciales (sin ofertas, adjudicación ni adjuntos). Son datos ficticios, no garantías de producción.

## Pruebas

```powershell
.\scripts\Run-Tests.ps1      # backend (83 pruebas) + build frontend
.\scripts\Test-Stack.ps1     # stack en ejecución
```

Resultados y alcance en [docs/RESULTADOS_PRUEBAS.md](docs/RESULTADOS_PRUEBAS.md).

## Documentación

- [docs/PLAN_IMPLEMENTACION.md](docs/PLAN_IMPLEMENTACION.md): estado y bloqueos.
- [docs/MATRIZ_TRAZABILIDAD.md](docs/MATRIZ_TRAZABILIDAD.md): requisitos y evidencia.
- [docs/IA.md](docs/IA.md): integración con Ollama, política de salida de datos y bloqueo actual.
- [docs/DESPLIEGUE_COOLIFY.md](docs/DESPLIEGUE_COOLIFY.md): despliegue en Coolify.
- [docs/OPERACION_BACKUP.md](docs/OPERACION_BACKUP.md): respaldo, restauración y persistencia.
- [docs/RESULTADOS_PRUEBAS.md](docs/RESULTADOS_PRUEBAS.md): evidencia de verificación.
