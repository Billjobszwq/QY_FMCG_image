# Recognition models

This directory is the canonical local zone for recognition-model assets. All
contents other than this README are machine-local and ignored by Git; never commit
model weights or exported bundles.

- `production/` holds locally installed production bundles.
- `candidates/` holds bundles under evaluation.
- `foundation/` holds shared foundation-model assets and checkpoints.
- `registry/` holds local registry metadata and legacy model layouts.

`registry/bundles/CURRENT.json` is the source of truth for the local selection. It
currently identifies `prod_v4_best_r1` as the production bundle and
`prod_20260805_v5_r1` as the previous rollback bundle. Both bundles remain
machine-local: this extraction uploads or commits neither one, and neither this
document nor the bootstrap changes the selected production model. Production
switches must remain an explicit, separately reviewed operation.

Bootstrap the local zones and compatibility links, then verify them without making
changes:

```bash
python3 scripts/bootstrap_local_assets.py
python3 scripts/bootstrap_local_assets.py --dry-run
```

An all-`unchanged` verification result means the compatibility links already point
to the intended local zones.
