"""1.0-C: the release pipeline's structure: single updater build, locked and uncontaminated release venv, fail-closed production
secrets, credential hardening, concurrency and truthful naming. Static (text/structure) checks plus the offline lock check."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.itemcheck

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def _steps(workflow: str) -> list[str]:
    """The workflow text split into its steps (each starts at '      - name:')."""
    return re.split(r"(?m)^      - name: ", workflow)[1:]


def _job_blocks(workflow: str) -> dict[str, str]:
    body = workflow.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z0-9-]+):\n", body)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


RELEASE = _read(".github/workflows/release.yml")
SIGNING = _read(".github/workflows/update-signing-validation.yml")
CLOUD = _read(".github/workflows/cloud-deploy.yml")
PR = _read(".github/workflows/pr-validation.yml")


# --- release dependency lock / venv -------------------------------------------------------------------------------------


def test_release_lock_is_consistent_offline():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "lock_release_deps.py"), "--check"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lock check OK" in result.stdout


def test_lock_check_runs_in_pr_validation_and_in_the_release_workflow():
    for text in (PR, RELEASE):
        assert "scripts/lock_release_deps.py --check" in text


def test_release_venv_install_is_hash_locked_and_pinned_to_python_version_file():
    preflight = _read("scripts/release_python_preflight.ps1")
    assert "--require-hashes" in preflight and "requirements-release.lock" in preflight
    assert ".python-version" in preflight
    assert "Assert-ReleaseVenvUncontaminated -PythonExecutable $venvPython" in preflight  # invoked, not only defined
    assert "contaminated" in preflight


def test_nothing_but_the_locked_install_writes_into_the_release_venv():
    for path in sorted((ROOT / "scripts").glob("*.ps1")) + sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "pip install" in line and path.name != "release_python_preflight.ps1":
                assert ".release-venv" not in line and "$ReleaseVenv" not in line and "$releasePy" not in line, f"{path.name}: {line}"
    assert not re.search(r"(?i)pip install(?!.*--require-hashes)[^\n]*(\$venvPython|\.release-venv)", _read("scripts/build_exe.ps1"))


def test_the_disposable_update_script_is_honestly_named_and_never_touches_the_release_venv():
    assert not (ROOT / "scripts" / "smoke_disposable_update_e2e.ps1").exists()
    script = _read("scripts/smoke_disposable_update_tests.ps1")
    assert "NOT a binary end-to-end" in script
    code = re.sub(r"(?s)<#.*?#>", "", script)  # the help block may DESCRIBE the rule; the code must not break it
    assert "pip install" not in code and ".release-venv" not in code and "$releasePy" not in code
    for path in list((ROOT / "docs").glob("*.md")) + list(WORKFLOWS.glob("*.yml")) + list((ROOT / "scripts").iterdir()):
        if path.is_file() and path.name not in ("1.0-HARDENING-PLAN.md",):
            assert "smoke_disposable_update_e2e" not in path.read_text(encoding="utf-8", errors="ignore"), path.name


# --- updater is built exactly once --------------------------------------------------------------------------------------


def test_the_updater_is_built_once_by_build_exe_and_the_workflow_does_not_rebuild_it():
    build = _read("scripts/build_exe.ps1")
    invocations = re.findall(r'(?m)^\s*&\s*\(Join-Path \$PSScriptRoot "build_updater\.ps1"\)', build)
    assert len(invocations) == 1
    assert build.index('"build_updater.ps1"') < build.index("& $PythonExe $ProvenanceScript")  # hashed AFTER the one build
    assert "--updater-built" in build
    assert "build_updater.ps1" not in RELEASE
    assert len(re.findall(r"-File \.\\scripts\\build_exe\.ps1", RELEASE)) == 1
    # nothing after provenance may replace the staged updater
    tail = build.split("& $PythonExe $ProvenanceScript", 1)[1]
    assert "-m PyInstaller" not in tail and '"build_updater.ps1"' not in tail


def test_provenance_script_requires_the_single_build_output():
    script = _read("scripts/validate_release_binary_provenance.py")
    assert '"--updater-built", required=True' in script


# --- production-secret hardening ----------------------------------------------------------------------------------------


def test_main_only_guards_exist_everywhere_production_secrets_are_reachable():
    assert "refs/heads/main" in RELEASE and _steps(RELEASE)[0].startswith("Reject dispatches outside main")
    jobs = _job_blocks(SIGNING)
    assert "environment:" not in jobs["validate-test-signing"]
    prod = jobs["validate-production-signing"]
    assert "environment: production-release" in prod and "github.ref == 'refs/heads/main'" in prod
    assert _steps(prod)[0].startswith("Reject dispatches outside main")
    assert "if: ${{ github.ref == 'refs/heads/main' }}" in _job_blocks(CLOUD)["deploy"]
    assert any(step.startswith("Reject dispatches outside main") for step in _steps(CLOUD))


def test_use_production_secret_false_never_reaches_the_production_key():
    jobs = _job_blocks(SIGNING)
    test_job = jobs["validate-test-signing"]
    assert "secrets." not in test_job and "materialize_update_signing_key" not in test_job
    assert "if: ${{ !inputs.use_production_secret }}" in test_job
    assert "inputs.use_production_secret &&" in jobs["validate-production-signing"]


def test_signing_key_secret_is_referenced_by_exactly_one_step_and_removed_afterwards():
    for name, text in (("release.yml", RELEASE), ("update-signing-validation.yml", SIGNING)):
        assert text.count("secrets.EXILELENS_UPDATE_SIGNING_KEY_B64") == 1, name
        steps = _steps(text)
        holders = [s for s in steps if "secrets.EXILELENS_UPDATE_SIGNING_KEY_B64" in s]
        assert len(holders) == 1 and holders[0].startswith("Materialize"), name
        assert "run: |" in holders[0] and "echo" not in holders[0].lower().replace("# echo", "")  # nothing echoes key material
        removals = [s for s in steps if s.startswith("Remove production update signing key material")]
        assert len(removals) == 1 and "if: ${{ always() }}" in removals[0] and "Remove-Item" in removals[0], name
    release_steps = [s.split("\n", 1)[0] for s in _steps(RELEASE)]
    assert release_steps.index("Remove production update signing key material") < release_steps.index("Create published release")


def test_cloudflare_credentials_are_step_scoped_not_job_scoped():
    deploy = _job_blocks(CLOUD)["deploy"]
    header = deploy.split("    steps:\n", 1)[0]
    assert "secrets." not in header  # not visible to npm ci / typecheck / tests
    holders = [s.split("\n", 1)[0] for s in _steps(CLOUD) if "secrets.CLOUDFLARE_API_TOKEN" in s]
    assert holders == ["Require credentials and a real database id", "Apply D1 migrations (remote, additive only)", "Deploy Worker"]
    for step in _steps(CLOUD):
        if step.startswith(("Install locked dependencies", "Typecheck and test")):
            assert "secrets." not in step


def test_no_secret_is_echoed_by_the_signing_materializer():
    script = _read("scripts/materialize_update_signing_key.ps1")
    assert "PEM contents not logged" in script
    assert not re.search(r"Write-Host[^\n]*\$keyB64|Write-Host[^\n]*\$pemText|Write-Output[^\n]*\$keyB64", script)


# --- checkout credentials and concurrency -------------------------------------------------------------------------------


@pytest.mark.parametrize("name,text", [("release", RELEASE), ("update-signing-validation", SIGNING), ("cloud-deploy", CLOUD)])
def test_release_sensitive_checkouts_do_not_persist_credentials(name, text):
    checkouts = [s for s in _steps(text) if "actions/checkout@" in s]
    assert checkouts, name
    for step in checkouts:
        assert "persist-credentials: false" in step, f"{name}: {step.splitlines()[0]}"


def test_release_steps_that_need_github_pass_gh_token_explicitly():
    steps = {s.split("\n", 1)[0]: s for s in _steps(RELEASE)}
    assert "GH_TOKEN: ${{ github.token }}" in steps["Create published release"]
    assert "GH_TOKEN: ${{ github.token }}" in steps["Validate release request and existing remote state"]


def test_release_and_signing_and_cloud_runs_are_serialized_without_cancelling_a_publication():
    for text, group in ((RELEASE, "release-production"), (SIGNING, "update-signing-validation"), (CLOUD, "cloud-deploy-${{ inputs.environment }}")):
        block = re.search(r"(?m)^concurrency:\n  group: (.+)\n  cancel-in-progress: (\w+)\n", text)
        assert block is not None and block.group(1) == group and block.group(2) == "false"


def test_pull_request_ci_does_not_serialize_unrelated_runs_or_build_the_package():
    assert "concurrency:" not in PR
    assert "build_exe.ps1" not in PR and "PyInstaller" not in PR  # the expensive build stays in the release / dry_run path


# --- pipeline wiring ----------------------------------------------------------------------------------------------------


def test_release_runs_source_secret_scan_leak_scan_and_the_artifact_gate_in_order():
    names = [s.split("\n", 1)[0] for s in _steps(RELEASE)]
    assert names.index("Release inputs are reproducible and secret-free (static, offline)") < names.index("Run source release gate")
    assert names.index("Build the official Windows onedir distribution") < names.index("Run packaged-artifact release gate")
    assert names.index("Package and verify release assets") < names.index("Leak scan the package directory and the final ZIP") < names.index("Create published release")
    assert "--require-artifact" in RELEASE and "leak_scan source" in RELEASE


def test_release_workflow_still_cannot_publish_from_a_dry_run():
    for step in _steps(RELEASE):
        if step.startswith(("Create published release", "Build Discord", "Announce published")):
            assert "if: ${{ !inputs.dry_run }}" in step


def test_pr_validation_runs_the_1_0c_static_guards():
    for token in ("generate_packaging_version_info.py --check", "exilelens.ops.leak_scan source .", "test_release_1_0c_pipeline.py", "test_release_1_0c_update_gaps.py"):
        assert token in PR


def test_the_qt_gpl_filter_matches_between_spec_and_gate():
    from exilelens.ops.release_gate import GPL_ONLY_QT_BINARY_TOKENS

    spec = _read("packaging/exilelens-gui.spec")
    tokens = tuple(re.findall(r'"([^"]+)"', re.search(r"_GPL_ONLY_QT_BINARY_TOKENS = \(([^)]*)\)", spec).group(1)))
    assert tokens == GPL_ONLY_QT_BINARY_TOKENS
