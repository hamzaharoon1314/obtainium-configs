# Obtainium Configs 

Adding patched APKs to [Obtainium](https://github.com/ImranR98/Obtainium) means hunting down the right package ID, finding the correct asset filter regex, and manually filling in every field. Do that for a dozen apps across a few repos and it gets old fast.

This repo automates all of that.

---

## What it does

A GitHub Actions workflow periodically scans a list of patched APK repositories (ReVanced, ReVanced Extended, Morphe, Anddea, Piko, and others). For each release asset it finds, it:

1. Extracts the package ID and version from the APK
2. Generates a ready-to-use Obtainium config (Discoverium JSON) with the correct source URL, asset filter regex, and app metadata pre-filled
3. Commits everything to this repo so the data stays current automatically

---

## How to use it

Visit the site to browse all tracked repos and packages:

**→ [hamzaharoon1314.github.io/obtainium-configs](https://hamzaharoon1314.github.io/obtainium-configs)**

Find the app you want, then hit **Add to Obtainium** — it opens Obtainium directly with the config pre-loaded. No manual setup needed.

There's also a **Copy JSON** button if you want the raw config, and a **Play Store** link where available.

---

## Tracked repos

<!-- TRACKED_REPOS_START -->
- [FiorenMas/Revanced-And-Revanced-Extended-Non-Root](https://github.com/FiorenMas/Revanced-And-Revanced-Extended-Non-Root) — 226 packages
- [crimera/twitter-apk](https://github.com/crimera/twitter-apk) — 4 packages

_Last updated: 2026-05-16 08:50 UTC_
<!-- TRACKED_REPOS_END -->

---

## Repository

[github.com/hamzaharoon1314/obtainium-configs](https://github.com/hamzaharoon1314/obtainium-configs)

---

## Adding a new repo

1. Add the repo identifier to `docs/repos/repos.json`
2. The workflow picks it up on the next run and generates all the configs

---

## Tech

- Python script scrapes release assets and extracts package metadata
- GitHub Actions runs the update on a schedule
- GitHub Pages hosts the browser UI