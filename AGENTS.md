# Next Fest 2026

- Public static research site for `inh1095/nextfest-2026`.
- Preserve observations. Missing or failed readings are null, never zero.
- Steam base and demo AppIDs must remain separate.
- Do not label community membership counts as followers.
- No SteamDB scraping, invented historic samples, inferred wishlists, or unsupported causal claims.
- Automated collection uses public Steam endpoints, with a fixed event end guard.
- Astra reviews design, content and behavior. GPT-6.1-SOL collects and verifies source evidence.
- Only reviewed analyses may be stored in `analyses`. New samples do not renew their review dates.
- Site files are in `site/`; configuration source is `config/manifest.json`.
- The complete registration catalog is `site/data/catalog.json`; `config.games` only retains the two original priority games and their evidence.
- Use `scripts/fleet.py` for schema 2 collection. Do not run the legacy two-game collector against production.
- Per-game histories are immutable evidence. Rebuild summary/event indexes after collection; never turn pending/error values into zeros.
- One writer at a time. Persist daily request reservations before network collection and retain abandoned reservations.
- Use `scripts/merge_legacy.py` to merge original records before transition; preserve conflicts for manual investigation instead of overwriting.
- List, CCU, news and reviewed-analysis coverage are separate. One reading is a baseline, not a trend or causal analysis.
- Run `python3 -m unittest discover -s tests -v`, `python3 scripts/validate.py`, and `node --check site/app.js` before publishing.
- GitHub account: inh1095. Do not modify unrelated repositories or global Git credentials.
