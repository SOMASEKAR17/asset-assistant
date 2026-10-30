# Creator Asset Assistant — web deployment

## Recommended: Vercel static preview (no VM needed)

Use the [Vercel deployment guide](vercel/README.md) for the current lightweight public preview. It serves the prepared sample media and a public JSON index, with browser-side keyword search and timestamped previews. It needs no API keys, Python runtime, paid inference or persistent backend. The desktop application retains semantic search and the full feature set. The original Docker deployment below remains an option for server-side uploads and live API features; it is not required for Vercel.

From the repository root:

```powershell
.venv/Scripts/python.exe deployment/export_static.py
node deployment/vercel/build.mjs
```

Commit the exported catalog and shared website files. In Vercel select root directory **deployment**, preset **Other**, build command **node vercel/build.mjs**, output **vercel/public**. Full publishing steps and limitations are in the guide above.

## Original Docker backend

This folder contains the landing page and a browser sandbox with a read-only shared library and private uploads. Desktop source files are not changed. `snapshot.ps1` copies the engine and display font here; Docker builds use only this directory. Nothing has been deployed to a cloud account.

## What is ready

- Landing page styled like the desktop app: grey panels, orange accents, custom display font and monospace text.
- Windows download and sandbox calls to action; release URLs are configured in `site/config.json`.
- Browser search, type filters, thumbnails, image/audio/video previews, timecoded shots and similar assets using the existing engine.
- Private session uploads into named folders, automatically expired after 24 hours. The shared library remains read-only. Desktop settings, arbitrary server folders, rescans, feedback writes, web downloads and b-roll endpoints remain blocked.
- Server-side path containment checks, host validation, a global API budget (240 requests/minute), two concurrent search workers, and a single application worker.
- Your server-side Nebius key funds NVIDIA descriptions during upload processing. Your Tavily key funds the optional web search. Keys are mounted as secrets, never shipped in frontend files or API responses. Ordinary library search makes no paid API call.
- Docker Compose for local preview and a Nebius CPU VM with Caddy HTTPS. Serverless Endpoint notes are below.

Your cleared media folder has not been supplied yet. The sandbox intentionally starts empty. This is a focused library demo, not every desktop feature. Do not import your personal desktop database or settings.

## 1. Publish the Windows release

The Windows installer is published as the `v0.1.0` GitHub release:

https://github.com/SOMASEKAR17/asset-assistant/releases/tag/v0.1.0

Installer SHA-256:

```text
5031FA4C35D3F7EE4BD5BC4AAE44D1D57FD43F381A5861FC50D3C77A1CB0A444
```

The release includes the `.exe` and its matching `.exe.sha256` checksum file. The installer is 485,898,442 bytes (about 463 MiB).

The site's `site/config.json` already points to this release:

```json
{
  "downloadUrl": "https://github.com/SOMASEKAR17/asset-assistant/releases/download/v0.1.0/CreatorAssetAssistant-Setup-0.1.0.exe",
  "checksumUrl": "https://github.com/SOMASEKAR17/asset-assistant/releases/download/v0.1.0/CreatorAssetAssistant-Setup-0.1.0.exe.sha256",
  "sandboxUrl": "sandbox.html",
  "version": "0.1.0",
  "downloadSize": "463 MB"
}
```

Until a valid URL is set the download control is disabled, with an explanation. The installer is unsigned and includes Python, FFmpeg and model runtimes; the desktop app downloads model weights on first launch. No installer is copied into the container.

