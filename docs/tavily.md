# Tavily in Creator Asset Assistant

Tavily supplies web search results and extracted public-page text. The app uses it for asset discovery, source/licence lookup, b-roll research and a connectivity diagnostic. It does not download the media files, generate thumbnails or write the b-roll plan. Asset-page fallbacks, preview images and media downloads contact the stock sites directly; Nemotron calls go separately to Token Factory.

This document describes the current source implementation, reviewed on 2026-10-29. An installed build must include these source changes to behave the same way.

| Feature | Where in the app | Tavily endpoints | Other models |
|---|---|---|---|
| **Free on the web** (gap filler) | Search results, "Free on the web" section; gaps in a b-roll plan | `/search`, then `/extract` when you save | Nemotron Nano reads the licence |
| **Where did this file come from?** (licence check) | Licences view; Licence block in the details panel | `/extract` (batched), `/search` when the page address is unknown | Nemotron Nano reads the licence |
| **Research → b-roll plan** | B-roll plan view | `/search` with an answer | Nemotron Ultra writes the beats; local search finds the shots |

Searching your own library never uses Tavily. It stays on the computer.

## Exact call sites and purposes

All Tavily HTTP traffic is implemented in [Tavily](../engine/caa/tavily.py): `POST https://api.tavily.com/search` or `/extract`, authenticated with the configured key. [Services.__init__](../engine/caa/services.py) creates one shared client backed by the library database and passes it to `WebAssets` and `BrollPlanner`.

| Source call | Trigger / entry point | What is sent | What the response is used for |
|---|---|---|---|
| [WebAssets.search](../engine/caa/sources.py) → `tavily.search` (initial search) | UI **Free on the web**, a b-roll beat's **Find free…**, `GET /api/web/search`, CLI `web` | Search words plus media-type suffix; supported domains; basic search; images requested; 10–20 results | Individual asset URLs, titles, snippets, scores and candidate thumbnail URLs. Search/category pages are filtered out before returning cards. |
| `WebAssets.search` → `tavily.search` (targeted video follow-up) | Same action, when `kind == "video"` and the initial response has fewer item-page URLs than the requested limit | Original words plus video suffix and `(site:pexels.com/video/ OR site:pixabay.com/videos/ OR site:mixkit.co/free-stock-video/) -inurl:search -inurl:collections`; same domains and result bounds | Adds individual-video candidates, merges and deduplicates URLs, then filters and ranks. This is at most one extra search per invocation; cached calls do not make HTTP requests. Failure preserves the initial individual results. |
| [WebAssets.read_page](../engine/caa/sources.py) → `tavily.extract` | `save`, `check`, and `find_source`; reached from Save to Inbox, `POST /api/web/licence`, single/bulk licence checks and CLI `web --save` / `source` | Asset page URL; basic extraction; Markdown output; images requested | `raw_content` provides licence evidence and downloadable media links; `images` supplies additional media candidates; a Markdown heading supplies the title. This shared method is the only normal single-page extraction call. |
| `WebAssets.find_source` → `tavily.search` | Licence/source lookup when `identify(filename)` cannot construct a page URL | Recognised site, filename-derived words and ID; restricted to that site's domain; up to six results; no image or answer request | Ranks candidate source pages by ID, filename words and item-page shape, then calls `read_page`. The file itself is never uploaded. No recognition means no Tavily lookup. |
| [SourceAudit.start](../engine/caa/sources.py) → `tavily.extract_many` | **Check N files** / `POST /api/licences/check` without `asset_id` | More than one known page URL from candidate filenames; images requested; deduplicated uncached URLs in batches of up to 20 | Prefills the per-page extract cache. Each subsequent `check_one` calls `find_source` and reuses cached page text. Unknown URLs still need discovery searches. Batch failures fall back to individual checks. |
| [BrollPlanner.research](../engine/caa/broll.py) → `tavily.search` | B-roll planning with research enabled; `POST /api/broll`; CLI `broll` | Topic; basic search; up to six results; `include_answer: "basic"`; no domain restriction or image request | Numbered sources with titles, URLs and snippets (up to 500 characters each), plus an answer. These become Nemotron's planning notes and source references for facts. Local library matching uses no Tavily calls. |
| [Tavily.ping](../engine/caa/tavily.py) → `_post("/search", …)` | [CLI doctor](../engine/caa/cli.py), only with a key and privacy not Local only | Fixed query `creative commons stock footage`; basic search; one result | Connectivity check reporting result count and response time. It bypasses the database cache and uses a separate client. |

