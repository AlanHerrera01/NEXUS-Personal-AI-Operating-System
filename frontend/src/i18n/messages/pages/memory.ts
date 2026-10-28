/** Strings for the Memory screen. Spanish is the reference; English is typed from it. */
export const es = {
  header: {
    brand: 'NEXUS CORE OS',
    subsystem: 'LONG-TERM MEMORY SUBSYSTEM',
    engine: 'pgvector',
    title: 'Gestión de Memoria',
    description: 'Inspecciona, filtra y audita los recuerdos persistentes del sistema.',
  },
  firewall: {
    active: 'MEMORY FIREWALL: ACTIVO',
    offline: 'MEMORY FIREWALL: SIN CONEXIÓN',
    trust: 'TRUST {decision}',
    description: 'Sanitización de secretos y detección de inyección antes de persistir.',
  },
  agent: {
    label: 'AGENT {id}',
    none: 'SIN AGENTE',
  },
  metrics: {
    memories: 'Recuerdos',
    episodic: 'Episódicos',
    semantic: 'Semánticos',
    preference: 'Preferencias',
    vectorEngine: 'Motor PGVector',
    connected: 'Conectado',
    offline: 'Sin conexión',
    loadedMax: 'cargados (máx 100)',
    db: 'DB {value}',
  },
  search: {
    placeholder: 'Buscar en memoria semántica por concepto…',
    searching: 'Buscando…',
    clear: 'Limpiar',
  },
  actions: {
    export: 'Exportar',
    new: 'Nuevo',
  },
  tabs: {
    episodic: 'Episódica',
    semantic: 'Semántica',
    preference: 'Preferencias',
  },
  types: {
    episodic: 'EPISÓDICA',
    semantic: 'SEMÁNTICA',
    preference: 'PREFERENCIA',
  },
  form: {
    title: 'Registrar Recuerdo',
    placeholder: 'Qué debe recordar el agente…',
  },
  stream: {
    results: 'Resultados de búsqueda',
    synced: 'Registros sincronizados',
    showing: '(mostrando {shown} de {total})',
    online: 'Backend en línea',
    offline: 'Sin conexión',
  },
  empty: {
    noAgent:
      'No hay un agente activo. La memoria está scoped a un agente, así que aparece cuando exista uno.',
    loading: 'Cargando recuerdos…',
    noResults: 'Sin coincidencias para la búsqueda.',
    noMemories: 'Este agente aún no tiene recuerdos.',
    noType: 'No hay recuerdos de este tipo.',
  },
  card: {
    importance: 'IMPORTANCIA: {value}',
    source: 'Origen:',
    persisted: 'Persistido',
    notPersisted: 'No persistido',
  },
  policy: {
    heading: 'POLÍTICA DE SEGURIDAD Y PRIVACIDAD',
    title: 'Nexus Memory Firewall',
    bodyBefore:
      'Ninguna memoria persistente se consolida sin pasar el filtro de desinfección de secretos y la heurística anti-inyección (',
    heuristic: 'jailbreak / prompt leakage',
    bodyAfter: ') del backend. La escritura directa del operador se marca como explícita.',
    decision: 'Política de decisión',
    persistence: 'Persistencia solicitada',
  },
  storage: {
    label: 'Hardware Storage Layer',
    engine: 'Postgres + pgvector',
    connected: 'Base de datos conectada',
    unavailable: 'Base de datos no disponible',
  },
  operations: {
    download: 'Descargar recuerdos (.jsonl)',
    clear: 'Limpiar memoria del agente',
  },
  log: {
    title: 'Live Firewall Log',
    body: 'El backend no expone un flujo de eventos del firewall de memoria en tiempo real. Las decisiones de persistencia se ven por recuerdo en cada tarjeta.',
  },
  confirm: {
    clearAll: '¿Eliminar todos los recuerdos de este agente? Es irreversible.',
  },
  errors: {
    search: 'La búsqueda ha fallado.',
    save: 'No se pudo guardar el recuerdo.',
    remove: 'No se pudo eliminar el recuerdo.',
    clear: 'No se pudo limpiar la memoria.',
  },
};

export const en: typeof es = {
  header: {
    brand: 'NEXUS CORE OS',
    subsystem: 'LONG-TERM MEMORY SUBSYSTEM',
    engine: 'pgvector',
    title: 'Memory Management',
    description: "Inspect, filter and audit the system's persistent memories.",
  },
  firewall: {
    active: 'MEMORY FIREWALL: ACTIVE',
    offline: 'MEMORY FIREWALL: OFFLINE',
    trust: 'TRUST {decision}',
    description: 'Secret sanitization and injection detection before persisting.',
  },
  agent: {
    label: 'AGENT {id}',
    none: 'NO AGENT',
  },
  metrics: {
    memories: 'Memories',
    episodic: 'Episodic',
    semantic: 'Semantic',
    preference: 'Preferences',
    vectorEngine: 'PGVector Engine',
    connected: 'Connected',
    offline: 'Offline',
    loadedMax: 'loaded (max 100)',
    db: 'DB {value}',
  },
  search: {
    placeholder: 'Search semantic memory by concept…',
    searching: 'Searching…',
    clear: 'Clear',
  },
  actions: {
    export: 'Export',
    new: 'New',
  },
  tabs: {
    episodic: 'Episodic',
    semantic: 'Semantic',
    preference: 'Preferences',
  },
  types: {
    episodic: 'EPISODIC',
    semantic: 'SEMANTIC',
    preference: 'PREFERENCE',
  },
  form: {
    title: 'Log Memory',
    placeholder: 'What should the agent remember…',
  },
  stream: {
    results: 'Search results',
    synced: 'Synced records',
    showing: '(showing {shown} of {total})',
    online: 'Backend online',
    offline: 'Offline',
  },
  empty: {
    noAgent:
      'There is no active agent. Memory is scoped to an agent, so it appears once one exists.',
    loading: 'Loading memories…',
    noResults: 'No matches for the search.',
    noMemories: 'This agent has no memories yet.',
    noType: 'There are no memories of this type.',
  },
  card: {
    importance: 'IMPORTANCE: {value}',
    source: 'Source:',
    persisted: 'Persisted',
    notPersisted: 'Not persisted',
  },
  policy: {
    heading: 'SECURITY AND PRIVACY POLICY',
    title: 'Nexus Memory Firewall',
    bodyBefore:
      "No persistent memory is consolidated without passing the backend's secret-sanitization filter and anti-injection heuristic (",
    heuristic: 'jailbreak / prompt leakage',
    bodyAfter: '). Direct operator writes are marked as explicit.',
    decision: 'Decision policy',
    persistence: 'Requested persistence',
  },
  storage: {
    label: 'Hardware Storage Layer',
    engine: 'Postgres + pgvector',
    connected: 'Database connected',
    unavailable: 'Database unavailable',
  },
  operations: {
    download: 'Download memories (.jsonl)',
    clear: 'Clear agent memory',
  },
  log: {
    title: 'Live Firewall Log',
    body: 'The backend does not expose a real-time memory firewall event stream. Persistence decisions are shown per memory on each card.',
  },
  confirm: {
    clearAll: 'Delete all memories for this agent? This cannot be undone.',
  },
  errors: {
    search: 'The search failed.',
    save: 'The memory could not be saved.',
    remove: 'The memory could not be deleted.',
    clear: 'Memory could not be cleared.',
  },
};
