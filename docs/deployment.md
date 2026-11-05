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

### Anthropic (Claude) — de pago

Requiere una cuenta en la consola de Anthropic con facturación, **solo con autorización del director**.

1. En `.env`: `OFFICE_ANTHROPIC_API_KEY`, y los precios del modelo elegido en USD por millón de tokens (`OFFICE_ANTHROPIC_INPUT_PRICE_PER_MTOK`, `OFFICE_ANTHROPIC_OUTPUT_PRICE_PER_MTOK`). Sin precios la app no arranca, para que ningún gasto quede sin registrar.
2. `OFFICE_ALLOW_PAID_PROVIDERS=true` (sin esto, cualquier ejecución con Anthropic responde 402).
3. Asignar el proveedor a los agentes deseados: `PATCH /api/v1/agents/{id}` con `{"provider": "anthropic", "model": "<modelo>"}`.
4. Recomendado: fijar un límite de gasto en la consola de Anthropic y mantener `max_tokens_per_task` bajo.

## 3. Cloud gratuito (fase posterior, requiere autorización)

Arquitectura propuesta: **Render (web service Free)** + **Neon (PostgreSQL Free)**.

1. Crear una base en Neon y copiar la cadena de conexión en formato `postgresql+psycopg://…`.
2. Crear un *Web Service* en Render conectado al repositorio, plan **Free**:
   - Build: `pip install ".[postgres]"`
   - Start: `uvicorn kavryndex_office.api:create_app --factory --host 0.0.0.0 --port $PORT` (aplica migraciones al arrancar)
   - Variables: `OFFICE_ENV=production`, `OFFICE_DATABASE_URL`, `OFFICE_ADMIN_API_KEY`, `OFFICE_ALLOW_PAID_PROVIDERS=false`.
3. Verificar `GET /health`.

Limitaciones conocidas: el servicio Free de Render se suspende tras 15 minutos sin tráfico y tarda en despertar; su disco es efímero (por eso la base va en Neon).

Migraciones: por defecto se aplican al arrancar. Para controlarlas manualmente, poner `OFFICE_AUTO_MIGRATE=false` y ejecutar `kavryndex-office migrate` antes de cada despliegue; la app se niega a arrancar si la base no está al día.
