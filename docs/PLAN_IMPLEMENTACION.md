# Plan de implementación

Estado al 13/10/2026. Los objetivos corresponden a `Prompt_Codex_Compra_Clara_Produccion.md`.

Leyenda: **Hecho** = implementado y verificado localmente. **Parcial** = implementado, con verificación o alcance incompletos (detallado en la columna Nota). **Pendiente** = no iniciado.

| ID | Objetivo ejecutable | Depende de | Estado | Nota |
|---|---|---|---|---|
| O1 | Inspección de referencias y documentos iniciales (`docs/ANALISIS_REFERENCIAS.md`, matriz, plan) | — | Hecho | |
| O2a | Repositorio: `.gitignore`, `.dockerignore`, `.env.example`, estructura `backend/ frontend/ docs/ scripts/ deploy/` | O1 | Hecho | `deploy/` está vacío; la configuración de despliegue vive en `docker-compose*.yml`. |
| O2b | Backend núcleo: fábrica, config, modelos, migraciones, identidad/permisos, auditoría en cadena, almacenamiento | O2a | Parcial | Migraciones aplicadas en el stack. Almacenamiento: solo local; MinIO no conectado. |
| O4 | Dominio: casos, acciones/estados, pliegos, ofertas/custodia, evaluación, decisión, orden/recepción/facturas/pagos, cierre, ramas | O2b | Parcial | Lógica cubierta por pruebas. Flujo completo de expediente en navegador no ejecutado. Semillas demo parciales. |
| O5 | Motor de evaluación determinista y versionado + reglas/vigencias | O2b | Hecho | Regresión de luminarias verificada (95,18 / 86,00 / excluida / Luz del Este primera en mínimo+precio). La UI no permite crear conjuntos de reglas. |
| O6 | Documentos: validación, versiones, descarga, ingesta persistente | O2b | Parcial | Volumen local persistente y respaldable. Ingesta y custodia de archivos reales sin prueba dirigida. |
| O7 | IA: cliente Ollama, política de envío, RAG autorizado, extracción, consulta normativa, explicación, borradores, SSE | O4, O6 | Parcial | Código presente; deshabilitada. Bloqueada por clave ausente y modelo configurado retirado (HTTP 410). Ver [IA.md](IA.md). |
| O8 | Identidad: login + 2FA, roles, delegaciones, segregación, CSRF, límites | O2b | Hecho | Login con captcha y 2FA verificado en API y navegador. Permisos por rol verificados en la interfaz. Administración de segregación y asignaciones en UI sin prueba completa. |
| O9 | Integraciones: adaptadores con estados explícitos | O4 | Parcial | Estados explícitos implementados; sin contratos oficiales, por lo que no se conectan. |
| O3 | Frontend: layout y pantallas con la identidad visual del HTML | O4 | Hecho | Build y typecheck OK. Pantallas principales renderizan en navegador sin errores de JavaScript. |
| O10 | Docker Desktop/Coolify: imágenes, Compose, proxy, health checks, scripts PowerShell | O7 | Hecho (local) / Preparado (Coolify) | Stack local verificado. Coolify no desplegado. Ver [DESPLIEGUE_COOLIFY.md](DESPLIEGUE_COOLIFY.md). |
| O11 | Pruebas: pytest, Playwright contra proxy real, concurrencia, seguridad, IA, backup/restore, prueba live | O3, O10 | Parcial | Pytest 83/83; Playwright de login y navegación; backup/restore y persistencia verificados. Pendientes: concurrencia, seguridad dirigida, IA en vivo. Ver [RESULTADOS_PRUEBAS.md](RESULTADOS_PRUEBAS.md). |
| O12 | Documentación final y cierre (`README.md`, `docs/*`, `docs/RESULTADOS_PRUEBAS.md`) | O11 | Parcial | README, despliegue, backup, IA y resultados redactados. Falta validación institucional. |

Bloqueos externos conocidos:

- Modelo de Ollama configurado (`deepseek-v4-flash:cloud`) devolvió HTTP 410 (retirado). Sin clave `OLLAMA_API_KEY`.
- Integraciones oficiales (SMTP institucional, almacenamiento definitivo, contratos de datos) sin definir.
- Despliegue remoto en Coolify no autorizado en esta tarea.