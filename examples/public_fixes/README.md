# Reviewed public-project delivery patches

These eight SQL models are reproducible delivery artifacts for the pinned
Snowflake data-eng-bench public development tasks. They are stored outside
all solver workspaces. They are **operator-reviewed patches**, not eight new
autonomous model runs. provenance.json records the original four Flash candidates
and reviewed patch hashes. expanded-provenance.json records the four additional
operator-developed patches, public sources and development-feedback boundaries.

- Refund, customer and inventory SQL retain the recorded passing Flash changes.
- Product SQL repairs orphan product attribution: retain a valid direct product;
  otherwise use an unambiguous variant that maps to an existing product. Verify
  lookup uniqueness and source quantity/revenue reconciliation independently.
- The four additional models address timestamp parsing, continuous daily reporting,
  settlement-date FX and cohort retention. Their development failures are retained.
- The public project's existing sources and macros remain dependencies.
- Derived upstream SQL follows the Apache-2.0 license and notice in
  ../../LICENSES/data-eng-bench/.

From the repository root, with the pinned input snapshot already fetched:

```powershell
.venv/Scripts/python.exe scripts/verify_public_fixes.py
```

This default command selects the original four tasks. It creates fresh isolated
cases, materializes each candidate and its current ancestors, builds each target,
then executes the original
upstream tests outside its workspace. It invokes no model provider. Existing
cases/results are never overwritten; select a new --case-root and --output to
repeat local acceptance. Results are in artifacts/acceptance, separate from
autonomous Agent evaluations. Actual scores are documented after execution.

A fresh Agent run starts from the public project's original inputs and missing
or broken target, not from these patches. Its new context profiles selected
relationships for orphan keys and lookup uniqueness; it must still decide and
validate the requested business semantics.

The expanded four tasks are explicit and use the pinned upstream materialization
and pytest policy, with UTC declared for both dbt and verifier connections:

```powershell
.venv/Scripts/python.exe scripts/verify_public_fixes.py --snapshot external/data-eng-bench-expanded --case-root external/native-cases/my-expanded-check --output artifacts/acceptance/my-expanded-check.json --task dbt-fix-timezone-sales --task dbt-fix-daily-revenue --task dbt-exchange-rate-settlement-date --task cohort-retention-matrix --acceptance-policy upstream_harness --duckdb-timezone UTC
```

The timezone task inherits failing order-key quality tests from its original
source. Its raw extra `dbt build` failure remains visible as `project_quality`;
the explicit upstream policy requires real materialization and unchanged original
pytest assertions. It does not relabel that build as successful. See
[the task-by-task explanation](../../docs/PUBLIC_EIGHT_TASKS.md).
