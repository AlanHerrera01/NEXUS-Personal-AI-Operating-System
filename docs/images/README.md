# Architecture Diagrams

This directory contains Mermaid diagram source files for the NEXUS architecture.

## Diagrams

- `architecture.mmd` - System architecture overview
- `request-flow.mmd` - Request flow sequence diagram
- `security-boundaries.mmd` - Security trust boundaries
- `docker-architecture.mmd` - Docker Compose architecture
- `threat-model.mmd` - STRIDE threat model
- `deployment-architecture.mmd` - Production deployment architecture

## Rendering

### Online

Visit [Mermaid Live Editor](https://mermaid.live/) and paste the content of any `.mmd` file to render and export as PNG/SVG.

### Command Line

Install the Mermaid CLI:

```bash
npm install -g @mermaid-js/mermaid-cli
```

Generate SVG images:

```bash
cd docs/images
mmdc -i architecture.mmd -o architecture.svg
mmdc -i request-flow.mmd -o request-flow.svg
mmdc -i security-boundaries.mmd -o security-boundaries.svg
mmdc -i docker-architecture.mmd -o docker-architecture.svg
mmdc -i threat-model.mmd -o threat-model.svg
mmdc -i deployment-architecture.mmd -o deployment-architecture.svg
```

Generate PNG images:

```bash
mmdc -i architecture.mmd -o architecture.png
mmdc -i request-flow.mmd -o request-flow.png
mmdc -i security-boundaries.mmd -o security-boundaries.png
mmdc -i docker-architecture.mmd -o docker-architecture.png
mmdc -i threat-model.mmd -o threat-model.png
mmdc -i deployment-architecture.mmd -o deployment-architecture.png
```

### Native Rendering

The diagrams render natively in:
- GitHub markdown
- GitLab markdown
- VS Code (with Mermaid extension)
- Many other markdown viewers

No conversion needed for these platforms.
