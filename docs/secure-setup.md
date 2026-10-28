# Secure setup and integrations

## Operator access

Run `python scripts/setup_local.py` from the repository root. It generates a
random database password in the ignored root `.env` and a random access key in
`.nexus-access-key`. Only the SHA-256 digest (`AUTH_TOKEN_HASH`) goes to the
backend. Existing nonempty environment values are preserved. Keep the key
private and enter it on the login screen. The browser retains it in memory only;
logout or reloading signs out. Never put it in `VITE_*` variables.

Scripts must send `Authorization: Bearer <key>`. Authentication is mandatory
in development and production, including reads, settings, MCP configuration,
runs and approvals. Missing configuration returns 503; a wrong/missing key
returns 401. Health probes are public. `/api/v1/events/trigger` validates its
separate `ALWAYS_ON_EVENT_INGRESS_SECRET`. This is a single-operator deployment,
not a multi-user account system. The stable owner UUID preserves existing data.

To rotate access, generate a new random key with at least 32 bytes of entropy,
update its SHA-256 hex digest in the root `.env` and local `backend/.env`, then
restart the backend. The setup script does not rotate existing keys.

## Docker and existing volumes

Compose exposes only `127.0.0.1:3000` by default. PostgreSQL and the backend are
internal. nginx forwards `/api/` to the backend; Vite does the same locally.
Leave `VITE_API_BASE_URL` empty. To allow another computer, set
`NEXUS_BIND_ADDRESS` to the intended interface and terminate HTTPS at a trusted
reverse proxy before exposing the service beyond your machine.

The backend no longer mounts the Docker Engine socket or joins the root group.
`docker.logs` reports unavailable in the default stack. A read-only socket mount
does not restrict Docker API methods; use an independently restricted log
service if container logs are needed.

**Existing volumes:** changing `POSTGRES_PASSWORD` does not change a password
inside a populated PostgreSQL directory. Back up first. Use the existing password
in the root `.env` during migration, rotate the role password through an
authenticated PostgreSQL administration session, and update `.env` to match.
Never delete the volume to fix authentication. No script automatically rotates
or deletes an existing database. Generated passwords are URL-safe hex; if using
your own password, URL-encode reserved characters when configuring DATABASE_URL.

The image includes pgvector for PostgreSQL 17. Migration `0014_memory_embeddings`
creates the extension and nullable vector columns. External PostgreSQL servers
must have pgvector installed, and the migration account needs extension privileges.

## Real GitHub tools

Public reads do not need a GitHub token: list an explicit `user`/`org`, inspect
`github.get_repository` with `repository: "owner/repo"`, then use
`github.read_contents` to list directories (empty `path`) or read a code/README
file. Optional `ref` selects a branch, tag or commit. Text reads are limited to
256 KiB per file and return up to 20,000 characters with a truncation flag.
The app's operator login and Trust Engine still apply to public reads.

For private repositories or writes, set `GITHUB_PERSONAL_ACCESS_TOKEN` in
`backend/.env` to a fine-grained token restricted to intended repositories.
Private file reads need Contents read. Listing needs metadata access; writing
issues needs Issues write, and pull requests need Pull requests write. Operations
requiring credentials return `GITHUB_NOT_CONFIGURED` when no token is set;
results are never simulated. Unauthenticated public reads have GitHub's limit
of 60 requests per hour per originating IP. Exhaustion returns
`GITHUB_RATE_LIMITED`; see [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

`github.list_repos` returns `{items, page}` and accepts bounded `limit` and `page`.
Omit user/org to list the token owner's repositories. Both write tools accept
`repository: "owner/repo"`, or use `GITHUB_DEFAULT_REPOSITORY`. Writes retain
Trust Engine authorization and human confirmation. Requests go only to
`https://api.github.com`, refuse redirects, cap responses, and do not retry
writes. After a network error, check GitHub before retrying.

References: [repositories](https://docs.github.com/en/rest/repos/repos),
[issues](https://docs.github.com/en/rest/issues/issues),
[pull requests](https://docs.github.com/en/rest/pulls/pulls).

## Semantic memory

`MEMORY_SEARCH_MODE=keyword` is the offline default: term matching without a
provider key. The separate knowledge-document store also remains keyword-based.
For real pgvector memory retrieval, explicitly configure:

```dotenv
MEMORY_SEARCH_MODE=semantic
EMBEDDING_BASE_URL=https://your-provider.example/v1
EMBEDDING_API_KEY=<provider-key>
EMBEDDING_MODEL=<embedding-model-id>
EMBEDDING_DIMENSIONS=<model-output-dimensions>
EMBEDDING_TIMEOUT_SECONDS=20
```

Use a model/endpoint providing an OpenAI-compatible `/embeddings` response.
This is separate from the chat model. Enabling semantic mode sends memory and
queries to that provider and may cost money. Invalid configuration prevents
startup; failures surface as errors instead of silently reverting to keyword
results. Saves generate validated normalized vectors after the Memory Firewall.
PostgreSQL ranks by cosine distance, preserving agent, owner and memory-type
filters. Provider/model/dimension fingerprints prevent mixing embedding spaces.
Ranking is exact over the scoped vectors, with no approximate index yet.

Existing memories have null vectors. Explicitly run
`docker compose exec backend python -m scripts.reindex_memories` after configuring
the provider (or the same module from `backend` locally). It processes the local
operator's memories in batches of 50 and resumes after interruption. Run it again
after changing provider/model/dimensions. Semantic search excludes rows not indexed
for the active model. Keyword-mode edits invalidate previous vectors.

Reference: [pgvector SQLAlchemy integration](https://github.com/pgvector/pgvector-python#sqlalchemy).

## Validation

Backend: `python -m pytest -m "not integration and not external and not openshell"`.
Integration tests need a disposable migrated PostgreSQL instance with pgvector.
Frontend: `npm run build`, `npm run lint`, `npm test`.
