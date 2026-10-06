# Third-party notices

NovaGuard includes and depends on third-party software. NovaGuard's Apache-2.0
license does not replace the licenses of those components. Exact resolved
versions are recorded in `requirements.lock` and `website-3/package-lock.json`;
the package distributions remain the authoritative source for their copyright,
license and notice texts.

## Distributed font assets

The website self-hosts these font files, all four bundled from their Fontsource
packages by the Astro build:

- Manrope — Copyright 2019 The Manrope Project Authors; SIL Open Font License
  1.1.
- DM Mono — Copyright 2020 The DM Mono Project Authors; SIL Open Font License
  1.1.
- Hanken Grotesk — Copyright 2021 The Hanken Grotesk Project Authors; SIL Open
  Font License 1.1.
- Outfit — Copyright 2021 The Outfit Project Authors; SIL Open Font License 1.1.

The Coming Soon page is built separately and carries only the two faces it
uses: `website-3/scripts/soft-launch.mjs` copies the complete Manrope and DM
Mono license texts from the installed Fontsource packages into that artifact as
`assets/THIRD-PARTY-FONT-LICENSES.txt`, and fails the build if either source
package is unavailable. The license files for all four ship inside their
Fontsource packages and are inventoried by the SBOM below.

## Release inventory

For every release, retain inventories generated from the exact locked/install
environment, together with the completed private compliance evidence record:

```bash
python -m pip inspect --local
cd website-3
npm run sbom
```

The Node command emits a CycloneDX SBOM for production dependencies. Review
packages with non-permissive, unknown or compound license expressions before
redistribution; an inventory is not a substitute for reading the applicable
license and `NOTICE` files.
