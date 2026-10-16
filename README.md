<p align="center"><img src="imgs/veiled-eye-logo.png" width="160" alt="Veiled Eye"></p>
<h1 align="center">Veiled Eye</h1>
<p align="center"><em>Every shadow has a story.</em></p>

Veiled Eye is an identity investigation tool for OSINT and CTI work. Give it an
e-mail, a username, a phone number or a crypto wallet; it runs 46 sources in
parallel, follows every lead they return (a GitHub account found by maigret
is looked up on GitHub, a wallet in a bio goes to the wallet module, …) and
correlates the results into one profile, with exports for your case file.

<p align="center"><img src="imgs/screen-investigation.png" width="900" alt="Investigation page"></p>

- **One search box.** The type of the selector is detected for you.
- **Account discovery** on thousands of sites (maigret, WhatsMyName,
  user-scanner) and on indexed cybercrime forums (dark-sherlock), each account
  tagged with its platform category: underground forum, forum, social network,
  messaging, developer, gaming…
- **Cross analysis.** Accounts are graded *confirmed / likely / candidate* by
  the number of independent sources; names, e-mails, locations and
  organisations are ranked by agreement; the same profile picture behind two
  accounts is matched by perceptual hash.
- **Exposure.** Breaches, infostealer logs, .onion indexes and dark-web search.
- **Exports.** HTML / PDF report, STIX 2.1, GraphML, CSV, JSON — each with the
  SHA-256 of the evidence it was built from.
- **Free first.** Every identity source works without an API key. Paid or
  account-bound sources are optional and listed below.

## Install

### pip / pipx

```shell
pipx install veiled-eye        # recommended (isolated environment)
# or
pip install veiled-eye
# latest code from GitHub
pipx install git+https://github.com/emrekybs/veiled-eye
```

This installs the `veiled-eye` command (short alias `veye`).

```shell
veiled-eye serve                                   # web UI + API + worker → http://127.0.0.1:4300
veiled-eye scan johndoe                            # terminal investigation, no Redis needed
veiled-eye scan -e john@acme.com -u johndoe -o report.json
veiled-eye scan +905321234567                      # phone (type is auto-detected)
veiled-eye scan 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa # wallet
veiled-eye scan johndoe -x html,pdf,stix --outdir case/
veiled-eye modules                                 # list the sources
veiled-eye doctor                                  # check git / redis / tor
veiled-eye proxies                                 # check proxy_list: exit IP, latency
```

`veiled-eye serve` needs Redis; it starts a local `redis-server` when one is
installed (otherwise `docker run -d -p 6379:6379 redis:7-alpine`). Keys,
cookies and cache live in `~/.config/veiled-eye` (`VEILED_HOME`).

### Docker

```shell
git clone https://github.com/emrekybs/veiled-eye && cd veiled-eye
just build && just up        # or: docker compose up -d
```

Open http://localhost:4300. Services: `frontend` (nginx, 4300), `backend`
(FastAPI + Celery, 5000), `redis`, and `tor` for .onion lookups.

## Sources

| Group | Modules |
| :---- | :------ |
| Account discovery | maigret, whatsmyname, userscanner, emailreg, sherlock, socialscan, holehe, usersearch, darksherlock |
| Profiles | github, gitlab, keybase, reddit, mastodon, twitch, youtube, spotify, instagram, tiktok, twitter, linkedin, venmo, telegram, steam, bluesky, hackernews, stackexchange, kick, snapchat, gravatar |
| Selectors | phone, crypto, pgp |
| Exposure | leaks (XposedOrNot), hudsonrock, leaklookup, darkweb, ahmia, emailrep, peopledatalabs |
| Web | search, dorks, wayback, domaininfo |
| Organisation | crosslinked, gitsniff |
| Correlation | crossref |

Several selectors can be searched together: separate them with commas
(`john@acme.com, johndoe, +905321234567`). Each one is a starting point.

Leads are followed automatically: usernames go to the identity modules,
e-mails to the e-mail modules, accounts found by maigret / user-scanner to
the matching profile module, phones and checksum-valid wallets found anywhere
to `phone` / `crypto`, a GitHub company to `crosslinked`, a corporate
e-mail domain to `domaininfo`. Leads are followed **two steps** deep from
what you typed (`VEILED_PIVOT_DEPTH`), so "username → GitHub → commit e-mail
→ registrations" happens but the search does not wander off. The
Investigation page shows the **pivot trail**: which finding led to which
selector. Set `VEILED_AUTOCHAIN=0` to switch chaining off.

### GitHub

Besides the profile, repositories, organisations and contribution calendar:

- **commit e-mails and names** from the user's own repositories and recent
  public pushes, each with how often and where it appears
