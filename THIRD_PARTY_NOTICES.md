# Third-party notices

NovaGuard includes and depends on third-party software. NovaGuard's Apache-2.0
license does not replace the licenses of those components. Exact resolved
versions are recorded in `requirements.lock` and `website-3/package-lock.json`;
the package distributions remain the authoritative source for their copyright,
license and notice texts.

## Distributed font assets

The soft-launch website distributes these self-hosted font files:

- Manrope — Copyright 2019 The Manrope Project Authors; SIL Open Font License
  1.1.
- DM Mono — Copyright 2020 The DM Mono Project Authors; SIL Open Font License
  1.1.

`website-3/scripts/soft-launch.mjs` copies the complete license texts from the
installed Fontsource packages into the deployed artifact as
`assets/THIRD-PARTY-FONT-LICENSES.txt`. The script fails the build if its source
font packages are unavailable.

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
