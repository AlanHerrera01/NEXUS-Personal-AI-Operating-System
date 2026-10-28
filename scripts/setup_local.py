"""Generate single-operator credentials without printing secrets or replacing env files."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env_values(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {
        line.partition("=")[0].strip(): line.partition("=")[2].strip().strip("\"'")
        for line in text.splitlines() if "=" in line and not line.lstrip().startswith("#")
    }


def append_missing(path: Path, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = env_values(path)
    lines = text.splitlines()
    for key, value in values.items():
        if existing.get(key):
            continue
        if key in existing:
            lines = [f"{key}={value}" if line.partition("=")[0].strip() == key else line for line in lines]
        else:
            lines.append(f"{key}={value}")
    updated = "\n".join(lines) + "\n"
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def main() -> None:
    env_path = ROOT / ".env"
    # Existing DB volumes need their existing password. This script deliberately
    # never changes database credentials or overwrites an existing .env.
    if not env_path.exists():
        env_path.write_text(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nNEXUS_BIND_ADDRESS=127.0.0.1\n", encoding="utf-8")
    append_missing(env_path, {"POSTGRES_PASSWORD": secrets.token_hex(24), "NEXUS_BIND_ADDRESS": "127.0.0.1"})
    token_path = ROOT / ".nexus-access-key"
    if not token_path.exists():
        with token_path.open("x", encoding="utf-8") as target:
            target.write(secrets.token_urlsafe(48))
        token_path.chmod(0o600)
    token = token_path.read_text(encoding="utf-8").strip()
    digest = hashlib.sha256(token.encode()).hexdigest()
    for configured in (env_path, ROOT / "backend" / ".env"):
        current = env_values(configured).get("AUTH_TOKEN_HASH")
        if current and current != digest:
            raise SystemExit("Existing AUTH_TOKEN_HASH does not match .nexus-access-key; keep your current key or rotate the configuration explicitly.")
    append_missing(env_path, {"AUTH_TOKEN_HASH": digest})
    backend_env = ROOT / "backend" / ".env"
    if not backend_env.exists():
        backend_env.write_text((ROOT / "backend" / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    append_missing(backend_env, {"AUTH_TOKEN_HASH": digest})
    print("Configuration preserved. Access key: .nexus-access-key (keep private).")
    print("Existing PostgreSQL volume: set POSTGRES_PASSWORD in .env to its current password before starting Compose.")


if __name__ == "__main__":
    main()
