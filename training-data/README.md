# Training data

This directory is the canonical local zone for training and evaluation data. Its
contents are machine-local and ignored by Git; never commit datasets, annotations,
customer material, or generated samples.

- `raw/` contains source inputs. Keep these read-only where practical, preserve
  their provenance, and let the designated data owner control replacement.
- `processed/` contains reproducible transforms and prepared datasets. Operators
  own regeneration; jobs should not modify the raw sources in place.
- `evaluation/` contains curated gold sets, protocols, and evaluation inputs.
  Limit write access to the maintainers responsible for evaluation integrity.

Create the local directories and compatibility links from the repository root:

```bash
python3 scripts/bootstrap_local_assets.py
```

Use `--dry-run` first when inspecting an existing checkout. The bootstrap never
overwrites an existing legacy path.
