"""Small public checks that do not depend on internal fixtures or local PoB data."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_build_inputs_are_present_and_pinned() -> None:
    requirements = ROOT / "packaging" / "requirements-release.txt"
    assert requirements.is_file()
    pins = [line for line in requirements.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert pins
    assert all("==" in line for line in pins)
    for relative in (
        "scripts/build_exe.ps1",
        "scripts/release_python_preflight.ps1",
        "scripts/validate_release_binary_provenance.py",
        "packaging/poe2value-gui.spec",
    ):
        assert (ROOT / relative).is_file(), relative


def test_public_documentation_and_attribution_are_present() -> None:
    for relative in ("README.md", "LICENSE", "SECURITY.md", "PRIVACY.md", "packaging/THIRD_PARTY_NOTICES.txt"):
        assert (ROOT / relative).is_file(), relative
