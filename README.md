# FoamBench — OpenFOAM benchmark orchestration (Stage 1)

Install once; import OpenFOAM cases from Git or local folders; run a **single selected OpenFOAM environment** with reproducible parameter sweeps; archive selected artifacts. A mock benchmark is provided so beginners can test the automation without OpenFOAM.

**New to this? Start with [docs/BEGINNERS_GUIDE.md](docs/BEGINNERS_GUIDE.md).** See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the configuration contract, limitations and extension points.

## Quick start (Linux)

```bash
./install.sh
./fetchCases.sh
./Allrun --dry-run
./Allrun
# List runs, then:
python analysis/analyse.py --run <run-id>
```

The shipped `config/run.yaml` is a **synthetic smoke test**, not a real CFD benchmark. For a real benchmark, configure a valid OpenFOAM bashrc, source and benchmark manifest before running. `fetchCases.sh config/run.yaml` imports source repositories or validates local folders.

For programmatic CLI usage: `./.venv/bin/foambench run --config config/run.yaml --dry-run`.

## Contract

- Original sources are never rewritten by the framework. Case copies live under `runs/<run-id>/cases/`.
- No execution across multiple OpenFOAM environments in one `Allrun`.
- A run is fingerprinted against its config, source identity, template content, and benchmark manifest; resume refuses changes.
- `--dry-run` validates and prints the plan without writing run artifacts.
- `references/candidates/` is populated after successfully completed cases. Promotion to `references/approved/` is intentionally manual.
- Generated cases are retained by default. `after_archive` cleanup removes only a generated successful case after checksum verification.
- No OpenFOAM solver, external library, Gmsh, or reference comparison is bundled or installed automatically.

## Status

Stage 1 scaffold with live orchestrator and synthetic smoke tests. Benchmark-specific mappings, physical post-processing and scientific validation are Stage 2/3 work, pending supplied cases and parameters.
