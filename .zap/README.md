# NovaGuard ZAP profile

This profile answers one precise question: does a NovaGuard-owned public
response currently raise a Low, Medium or High ZAP alert?

It does not follow or report Discord OAuth pages, Microsoft/Azure browser
services, localhost traffic or extension traffic. Those systems are outside
NovaGuard's control and were the source of every Medium alert in the
1 September 2026 report.

The generated security report omits Informational observations. They remain
useful during investigation, but they are not vulnerabilities: ZAP explicitly
uses that level for facts such as "Modern Web Application", a theme stored in
`localStorage`, a public response retrieved from cache and a session cookie
being identified.

## Run in ZAP Desktop 2.17+

1. Start a new ZAP session so alerts from an older, unscoped scan are absent.
2. Open the **Automation** tab.
3. Choose **Load Plan** and select `novaguard-baseline.yaml` from this folder.
4. Run the plan.
5. Open `reports/novaguard-zap-security.html` next to this file.

Do not start this check through **Quick Start → Automated Scan**. That workflow
created the mixed report by allowing a browser to leave NovaGuard's scope.

## Run with the official Docker image

From the repository root:

```bash
mkdir -p .zap/reports
docker run --rm \
  -v "$PWD:/zap/wrk:rw" \
  -t ghcr.io/zaproxy/zaproxy:stable \
  zap.sh -cmd -autorun /zap/wrk/.zap/novaguard-baseline.yaml
```

Exit code `0` means no Low-or-higher finding. Exit code `1` means the report
contains something that must be reviewed; it must not be silenced merely to
restore a green result.
