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
- Run `python3 -m unittest discover -s tests -v`, `python3 scripts/validate.py`, and `node --check site/app.js` before publishing.
- GitHub account: inh1095. Do not modify unrelated repositories or global Git credentials.
