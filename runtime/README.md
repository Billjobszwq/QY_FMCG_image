# Runtime state

This directory is the canonical local zone for operational state: databases,
logs, caches, imports, review queues, and legacy reports. Everything other than
this README is local-only and ignored by Git.

Treat runtime state as disposable whenever possible. Services and documented
import procedures should be able to rebuild it; preserve only explicitly required
backups outside the repository. Never commit credentials, access tokens, cookies,
or private connection settings here.

Create the local directories and compatibility links from the repository root:

```bash
python3 scripts/bootstrap_local_assets.py
```

Use `--dry-run` to inspect the planned changes. Existing legacy paths are reported
as conflicts and are never removed or overwritten.
