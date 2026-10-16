# NEXUS - Personal AI Operating System

## Hackathon: Nebius Global AI Hackathon 2026 - Category: Personal AI

---

## 1. Visión General

**NEXUS** es un sistema de inteligencia artificial persistente que conecta al usuario con sus herramientas digitales y flujos de trabajo cotidianos. A diferencia de los chatbots convencionales, NEXUS recuerda el contexto del usuario, planifica tareas, utiliza herramientas y ejecuta acciones de forma controlada bajo políticas de seguridad definidas por el usuario.

### Ciclo de NEXUS: Recordar → Comprender → Planificar → Solicitar autorización → Actuar → Aprender

---

## 2. Arquitectura Principales Componentes

### A. Memoria Persistente
- **PostgreSQL + pgvector**: Almacenamiento y recuperación semántica de recuerdos
- **Memory Firewall**: Política stricta que evita que el modelo decida qué información guardar permanentemente
- **Three memory types**:
  - *Episódica*: Interacciones, eventos y acciones anteriores
  - *Semántica*: Factos y conocimientos relevantes
  - *Preferencias*: Decisiones y preferencias recurrentes del usuario
- **Política de memoria**: `DeterministicMemoryPolicy` que bloquea secrets, instrucciones de inyección y contenido muy corto

### B. Agent Orchestrator
Coordina el trabajo del agente mediante una pipeline documentada:

1. Recibir la solicitud del usuario
2. Cargar el contexto del usuario (memorias, preferencias)
3. Recuperar recuerdos relevantes via pgvector search
4. Generar un plan ejecutable (ExecutionPlan)
5. Validar el plan (DefaultPlanValidator)
6. Consultar el Trust Engine (decisiones ALLOW/ASK/DENY)
7. Ejecutar acciones autorizadas por el Tool Executor
8. Observar los resultados
9. Preparar la respuesta final y actualizar memoria

**Principio clave**: El LLM propone, el Trust Engine dispone. Nunca se ejecuta una acción sin autorización.

### C. Trust Engine
Motor de toma de decisiones de seguridad con tres decisiones posibles:

| Decisión | Significado |
|----------|-------------|
| **ALLOW** | La acción está autorizada por las políticas aplicables |
| **ASK** | Se requiere confirmación del usuario |
| **DENY** | La acción debe bloquearse |

Considera: tipo de acción, riesgo, permisos del usuario y recurso afectado. **Invariante**: Si requiere_confirmation=True, siempre será ASK aunque la política diga ALLOW.

### D. Skills Reutilizables
Skills que agrupan herramientas relacionadas, seguiendo el patrón Ports and Adapters:

| Skill | Herramientas | Categoría |
|-------|-------------|-----------|
| **Tasks** | create, list, get, update, complete | productivity |
| **Memory** | save, search, get, delete | knowledge |
| **GitHub** *(nuevo)* | list_repos, create_issue, create_pull_request | development |
| **Calendar** *(nuevo)* | create_event, list_events | productivity |

Cada skill expone operaciones concretas mediante `SkillDefinition` y `ToolDefinition`, permitiendo agregar nuevas habilidades sin reescribir el núcleo.

### E. MCP y Herramientas Externas
**Model Context Protocol** como capa de integración estandarizada:

```
Orchestrator → Plan Validator → Trust Engine → MCP/Tool Registry → Tool Executor
```

Las respuestas de herramientas se tratan como datos potencialmente no confiables para reducir riesgos de inyección de instrucciones.

### F. Plan Validator
Valida los planes de ejecución antes de consultar al Trust Engine, evitando que toda la lógica termine concentrada en una única llamada al modelo.

### G. Always-On / Scheduled Jobs
Tareas programadas o activadas por eventos (recordatorios, investigación periódica, preparación de información antes reuniones). Requiere: planificador, estados de ejecución, cancelación, límites de recursos, control de reintentos e idempotencia.

---

## 3. Flujo Completo: Solicitud → Orchestrator → Trust Engine → Ejecución

```
Usuario → Frontend → API → Agent Orchestrator → PlanValidator → Trust Engine
           ↓                          ↓                      ↓
      (user_request)           (execution_plan)      (ALLOW/ASK/DENY)
           ↓                          ↓                      ↓
     Tool Catalog           Tool Executor        Human Approval (ASK)
           ↓                          ↓
      Skills (Tasks, Memory,    Execution Authorized
       GitHub, Calendar)              ✓ / ✗
```

### Ejemplo de flujo:

1. **Usuario**: "Revisa mis tareas pendientes y ayúdame a organizar el trabajo de mañana"
2. **Orchestrator**: Carga contexto, recupera memoris relevantes, genera plan
3. **PlanValidator**: Verifica que el plan es válido
4. **Trust Engine**: Evalúa cada herramienta a usar:
   - `tasks.list_tasks` → ALLOW (bajo riesgo)
   - `calendar.create_event` → ASK (requiere confirmación)
5. **Orchestrator**: Si ASK, pausa y espera aprobación del usuario
6. **Execution**: Si ALLOW, ejecuta las herramientas autorizadas
7. **Result**: Se observan los resultados y se actualiza la memoria

---

## 4. Tecnologías

| Tecnología | Responsabilidad |
|------------|-----------------|
| **Python + FastAPI** | API y lógica de aplicación |
| **React + TypeScript** | Interfaz web |
| **PostgreSQL + pgvector** | Persistencia y recuperación semántica |
| **NVIDIA Nemotron 3.5 Super VL** | Razonamiento del agente (via Nebius API) |
| **Nebius Token Factory** | Inferencia del modelo mediante API |
| **MCP** | Integración con herramientas externas |
| **Docker** | Empaquetado y despliegue |
| **pytest** | Pruebas automatizadas |
| **Hermes, NemoClaw, OpenShell** | Tecnologías contempladas para la capa de ejecución |

---

## 5. Seguridad y Políticas Principales

- **Fail-closed por defecto**: `trust_default_decision: DENY` en configuración
- **LLM no autoriza ni ejecuta**: El Trust Engine es el único responsable de decisiones
- **Autorización por confirmación**: Herramientas con `requires_confirmation=True` siempre piden al usuario
- **Aislamiento sandbox**: Runtime con límites de ejecución, memoria, CPU y filesystem
- **Detección de inyección**: Prompt injection detection en tiempo de escritura de memoria
- **Bloqueo de secrets**: La Memory Firewall se niega a almacenar credenciales

---

## 6. Próximos Pasos / Fase Futura

- Habilitar Always-On/Scheduled Jobs para tareas programadas
- Integrar runtime sandbox real (Hermes/NemoClaw/OpenShell)
- Expandir skills: Web Research, Email, Notifications
- Interfaz de gestión de permisos para el usuario
- Soporte para múltiples proveedores de LLM

---

## 7. Equipo y Contexto

Desarrollado para el **Nebius Global AI Hackathon 2026** en la categoría **Personal AI**. El proyecto busca combinar autonomía con control explícito del usuario, abordando las limitaciones de los asistentes convencionales: contexto persistente limitado, poca capacidad de actuación integrada y control insuficiente sobre acciones.

**Enlaces útiles:**
- API Docs: http://localhost:8000/docs (desarrollo local)
- Frontend: http://localhost:3000 (desarrollo local)
- Docker: `docker compose up --build`