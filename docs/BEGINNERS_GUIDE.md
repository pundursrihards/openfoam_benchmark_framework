# Beginner's guide: from installation to your first benchmark

This guide assumes Linux, Bash, Python 3.10+, Git, and basic terminal access. For *real CFD*, you also need a working OpenFOAM installation. A test without OpenFOAM is included.

## 1. Learn the folder terminology

An **OpenFOAM case** is a folder containing the inputs needed by the solver. Usually `0/` has initial/boundary fields, `constant/` has physical/mesh properties, and `system/` contains run controls, discretization and solver settings. A **solver** is an executable that advances the calculation. **OpenFOAM environment** means an installed distribution/release and its compiled executables/libraries; it is activated by sourcing its `etc/bashrc`. A **benchmark** is a reusable case template with definitions for modifying inputs. A **study** selects which benchmarks and parameter values to run. A **reference** is a saved result used for comparison. An **archive** is a preserved snapshot of a finished run; by default it is only selected files, not the entire solution.

## 2. Install

```bash
cd openfoam-benchmarks
./install.sh
```

The installer creates `.venv/` for Python dependencies. You do not need to activate it when calling `Allrun` or `fetchCases.sh`; those scripts use it automatically. No administrator permission is expected for the Python installation. It does **not** install OpenFOAM. For optional Python tools, use `./install.sh analysis` (NumPy/pandas/Matplotlib/SciPy) or `./install.sh casefoam` (CaseFOAM). These optional dependencies require package-index access and may impose their own Python version requirements.

## 3. Run a safe test without OpenFOAM

The default configuration points to `examples/mock-source/mock-benchmark`, a synthetic fixture that writes a small CSV. It is *not* a physically meaningful CFD case.

```bash
./fetchCases.sh
./Allrun --dry-run
./Allrun
```

The dry run shows the two planned cases with different values of `end_time`. Actual execution makes a timestamped directory under `runs/`, and successful cases are archived under `references/candidates/<run-id>/`.

To inspect the generated results:

```bash
ls runs/
ls references/candidates/
python analysis/analyse.py --run <run-id>
```

## 4. Set up a real OpenFOAM environment

Find the installed `etc/bashrc` (for example `/opt/OpenFOAM/OpenFOAM-v2506/etc/bashrc`). Verify your OpenFOAM installation independently:

```bash
source /opt/OpenFOAM/OpenFOAM-v2506/etc/bashrc
which foamDictionary
foamVersion
```

Edit `config/run.yaml`, select a *single* environment under `openfoam.environment`, and define its `bashrc` under `openfoam.environments`. Remove `type: mock` and use `type: openfoam`. Each `Allrun` uses only that selected environment. To compare two installations, launch two separate runs and compare their archived results later.

## 5. Register a source of cases

Use `sources:` entries in `config/run.yaml`.

**Local folder:**

```yaml
sources:
  - name: my-cases
    type: local
    path: /home/me/OpenFOAM/my-benchmarks
```

The framework reads the original folder, without changing its contents. Relative local paths are resolved relative to the framework root, not your terminal's current folder.

**Git repository:**

```yaml
sources:
  - name: shared-cases
    type: git
    url: https://github.com/ORG/benchmarks.git
    ref: main
```

Then run `./fetchCases.sh`. It clones into `sources/shared-cases/`, updates when requested again, and checks out the resolved commit. **Do not hand-edit imported Git checkouts.** Private repositories require Git credentials configured outside FoamBench.

## 6. Describe a benchmark

A benchmark is a folder inside a source repository. It needs `benchmark.yaml` alongside its case template. Example:

```text
my-benchmarks/
└── risingBubble/
    ├── benchmark.yaml
    └── template/
        ├── 0/
        ├── constant/
        └── system/
```

Minimal `benchmark.yaml` example:

```yaml
id: risingBubble
template: template
profile: standard
parameters:
  end_time:
    file: system/controlDict
    entry: endTime
steps:
  - name: mesh
    command: blockMesh
  - name: solve
    command: '{solver}'
```

