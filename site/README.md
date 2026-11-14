# starbuck.tiagojacinto.eu

The Starbuck website: an 11ty site with the design of the Sub-Sub site. `src/assets/css/site.css`,
`src/assets/js/site.js` and the fonts are copies of `apps/subsub/site/src/assets/`; the Starbuck
changes are in `src/assets/css/starbuck.css` only, so the copies can be refreshed from Sub-Sub.

The pages read the version from `../pyproject.toml`, the Changes page from `../CHANGELOG.md`, and
the validation numbers from the newest live run in `../validation/results/` (not a replay).

## Build

```sh
cd site
npm install
npm run build     # writes _site/
npm run serve     # http://localhost:8080, rebuilds on change
npm run check     # internal links and anchors
```

## Deploy

```sh
cd site
npm run deploy
```

`scripts/deploy.sh` refuses to run with uncommitted changes, builds and checks the site, copies
`_site/` to `/opt/vps/caddy/srv/starbuck.tiagojacinto.eu/releases/<n>-<commit>/` and points
`current` at it. To go back, point `current` at an earlier release. Deploy after each release, so
that the version and the validation numbers are current.
