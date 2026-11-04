# Ejecución y despliegue

> Nada de esta guía crea cuentas ni activa facturación automáticamente. Cada paso cloud lo ejecuta el director cuando lo autorice.

## 1. Local (recomendado para desarrollo)

Ver el inicio rápido del [README](../README.md). Usa SQLite en `./data/office.db` y el proveedor `mock` ($0).

## 2. Modelos reales gratuitos (opcional)

AI OFFICE habla con cualquier API compatible con OpenAI Chat Completions mediante el proveedor `openai_compat`.

| Opción | `OFFICE_OPENAI_COMPAT_BASE_URL` | Notas |
|---|---|---|
| Ollama (local) | `http://localhost:11434/v1` | Requiere instalar Ollama y un modelo; $0, datos locales. Depende del hardware (pendiente del informe de auditoría local). |
| Groq Free | `https://api.groq.com/openai/v1` | Cuenta gratuita y clave de API; límites por minuto/día. |
| Gemini API Free | `https://generativelanguage.googleapis.com/v1beta/openai` | Clave desde Google AI Studio; en el nivel gratuito el contenido puede usarse para mejorar productos de Google. |

Pasos:

1. Poner la URL y la clave en `.env` (`OFFICE_OPENAI_COMPAT_API_KEY`).
2. Mantener `OFFICE_OPENAI_COMPAT_IS_PAID=true` salvo que se confirme que la cuenta no tiene facturación activa; solo entonces cambiarlo a `false`.
3. Cambiar el proveedor de un agente: `PATCH /api/v1/agents/{id}` con `{"provider": "openai_compat", "model": "<modelo>"}`.

## 3. Cloud gratuito (fase posterior, requiere autorización)

Arquitectura propuesta: **Render (web service Free)** + **Neon (PostgreSQL Free)**.

1. Crear una base en Neon y copiar la cadena de conexión en formato `postgresql+psycopg://…`.
2. Crear un *Web Service* en Render conectado al repositorio, plan **Free**:
   - Build: `pip install ".[postgres]"`
   - Start: `uvicorn kavryndex_office.api:create_app --factory --host 0.0.0.0 --port $PORT`
   - Variables: `OFFICE_ENV=production`, `OFFICE_DATABASE_URL`, `OFFICE_ADMIN_API_KEY`, `OFFICE_ALLOW_PAID_PROVIDERS=false`.
3. Verificar `GET /health`.

Limitaciones conocidas: el servicio Free de Render se suspende tras 15 minutos sin tráfico y tarda en despertar; su disco es efímero (por eso la base va en Neon). Antes del primer despliegue con datos reales se deben añadir migraciones Alembic (v0.2).