The `parameters` mapping tells FoamBench where to change each parameter. For a *real OpenFOAM* environment, modifications use `foamDictionary`; they do not rely on brittle text substitution. Values must match the expected OpenFOAM dictionary syntax. A case with a more complex setup may specify additional steps (`setFields`, `decomposePar`, etc.) or an existing `./Allrun` command. Imported code executes with your permissions: use trusted sources only.

## 7. Select benchmarks and parameter values

In `config/run.yaml`:

```yaml
benchmarks:
  - id: risingBubble
    enabled: true
    source: my-cases
    path: risingBubble
    solver: interFoam
    sweep:
      parameters:
        end_time: ['0.5', '1.0']
```

This runs two copies of the original template, each with a different `endTime`. For a grid, method, or multi-variable study, add more named parameters to both the manifest and `sweep.parameters` (their lists form a Cartesian product). To run only specific tuples, use `sweep.combinations: [{end_time: '0.5'}, {end_time: '1.0'}]`. First check that your OpenFOAM version actually has the named solver.

## 8. Decide resource limits

```yaml
execution:
  total_cores: 8
  max_parallel_cases: 2
  cores_per_case: 4
  max_walltime: '02:00:00'
  on_failure: continue
```

This means at most **two concurrent cases**, each allocated a nominal budget of four cores. **Note:** `cores_per_case` is a scheduling budget, not automatic MPI configuration. For MPI use explicit commands and decompositions in the benchmark's `steps`, e.g. `decomposePar`, `mpirun -np {cores} {solver} -parallel`, `reconstructPar`; set `numberOfSubdomains` consistently. Avoid oversubscribing CPUs through OpenMP or meshing tools. The walltime is a total per-case budget, enforced across steps. If a case exceeds it, the controller terminates its process group.

## 9. Preview, run, inspect

```bash
./Allrun --dry-run
./Allrun
```

Review printed case counts, case paths, commands, and core allocation before actual execution. Each run produces `runs/<run-id>/plan.json`, `config.resolved.json`, per-case logs and statuses, and a `summary.json`.

A successful archived case contains its parameters and provenance in `manifest.json`, checksum verification in `checksums.json`, selected dictionaries, logs, and (when present) `postProcessing/`. Candidates are **not automatically promoted** into trusted references.

## 10. Cleanup, interrupted runs, and references

Default: keep all generated cases. To remove *successful* generated working cases only **after archive verification**:

```yaml
execution:
  cleanup:
    completed_cases: after_archive
    failed_cases: keep
```

Failed working directories always remain for diagnosis. To resume an interrupted run, use `./Allrun --resume <run-id>` with **the same configuration and unchanged sources**; previously completed cases are skipped. If a failed case directory remains, the runner refuses to overwrite it. Inspect and manually relocate that failed directory first, or launch a new run.

Run `python analysis/analyse.py --run <run-id>` to see a Stage-1 status summary. The optional `--reference <id>` checks that an approved reference exists. Actual numerical comparison requires benchmark-specific analysis scripts and is deferred to Stage 3. Do not interpret successful execution as validation of the physical model.

## Troubleshooting

- **`foamDictionary` not found:** check the selected OpenFOAM `bashrc` path and source it manually to test your installation.
- **`Source not fetched`:** run `./fetchCases.sh`; verify Git access or local source path.
- **`Unknown parameter`:** add a mapping under `benchmark.yaml: parameters`.
- **`Missing template`:** check `template:` and `benchmarks[].path`; they resolve relative to the source.
- **Solver fails:** inspect `runs/<run-id>/logs/<case-id>/` and `statuses/<case-id>.json`.
- **No extracted results:** ensure your case writes into `postProcessing/` or specify field files in `archiving.field_paths`.
- **Run marked completed but results wrong:** completion only checks command exit status; benchmark-specific validity checks must be added before scientific reference approval.

## Glossary and further steps

A *parameter sweep* is a series of simulations with deliberately varied inputs; a *mesh-convergence study* changes spatial resolution to assess discretization effects; an *MPI rank* is one OpenFOAM parallel process; *walltime* is elapsed clock time, not simulated physical time. See `docs/ARCHITECTURE.md` before adding complex benchmark hooks or Slurm support.