## 2. Prepare this folder

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File deployment/snapshot.ps1
Set-Location deployment
Copy-Item .env.example .env
```

The snapshot is already generated in this workspace. Rerun it only when intentionally taking a newer desktop engine version. Keep `vendor/` when copying this folder to a server; it is ignored by Git, so a plain clone will not contain it. `vendor/source-hashes.json` records the copied Python files.

Start Docker Desktop in Linux-container mode. Docker's engine was stopped during preparation, so container execution has not yet been verified here.

Copy only media cleared for public preview into `deployment/library/`. Keep a separate list of source URLs, licence terms and attribution obligations. The demo exposes the sample files to visitors; do not treat it as copy protection. For consistent browser playback use H.264/AAC MP4 video, JPEG/PNG/WebP images, and MP3/WAV audio. Convert unsupported formats before indexing. Avoid unsupported templates in the initial library.

## 3. Build and index the sample library

Run in `deployment/`:

```powershell
docker compose build web
docker compose --profile prepare run --rm index
```

Configure the server secret files as described below. Both the preparation job and the upload worker read your Nebius key from `/run/secrets/nebius_key`; visitors cannot read that path. The indexer sends keyframes and audio excerpts to Nebius in this mode. Without a key it uses local descriptions. Indexing downloads SigLIP, the multilingual meaning model and Parakeet into the `models` Docker volume and creates `seed/library.db` plus `seed/thumbs/`.

Index **inside this container**, not with your Windows desktop app. The database paths must remain `/library/...` and `/data/thumbs/...` in deployment. The runtime mounts samples read-only and copies the prepared database and thumbnails into temporary `/data` storage. It does not write back to the seed.

Wait for a successful indexing exit with zero incomplete assets. Stop any running web container before regenerating the seed, then restart it afterward. Keep credentials in secret files; do not put them into `.env`, the image, or `site/config.json`. Do not delete the models volume.

```powershell
  docker compose up -d web
docker compose logs --tail 80 web
```

For local HTTP testing only, set `DEMO_SECURE_COOKIE=0` in `.env` and recreate `web`. Keep it at `1` for production HTTPS. Open `http://127.0.0.1:8080`. Check a real query, a timecoded video preview, an audio preview and an image. Models load in the background; early searches may use keywords until loading finishes. The web service is offline for model downloads, so its model cache must already be prepared.

The default seed limit is 1 GB of temporary storage and the web memory limit is 8 GB. Start with a small library (for example 20–50 clips). Measure actual memory/index size and increase these limits before expanding it. Indexing has a 12 GB memory limit.

## 4. Deploy on Nebius AI Cloud

The most direct first deployment is a **CPU VM running this Compose stack**. It gives the app a persistent model cache, sample files, an index and automatic HTTPS in one place. No GPU is required for public search; NVIDIA Nemotron runs through Token Factory during indexing.

