# Análisis de referencias

Fecha del análisis: 13/10/2026. Las carpetas `model/` y `sample/` se leyeron sin modificarlas y sin ejecutar ninguno de sus scripts. Se excluyeron `node_modules`, `.git`, entornos virtuales, cachés de modelos (`sample/rag-chat/.model_cache`), índices generados (`sample/rag-chat/index`) y el contenido de los `.env`.

## 1. Archivos examinados

| Origen | Archivos |
|---|---|
| `model/` | `Compra_Clara_Lavalleja.html` (CSS, datos, JavaScript completos), `Informe_Compras_Lavalleja.pdf` (28 páginas, texto íntegro, tablas, catálogo S01–S50) |
| `sample/backend` | `Dockerfile`, `requirements.lock`, `wsgi.py`, `run.py`, `wait_for_db.py`, `.env.example`, `Instructions.txt`, `app/__init__.py`, `app/config.py`, `app/extensions.py`, `app/shared/{errors,contracts}.py`, `app/infrastructure/{models,storage}.py`, `app/modules/{admin,identity,intake,documents,receipts,catalog}/*`, `app/ai/{provider,routes,document_reader}.py`, `migrations/*` |
| `sample/frontend` | `package.json`, lockfile, `vite.config.ts`, `tsconfig.json`, `Dockerfile`, `nginx.conf`, `.dockerignore`, `index.html`, `src/{main,App,api,types,institutional-theme}.ts(x)`, `src/styles.css`, `playwright.config.ts`, `admin-auth-e2e.mjs`, `a11y-enhanced.mjs` |
| `sample/rag-chat` | `config.py`, `main.py`, `graph.py`, `advisor.py`, `rag.py`, `store.py`, `lexical.py`, `ingest.py`, `tools.py`, `prompt.py`, `requirements.txt` |

## 2. Tecnologías y versiones verificadas

### Frontend (`sample/frontend`)
React 19.2.4, React DOM 19.2.4, TypeScript 5.9.3, Vite 6.4.3 (`@vitejs/plugin-react` 4.7.0), `react-router-dom` 7.18.3 (`BrowserRouter`), `@fluentui/react-components` 9.72.0 (tema `institutional-theme.ts` sobre `webLightTheme`), `@tanstack/react-query` 5.90.21, `axios` 1.20.0, `react-hook-form` 7.71.2, `zustand` 5.0.11, Playwright 1.58.2 + `@axe-core/playwright` 4.11.1. Docker: `node:22.15.1-alpine` para compilar y `nginx:1.27.5-alpine` para servir.

Patrones observados (operación completa pantalla → API → pantalla, “Mis solicitudes / Intake”): cliente axios con `baseURL=/api/v1`, `withCredentials`, token CSRF en `X-CSRF-Token`; `useQuery` para lectura y `useMutation` para escritura; guardado automático con `expected_version`, bloqueo y recuperación ante `409`, `beforeunload` ante cambios sin guardar, `idempotency_key` en el envío, errores `{code,message,fields,request_id}` mostrados con `errorText/errorFields`, foco en `h1` al navegar y enlace “Saltar al contenido”. Todo el código de pantallas está en un único `App.tsx` (≈34 KB): es el antipatrón que el proyecto final no puede copiar.

### Backend (`sample/backend`)
Python 3.11, Flask 3.1.2, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.46, Flask-Migrate 4.1.0 / Alembic 1.19.2, Flask-Login 0.6.3, Flask-Mail 0.10.0, argon2-cffi 25.1.0, PyMySQL 1.1.2 + `mariadb` 1.1.14, MariaDB como motor (`/api/v1/health/ready` responde `database: MariaDB`), MinIO 7.2.20 o volumen privado (`DOCUMENT_STORAGE=minio|local`), pypdf 6.7.5, Pillow 12.1.0, reportlab 4.4.10, pydantic 2.13.5, pydantic-ai-slim 2.40.0 (cliente OpenAI-compatible), waitress 3.0.2 (desarrollo) y gunicorn 24.1.1 (`gthread`, 1 worker × 8 hilos, puerto 5006) en el Dockerfile (`python:3.11.14-slim`).

