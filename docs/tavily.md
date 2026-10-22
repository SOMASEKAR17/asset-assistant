# Tavily in Creator Asset Assistant

Tavily is the app's only connection to the open web. It does three jobs, each started by the creator:

| Feature | Where in the app | Tavily endpoints | Other models |
|---|---|---|---|
| **Free on the web** (gap filler) | Search results, "Free on the web" section; gaps in a b-roll plan | `/search`, then `/extract` when you save | Nemotron Nano reads the licence |
| **Where did this file come from?** (licence check) | Licences view; Licence block in the details panel | `/extract` (batched), `/search` when the page address is unknown | Nemotron Nano reads the licence |
| **Research → b-roll plan** | B-roll plan view | `/search` with an answer | Nemotron Ultra writes the beats; local search finds the shots |

Searching your own library never uses Tavily. It stays on the computer.

## Setup

1. Get a key at [app.tavily.com](https://app.tavily.com).
2. In the app: **Folders & privacy → Keys & connections → Tavily API key**, then **Save**. The key goes into the system keychain (Windows Credential Manager). `TAVILY_API_KEY` in the environment or a `.env` file also works; a key saved in the app takes priority.
3. Privacy must be **Standard**. In **Local only** every Tavily feature is off and the app says so where the feature would appear.
4. Optional: change the **Inbox folder** (default `%USERPROFILE%\Videos\CreatorAssets\Inbox`). Free assets you save go there.

`scripts\run.ps1 doctor` sends one test search and shows the response time.

## What leaves the computer

| Action | Sent to Tavily | Sent anywhere else |
|---|---|---|
| Look for free assets | Your search words plus "free stock video / photo / sound effect", and the list of free sites | The thumbnails are loaded from the sites' image servers (Pexels, Pixabay, …) when the results are shown |
| Save to Inbox | The item's page address | The file is downloaded from the site; a short licence excerpt (up to 3,500 characters of the public page) goes to Nemotron Nano on Token Factory |
| Check a file's licence | The file **name** (or the page address built from it). Never the file | The public licence excerpt goes to Nemotron Nano |
| B-roll plan | The topic you type | The topic, your script (if you paste one) and the research snippets go to Nemotron on Token Factory |

## Feature 1: Free on the web

### When it appears

- Below the search results, as **Free on the web**. If your library has no match, it runs automatically. If it has matches, one click on **Look for free videos** (or photos, sounds) runs it, so a normal search costs nothing.
- In a b-roll plan, a beat with no footage in your library gets **Find free videos**.

### The request

One `POST /search` per query and type, `search_depth: "basic"`, `include_images: true`, `max_results` 10–20:

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
3. Marks **item pages** (one asset, e.g. `pexels.com/video/waves-on-a-beach-at-sunset-1093662/`) and puts them before search pages. Only item pages get **Save to Inbox**.
4. Matches Tavily's image list to results by the item number in the address, so each card shows its own thumbnail (or no thumbnail, never a wrong one).
5. Shows the site's usual licence as a badge: **Free to use, no credit** (Pexels, Pixabay, Unsplash), **Check the item** (Mixkit has Free and Restricted items; Freesound and Openverse differ per item).

### Save to Inbox

1. `POST /extract` on the item page (`format: "markdown"`, `include_images: true`, `extract_depth: "basic"`).
2. **Pick the file.** Every media address in the page is scored: right type (`.mp4`, `.wav`, `.jpg`, …), on the site's file server (`videos.pexels.com`, `cdn.pixabay.com`, `assets.mixkit.co`, `cdn.freesound.org`, `images.unsplash.com`), large sizes (`1920`, `1080`, `hd`, `original`) up, avatars, logos and thumbnails down. If the page has no direct file, Pexels and Unsplash download addresses are built from the item number.
3. **Read the licence** from the same page (see [Reading a licence](#reading-a-licence)).
4. **Download** into the Inbox as `<site>-<item name>.<ext>`: written to a `.part` file and renamed when complete, at most 800 MB, refused if the site returns a web page instead of a file. Existing files are never overwritten.
5. **Record** the page, the file address and the licence in the `downloads` table.
6. **Index.** The Inbox is added to your library as a watched folder (shown with an inbox icon) on the first save, and the file is queued at once. When indexing finishes, the licence and the source page are attached to the asset, so the Licences view and the details panel show them.

If a site only allows downloads after a click in the browser, the app says "Open the page and download it there" and nothing is left behind.

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
- **Check N files** runs a background check with progress. Pages whose address is known are read in batches of up to 20 per `/extract` request (basic extraction costs 1 credit per 5 pages), then each file is finished from the cache.
- **Copy credits** copies one credit line per file (files that need credit first), ready for a video description.
- `POST /api/licences/{id}` sets a licence by hand (`method: "you"`); the app will not overwrite it.

## Feature 3: Research → b-roll plan

1. **Research.** `POST /search` with the topic, `include_answer: "basic"`, `max_results: 6`. The answer and the six results become numbered research notes.
2. **Plan.** Nemotron's `reasoning` role (Nemotron 3 Ultra; if it fails, `agent`, then `fast`) gets the topic, the length, your script if you pasted one, and the notes, and returns JSON: a title, a hook, 3–14 beats (`line`, `shot`, `search`, `kind`, `seconds`, `why`) and up to 5 facts, each tied to a source number. Facts must come from the notes.
3. **Match.** Each beat's search words go through the normal local search (meaning, keywords, look). The top 3 shots are shown; a video shot opens at its timecode.
4. **Gaps.** A beat with no match shows **Find free videos / photos / sounds**, which runs Feature 1 for that beat.
5. **Copy plan** copies the beats, the files to use (with timecodes), the facts and the sources as plain text.

Without Nemotron, the plan is split from your script's sentences (or the research answer) and still matched against the library. Without Tavily, the plan is made without research.

## Credits and caching

| Action | Tavily requests | Credits |
|---|---|---|
| Look for free assets | 1 search | 1 |
| Save to Inbox | 1 extract | 1 |
| Check one file | 1 extract, plus 1 search if the address is not in the name | 1–2 |
| Check many files | 1 extract per 20 known addresses, plus searches for the rest | about 1 per 5 files with known addresses |
| B-roll plan | 1 search | 1 |

Every Tavily response is cached in `library.db` (`cache` table): searches for a day, page reads for 7 days. Repeating a search, re-opening a plan topic or rechecking a file inside that time costs nothing. **Settings → Engine → Tavily** shows requests, cache hits and credits used this session; `GET /api/status` has the same under `tavily`.

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
| `engine/tests/test_web.py` | 18 tests with a fake Tavily, a fake download session and a fake Nemotron |

## Tests

`engine/tests/test_web.py` runs without network access: file-name recognition (including names that must not match), licence rules, Nemotron not overriding a licence read from the page, result filtering and sorting, thumbnail matching, caching, Local only, media picking, downloads into the Inbox (no `.part` left behind, no overwrite, web pages refused), finding sources by address and by search, batched page reads, the b-roll plan with and without Nemotron, and the API end to end (save → indexed with licence → Licences view → background check → manual licence → plan → Local only blocks the web).

## Known limits

- Some sites only serve downloads to a browser after a click (and Pixabay asks API users not to hotlink). When the download is refused, the app links to the page instead.
- The badge on a search card is the site's usual licence. The item's own licence is read when you save it or check it.
- Licence reading is an aid, not legal advice. Check the page for anything you will monetise.
- Pexels and Pixabay have their own APIs; this version goes through Tavily only, so one key covers every site.