1. In your Nebius project, create an Ubuntu Linux VM with a public IP, an SSH key, enough disk for media/model caches/container layers, and at least 16 GB RAM for the supplied preparation limits. Confirm your project's available presets and pricing before creating it.
2. Install Docker Engine and the Compose plugin using the [official Ubuntu Docker instructions](https://docs.docker.com/engine/install/ubuntu/).
3. Copy this `deployment/` folder to the VM, including `vendor/`, `site/` and cleared `library/`. Exclude `.preview/`, local `.env`, `secrets/`, and any installer; provision secret files separately as described below. Create a fresh `.env` on the VM from `.env.example`. If indexing locally, note that the named models volume is **not** part of this folder; the simplest approach is to index again on the VM.
4. Point an A record such as `creator.example.com` to the VM's public IP. Only publish an AAAA record if IPv6 reaches the same machine. Set `DOMAIN=creator.example.com` and your real `ACME_EMAIL` in `.env`.
5. Allow inbound TCP 80 and 443 to the VM, and SSH only from your administrative address. Port 8080 remains bound to loopback; do not expose it separately.
6. From the uploaded folder run:

```bash
docker compose build web
docker compose --profile prepare run --rm index
docker compose --profile production up -d web proxy
docker compose logs --tail 80 web proxy
```

7. Open `https://creator.example.com`. Caddy provisions HTTPS when DNS and ports 80/443 are correctly configured. Keep its data volume so certificates survive container replacement. [Caddy HTTPS setup](https://caddyserver.com/docs/quick-starts/https)
8. Verify the download reaches your published `.exe`, the checksum matches, search returns your samples, previews seek correctly, and `/api/settings` returns 404. A POST to `/api/folders` must return 405. Check the site from a phone as well.

Run `python check_live.py https://creator.example.com` for a read-only smoke check of HTTPS, release links, a populated library and hidden desktop routes. `release.json` records this build's filename, byte size and checksum.

If Docker commands require privileges on your VM, use `sudo docker ...` or configure Docker access according to its official installation documentation.

The landing page and sandbox share one origin, so no cross-origin API configuration is required. The public URL belongs in the project's demo submission.

### Planned Serverless Endpoint alternative

Nebius supports custom HTTP containers and documents CPU endpoints. [Official endpoint quickstart](https://github.com/nebius/serverless-ai-cookbook/blob/main/quickstarts/first-endpoint.md)

This same application image listens on port 8080, with `/healthz` as its health route. To use an Endpoint instead of the VM:

- Push `creator-asset-web:0.1.0` to a registry your Nebius project can pull.
- Mount the cleared sample library at `/library`, the prepared seed at `/seed`, and the populated model cache at `/models`. Samples and seed can come from Nebius Object Storage via supported mounts. `/data` and `/tmp` need writable temporary storage. Set `DEMO_HOME=/data`, `DEMO_SEED=/seed`, `DEMO_LIBRARY=/library`, `HF_HOME=/models`, and `HF_HUB_OFFLINE=1`.
- Set `DEMO_ALLOWED_HOSTS` to the real endpoint hostname and your public hostname, plus `127.0.0.1` for health checks. Keep one worker. Mount the key files as platform secrets and set `NEBIUS_API_KEY_FILE` and `TAVILY_API_KEY_FILE` to those paths; never use frontend configuration for credentials. Mount a persistent writable `/uploads` volume and set `DEMO_UPLOADS=/uploads`, `DEMO_ASR_MODELS=/models/asr`, and `DEMO_SECURE_COOKIE=1`.
- Configure CPU capacity, port 8080, ingress and a trusted HTTPS domain using the controls actually available in your project. A raw HTTP endpoint/IP is not a finished public website.
- Keep infrastructure authentication at your trusted ingress if required, and let the ingress serve browser traffic. Never embed a private endpoint bearer token in frontend JavaScript.
- Validate volume mounting, UID 10001 read permissions, media Range requests and restart behavior before switching the landing-page link. Check current endpoint billing and lifecycle rules; do not assume idle time is free.

The included Compose stack is the complete VM route. Endpoint provisioning is intentionally not represented by a guessed CLI command: storage/ingress configuration depends on your Nebius project. No cloud credentials, resource IDs or domain were supplied in this task.

### Hosting the landing page separately

You may instead publish only `site/` to a static host and set `sandboxUrl` to the absolute HTTPS URL of the sandbox's `sandbox.html`. Do not expect `sandbox.html` on a static-only host to run the Python API. The default configuration assumes everything is served together by this container.

## Updates, limits and operations

- Update code: take a new snapshot if needed, rebuild, then run `docker compose --profile production up -d web proxy`. Re-index if model IDs or index formats change. Keep the same image for indexing and serving.
- Update media: stop `web`, update `library`, rerun `index`, then start `web`. Preserve a backup of the previous library, seed and image tag for rollback.
- Ordinary library searches make no paid calls. Upload processing uses Nebius, and optional web searches use Tavily. Persistent global usage limits apply even when visitors create new sessions; they are request/job caps, not exact dollar limits. Configure provider billing alerts and limits too. CPU hosting, storage and bandwidth also cost money. At higher traffic add per-client limits at your trusted ingress.
- Do not run multiple application workers with this temporary SQLite seed setup. Scale only after defining per-replica data/model loading and ingress limits.
- Search result feedback is disabled, so visitors cannot change rankings for everyone else.
- Health checks prove the HTTP process is alive; they do not certify sample completeness or semantic-model readiness. Verify real searches before announcing the site.

## Local checks without Docker

From the repository root, using the existing development Python environment:

```powershell
.venv/Scripts/python.exe -m unittest discover -s deployment/tests -v
node --check deployment/site/site.js
node --check deployment/site/sandbox.js
docker compose -f deployment/compose.yaml config --quiet
```

For an empty-library layout preview (no model downloads):

```powershell
Set-Location deployment
$env:DEMO_ML = '0'
$env:DEMO_SECURE_COOKIE = '0' # localhost HTTP only
../.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8788
```

Open `http://127.0.0.1:8788`. Stop with Ctrl+C. This is a local preview, not a deployment. API tests create temporary synthetic fixtures only; no generated public media is included.


## Server credentials (updated upload deployment)

Your existing Nebius and Tavily keys have been copied to `deployment/secrets/nebius_api_key.txt` and `deployment/secrets/tavily_api_key.txt` in this workspace, without displaying their values. These files are ignored by Git and excluded from the Docker build context. They are not inside `site/` and there is no API to read or update credentials.

To refresh them from your desktop's existing configuration, run from the repository root:

```powershell
.venv/Scripts/python.exe deployment/configure_secrets.py --from-desktop
```

On the server, provision those two files through your normal secure transfer or secret-management process, not a public Git repository. Docker Compose mounts them read-only at `/run/secrets/nebius_key` and `/run/secrets/tavily_key`. The API clients read those files directly; credential values never enter JavaScript, API responses or subprocess command arguments. Server administrators still have access to server secrets.

On a Linux VM, ensure UID 10001 (the container user) can read the secret files. For example, after provisioning `secrets/` in the deployment directory:

```bash
sudo chown 10001:10001 secrets/nebius_api_key.txt secrets/tavily_api_key.txt
sudo chmod 0400 secrets/nebius_api_key.txt secrets/tavily_api_key.txt
```

Keep `DEMO_SECURE_COOKIE=1` in production. Use HTTPS. After key rotation, recreate the web service. Never paste a key into the public website, a URL, an issue, or `site/config.json`.

## Private upload behavior and limits

The website owner and public visitors can use **Upload privately**. Choose a private folder name and files; the server creates generated directories in its persistent `uploads` volume. Browser cookies identify a session with a high-entropy opaque token marked HttpOnly and SameSite=Strict. The server never accepts caller-supplied disk paths.

- Maximum file size: **50 MiB** (shown as 50 MB in the UI), enforced while streaming, including requests without Content-Length.
- Per session: **200 MiB** stored raw uploads and **10 upload attempts per 24 hours**. The quota reserves 50 MiB during an upload, so small remaining space may reject another file conservatively.
- Global raw-upload quota: **5 GiB**. Generated thumbnails, indexes, and the model cache require additional disk space.
- Global upload admission: **20 attempts/hour**, **100/day**, at most **4 receiving/queued/processing files**. One worker processes at a time, with a **5-minute process timeout** and at most **2 captioned video shots** per file.
- Formats: JPEG, PNG, single-frame WebP, MP4, WebM, MP3 and WAV. Content is inspected before indexing. Images are limited to 20 megapixels; audio/video to 2 minutes and video to 4K. Archives, executables, SVG, and playlists are rejected. Some codec combinations may still fail browser playback.
- Tavily searches: **10/session/day**, **30 globally/hour**, **100 globally/day**. No arbitrary provider URL or authenticated proxy is exposed.
- Sessions expire **24 hours after creation**, not 24 hours after the most recent upload. Access is denied at expiry. The janitor checks every 30 seconds; files held open are retried. If the service is stopped, disk deletion resumes at startup. Keep the service running to meet the retention schedule.
- Session databases and thumbnails are separate. Public library routes cannot read private uploads, and every private asset, thumbnail, media and search request checks the session. Private responses use `Cache-Control: private, no-store`.

The session list, usage counters and files survive a container restart. Upload processing interrupted by a restart is marked failed rather than automatically retried against your paid APIs. Do not run multiple web replicas against this store; the single-process quota/worker coordination assumes one replica. Do not back up the `uploads` volume if you want the 24-hour retention policy to apply to all copies. Keep backups of your curated `library` and `seed` separately.

Uploads are not anonymous public posts: they are private to whoever holds that browser session cookie, plus the server operator. Clearing cookies loses browser access; it does not restart or postpone expiry. Processing sends selected keyframes/audio excerpts to Nebius under your account's retention settings. Enable the provider retention settings you require; local deletion cannot delete a provider's separate logs.

For a permanent **shared** sample library, continue copying cleared files into `deployment/library/` and running the preparation job. The public upload control intentionally cannot modify that shared library.

### Redeploy this update

1. Provision the secret files above and set the HTTPS domain and `DEMO_SECURE_COOKIE=1`.
2. Rebuild the image: `docker compose build web`.
3. Rerun `docker compose --profile prepare run --rm index` to populate the shared `/models/asr` cache as well as the other models before accepting uploads. Use the curated library as before.
4. Run `docker compose --profile production up -d web proxy`. Compose creates the persistent `uploads` volume with the image's UID 10001 ownership.
5. In two separate browser profiles, upload a small file in one profile and confirm the other cannot see it. Test 50 MB rejection, session expiry, private previews and a Tavily query. Check provider usage and server disk space.

The local test suite covers real image indexing without paid calls, cross-session isolation, expiry/deletion, stream-size enforcement, CSRF controls, path validation, persisted usage caps and secret/error-response leakage. Real cloud requests are not made by tests. Cloud deployment and the Docker image still need validation in your running Docker/Nebius environment.
