# Recognition models

This directory is the canonical local zone for recognition-model assets. All
contents other than this README are machine-local and ignored by Git; never commit
model weights or exported bundles.

- `production/` holds locally installed production bundles.
- `candidates/` holds bundles under evaluation.
- `foundation/` holds shared foundation-model assets and checkpoints.
- `registry/` holds local registry metadata and legacy model layouts.

The current production bundle ID is `prod_20260805_v5_r1`. This is metadata only:
no weights are included here, and neither this document nor the bootstrap changes
the selected production model. Production switches must remain an explicit,
separately reviewed operation.

Bootstrap the local zones and compatibility links, then verify them without making
changes:

```bash
python3 scripts/bootstrap_local_assets.py
python3 scripts/bootstrap_local_assets.py --dry-run
```

An all-`unchanged` verification result means the compatibility links already point
to the intended local zones.
