# KAVRYNDEX AI OFFICE

Plataforma independiente, modular y API-first para operar una oficina de agentes de IA especializados (CEO, Desarrollo, Marketing, Investigación, QA y Operaciones). Los agentes colaboran mediante **tareas estructuradas con dependencias**, **entregas de resultados**, **memoria compartida con permisos**, **aprobaciones humanas** y **auditoría completa**.

- Fundación técnica: [`PROJECT_FOUNDATION.md`](PROJECT_FOUNDATION.md)
- Estándares: [`CONTRIBUTING.md`](CONTRIBUTING.md) · Seguridad: [`SECURITY.md`](SECURITY.md)
- Decisiones de arquitectura: [`docs/adr/`](docs/adr/) · Despliegue: [`docs/deployment.md`](docs/deployment.md)

## Estado: v0.2 (núcleo + migraciones y registro de agentes)

| Capacidad | Estado |
|---|---|
| Registro de agentes y 6 agentes por defecto | ✅ |
| Proyectos con acceso por agente | ✅ |
| Tareas: asignación, dependencias, prioridad, reintentos, cancelación | ✅ |
| Execution Engine con herramientas autorizadas por agente | ✅ |
| Orchestrator de proyecto (bajo demanda) y delegación del CEO | ✅ |
| Memoria agente / proyecto / organización | ✅ (texto) |
| Aprobaciones humanas para herramientas destructivas | ✅ |
| Auditoría, tokens y coste por ejecución | ✅ |
| Proveedores: `mock` ($0) y OpenAI-compatible (Ollama, Groq, Gemini) | ✅ |
| Proveedores de pago bloqueados por defecto | ✅ |
| Migraciones Alembic (SQLite y PostgreSQL) y CLI de administración | ✅ |
| Registro de agentes con reglas de coherencia, versiones y auditoría de cambios | ✅ |
| Dashboard, adaptador Anthropic, búsqueda semántica | ⏳ roadmap |

## Requisitos

- Python 3.12 o superior
- Git

## Inicio rápido (local, $0)

```bash
git clone https://github.com/phillip209/kavryndex-ai-office.git
cd kavryndex-ai-office
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # Windows: copy .env.example .env
# Generar una clave y ponerla en OFFICE_ADMIN_API_KEY dentro de .env:
python -c "import secrets; print(secrets.token_urlsafe(32))"
uvicorn kavryndex_office.api:create_app --factory --reload
```

La base de datos se migra automáticamente al arrancar (`OFFICE_AUTO_MIGRATE=true`).

## CLI de administración

```bash
kavryndex-office migrate            # aplica migraciones pendientes
kavryndex-office db-status          # revisión actual vs. última (código 1 si falta migrar)
kavryndex-office bootstrap-agents   # crea los 6 agentes por defecto que falten
kavryndex-office generate-key       # genera una API key (no la guarda)
```

## Cambiar el esquema

1. Modificar los modelos en `src/kavryndex_office/models/`.
2. `alembic revision --autogenerate -m "descripcion"` y **revisar** el archivo generado.
3. `pytest` verifica que modelos y migraciones coinciden.

Documentación interactiva de la API: <http://127.0.0.1:8000/docs> (botón **Authorize** → tu clave).

## Flujo de ejemplo

```bash
KEY="tu-clave"; API=http://127.0.0.1:8000/api/v1
# 1. Crear los 6 agentes por defecto (o: kavryndex-office bootstrap-agents)
curl -X POST -H "X-API-Key: $KEY" $API/agents/bootstrap
# 2. Crear un proyecto y dar acceso a especialistas
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"slug":"demo","name":"Demo","members":["developer","qa"]}' $API/projects
# 3. Crear un objetivo para el CEO (con el proveedor mock, input.mock_tool_calls simula la delegación)
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{
  "project_id":"<ID>","title":"Lanzar módulo","assignee_slug":"ceo",
  "input":{"mock_tool_calls":[
    {"name":"task_delegate","arguments":{"title":"Construir","assignee_slug":"developer"}},
    {"name":"task_delegate","arguments":{"title":"Probar","assignee_slug":"qa","depends_on_titles":["Construir"]}}]}}' $API/tasks
# 4. Ejecutar el proyecto: CEO → Desarrollo → QA, en orden de dependencias
curl -X POST -H "X-API-Key: $KEY" $API/projects/<ID>/run
# 5. Revisar resultados, entregas y auditoría
curl -H "X-API-Key: $KEY" "$API/tasks?project_id=<ID>"
curl -H "X-API-Key: $KEY" "$API/messages?project_id=<ID>"
curl -H "X-API-Key: $KEY" "$API/audit?project_id=<ID>"
```

## Calidad

```bash
ruff check . && ruff format --check .
mypy src
pytest              # incluye cobertura (mínimo 85 %)
```

## Endpoints principales (`/api/v1`)

| Recurso | Endpoints |
|---|---|
| Sistema | `GET /system/info`, `GET /tools`, `GET /health` (público) |
| Agentes | `POST /agents`, `POST /agents/bootstrap`, `GET /agents`, `GET/PATCH /agents/{id}` |
| Proyectos | `POST /projects`, `GET /projects`, `GET /projects/{id}`, `POST/DELETE /projects/{id}/members`, `POST /projects/{id}/run` |
| Tareas | `POST /tasks`, `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/assign`, `POST /tasks/{id}/cancel`, `POST /tasks/{id}/run`, `GET /tasks/{id}/runs` |
| Aprobaciones | `GET /approvals`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject` |
| Memoria | `GET /memory`, `PUT /memory` |
| Comunicación | `GET /messages` |
| Auditoría | `GET /audit` |
