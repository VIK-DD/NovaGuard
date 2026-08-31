"""Security-header constants for the dashboard API.

Deliberately free of imports, environment reads and any other import-time side
effect. `core.webserver` configures itself from the environment the moment it
is imported, so a test that only wants to assert a header value must not be
the thing that triggers that import: whichever test file imports it first
fixes the configuration for the whole pytest session.
"""

# This is a pure JSON API: forbid loading or executing any resource at all.
# base-uri, form-action and frame-ancestors are spelled out because none of
# them falls back to default-src — omitting one allows anything for it, which
# is what a scanner reports as "directive with no fallback".
API_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

# Nothing here is a browser feature this API could ever need, and a JSON
# endpoint has no legitimate reason to ask for a camera. The value is cheap
# insurance rather than a fix for anything reachable: if a response from this
# origin is ever rendered as a document - a mistaken Content-Type, a future
# HTML error page - the features are already off.
API_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), "
    "fullscreen=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), "
    "midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), "
    "screen-wake-lock=(), usb=(), xr-spatial-tracking=()"
)
