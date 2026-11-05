# ADR 0003 — Objetivos: planificación delegada + informe consolidado

- **Estado:** propuesto
- **Fecha:** 2026-11-04

## Contexto

El director debe poder entregar un objetivo de negocio y recibir un resultado consolidado, sin coordinar cada subtarea. El CEO puede delegar, pero su tarea termina al delegar: nadie esperaba el trabajo del equipo ni lo resumía.

## Decisión

1. `POST /projects/{id}/goals` crea dos tareas del planificador (CEO por defecto):
   - **Planificar**: ve el *equipo disponible* (agentes activos con acceso al proyecto) y delega con `task_delegate`, usando `depends_on_titles` para ordenar.
   - **Informe final**: depende del plan con `await_descendants=true`. Solo está lista cuando el plan y **todas** sus subtareas, a cualquier profundidad, han terminado (completadas, fallidas o canceladas). Recibe los resultados y errores del equipo y no puede delegar.
2. Límites contra planes desbocados: `OFFICE_MAX_DELEGATIONS_PER_TASK` y `OFFICE_MAX_DELEGATION_DEPTH`. Superarlos se devuelve al modelo como error de herramienta.
3. `GET /tasks/{id}/tree` muestra el árbol de delegación.

## Consecuencias

- (+) Flujo completo objetivo → plan → ejecución → informe, auditado y sin conversación libre entre agentes.
- (+) Los fallos parciales llegan al informe; el CEO debe reportarlos, no ocultarlos.
- (−) La calidad del plan depende del modelo real; con `mock` el plan se simula mediante `input.mock_tool_calls`.