Arquitectura real y responsabilidades:

| Responsabilidad | Dónde está en el ejemplo |
|---|---|
| Inicialización / fábrica | `app/__init__.py::create_app` (config, ProxyFix opcional con `TRUST_PROXY`, cabeceras de seguridad, `request_id`, manejadores `ApiError/HTTPException/Exception`, health `live/ready`, CLI `reconcile-storage`) |
| Configuración | `app/config.py::settings()` (variables de proceso sobreescriben `backend/.env`) |
| Transporte HTTP | Blueprints por módulo (`modules/intake/routes.py`, `modules/admin/routes.py`, `ai/routes.py`) |
| Servicios | `modules/*/service.py` (reglas, canonical hash, bloqueo de borradores `with_for_update`, `expected_version`) |
| Errores | `shared/errors.py::ApiError/require` con `code,message,fields,status` |
| Persistencia | SQLAlchemy sobre MariaDB, `READ COMMITTED`, migraciones Alembic (`migrations/versions/*`) |
| Autenticación | Admin: Flask-Login + argon2 + captcha aritmético firmado + segundo factor por correo (código de 6 dígitos con hash, 5 intentos, 10 min) + CSRF `X-CSRF-Token` + límite de intentos persistente en BD (`RateWindow`) |
| Almacenamiento documental | `infrastructure/storage.py`: puerto `DocumentStoragePort` con adaptadores `LocalDocumentStorage` y `MinioDocumentStorage` (claves opacas, sin crear buckets) |
| Validación de archivos | `modules/documents/validation.py` (subproceso con límite de 5 s, firma PDF, PDF sin cifrar/acciones, imágenes con límite de píxeles) |
| Tareas / leases | `modules/receipts/service.py::generate_receipt` (fila con `lease_owner/lease_until`, reintentable) |
| Idempotencia | `IdempotencyRecord(owner_id,key)` único |
| IA | `ai/provider.py` (salida estricta con Pydantic, un reintento de reparación, `ProviderUnavailable`), `ai/routes.py` (turnos con `expected_version`, expiración, resultados obsoletos), `ai/document_reader.py` (parser hijo aislado) |
| Health | `/api/v1/health/live` y `/api/v1/health/ready` |
| Producción | `Dockerfile`: `wait_for_db.py` → `flask db upgrade` → gunicorn. Sin Compose en el ejemplo. |

Patrones inseguros o a corregir (justificados en `docs/ARQUITECTURA.md`): el arranque ejecuta `flask db upgrade` dentro de cada contenedor (riesgo de migraciones concurrentes); `create-admin` recibe la contraseña como argumento (queda en el historial de comandos); el panel `/admin` renderiza HTML en el servidor y el login depende de un captcha aritmético; `AI_API_KEY=ollama` es un marcador y no un secreto; el rate limit usa `request.remote_addr` sin confiar en proxy salvo `TRUST_PROXY`.

### RAG (`sample/rag-chat`)
FastAPI + uvicorn, `httpx`, `python-dotenv`, `numpy`, `fastembed` (modelo ONNX `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensiones, CPU), `lancedb` (opcional) o NumPy en memoria, `langgraph` + `langchain-ollama` (`ChatOllama`), `python-docx`.

Reconstrucción del flujo:
1. `ingest.py`: `.docx` → bloques (párrafos/tablas) → secciones con migas de títulos → fragmentos de ≈900 caracteres (máx. 1400) con metadatos `section, zone, card, doc` → embeddings fastembed normalizados → `chunks.json`, `embeddings.npy`, índice LanceDB y `overview.txt`.
2. `main.py` `/api/chat` (SSE): límites (2000 caracteres/mensaje, 8 turnos, 20 mensajes/minuto/IP), eventos `status`, `sources`, `token`, `reset`, `tools`, `suggest`, `error`, `done`.
3. `graph.py` (LangGraph): `entender` (planificador `advisor.plan`: JSON con intención, consultas autosuficientes; heurística de reserva si falla) → `retriever.gather` → `asesor` (ChatOllama con herramientas, máx. 4 rondas) ⇄ `herramientas` (`tools.py`: búsqueda, fichas, filtros; todas de lectura).
4. `rag.py`: expansión de consulta, recuperación híbrida **densa + BM25 (`lexical.py`) con fusión RRF (k=60)**, filtros por metadatos validados con lista blanca (`store.check_where`), `search_multi`, `gather`.
5. Prompts en `prompt.py`; cliente: `ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_HOST, Authorization: Bearer OLLAMA_API_KEY)`; el modelo se llama sin sufijo `:cloud` cuando se usa `https://ollama.com` directo.

