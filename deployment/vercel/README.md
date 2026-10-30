# Vercel static interactive preview

This is a lightweight glimpse of the desktop app, not a full sandbox. It searches the prepared sample library by keywords in names, captions, tags and transcripts. Results retain shot timestamps and playable previews. There are no Python functions, model downloads, API calls, private uploads or background workers in this deployment. No API keys are needed in Vercel.

The desktop app adds semantic search, indexing your own folders, folder watching, b-roll planning and licence tools. No speed or accuracy multiplier has been measured, so the website makes no comparative benchmark claims.

## 1. Export the prepared library locally

From the repository root, after indexing your cleared public samples:

```powershell
.venv/Scripts/python.exe deployment/export_static.py
node deployment/vercel/build.mjs
node --test deployment/vercel/search.test.mjs
.venv/Scripts/python.exe deployment/vercel/check_git_inputs.py
```

The exporter reads `deployment/seed/library.db`, maps `/library` to `deployment/library` and `/data` to `deployment/seed`, then writes `vercel/catalog/index.json` and content-addressed media. It copies existing samples and thumbnails; it does not reindex, transcode or call any API. Original sample videos are retained and indexed segment timestamps seek within them; footage is not cut again. Already-cut clips can also be indexed and exported.

The exported JSON includes only selected public text, timing and licence fields. It excludes raw paths, GPS, device IDs, credentials, model vectors and feedback tables. Review captions/transcripts and media for suitability before publishing. Only export media cleared for public redistribution: the sample files and JSON will be publicly downloadable.

Do not commit the raw SQLite database, private uploads, secrets or the original personal library. `library/`, `seed/`, `uploads/` and `secrets/` remain ignored. Only `vercel/catalog/media` has a deliberate media exception in `.gitignore`.

## 2. Push the static inputs to GitHub

Commit the new deployment configuration/scripts, `vercel/catalog/index.json`, `vercel/catalog/media/`, and shared `site/` files including fonts and the demo video. Use normal Git for these small sample files, not Git LFS pointer files. The generated `vercel/public/` output is ignored and rebuilt by Vercel. Confirm exported assets are included with `git status --short -- deployment/vercel/catalog`.

`check_git_inputs.py` verifies every catalog-referenced media file, shared font and build input exists and is not ignored, while confirming secrets and generated output remain ignored. Run it after updating samples. Git-visible means ready to commit, not already pushed.

The exporter rejects individual media files at or above 95 MiB to leave room below common Git/static-file limits. Compress or split large samples before indexing. GitHub and Vercel storage/bandwidth quotas still apply; this does not guarantee unlimited free hosting.

## 3. Import the repository into Vercel

1. Add a new Vercel project and import this GitHub repository.
2. Set **Root Directory** to **`deployment`**, not the repository root and not `deployment/vercel`.
3. Set **Framework Preset** to **Other**.
4. Build command: **`node vercel/build.mjs`**.
5. Output directory: **`vercel/public`**.
6. No dependency install command or environment variables are required. `deployment/vercel.json` supplies the settings and security headers.
7. Deploy. Check `/`, `/sandbox.html`, demo playback, a keyword query, media filters and a timestamped preview.

The allowlisted build copies only website files and catalog-referenced media to the public output. It changes the landing page's upload/privacy text for this static variant and preserves the full Docker site's behavior. The Windows installer continues to download from the configured GitHub Release, not from Vercel.

## Updating samples

Update the local prepared index, rerun the exporter, build and test, then commit/push the exported catalog and referenced media. Vercel rebuilds from Git. Hash-based media names change when file contents change. HTML and the JSON index revalidate on reload to avoid stale interfaces. Old unreferenced exported media are not copied to the public build; they can be removed from the source catalog separately after reviewing references.

## Local preview

```powershell
node deployment/vercel/build.mjs
.venv/Scripts/python.exe deployment/vercel/preview.py
```

Open `http://127.0.0.1:8093/`. This local helper uses the project's existing Starlette/Uvicorn installation to support HTTP Range requests for video seeking. Python is only used for this optional local preview; Vercel serves the built files directly. Use HTTP rather than double-clicking the HTML because the browser fetches the JSON catalog and JavaScript modules.

For private uploads, live Tavily search and AI processing, the original Docker backend remains available as a separate hosting option. This static version does not replace those capabilities with misleading controls.
