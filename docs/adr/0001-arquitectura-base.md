# ADR 0001 — Arquitectura base: monolito modular API-first con adaptadores de IA

- **Estado:** propuesto
- **Fecha:** 2026-11-04

## Contexto

KAVRYNDEX AI OFFICE debe coordinar agentes especializados con permisos, memoria y auditoría, con presupuesto inicial de USD $0, ejecución cloud bajo demanda e independencia de cualquier proveedor de IA y de otros productos (incluido KAVRYNDEX ALGORITHM).

## Decisión

1. **Monolito modular** en Python (FastAPI + SQLAlchemy 2). Cada dominio (agentes, tareas, ejecución, memoria, comunicación, aprobaciones, auditoría) es un paquete con su servicio y su router; los dominios se comunican por servicios, no por acceso directo a tablas ajenas desde la API.
2. **API-first:** toda capacidad se expone por REST documentado (OpenAPI). El dashboard y otros productos son clientes de esa API.
3. **Adaptadores de proveedor IA** detrás de la interfaz `LLMProvider`. Proveedor `mock` por defecto; adaptador OpenAI-compatible para Ollama/Groq/Gemini; Anthropic cuando exista API.
4. **Colaboración por tareas** (dependencias, entregas, memoria), no por conversación libre entre agentes.
5. **SQLite** en local y pruebas; **PostgreSQL** en cloud.

## Consecuencias

- (+) Despliegue simple en un solo servicio gratuito; fácil de probar.
- (+) Se puede extraer un módulo a servicio independiente más adelante sin cambiar la API.
- (−) La ejecución es síncrona en el MVP; tareas largas requerirán una cola (v0.8).
- (−) `create_all` en el MVP; Alembic obligatorio antes de datos reales.