Partes reutilizadas como módulos y partes que requieren proceso aparte: BM25 + RRF + expansión + planificador + eventos SSE se reutilizan como módulos Python dentro del backend Flask (`backend/app/ai/rag/*`); la ingesta/embedding (CPU, pesada) corre en el proceso `worker` del mismo código; **no se despliega un segundo servidor HTTP (FastAPI)** para no duplicar capas ni usuarios.

## 3. Configuración de IA (sin valores secretos)

Origen: `sample/backend/.env` (cargado con `python-dotenv` por `app/config.py`; el `.env` de `rag-chat` no existe, `config.py` de `rag-chat` espera `OLLAMA_API_KEY`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `TOP_K`, `VECTOR_BACKEND` en `../.env`).

| Variable (origen) | Propósito | Secreta | Obligatoria | Consumidor en el ejemplo |
|---|---|---|---|---|
| `OLLAMA_BASE_URL` (backend/.env) | URL del daemon Ollama. Valor observado: daemon local en el puerto 11434 que reenvía los modelos `:cloud` | No | Sí | `.env` → `AI_BASE_URL` |
| `OLLAMA_MODEL` | Modelo (`deepseek-v4-flash:cloud`) | No | Sí | `AI_ASSISTANT_MODEL` |
| `AI_ENABLED` | Interruptor de asistencia | No | Sí | `ai/provider.py::_config` |
| `AI_BASE_URL` | `${OLLAMA_BASE_URL}/v1` (OpenAI-compatible) | No | Sí | `provider.py` |
| `AI_API_KEY` | Marcador `ollama` para el daemon local | Tratada como secreta | Sí | `provider.py` |
| `AI_ASSISTANT_MODEL`, `AI_VISION_MODEL`, `AI_OUTPUT_MODE` | Modelo de texto, de visión (vacío) y modo `tool/native/prompted` | No | Sí/No | `provider.py` |
| `OLLAMA_API_KEY` (rag-chat) | Clave Bearer cuando se llama directo a `https://ollama.com` | **Sí** | Solo en conexión directa | `rag-chat/graph.py`, `advisor.py` |
| `OLLAMA_HOST` (rag-chat) | Host directo (por defecto `https://ollama.com`) | No | No | `rag-chat/config.py` |

Conexión: en el `.env` real la conexión **pasa por un componente existente** (daemon Ollama del equipo, autenticado contra Ollama Cloud), no es directa; `rag-chat` está escrito para conexión directa con `OLLAMA_API_KEY`. No existe `OLLAMA_API_KEY` en ningún `.env` leído. Mapa de destino y decisión en `docs/IA.md`. Verificación del 13/10/2026: el daemon responde (`/api/tags`, `/api/version`), pero el modelo configurado `deepseek-v4-flash:cloud` devuelve **HTTP 410: “deepseek-v4-flash:0731 was retired at 2026-09-25”**; la prueba live queda bloqueada hasta que el usuario elija un modelo disponible (no se cambia silenciosamente).

## 4. HTML de referencia (`model/Compra_Clara_Lavalleja.html`)