### Related code that does not call Tavily

- [ui/app.js](../ui/app.js) calls the app's local HTTP API, never Tavily directly. `fillWeb` also caches results in UI memory. Opening a card follows its source URL in the browser.
- `WebAssets.page_preview` reads a missing preview directly from the stock site's HTML; `direct_page` is the direct-page fallback for saving; `_download` retrieves media bytes. None uses Tavily credits.
- `WebAssets.licence_for` combines local rules with the optional Nemotron `fast` role. Tavily supplies page text, not a licence verdict.
- `BrollPlanner._ask` asks Nemotron to write the plan; `_match` searches the local library with `use_llm=False`. `research=False` skips Tavily research. If no topic is provided, `plan` derives one from the first script sentence (up to 120 characters), which can therefore be sent as the research query.
- [api.py](../engine/caa/api.py) routes requests to those services. `GET /api/status`, listing licences, setting a licence manually and adding the Inbox folder do not themselves make Tavily requests.
- [indexer.py](../engine/caa/indexer.py) attaches already-recorded download licence/source metadata when indexing; this is not a fresh Tavily check.

## Setup

1. Get a key at [app.tavily.com](https://app.tavily.com).
2. In the app: **Folders & privacy → Keys & connections → Tavily API key**, then **Save**. The key goes into the system keychain (Windows Credential Manager). `TAVILY_API_KEY` in the environment or a `.env` file also works; a key saved in the app takes priority.
3. Privacy must be **Standard**. In **Local only** every Tavily feature is off and the app says so where the feature would appear.
4. Optional: change the **Inbox folder** (default `%USERPROFILE%\Videos\CreatorAssets\Inbox`). Free assets you save go there.

`scripts\run.ps1 doctor` sends one test search and shows the response time.

## What leaves the computer

| Action | Sent to Tavily | Sent anywhere else |
|---|---|---|
| Look for free assets | Search words, media-type suffix and supported domains; possibly a targeted video query | Missing previews may trigger direct asset-page requests; thumbnail bytes load from image servers |
| Save to Inbox | The item's page address | Direct page fallback when extraction fails; media downloaded directly from the site. Available licence text (up to 3,500 characters) goes to Nemotron's `fast` role when enabled |
| Check a file's licence | The file **name** (or the page address built from it). Never the file | The public licence excerpt goes to Nemotron Nano |
| B-roll plan | Topic, or the first script sentence if no topic is supplied; only when research is enabled | Topic, script and research snippets go to Nemotron on Token Factory when enabled |
| CLI doctor | Fixed diagnostic query | Other diagnostics may contact their own services separately |

## Feature 1: Free on the web

### When it appears

- Below the search results, as **Free on the web**. If your library has no match, it runs automatically. If it has matches, one click on **Look for free videos** (or photos, sounds) runs it, so a normal search costs nothing.
- In a b-roll plan, a beat with no footage in your library gets **Find free videos**.

### The request

One initial `POST /search` per query and type, plus at most one targeted follow-up for sparse video results. Both use `search_depth: "basic"`, `include_images: true`, `max_results` 10–20:

| Type | Query suffix | `include_domains` |
|---|---|---|
| Video | `free stock video` | pexels.com, pixabay.com, mixkit.co |
| Photo | `free stock photo` | pexels.com, pixabay.com, unsplash.com, openverse.org |
| Sound | `free sound effect` | freesound.org, pixabay.com, mixkit.co |
| Template | `free video template` | mixkit.co |

The type comes from the tab you are on, or from your words ("whoosh" means sounds); otherwise video.

### What the app does with the results

1. Drops anything not on a supported site.
2. Works out the type from the address (`/video/`, `/photos/`, `/free-sound-effects/`, …) and drops results of another type.
3. Shows only **item pages** (one asset, e.g. `pexels.com/video/waves-on-a-beach-at-sunset-1093662/`). Search pages and collections are excluded. When video results are sparse, makes one additional cached Tavily search targeting individual video paths. This may use an additional search credit; if it fails, existing individual results still appear.
4. Matches image candidates by complete item number in the URL path and rejects avatar, flag, logo and icon paths. Pexels also requires `images.pexels.com` with the matching `/videos/<id>/` or `/photos/<id>/` path. Pexels photos have a constructed image fallback. For remaining video/image items, reads video poster, Open Graph or Twitter metadata directly from the asset page. These bounded requests run up to four at a time and are cached for a day, including unavailable previews. Missing or failed previews show “Preview unavailable”; category pages are excluded from the grid.
5. Shows the site's usual licence as a badge: **Free to use, no credit** (Pexels, Pixabay, Unsplash), **Check the item** (Mixkit has Free and Restricted items; Freesound and Openverse differ per item).

### Save to Inbox

If Tavily cannot extract the asset page, Save tries a bounded direct page request and reads media URLs from its HTML (including escaped JSON URLs). If both page reads fail, supported Pexels/Unsplash download routes may still work; the saved licence is then explicitly unverified. If no download is available, the card retains an error explaining how to use Open page and download into the Inbox manually. Sites can still refuse automated downloads.

1. `POST /extract` on the item page (`format: "markdown"`, `include_images: true`, `extract_depth: "basic"`).
2. **Pick the file.** Every media address in the page is scored: right type (`.mp4`, `.wav`, `.jpg`, …), on the site's file server (`videos.pexels.com`, `cdn.pixabay.com`, `assets.mixkit.co`, `cdn.freesound.org`, `images.unsplash.com`), large sizes (`1920`, `1080`, `hd`, `original`) up, avatars, logos and thumbnails down. If the page has no direct file, Pexels and Unsplash download addresses are built from the item number.
3. **Read the licence** from the same page (see [Reading a licence](#reading-a-licence)).
4. **Download** into the Inbox as `<site>-<item name>.<ext>`: written to a `.part` file and renamed when complete, at most 800 MB, refused if the site returns a web page instead of a file. Existing files are never overwritten.
5. **Record** the page, the file address and the licence in the `downloads` table.
6. **Index.** The Inbox is added to your library as a watched folder (shown with an inbox icon) on the first save, and the file is queued at once. When indexing finishes, the licence and the source page are attached to the asset, so the Licences view and the details panel show them.

If a site refuses automated downloads, the card keeps an error directing the user to Open page. A successful search does not guarantee a readable page or downloadable file.

## Feature 2: Where did this file come from?

Creators keep stock downloads with the site's own file names. The app recognises them, finds each file's page with Tavily and reads its licence, without sending the file.

### Recognised names

| Site | Example name | Page found by |
|---|---|---|
| Pexels photo | `pexels-cottonbro-5698420.jpg`, `pexels-photo-1181671.jpeg` | Address built from the number: `pexels.com/photo/5698420/` |
| Pexels video | `3195394-uhd_3840_2160_25fps.mp4`, `pexels-tima-miroshnichenko-6010489.mp4` | `pexels.com/video/3195394/` |
| Freesound | `123456__InspectorJ__wind-chime-gamelan.wav` | `freesound.org/people/InspectorJ/sounds/123456/` |
| Unsplash | `john-doe-AbCdEfGhIjK-unsplash.jpg` | `unsplash.com/photos/AbCdEfGhIjK` |
| Pixabay photo | `mountain-landscape-2031539_1920.jpg` | Tavily search on pixabay.com; the result must contain the number |
| Pixabay video | `190002-887245614_medium.mp4` | Tavily search on pixabay.com |
| Pixabay music (likely) | `the-cradle-of-your-soul-15700.mp3` | Tavily search; accepted only if the result contains the number. Year-like numbers (`intro-2024.mp3`) are ignored |
| Mixkit | `mixkit-fast-small-sweep-transition-166.wav`, `mixkit-…-1226-medium.mp4` | Tavily search on mixkit.co; the best address by number and name words |
| Any | a name containing `pexels`, `pixabay`, `mixkit`, `unsplash`, `freesound` | Tavily search on that site |

### Reading a licence

Rules first, then Nemotron:

1. **Rules** read the page text. Freesound and Openverse: CC0, CC BY, CC BY-SA, CC BY-NC, Sampling+. Mixkit: Free License or Restricted License. Pexels, Pixabay and Unsplash use one licence for every item. The author comes from the address (`/people/<name>/`) or "Photo by …" / "Video by …" on the page. Creative Commons licences link to their deed.
2. **Nemotron Nano** (the `fast` role) reads a 3,500-character excerpt around the licence words and returns `{licence, commercial_ok, attribution_required, credit, notes}`.
3. **Precedence.** A licence the rules found on the page is never replaced by Nemotron's wording, and a yes/no the rules set is never flipped. Nemotron fills what the rules could not decide and writes the credit line. For Pexels, Pixabay and Unsplash the licence name always stays the site's. Without Nemotron, the rules' result is used.

Each result is stored on the asset:

```json
{"site": "freesound", "site_name": "Freesound", "licence": "CC BY", "commercial_ok": true, "attribution_required": true,
 "credit": "wind chime gamelan by InspectorJ (freesound.org), CC BY 4.0", "note": "Credit the author in your video description.",
 "terms_url": "https://creativecommons.org/licenses/by/4.0/", "source_url": "https://freesound.org/people/InspectorJ/sounds/123456/",
 "method": "page + nemotron", "status": "found", "checked_at": 1792569600}
```

`status` is `found` (page read), `unverified` (page address known but unreadable; site's usual licence shown with **Not verified**) or `not_found` (looks like the site's file, page not found).

### Licences view

- Counts across the top, each one a filter: Files, Credit needed, Not commercial, Check the item, Not checked.
- One row per file: type, name (opens the details panel), site, badges, licence, credit line, and **Copy**, **Page**, **Check / Recheck**.
- **Check N files** runs a background check with progress. Pages whose address is known are read in batches of up to 20 per `/extract` request, then each file uses the cache where extraction succeeded.
- **Copy credits** copies one credit line per file (files that need credit first), ready for a video description.
- `POST /api/licences/{id}` sets a licence by hand (`method: "you"`). Ordinary bulk checks skip assets with existing licence metadata; forced bulk checks and explicit single-file checks can replace it.

## Feature 3: Research → b-roll plan

1. **Research.** `POST /search` with the topic, `include_answer: "basic"`, `max_results: 6`. The answer and the six results become numbered research notes.
2. **Plan.** Nemotron's `reasoning` role (Nemotron 3 Ultra; if it fails, `agent`, then `fast`) gets the topic, the length, your script if you pasted one, and the notes, and returns JSON: a title, a hook, 3–14 beats (`line`, `shot`, `search`, `kind`, `seconds`, `why`) and up to 5 facts, each tied to a source number. Facts must come from the notes.
3. **Match.** Each beat's search words go through the normal local search (meaning, keywords, look). The top 3 shots are shown; a video shot opens at its timecode.
4. **Gaps.** A beat with no match shows **Find free videos / photos / sounds**, which runs Feature 1 for that beat.
5. **Copy plan** copies the beats, the files to use (with timecodes), the facts and the sources as plain text.

Without Nemotron, the plan is split from your script's sentences (or the research answer) and still matched against the library. Without Tavily, the plan is made without research.

## Requests, usage reporting and caching

| Action | Requests on cache misses |
|---|---|
| Look for free assets | 1 search; up to 2 for video |
| Save to Inbox | 1 extract; direct site fallbacks are not Tavily requests |
| Check one recognised file | 1 extract, plus 1 search if the address cannot be constructed; no extract if no acceptable page is found |
| Check many files | Batched extracts for known uncached addresses (up to 20 per request), searches for other files, individual extracts for pages not populated in cache |
| B-roll plan | 1 search when research is enabled and Tavily available; otherwise 0 |
| CLI doctor | 1 uncached search when enabled |

Normal search/extract responses are cached in `library.db` (`cache` table): searches for one day and page reads for seven days. Keys include the endpoint and complete request body; changed parameters have different entries. Identical cached calls send no Tavily HTTP request. Single-page responses containing extraction failures can also be cached. Batched extraction stores only successful nonempty pages as single-page entries. CLI `ping` bypasses caching.

**Settings → Engine → Tavily** and `GET /api/status` expose session counters: successful HTTP calls, cache hits, errors, last error and credits. The client adds `response.usage.credits` when present and otherwise adds zero; it does not calculate a tariff or guarantee billing completeness. These counters exclude direct stock-site traffic, and the CLI diagnostic uses a separate client. Request counts above describe the code, not a pricing commitment.

## API

| Route | Purpose |
|---|---|
| `GET /api/web/search?q=&kind=&limit=` | Free assets on the web. Returns `{items, sites}`, or `{off}` with the reason when Tavily is off |
| `POST /api/web/save` `{url, kind}` | Download an item page's file into the Inbox with its licence |
| `POST /api/web/licence` `{url}` | Read the licence of any supported page |
| `GET /api/licences` | Files from free sites with their licences, the summary counts and the check's progress |
| `POST /api/licences/check` `{asset_id}` or `{force}` | Check one file now, or start the background check |
| `POST /api/licences/{id}` `{licence}` | Set or clear a licence by hand |
| `POST /api/broll` `{topic, script, seconds, research}` | Research and plan b-roll |
| `POST /api/inbox` | Add the Inbox folder to the library now |

Errors: `409` when Tavily is off (with the reason), `502` when Tavily fails, `400` for a page or file the app cannot use.

## Command line

```powershell
scripts\run.ps1 web sunset beach --kind video           # free videos on the web
scripts\run.ps1 web sunset beach --kind video --save 1  # save result 1 to the Inbox
scripts\run.ps1 source D:\SFX\123456__InspectorJ__wind-chime-gamelan.wav D:\Stills\pexels-cottonbro-5698420.jpg
scripts\run.ps1 broll "where coffee comes from" --seconds 60 --script script.txt
```

## Code

| File | What it does |
|---|---|
| `engine/caa/tavily.py` | Tavily client: `search`, `extract`, batched `extract_many`, cache, usage counters, off in Local only |
| `engine/caa/sources.py` | Supported sites, file-name recognition, licence rules + Nemotron, free-asset search, media picking, download into the Inbox, `find_source`, background `SourceAudit` |
| `engine/caa/broll.py` | Research, Nemotron plan, beat clean-up, local matching, fallbacks |
| `engine/caa/indexer.py` | Attaches a saved file's licence and source page when it is indexed |
| `engine/caa/db.py` | `downloads` table, cache with an age limit |
| `engine/caa/api.py` | The routes above; `source_guess` in asset details |
| `ui/app.js` | Free on the web section, Save to Inbox, Licence block, Licences view, B-roll plan view, Inbox and Tavily in Settings |
| `engine/tests/test_web.py` | Fake Tavily, download and Nemotron regression tests, plus local HTTP API integration tests |

## Tests

`engine/tests/test_web.py` uses fake Tavily and stock-site responses; API integration tests require localhost sockets. Coverage includes filename recognition, licence rules and model precedence, individual-only results, targeted search, rejecting unrelated thumbnail images, preview metadata fallback, caching, Local only, media picking, successful downloads without leftover `.part` files, no overwrite, rejection of HTML downloads, direct-page fallback after extraction failure, unverified licences when using a download route without readable page text, actionable blocked-site errors, source lookup, batched extracts, b-roll planning and the local API flow. These tests do not establish that a live stock site will permit extraction or downloading.

## Known limits

- Some sites only serve downloads through browser interaction. When a download is refused, the user can follow Open page.
- The badge on a search card is the site's usual licence. The item's own licence is read when you save it or check it.
- Licence reading is an aid, not legal advice. Check the page for anything you will monetise.
- No stock-provider API client is used here. Discovery and primary page extraction use Tavily; preview fallbacks, save fallbacks and media downloads use direct HTTP requests to the sites.
