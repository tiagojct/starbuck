# starbuck

Reference-integrity checks for manuscripts. Starbuck reads a Markdown or Quarto
manuscript with its bibliography and checks each cited reference against public
scholarly records. It has a CLI (`starbuck`) and an MCP server (`starbuck-mcp`).

- Tests: `uv run pytest -q` (no network).
- Validation replay (no network): `uv run python validation/run.py --replay validation/recordings/2026-11-14.json.gz`.
  Run it after a change to the checks; the scores must stay the same (65/65 strict, 50/50 specificity). It writes dated files to validation/results/;
  delete the replay files after the comparison.
- Website: site/ (starbuck.tiagojacinto.eu), see site/README.md. Deploy with `cd site && npm run deploy` after a release.
- Sub-Sub pins one Starbuck version (STARBUCK_VERSION in apps/subsub/src/config.ts). Raise it after a release.
- Release: a push to main that changes the version in pyproject.toml publishes to PyPI. Do not change the version
  without approval.

Metadata: workspace.yml. Shared rules: the root CLAUDE.md of the workspace.