Aplicación de un solo archivo (≈146 KB): estado en `localStorage` (`compra-clara-lavalleja-v3`), vistas `home, cases, case, evaluate, providers, audit, rules, settings`, modales (asistente de 3 pasos, rol, ayuda, explicación, laboratorio, orden imprimible, expediente imprimible), 8 etapas, 5 expedientes iniciales (`SC-2026-0042…0046`), motor `evaluate()` (UYU, 1 renglón, IVA 22 %, escalas 70/20/10), exportaciones JSON/CSV (neutraliza fórmulas), impresión, accesibilidad (texto grande, contraste, sin movimiento, foco atrapado en modales, `aria-*`), CSS responsive (≥1550, ≤1200, ≤1000, ≤760).

### Simplificaciones de demostración detectadas (no se trasladan como garantía)
1. Persistencia en `localStorage` y estado como fuente de verdad.
2. Selector de perfil de prueba (`#role`) sin autenticación; `requireRole` ofrece “usar el perfil”.
3. Reloj ficticio: “Simular llegada a la apertura” adelanta la apertura.
4. Datos precargados y proveedores/ofertas autogenerados al “fijar reglas” (`makeOffer` con 15 % menos).
5. Referencias documentales sin archivo; confirmaciones genéricas con casillas.
6. Puntajes codificados 70/20/10 y escalas fijas; mínimos IP66/24 meses/30 días impuestos por plantilla.
7. Restricciones: un renglón, UYU, cantidades enteras, IVA fijo 22 %, flete ya gravado; prorrateo del total adjudicado en la recepción.
8. Acciones que solo cambian booleanos (`credit`, `callAuthorized`, `published`, `conformed`, `control`, `authorized`, `paid`).
9. Etapa como entero editable en cliente (`c.step`), controles saltables por JavaScript.
10. Restaurar demo, exportación de sobres “reservados” con reserva solo visual.

## 5. Informe PDF (`model/Informe_Compras_Lavalleja.pdf`)
Se extrajo el texto completo con `pypdf` y se verificaron tablas (secciones 07 montos, 12 flujo, 14 perfiles, 15 ejemplo numérico). Uso: requisitos de producto, reglas parametrizables (con clase *normativo / observado / propuesto / pendiente*), umbrales 2026, caso de regresión de 120 luminarias y catálogo de 50 fuentes. **El informe es un documento de diseño, no una norma**; se rotula así en el corpus de IA. Umbrales 2026 contrastados el 13/10/2026 con el boletín oficial ARCE/INE (`TOCAF Enero - Diciembre 2026.pdf`, publicado 30/12/2025): compra directa departamental $ 1.024.000, concurso de precios $ 1.371.000, licitación abreviada $ 13.705.000, comisión asesora $ 4.577.000, garantía de cumplimiento $ 5.482.000 y de mantenimiento $ 13.705.000 coinciden. Los umbrales derivados (publicación art. 50: 20 % de 1.024.000 = 204.800; RUPE: 35 % de 654.000 = 228.900; vista: 4 × 13.705.000 = 54.820.000) coinciden aritméticamente con el informe, pero su base normativa está sujeta a validación jurídica. Topes “ampliados” del art. 44 no se activan.

## 6. Decisiones de reutilización (ruta de origen → destino)

