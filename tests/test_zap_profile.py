from pathlib import Path


PROFILE = (
    Path(__file__).resolve().parents[1] / ".zap" / "novaguard-baseline.yaml"
).read_text(encoding="utf-8")


def test_zap_profile_scans_only_origins_we_control():
    assert '"https://novaguard.fun"' in PROFILE
    assert '"https://api.novaguard.fun"' in PROFILE
    assert "scanOnlyInScope: true" in PROFILE
    assert "discord.com" not in PROFILE
    assert "azureedge.net" not in PROFILE
    assert "127.0.0.1" not in PROFILE


def test_zap_profile_never_hides_a_real_security_finding():
    assert "- high" in PROFILE
    assert "- medium" in PROFILE
    assert "- low" in PROFILE
    assert "errorLevel: Low" in PROFILE
    assert "False Positive" not in PROFILE
    assert "disableAllRules: true" not in PROFILE


def test_zap_profile_exercises_the_former_timestamp_finding():
    assert 'url: "https://api.novaguard.fun/api/v1/auth/login"' in PROFILE
    assert "responseCode: 302" in PROFILE


def test_zap_report_is_written_next_to_the_plan():
    assert 'reportFile: "novaguard-zap-security.html"' in PROFILE
    assert "reportDir:" not in PROFILE
