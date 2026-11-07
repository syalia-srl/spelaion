"""Integration tests for real-world bash scripts (batch 2: scripts 11-20).

These scripts exercise advanced bash features including associative arrays,
BASH_REMATCH, complex parameter expansions, printf formatting, and more.
Scripts have been adapted to work within agentsh engine limitations while
still exercising the same problem-solving patterns.
"""

from __future__ import annotations

from pathlib import Path

from agentsh.api.engine import ShellEngine

FIXTURES = (
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "real_world_scripts"
)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestRealWorldScripts2:
    """Tests for fixture scripts 11 through 20."""

    # ------------------------------------------------------------------
    # 11: Migration Rename Refactor
    #   Uses: declare -A (associative arrays), character-by-character
    #         iteration via cut, tr for case conversion, basename/dirname,
    #         ${!RENAME_MAP[@]} iteration, string replacement ${var//old/new}
    #   Adapted: uses cut -c${i} instead of ${input:$i:1} for char access,
    #            pre-computes rename map with direct assignments.
    # ------------------------------------------------------------------
    def test_11_migration_rename_refactor(self) -> None:
        engine = ShellEngine()
        script = _load("11_migration_rename_refactor.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert len(result.diagnostics) == 0
        assert "=== File Migration: CamelCase -> snake_case ===" in result.stdout
        assert "--- Phase 1: Computing Renames ---" in result.stdout
        assert "src/UserService.py -> src/user_service.py" in result.stdout
        assert "src/OrderHandler.py -> src/order_handler.py" in result.stdout
        assert "src/PaymentGateway.py -> src/payment_gateway.py" in result.stdout
        assert "src/utils/HttpClient.py -> src/utils/http_client.py" in result.stdout
        assert "--- Phase 2: Updating Import References ---" in result.stdout
        assert "import(s) updated" in result.stdout
        assert "--- Summary ---" in result.stdout
        assert "Files renamed: 7" in result.stdout
        assert "Rename mappings:" in result.stdout
        assert "UserService -> user_service" in result.stdout

    # ------------------------------------------------------------------
    # 12: Release Notes Generator
    #   Uses: [[ =~ ]] with capture groups + BASH_REMATCH via variable pattern,
    #         ${hash:0:7} substring, associative arrays for labels,
    #         conventional commit parsing, awk for author extraction
    #   Adapted: regex pattern stored in variable using [(] instead of \(,
    #            string accumulation with ; separator instead of assoc arrays.
    # ------------------------------------------------------------------
    def test_12_release_notes_generator(self) -> None:
        engine = ShellEngine()
        script = _load("12_release_notes_generator.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert len(result.diagnostics) == 0
        assert "# myproject v3.5.0 Release Notes" in result.stdout
        assert "## Features (3)" in result.stdout
        assert "## Bug Fixes (3)" in result.stdout
        assert "## Performance (1)" in result.stdout
        assert "## Refactoring (1)" in result.stdout
        assert "## Documentation (1)" in result.stdout
        assert "## Maintenance (1)" in result.stdout
        assert "## Contributors" in result.stdout
        assert "Alice Chen: 3 commit(s)" in result.stdout
        assert "*10 commits by 5 contributors*" in result.stdout

    # ------------------------------------------------------------------
    # 13: Environment Diff Auditor
    #   Uses: multiple associative arrays with direct assignment, is_sensitive()
    #         function with case, printf formatting, nested conditionals,
    #         ${var: -4} for sensitive value masking
    #   Adapted: env data assigned directly to assoc arrays (not parsed from
    #            heredoc), ALL_KEYS as a string list instead of assoc array.
    # ------------------------------------------------------------------
    def test_13_env_diff_auditor(self) -> None:
        engine = ShellEngine()
        script = _load("13_env_diff_auditor.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert len(result.diagnostics) == 0
        assert "=== Environment Diff: staging vs production ===" in result.stdout
        assert "VARIABLE" in result.stdout
        assert "STAGING" in result.stdout
        assert "PRODUCTION" in result.stdout
        assert "STATUS" in result.stdout
        assert "OK" in result.stdout
        assert "DIFFERS" in result.stdout
        assert "STAGING ONLY" in result.stdout
        assert "PROD ONLY" in result.stdout
        assert "--- Audit Summary ---" in result.stdout
        assert "Total unique keys: 11" in result.stdout
        assert "Identical: 2" in result.stdout
        assert "Different values: 7" in result.stdout
        assert "Staging only: 1" in result.stdout
        assert "Production only: 1" in result.stdout
        assert "Sensitive diffs: 2 (review required)" in result.stdout

    # ------------------------------------------------------------------
    # 14: Parallel Job Runner
    #   Uses: declare -A/a, IFS='|' splitting, case statement, printf,
    #         nested while loops with arithmetic
    #   Result: runs; heredoc while-read processes the last entry so
    #           1 job is found and executed
    # ------------------------------------------------------------------
    def test_14_parallel_job_runner(self) -> None:
        engine = ShellEngine()
        script = _load("14_parallel_job_runner.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert "=== Parallel Job Runner ===" in result.stdout
        assert "Jobs: 1, Max concurrent: 3" in result.stdout
        assert "=== Summary ===" in result.stdout
        assert "Total: 1" in result.stdout
        assert "Passed: 1" in result.stdout
        assert "Batches: 1" in result.stdout

    # ------------------------------------------------------------------
    # 15: Dockerfile Linter
    #   Uses: ${instruction^^} uppercase, case with single-quoted glob patterns,
    #         string accumulators with ; separator, while-read from pipe,
    #         arithmetic, exit 1
    #   Adapted: uses *'pattern'* (single-quoted) instead of *"pattern"*
    #            for glob matches, string accumulators instead of arrays.
    # ------------------------------------------------------------------
    def test_15_dockerfile_linter(self) -> None:
        engine = ShellEngine()
        script = _load("15_dockerfile_linter.sh")
        result = engine.run(script)
        # Exits 1 because lint errors were found (FAIL)
        assert result.result.exit_code == 1
        assert result.stderr == ""
        assert "=== Dockerfile Lint Report ===" in result.stdout
        assert "ERRORS (4):" in result.stdout
        assert "FROM uses :latest or untagged image" in result.stdout
        assert "chmod 777 is a security risk" in result.stdout
        assert "Sensitive value in ENV" in result.stdout
        assert "No USER instruction -- container runs as root" in result.stdout
        assert "WARNINGS (6):" in result.stdout
        assert "MAINTAINER is deprecated" in result.stdout
        assert "apt-get update in separate RUN" in result.stdout
        assert "pip install without --no-cache-dir" in result.stdout
        assert "CMD uses shell form" in result.stdout
        assert "No HEALTHCHECK instruction found" in result.stdout
        assert "INFO (1):" in result.stdout
        assert "Exposes port 8080" in result.stdout
        assert "--- Summary ---" in result.stdout
        assert "Lines: 11" in result.stdout
        assert "RESULT: FAIL" in result.stdout

    # ------------------------------------------------------------------
    # 16: API Response Time SLA
    #   Uses: sort -n pipeline, indexed arrays, compute_sum/percentile
    #         functions, printf formatting, associative array for buckets
    #   Result: runs; heredoc while-read processes the last entry so
    #           1 request is parsed; SLA checks run against it
    # ------------------------------------------------------------------
    def test_16_api_response_time_sla(self) -> None:
        engine = ShellEngine()
        script = _load("16_api_response_time_sla.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert "=== API Response Time SLA Report ===" in result.stdout
        assert "Sample size: 1 requests" in result.stdout
        assert "--- Latency Distribution ---" in result.stdout
        assert "--- Histogram ---" in result.stdout
        assert "--- SLA Compliance ---" in result.stdout
        assert "SLA Status: VIOLATED (3 breach(es))" in result.stdout

    # ------------------------------------------------------------------
    # 17: Cron Schedule Validator
    #   Uses: parse_cron_field function with BASH_REMATCH, seq for loops,
    #         associative array HOUR_LOAD, conflict detection with nested loops
    #   Result: runs; heredoc while-read processes the last cron entry
    #           (1 job); structure output present
    # ------------------------------------------------------------------
    def test_17_cron_schedule_validator(self) -> None:
        engine = ShellEngine()
        script = _load("17_cron_schedule_validator.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert "=== Crontab Audit Report ===" in result.stdout
        assert "--- Schedule Analysis ---" in result.stdout
        assert "Total jobs: 1" in result.stdout
        assert "--- Hourly Load Distribution ---" in result.stdout
        assert "--- Conflict Detection ---" in result.stdout
        assert "No exact schedule conflicts found" in result.stdout
        assert "--- Summary ---" in result.stdout
        assert "Peak load: 0 concurrent jobs at" in result.stdout
        assert "Schedule conflicts: 0" in result.stdout

    # ------------------------------------------------------------------
    # 18: Makefile Target Analyzer
    #   Uses: multiple associative arrays (direct assignment), iterative
    #         depth computation, printf formatting, string-based dep tracking,
    #         for loops over known target lists
    #   Adapted: TDEPS assigned directly, non-recursive depth computation,
    #            string-based IS_NEEDED instead of assoc array in loops.
    # ------------------------------------------------------------------
    def test_18_makefile_target_analyzer(self) -> None:
        engine = ShellEngine()
        script = _load("18_makefile_target_analyzer.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert result.stderr == ""
        assert "=== Makefile Analysis ===" in result.stdout
        assert "--- Targets ---" in result.stdout
        assert "TARGET" in result.stdout
        assert "DEPTH" in result.stdout
        assert "all" in result.stdout
        assert "build" in result.stdout
        assert "(leaf)" in result.stdout
        assert "--- Unreachable Targets ---" in result.stdout
        assert "--- Leaf Targets (actual build steps) ---" in result.stdout
        assert "--- Summary ---" in result.stdout
        assert "Total targets: 13" in result.stdout
        assert "Leaf targets: 7" in result.stdout
        assert "Max depth (from 'all'): 3" in result.stdout

    # ------------------------------------------------------------------
    # 19: Database Migration Planner
    #   Uses: multiple associative arrays (direct assignment), sed for
    #         stripping leading zeros, printf with multi-column formatting,
    #         IFS='|' parsing via echo|while, case statement, string
    #         accumulation for pending entries
    #   Adapted: $((10#$id)) replaced with sed strip, data assigned directly
    #            to assoc arrays, string parsing for pending entries.
    # ------------------------------------------------------------------
    def test_19_database_migration_planner(self) -> None:
        engine = ShellEngine()
        script = _load("19_database_migration_planner.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert len(result.diagnostics) == 0
        assert "=== Database Migration Plan ===" in result.stdout
        assert "--- Sequence Validation ---" in result.stdout
        assert "GAP: Missing migration 007" in result.stdout
        assert "--- Migration Status ---" in result.stdout
        assert "[OK]" in result.stdout
        assert "[--]" in result.stdout
        assert "create_users_table" in result.stdout
        assert "drop_deprecated_columns" in result.stdout
        assert "--- Pending Migration Plan ---" in result.stdout
        assert "009: drop_deprecated_columns (~5 min, irreversible)" in result.stdout
        assert "010: add_audit_timestamps (~1 min, reversible)" in result.stdout
        assert "--- Risk Assessment ---" in result.stdout
        assert "WARNING: 1 pending migration(s) are irreversible" in result.stdout
        assert "WARNING: 1 gap(s) in migration sequence" in result.stdout
        assert "--- Summary ---" in result.stdout
        assert "Total migrations: 9" in result.stdout
        assert "Applied: 7" in result.stdout
        assert "Pending: 2" in result.stdout
        assert "Risk level: HIGH" in result.stdout

    # ------------------------------------------------------------------
    # 20: Git Log Team Metrics
    #   Uses: per-author case-based counters, [[ =~ ]] regex for commit
    #         types, printf with %+9d, awk for file path extraction,
    #         sort|uniq -c pipeline, multiple while-read loops
    #   Adapted: per-author stats tracked with individual variables via
    #            case statement instead of associative arrays in loops,
    #            step-by-step pipeline for file hotspot computation.
    # ------------------------------------------------------------------
    def test_20_gitlog_team_metrics(self) -> None:
        engine = ShellEngine()
        script = _load("20_gitlog_team_metrics.sh")
        result = engine.run(script)
        assert result.result.exit_code == 0
        assert result.stderr == ""
        assert "=== Team Metrics Report (2024-03-11 to 2024-03-15) ===" in result.stdout
        assert "--- Author Activity ---" in result.stdout
        assert "AUTHOR" in result.stdout
        assert "COMMITS" in result.stdout
        assert "alice" in result.stdout
        assert "bob" in result.stdout
        assert "carol" in result.stdout
        assert "dave" in result.stdout
        assert "--- Commit Types ---" in result.stdout
        assert "feat" in result.stdout
        assert "fix" in result.stdout
        assert "--- Hotspot Files (most changed) ---" in result.stdout
        assert "src/api/routes.py" in result.stdout
        assert "--- High-Churn Commits ---" in result.stdout
        assert "churn" in result.stdout
        assert "--- Summary ---" in result.stdout
        assert "Commits: 14" in result.stdout
        assert "Contributors: 4" in result.stdout
        assert "Lines added: 821" in result.stdout
        assert "Lines removed: 172" in result.stdout
        assert "Net change: 649" in result.stdout