| Capacidad | Origen | Destino | Decisión |
|---|---|---|---|
| Fábrica de app, cabeceras, `request_id`, manejadores de error, health | `sample/backend/app/__init__.py` | `backend/app/__init__.py` | Reutilizar y ampliar (`ready` verifica BD, almacenamiento y worker; cabeceras CSP) |
| Config por entorno | `sample/backend/app/config.py` | `backend/app/config.py` | Reutilizar, nuevas variables, cookie `Lax`/`Strict` configurable, límites de carga |
| `ApiError/require` | `sample/backend/app/shared/errors.py` | `backend/app/shared/errors.py` | Reutilizar tal cual + `conflict` |
| Almacenamiento (puerto + Local + MinIO) | `sample/backend/app/infrastructure/storage.py` | `backend/app/infrastructure/storage.py` | Reutilizar; añade `stream`, sin cambiar claves opacas |
| Validación de archivos con subproceso | `sample/backend/app/modules/documents/validation.py` | `backend/app/modules/documents/validation.py` | Reutilizar; se agregan TXT, extracción de texto por página y límites |
| Parser aislado | `sample/backend/app/ai/document_reader.py` | `backend/app/modules/documents/reader.py` | Reutilizar el principio (subproceso, límites) para texto por página |
| Autenticación (argon2, captcha, 2FA por correo, CSRF, rate limit en BD) | `sample/backend/app/modules/admin/*`, `identity/service.py` | `backend/app/modules/identity/*` | Reutilizar y completar: roles/permisos por recurso, delegaciones, bloqueo por intentos, alta segura del primer administrador sin contraseña en argumentos |
| Migraciones | `sample/backend/migrations` | `backend/migrations` | Reutilizar Alembic/Flask-Migrate; ejecución en un servicio único `migrate` |
| Tareas con lease | `sample/backend/.../receipts/service.py` | `backend/app/infrastructure/tasks.py`, `backend/app/worker.py` | Generalizar a una cola persistente `background_task` |
| Idempotencia | `IdempotencyRecord` | `backend/app/infrastructure/models/core.py::IdempotencyRecord` | Generalizar a `(actor, scope, key)` con hash de petición |
| `expected_version` / 409 | `modules/intake/service.py` | `backend/app/modules/procurement/service.py` | Reutilizar patrón en `procurement_case.version` |
| Auditoría | `AuditEvent` | `backend/app/infrastructure/audit.py` | Rediseñar a cadena hash append-only con triggers |
| IA estricta y proposal-only | `sample/backend/app/ai/provider.py` | `backend/app/ai/*` | Reutilizar principios (esquemas `extra=forbid`, una reparación, `ProviderUnavailable`, datos no confiables); cliente → Ollama nativo (rag-chat) |
| Cliente Ollama, `plan`, SSE, recuperación híbrida, BM25 | `sample/rag-chat/{advisor,main,rag,lexical,store}.py` | `backend/app/ai/{client,rag/*,routes}.py` | Reutilizar como módulos; vector store NumPy sobre el subconjunto **autorizado** cargado de MariaDB (LanceDB no se adopta: segunda fuente de verdad y no permite revocación inmediata) |
| Embeddings | `rag-chat/config.py::EMBED_MODEL` + `ingest.py` | `backend/app/ai/rag/embedder.py` | Reutilizar fastembed + modelo; caché en volumen propio |
| Frontend: React/Vite/Fluent/RQ/axios/RHF/zustand/Router | `sample/frontend/package.json` | `frontend/package.json` | Mantener versiones; sin cambios mayores |
| Cliente HTTP / CSRF / errores | `sample/frontend/src/api.ts` | `frontend/src/api/client.ts` | Reutilizar y ampliar (idempotency key, 409) |
| Nginx / Docker frontend | `sample/frontend/{Dockerfile,nginx.conf}` | `frontend/{Dockerfile,nginx.conf}` | Reutilizar; añade streaming SSE, límites, CSP |
| Tema Fluent | `sample/frontend/src/institutional-theme.ts` | `frontend/src/theme.ts` | Adaptar tokens a la paleta Compra Clara (`--primary:#6b51d8`) |
| Estilos | `model/…html` (`<style>`) | `frontend/src/styles/compra-clara.css` | Trasladar la identidad visual del HTML |
| E2E Playwright + axe | `sample/frontend/{playwright.config.ts,admin-auth-e2e.mjs}` | `frontend/e2e/*` | Reutilizar enfoque contra la app servida por proxy |

## 7. Qué no se reutiliza (y por qué)
- Plantillas Jinja del panel `/admin` y `admin.css`: la administración vive en la SPA con el mismo lenguaje visual de Compra Clara.
- Dominio “arquitectura/trámites”, catálogo, borradores anónimos (`ActorSession`), seguimiento por clave y PDF de comprobante: no aplican al proceso de compras.
- LangGraph/LangChain: el flujo central (planificar → recuperar → responder con herramientas de consulta) se reimplementa en pocas líneas para no sumar dependencias pesadas; se conserva el contrato de eventos SSE.
- `sample/rag-chat/frontend`/estáticos y el índice `.lance` del ejemplo (dominio de inversión).
