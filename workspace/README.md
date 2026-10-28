# NEXUS workspace

This directory is mounted read-only at `/workspace` inside the backend
container. Put documents here that the agent may read:

- text, Markdown, code, JSON and CSV files for `files.search` / `files.read`;
- PDF, DOCX and XLSX files for `docs.extract`;
- any of the above for `knowledge.ingest`.

The file tools resolve every path under this directory and refuse sensitive
names such as `.env`, private keys and credential stores even when they are
inside it. Writes are not exposed: the mount is read-only, and no write tool is
registered.

To use a different folder, change the `./workspace:/workspace:ro` volume in
`docker-compose.yml` and `FILES_WORKSPACE_ROOT` together. Do not point the mount
at your home directory unless you intend to expose every file in it.
