# Architecture and implementation contract (v0.1.0)

## Layers

1. `sources/`: Git clone destinations. Local sources are referenced by absolute/relative paths and **never copied into** `sources/`. `fetchCases.sh` fetches Git and checks local directories; the CLI reads benchmark templates directly from the source.
2. `benchmark.yaml`: benchmark-specific template, parameter-to-OpenFOAM-dictionary mappings, and execution steps. The benchmark must be represented by a *trusted* source directory. The framework does not autodiscover arbitrary OpenFOAM folders without a manifest.
3. `config/run.yaml`: selected OpenFOAM environment, source aliases, benchmark selectors, sweeps, resource limits, archive and cleanup policy. One environment for the entire invocation.
4. `runs/<run-id>/`: generated working cases, step logs, status files, resolved configuration and plan. `plan.json` fingerprint is calculated from config, source identities, template content hashes, benchmark manifests, parameters and commands.
5. `references/candidates/<run-id>/<case-id>/`: results copied only after all steps exit successfully; checksum verification before optional working case deletion. `approved/` is intentionally unmanaged until scientific reference approval and comparison are implemented.

## YAML example for real OpenFOAM

```yaml
study: {name: hysing-grid-test}
sources:
  - {name: local-cases, type: local, path: /home/me/HysingBenchmarks}
openfoam:
  environment: of2506
  environments:
    of2506:
      type: openfoam
      bashrc: /opt/OpenFOAM/OpenFOAM-v2506/etc/bashrc
execution:
  total_cores: 8
  max_parallel_cases: 2
  cores_per_case: 4
  max_walltime: '02:00:00'
  on_failure: continue
  cleanup: {completed_cases: keep, failed_cases: keep}
archiving:
  enabled: true
  include: [dictionaries, logs, extracted_results, selected_fields]
  field_paths: ['0/U']
benchmarks:
  - id: risingBubble
    source: local-cases
    path: risingBubble
    solver: interFoam
    sweep:
      parameters:
        end_time: ['0.5','1.0']
```

Benchmark manifest example:

```yaml
id: risingBubble
template: template
profile: standard
parameters:
  end_time: {file: system/controlDict, entry: endTime}
steps:
  - {name: mesh, command: blockMesh}
  - {name: decompose, command: decomposePar -force}
  - {name: solve, command: 'mpirun -np {cores} {solver} -parallel'}
  - {name: reconstruct, command: reconstructPar}
```

`{solver}` and `{cores}` are the only built-in step tokens. Shell steps run in a fresh shell sourcing the *same selected* OpenFOAM environment. When using MPI, configure `decomposeParDict` yourself; `cores_per_case` limits concurrent resource scheduling but does not edit MPI settings. Solver binaries and templates must be supplied by users.

## Profiles

`profiles/standard.yaml` and `profiles/twophaseflow.yaml` document required utilities and compatibility. In v0.1.0 profile labels are stored in provenance and declared **required executables are preflight-checked** under the selected environment before execution, but profile-specific dependency installation/building and compiled-library validation are not implemented. Before running, independently verify required libraries, Gmsh and utilities for your chosen OpenFOAM version. TwoPhaseFlow releases are specific to OpenCFD/OpenFOAM.com; this scaffold does not make them portable to Foundation versions.

## CLI

- `./install.sh`: installs base Python package into `.venv` (optional argument `analysis` or `casefoam` selects Python extras). Does not install OpenFOAM, MPI, Gmsh, or case-specific packages.
- `./fetchCases.sh [config-path]`: imports Git sources or validates local directories.
- `./Allrun --config config/run.yaml --dry-run`: validates and displays selected cases, resolved parameter values, command steps and core resource envelope; creates **no run directories**.
- `./Allrun --config config/run.yaml`: executes a new run.
- `./Allrun --config config/run.yaml --resume RUN_ID`: skips completed cases if the resolved fingerprint matches; refuses failed case directories instead of deleting them.
- `python analysis/analyse.py --run RUN_ID`: reports run status/archives only; not physical-error comparisons yet.

## Generation, scheduling, failure and archive semantics

- Sweeps support Cartesian product `sweep.parameters` and explicit `sweep.combinations`. Every variation receives a parameter-based ID.
- Real OpenFOAM dictionary updates call `foamDictionary -entry ... -set ...` under the sourced OpenFOAM environment. Synthetic mock fixture uses a small text replacer only to enable tests without OpenFOAM.
- A generated case copies the whole template to an isolated directory; the imported source remains intact.
- The local scheduler uses a bounded thread pool; concurrency is `min(max_parallel_cases, total_cores // cores_per_case)`. It does not enforce CPU affinity or physical memory limits.
- The **walltime includes all steps of a single case**; process groups are terminated on timeout. MPI subprocesses may have distinct process shutdown behavior depending on MPI implementation.
- Step exit code 0 means *command-level* success only. No OpenFOAM numerical-completion parsing, divergence detection or scientific quality metrics are included in Stage 1.
- When enabled, archives copy input dictionaries (excluding `polyMesh` and processor directories), logs, and `postProcessing` tree. Optional selected field files must be explicitly named with relative paths. Very large `postProcessing` directories may therefore produce large archives.
- `references/candidates/` is an output location for results, **not a trusted baseline**. Approval and numerical comparisons are not implemented.
- `cleanup.completed_cases: after_archive` deletes only the generated successful case after archive checksums are verified; otherwise the generated directory is preserved. Failed cases are always kept.
- No automatic rerun of failed cases; a resume refuses to overwrite a failed working directory. This is a deliberate safety default.

## Security and scientific caveats

- Manifest commands use Bash and have the same privileges as the invoking user. Do not import unknown or untrusted benchmark repositories.
- Git import runs `git fetch` and `checkout --detach FETCH_HEAD`; existing Git clone URLs must match config. Local sources are not rewritten.
- Runtime commands, shell environment and `foamDictionary` vary by OpenFOAM release; a basic path existence check is not full compatibility validation.
- The framework currently provides a **minimal executable foundation** rather than a universal adapter for all OpenFOAM scripts and multi-region cases. Complex cases can supply custom commands and preprocessors, but their correctness has not yet been tested on real solver builds.
- Reference promotion should only happen after comparing against accepted scientific data and validating mesh/physics/solver behavior.

## Planned expansions

1. Make profiles executable install/build/validation recipes, including per-OpenFOAM-version compiled external libraries.
2. Provide optional explicitly-approved Python dependency installation from benchmark manifests and compatible Gmsh versions.
3. Add robust `Allrun`/`Allclean` legacy adapters, configurable prepare/execute/post steps, nested region handling and parameter-hook functions.
4. Provide SLURM backend and multi-host scheduling.
5. Add numerical status checks, richer structured metrics, scientific reference approval, baseline comparisons and plots.
6. Add direct built-in data extraction for diverse CFD post-processors and mesh-convergence reports.

No real solver benchmarks or external scientific results have yet been validated.
