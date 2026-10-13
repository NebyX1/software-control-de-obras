# Despliegue en Coolify

Estado: **preparado, no desplegado**. No se realizó ningún despliegue remoto. Requiere autorización y validación institucional antes de usarse con datos reales.

## Qué se necesita en Coolify

- Un recurso tipo "Docker Compose" apuntando a este repositorio, con `docker-compose.yml` como archivo principal.
- **No** usar `docker-compose.local.yml` (publica puertos en localhost y solo sirve en Docker Desktop).
- Coolify gestiona el dominio y HTTPS con su proxy. Asignar el dominio público al servicio `web` en el puerto interno `8080`.
- Variables de entorno definidas en Coolify (no subir `.env`). Las obligatorias (sintaxis `:?` en compose) son: `PUBLIC_ORIGIN`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD`, `MARIADB_ROOT_PASSWORD`, `SECRET_KEY`.

## Configuración de producción

| Variable | Valor recomendado | Motivo |
|---|---|---|
| `APP_ENV` | `production` | Desactiva semillas y modos de prueba. |
| `PUBLIC_ORIGIN` | `https://<dominio-institucional>` | Origen usado en enlaces y CORS. |
| `COOKIE_SECURE` | `true` | Cookies solo por HTTPS. |
| `TRUST_PROXY` | `true` | Coolify está delante de la aplicación. |
| `TRUSTED_PROXY_HOPS` | `1` | Un proxy (Coolify). Confirmar con la topología real. |
| `ALLOW_DEMO_SEED` | `false` | Nunca cargar datos ficticios en producción. |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS` | SMTP institucional | Mailpit es solo local. Pendiente de credenciales. |
| `AI_ENABLED` | `false` hasta validar | Ver [IA.md](IA.md). |

Mantener `FLASK_DEBUG=0` y `LOGIN_CAPTCHA=true`.

## Servicios

- `db`: MariaDB 11.4.8 con volumen `db-data`. Sin puertos publicados.
- `migrate`: aplica migraciones Alembic y termina. Los demás servicios esperan a que termine con éxito.
- `backend`: gunicorn en `5006` (interno), healthcheck propio.
- `worker`: procesos en segundo plano (tareas, indexado). Sin healthcheck propio; se verifica como `running`.
- `web`: nginx con la SPA y proxy a `/api`. Expone `8080` (interno).
- `mailpit`: solo perfil `local`. No se despliega en Coolify.

## Almacenamiento

Los documentos se guardan en el volumen `documents` (`DOCUMENT_STORAGE=local`). El adaptador MinIO existe en el código pero **no está conectado** al compose. Antes de producción, decidir si los documentos van a un volumen respaldado o a un almacenamiento de objetos institucional, y validarlo.

## Procedimiento sugerido

1. Crear el recurso en Coolify apuntando al repositorio y a `docker-compose.yml`.
2. Cargar las variables de la tabla anterior. Generar `SECRET_KEY` y contraseñas de base nuevas (no reutilizar las de Docker local).
3. Asignar el dominio al servicio `web`, puerto `8080`.
4. Desplegar. Confirmar que `migrate` termina con código 0 y que `db`, `backend` y `web` quedan `healthy`.
5. Verificar `https://<dominio>/healthz` (200), `/api/v1/health/live` y `/api/v1/health/ready` (200).
6. Crear el primer administrador con el comando de [README](../README.md), ejecutado dentro del contenedor `backend` de Coolify.
7. Configurar respaldos (ver [OPERACION_BACKUP.md](OPERACION_BACKUP.md)) y **probar una restauración** en un entorno separado antes de confiar en ellos.

## Pendientes para validación institucional

- Autorización formal del despliegue remoto.
- Dominio, certificado y política de HTTPS.
- SMTP institucional y remitente válido.
- Red y firewall: restringir acceso a la base y al backend. Los rangos de red reales no están definidos en este repositorio.
- Almacenamiento definitivo de documentos y política de retención.
- Integración de IA: clave, modelo vigente y política de salida de datos ([IA.md](IA.md)).
- Datos reales y migración desde las fuentes institucionales.
