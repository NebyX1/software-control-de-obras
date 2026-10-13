# Integración de IA (Ollama)

## Estado: deshabilitada y bloqueada

- `AI_ENABLED=false` en `.env`. La aplicación funciona completa sin IA.
- `OLLAMA_API_KEY` está vacía. No se cargó ninguna clave.
- El modelo configurado, `deepseek-v4-flash:cloud`, devolvió **HTTP 410** en una verificación anterior (modelo retirado). Esa respuesta no se volvió a comprobar en esta sesión.
- **No se cambió de modelo en silencio.** Cualquier modelo nuevo debe elegirse explícitamente y anotarse en `OLLAMA_MODEL`.

Sin clave y modelo vigente, la prueba de IA en vivo queda **pendiente**.

## Cómo habilitarla

1. Obtener una clave válida del proveedor y el nombre exacto de un modelo vigente.
2. En `.env`: `OLLAMA_API_KEY=...`, `OLLAMA_MODEL=<modelo exacto>`.
3. Revisar la política de salida (abajo) y confirmar con el responsable de datos.
4. Poner `AI_ENABLED=true` y reiniciar `backend` y `worker`.
5. Verificar en la aplicación con un usuario autorizado: `GET /api/v1/health/ai` (requiere sesión).

## Política de salida de datos

| Variable | Valor por defecto | Significado |
|---|---|---|
| `AI_EGRESS_POLICY` | `minimized` | `off` (nada sale), `metadata_only`, `minimized`, `full_text`. |
| `AI_EGRESS_CLASSES` | `public,internal` | Clasificaciones de documento que pueden salir al proveedor. |
| `AI_MAX_CONTEXT_CHARS` | `24000` | Límite de contexto enviado. |

Los documentos clasificados fuera de `AI_EGRESS_CLASSES` no se envían. Antes de habilitar en producción, confirmar la clasificación de cada tipo de documento y que el proveedor cumple la normativa aplicable.

## Recuperación de normativa

El comando `flask --app wsgi ai-index-normative` indexa las fuentes normativas para el RAG. El embedder por defecto es `fastembed` (modelo `EMBED_MODEL`). `EMBEDDER=hash` existe solo para pruebas unitarias y no debe usarse en producción.

## Lo que ya está verificado

- Con `AI_ENABLED=false` el stack levanta y pasa `Test-Stack.ps1`.
- Las pruebas de backend (83) pasan en esta configuración.
