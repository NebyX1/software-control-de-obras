# Resultados de verificación

Fecha de la verificación: sesión de desarrollo local en Docker Desktop (Windows). Todo lo listado como "verificado" se ejecutó en esta máquina.

## Verificado localmente

| Área | Prueba | Resultado |
|---|---|---|
| Backend | `pytest -q` (incluye regresión de luminarias, flujo de caso, autorización, 409 de versión, semillas demo) | 83 de 83 OK (~80 s) |
| Frontend | `npm run typecheck` y `npm run build` | OK. Bundle de aplicación ~184 KB y React ~232 KB |
| Stack | `Start-Stack.ps1` (idempotente) y `Test-Stack.ps1` | db, migrate, backend, worker y web en estado correcto; `/healthz`, `/api/v1/health/live`, `/api/v1/health/ready` y ruta SPA profunda responden 200 |
| Persistencia | `docker compose restart` de db, backend, worker y web | 12 usuarios y 5 expedientes conservados; stack OK tras reinicio |
| Respaldo | `Backup-Stack.ps1` | `database.sql` (~157 KB) y `documents.tgz` generados |
| Restauración | `Restore-Stack.ps1 -TargetDatabase cc_restore_check` | 66 tablas; conteos iguales a la base activa (12 usuarios, 5 expedientes, 51 auditorías, 8 proveedores). Base de prueba eliminada |
| API de autenticación | challenge con captcha, login, 2FA por correo, `me`, logout | OK. `me` devuelve 401 tras cerrar sesión |
| Interfaz (navegador) | login con captcha y 2FA, dashboard, `/administracion`, `/preferencias`, `/auditoria`, `/reglas` | Renderizan; sin errores de JavaScript observados en la sesión |
| Permisos | rol `administrador` en `/compras` y `/evaluar` | Acceso denegado correctamente |
| Seguridad (básica) | búsqueda de valores de `.env` en `frontend/dist` y en logs de contenedores | 0 coincidencias |
| Evaluación | regresión de luminarias en `test_engine.py` y `test_workflow.py` | Serrana 95,18; Luz del Este 86,00; Faro excluido; precio de referencia 1.704.000; en modo mínimo+precio gana Luz del Este |

## Pendiente o no cubierto

- **Flujo completo de expediente en navegador** (crear solicitud, ofertas, evaluación, adjudicación): no ejecutado de extremo a extremo. El rol administrador no puede crear expedientes por diseño.
- **Pruebas de seguridad específicas**: XSS en campos de texto, inyección CSV en la exportación de auditoría, validación de subida de archivos. No se ejecutaron pruebas dirigidas.
- **IA en vivo**: bloqueada (sin clave y modelo retirado). Ver [IA.md](IA.md).
- **Restauración de documentos** (`-RestoreDocuments`): no probada con archivos reales, porque el volumen de documentos estaba vacío.
- **Despliegue remoto en Coolify**: no realizado. Ver [DESPLIEGUE_COOLIFY.md](DESPLIEGUE_COOLIFY.md).

## Notas de higiene

- `backend/tests/conftest.py` contiene una credencial de base de datos **solo de prueba**. Debe reemplazarse por una variable de entorno antes de compartir el repositorio.
- La cuenta de prueba `adminlocal` tiene una contraseña aleatoria no registrada. Para volver a entrar, crear otro administrador con `create-admin`.
