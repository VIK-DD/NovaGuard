from pathlib import Path


PROFILE = (
    Path(__file__).resolve().parents[1] / ".zap" / "novaguard-baseline.yaml"
).read_text(encoding="utf-8")
WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "zap-baseline.yml"
).read_text(encoding="utf-8")


def test_zap_profile_scans_only_origins_we_control():
    assert '"https://novaguard.fun"' in PROFILE
    assert '"https://api.novaguard.fun/api/v1/health"' in PROFILE
    assert "scanOnlyInScope: true" in PROFILE
    assert "discord.com" not in PROFILE
    assert "azureedge.net" not in PROFILE
    assert "127.0.0.1" not in PROFILE


def test_zap_profile_identifies_the_authorised_scan_before_crawling():
    assert PROFILE.index("- type: replacer") < PROFILE.index("- type: spider")
    assert "NovaGuard-ZAP-Security-Scan/1.0" in PROFILE
    assert 'url: "^https://(?:api\\\\.)?novaguard\\\\.fun(?:/.*)?$"' in PROFILE


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


def test_zap_workflow_is_manual_and_read_only():
    assert "workflow_dispatch:" in WORKFLOW
    assert "contents: read" in WORKFLOW
    assert "persist-credentials: false" in WORKFLOW
    assert "pull_request:" not in WORKFLOW
    assert "push:" not in WORKFLOW


def test_zap_workflow_runs_the_committed_plan_and_keeps_the_report():
    assert "/zap/wrk/.zap/novaguard-baseline.yaml" in WORKFLOW
    assert ".zap/novaguard-zap-security.html" in WORKFLOW
    assert "chmod a+rwx .zap" in WORKFLOW
    assert "if: ${{ always() }}" in WORKFLOW