- **previous usernames**: GitHub's `<id>+<login>@users.noreply.github.com`
  addresses carry the account's permanent numeric ID, so a different login
  next to the same ID is a former name. With your own Google Cloud project
  (`VEILED_GHARCHIVE_PROJECT`, `google-cloud-bigquery` installed) GH Archive
  adds every login the ID ever used; a dry run checks the scan size first
  and nothing above `VEILED_GHARCHIVE_MAX_GB` (100) runs
- **time zone** from the `Date:` line of commit patches (the author's clock)
- e-mails inside public **GPG keys**; **SSH keys** compared with the same
  username on GitLab and Codeberg — the same key means the same person
- links and e-mails in the **profile README**

Found e-mails go on to `emailreg`, Gravatar and PGP; former usernames to
maigret. `GITHUB_TOKEN` raises the API limit from 60 to 5000 calls an hour.

### Cross analysis

`crossref` grades accounts, ranks names / e-mails / locations by how many
sources agree, matches profile pictures, and adds:

- **places**: every coordinate any source produced (Instagram posts and
  business address, GitHub location…) plus the most cited written locations,
  geocoded — all of them on the Identity → Map tab
- **activity by hour** and the likely **time zone** (commit clocks first,
  otherwise the daily rhythm of every dated event, ±2 h)
- reverse image search links (Yandex, Bing, Google Lens) for the profile
  pictures, and handle patterns to try for the best-supported full name

### Relationship graph

The **Graph** page draws the current investigation as one network: the
subject (consensus name), the selectors you searched, the accounts found for
each, names, organisations and places, and every lead the orchestrator
followed (dashed arrows, e.g. GitHub → commit e-mail → registrations).

- accounts show the platform logo; ring weight shows the cross-analysis grade
  (confirmed / likely / unconfirmed), underground forums are marked red, and
  accounts sharing a profile picture are joined
- more than 30 single-source hits for one username fold into one node that
  lists them and can be expanded
- click a node for its sources, links, reverse image search (Yandex, Bing,
  Google Lens), connected nodes and "Investigate" to start a new search
- filter by type or confidence, search inside the graph, export PNG or JSON
- the case is kept for the browser tab, so a reload keeps the graph

The stock UI runs each module for one value only; leads it would drop (a
second username for maigret, a second e-mail for registrations) are run by
the web helper itself, two at a time, and show up in the feed and the graph.

### Domains

For e-mails on their own domain, `domaininfo` reads RDAP (registrar,
registration date, organisation when published), DNS (mail provider from MX,
SPF, DMARC, name servers) and certificate transparency (subdomains, first
certificate).

### Instagram

Instagram is read without a password. Sources are tried in order and one that
gets blocked is skipped for 10 minutes by every worker:

1. the public profile API (anonymous) — name, bio, counters, latest 12 posts
2. the same API with **your** session cookies — far fewer blocks
3. the public profile page — name, counters and avatar when the API is closed

With session cookies the module also reads what the profile shows publicly in
the app: business category, public e-mail and phone, address and coordinates,
bio links, pronouns, and the latest posts with their places (shown on the
map), tagged users, likes and comments. A numeric Instagram user ID is
resolved to the username.

Paste a Cookie-Editor export into `instagram_cookies` (it is split into the
fields on save) or fill `instagram_sessionid`, `instagram_ds_user_id`,
`instagram_csrftoken`, `instagram_mid`, `instagram_ig_did`, `instagram_datr`,
`instagram_ps_l`, `instagram_ps_n`, `instagram_wd` yourself. `sessionid` is
the one that signs you in; the rest make the request match your browser.

### E-mail registrations

`emailreg` merges holehe and user-scanner into one list: one row per site,
**confirmed** when both tools see the account, **likely** when one does, with
the recovery hints holehe exposes (masked phone, masked backup e-mail). It
reuses the two scanners' results instead of scanning twice, and tells whether
the address is free webmail, privacy-focused, disposable or a corporate domain.
Checks that would notify the address owner are never run.

## API keys and cookies

Everything works without keys. Add them on the **API keys** page to unlock
more sources:

| Source | Field | Cost |
| :----- | :---- | :--- |
| Instagram | `instagram_cookies` or the `instagram_*` cookie fields | Free — your own session, optional |
| Twitter / X | `twitter_cookies` | Free — your own account (cookies) |
| LinkedIn | `linkedin_cookies` | Free — your own account (cookies) |
| TikTok | `tiktok_cookies` | Free — your own account (cookies) |
| Spotify | `spotify_client_id` / `spotify_client_secret` | Free developer app |
| Twitch | `twitch_client_id` / `twitch_client_secret` | Free developer app |
| YouTube | `youtube_key` | Free Google Cloud key (daily quota) |
| EmailRep | `emailrep_key` | Free key: 250 queries / month; paid plans above that |
| PeopleDataLabs | `peopledatalabs_key` | 100 free records / month, then paid |
| Brave Search | `brave_key` | Paid; includes a monthly free credit |
| Google CSE | `cse_api_key` / `cse_cx` | Closed to new sign-ups; existing keys stop on 1 Jan 2027 |
| Leak-Lookup | `leaklookup_key` | Paid |
| Twitter comparison | X API keys | Paid (pay-per-use) |

Without search keys, `search` and `dorks` use DuckDuckGo. How to export
cookies: [docs/COOKIES.md](docs/COOKIES.md).

### Proxies

Put proxies in `proxy_list` on the API keys page — separated by commas, e.g.
`http://user:pass@1.2.3.4:8080, socks5h://5.6.7.8:1080, tor`. Requests rotate
over them; a proxy that fails is benched for 5 minutes and the request is
retried on the next one. There is no fallback to your own connection while
proxies are set. `proxy_hosts` limits the pool to some sites
(`instagram.com, linkedin.com`). Check them with `veiled-eye proxies`.
Tools with their own HTTP stack (maigret, holehe, WhatsMyName, user-scanner)
follow the worker's `HTTPS_PROXY` instead.

## Reports

The **Report** button on the Investigation page (and the PDF button on the
Graph page) downloads an A4 PDF: cover with the subject, summary figures,
accounts graded by confidence, single-source hits as a compact list,
identity attributes, places, exposure, timeline and the status of every
source. Columns are fixed and long values wrap inside their cell, so the
layout does not shift with the data. Fonts are embedded (DejaVu Sans), so
Turkish and other non-ASCII text prints correctly.

## Exports

From the CLI (`-x html,pdf,stix,graphml,csv,json`) or the browser:

```
http://127.0.0.1:4300/api/export/<target>?format=html
```

| Format | Use |
| :----- | :-- |
| `html`, `pdf` | report: summary, accounts, identity, avatar matches, exposure, timeline, source status |
| `stix` | STIX 2.1 bundle for MISP / OpenCTI |
| `graphml` | link graph for Gephi, yEd, Cytoscape, Maltego |
| `csv` | flat table |
| `json` | everything, raw source outputs included |

## Configuration

| Variable | Default | Effect |
| :------- | :------ | :----- |
| `VEILED_HOME` | `~/.config/veiled-eye` | keys, cookies, cache |
| `VEILED_WORKERS` | 12 | parallel sources (`veiled-eye serve -w`) |
| `VEILED_TASK_SOFT_LIMIT` | 900 | seconds before a stuck source is stopped |
| `VEILED_HTTP_TIMEOUT` | 45 | default read timeout for every HTTP call |
| `VEILED_RESULT_WAIT` | 5 | seconds one result request waits before the UI polls |
| `VEILED_MAIGRET_TOP` | 500 | sites maigret checks (`all` for every site) |
| `VEILED_PHONE_REGION` | TR | region for phone numbers without `+` |
| `VEILED_AUTOCHAIN` | 1 | follow leads automatically |
| `VEILED_PIVOT_DEPTH` | 2 | how many steps leads are followed |
| `VEILED_GITHUB_DEEP` | 1 | commit e-mails, former usernames, keys (GitHub) |
| `VEILED_GEOCODE` | 1 | geocode written locations for the map (Nominatim) |
| `VEILED_AVATAR_HASH` | 1 | profile picture matching in cross analysis |
| `VEILED_USERSCANNER_CROSS_DEPTH` | 2 | user-scanner `--cross-depth`: hops followed from profile links |
| `VEILED_USERSCANNER_CROSS_LINKS` | verified | user-scanner `--cross-links` (`verified` keeps false positives low, `all`) |
| `VEILED_MAIGRET_PIVOTS` | 3 | handles maigret found in profiles that get their own sweep |
| `VEILED_CROSSLINKED_MAX` | 60 | LinkedIn profiles CrossLinked collects per company |
| `VEILED_HTTP_RETRY` | 1 | one retry after HTTP 429/503 (honours `Retry-After`) |
| `GITHUB_TOKEN` | — | GitHub token (or the `github_token` API key): 60 → 5000 requests/hour |

## Development

```shell
just setup && source .venv/bin/activate
pip install -e .
cd backend && pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for adding a source.

## Responsible use

Use Veiled Eye on people and organisations you are authorised to investigate.
It reads public data; sessions you add are your own and are only used to read
public profiles. You are responsible for complying with the law and with the
terms of the services you query.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE), [NOTICE](NOTICE) and
[CREDITS](CREDITS.md).
