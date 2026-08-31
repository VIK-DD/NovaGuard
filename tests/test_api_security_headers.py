"""The API's own security headers, checked without starting a server.

The website worker and this API are separate codebases that each set their own
headers, so a policy tightened on one side does not reach the other. These
checks pin the API side directly.
"""

from core.api_security import API_CONTENT_SECURITY_POLICY, API_PERMISSIONS_POLICY


def _directives(policy: str) -> dict[str, str]:
    """Split a CSP header into {directive: value}."""
    parsed = {}
    for part in policy.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition(" ")
        parsed[name.lower()] = value.strip()
    return parsed


def test_policy_declares_every_directive_that_has_no_fallback():
    # base-uri, form-action and frame-ancestors do not fall back to
    # default-src. Leaving one out is the same as allowing anything for it,
    # which is what a scanner reports as "directive with no fallback".
    directives = _directives(API_CONTENT_SECURITY_POLICY)
    for directive in ("base-uri", "form-action", "frame-ancestors"):
        assert directive in directives, f"{directive} is missing from the API CSP"


def test_a_json_api_forbids_loading_anything():
    directives = _directives(API_CONTENT_SECURITY_POLICY)
    assert directives["default-src"] == "'none'"
    # Nothing here ever renders a form or a frame, so both are closed outright
    # rather than merely restricted to same-origin.
    assert directives["form-action"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"


def test_policy_allows_no_inline_or_eval_escape_hatch():
    assert "unsafe-inline" not in API_CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in API_CONTENT_SECURITY_POLICY


def test_permissions_policy_closes_the_features_worth_closing():
    # A JSON endpoint has no use for any of these. The header costs nothing
    # and means a response from this origin rendered as a document - a wrong
    # Content-Type, a future HTML error page - starts with them off.
    entries = {
        part.split("=", 1)[0].strip()
        for part in API_PERMISSIONS_POLICY.split(",")
        if "=" in part
    }
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert feature in entries, f"{feature} is not restricted"


def test_permissions_policy_grants_nothing_to_anyone():
    # Every allowlist must be empty: `feature=()`. A stray `*` or `self` here
    # would be worse than no header, because it reads as deliberate.
    for part in API_PERMISSIONS_POLICY.split(","):
        part = part.strip()
        if not part:
            continue
        assert part.endswith("=()"), f"{part} grants something"
