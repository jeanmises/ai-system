-- QUERY ESEMPIO PER AI SYSTEM DATABASE
-- Salva questo file per riferimento futuro

-- =============================================================================
-- 1. UTENTI E SESSIONI
-- =============================================================================

-- Crea un utente (sincronizzato da OIDC)
INSERT INTO app_user (id, external_id, provider, email, display_name, is_active)
VALUES (
    gen_random_uuid(),
    'google-oauth2|123456',
    'https://accounts.google.com',
    'user@example.com',
    'Mario Rossi',
    true
);

-- Trova tutte le sessioni di un utente
SELECT s.id, s.title, s.objective, s.status, s.created_at
FROM session s
JOIN app_user u ON s.owner_user_id = u.id
WHERE u.email = 'user@example.com'
ORDER BY s.created_at DESC;

-- Conta sessioni per status
SELECT status, COUNT(*) as count
FROM session
GROUP BY status;

-- =============================================================================
-- 2. AUDIT LOG - Traccia TUTTO
-- =============================================================================

-- Log un evento (esempio: user crea session)
INSERT INTO audit_event (
    id, event_type, actor_type, actor_id,
    action_verb, entity_type, entity_id,
    context, result_status
)
VALUES (
    gen_random_uuid(),
    'session.created',
    'user',
    'user-uuid-here',
    'created',
    'session',
    'session-uuid-here',
    '{"session_id": "session-uuid-here", "request_id": "req-123"}'::jsonb,
    'success'
);

-- Trova tutti gli eventi di una sessione (usa indice GIN!)
SELECT
    timestamp,
    event_type,
    actor_type,
    action_verb,
    result_status
FROM audit_event
WHERE context->>'session_id' = 'session-uuid-here'
ORDER BY timestamp DESC;

-- Trova eventi falliti nelle ultime 24h
SELECT
    timestamp,
    event_type,
    actor_id,
    result_error
FROM audit_event
WHERE result_status = 'failure'
  AND timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC;

-- =============================================================================
-- 3. CATALOGO AGENTI - Governance
-- =============================================================================

-- Aggiungi un agente al catalogo (draft)
INSERT INTO agent (id, version, role, capabilities, input_schema, output_schema, status)
VALUES (
    'audit-logger',
    '1.0.0',
    'Log all system events in append-only audit table',
    '["logging", "audit", "compliance"]'::jsonb,
    '{"type": "object", "properties": {"event_type": {"type": "string"}}}'::jsonb,
    '{"type": "object", "properties": {"event_id": {"type": "string"}}}'::jsonb,
    'draft'
);

-- Pubblica l'agente
UPDATE agent
SET status = 'published', published_at = NOW()
WHERE id = 'audit-logger' AND version = '1.0.0';

-- Trova tutti gli agenti pubblicati
SELECT id, version, role, published_at
FROM agent
WHERE status = 'published'
ORDER BY id, version DESC;

-- Trova l'ultima versione di ogni agente
SELECT DISTINCT ON (id)
    id, version, status, published_at
FROM agent
WHERE status = 'published'
ORDER BY id, version DESC;

-- =============================================================================
-- 4. META-PROPOSALS - Auto-evoluzione
-- =============================================================================

-- Crea una proposta di modifica
INSERT INTO meta_proposal (
    id, created_by_user_id, session_id,
    original_request, scope, changes, unchanged,
    expected_impact, risks, status
)
VALUES (
    gen_random_uuid(),
    'user-uuid',
    'session-uuid',
    'meta: Increase LLM timeout to 60 seconds',
    'parameters',
    '[{"entity": "llm_proxy", "field": "timeout_ms", "old": 30000, "new": 60000}]'::jsonb,
    '["architecture", "database_schema"]'::jsonb,
    'Longer timeout reduces failures for complex queries',
    '[{"risk": "Slower response times", "severity": "low"}]'::jsonb,
    'pending'
);

-- Trova proposte in attesa di approvazione
SELECT
    id,
    original_request,
    scope,
    status,
    created_at
FROM meta_proposal
WHERE status = 'pending'
ORDER BY created_at;

-- =============================================================================
-- 5. STATISTICHE E MONITORING
-- =============================================================================

-- Conta eventi per tipo (ultime 24h)
SELECT
    event_type,
    COUNT(*) as count,
    SUM(CASE WHEN result_status = 'success' THEN 1 ELSE 0 END) as successes,
    SUM(CASE WHEN result_status = 'failure' THEN 1 ELSE 0 END) as failures
FROM audit_event
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY event_type
ORDER BY count DESC;

-- Utenti più attivi
SELECT
    u.email,
    u.display_name,
    COUNT(s.id) as session_count,
    MAX(s.created_at) as last_session
FROM app_user u
LEFT JOIN session s ON s.owner_user_id = u.id
GROUP BY u.id, u.email, u.display_name
ORDER BY session_count DESC;

-- Dimensione database
SELECT
    pg_size_pretty(pg_database_size('ai_system')) as db_size;

-- Dimensione per tabella
SELECT
    schemaname,
    relname as table_name,
    pg_size_pretty(pg_total_relation_size(relid)) as total_size,
    pg_size_pretty(pg_relation_size(relid)) as table_size,
    pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) as indexes_size
FROM pg_catalog.pg_statio_user_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(relid) DESC;

-- =============================================================================
-- 6. VERIFICA INTEGRITÀ
-- =============================================================================

-- Trova sessioni orfane (owner cancellato) - non dovrebbe esistere grazie a CASCADE
SELECT s.id, s.owner_user_id
FROM session s
LEFT JOIN app_user u ON s.owner_user_id = u.id
WHERE u.id IS NULL;

-- Trova subsession senza parent
SELECT ss.id, ss.parent_session_id
FROM subsession ss
LEFT JOIN session s ON ss.parent_session_id = s.id
WHERE s.id IS NULL;

-- Verifica che audit_event non abbia UPDATE/DELETE (dovrebbe essere 0)
SELECT
    schemaname,
    relname,
    n_tup_upd as updates,
    n_tup_del as deletes
FROM pg_stat_user_tables
WHERE relname = 'audit_event';
