#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import tempfile
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


PKG_RE = re.compile(r"package:\s+name='([^']+)'")
VERSION_RE = re.compile(r"versionName='([^']+)'")
LABEL_RE = re.compile(r"application-label(?:-[^:]+)?:'([^']+)'")

def normalize_repo(value: str) -> str:
    """Accept either 'owner/repo' or any GitHub URL form and return 'owner/repo'."""
    value = value.strip().rstrip("/")
    # Strip common GitHub URL prefixes
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "github.com/",
    ):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    # Drop any trailing path (tree/main, releases, etc.)
    parts = value.split("/")
    if len(parts) < 2:
        raise SystemExit(f"Cannot parse repo from: {value!r}")
    return f"{parts[0]}/{parts[1]}"

@dataclass
class ApkInfo:
    asset_name: str
    app_name: str
    package_id: str
    version_name: str
    sha256: str
    size_bytes: int
    download_url: str
    play_store_url: str


def sanitize_filename(name: str) -> str:
    return name.replace("/", "__").replace("\\", "__")


def find_aapt() -> str:

    env_path = os.environ.get("AAPT_PATH")

    if env_path and Path(env_path).exists():
        return env_path

    for candidate in ("aapt", "aapt.exe"):

        found = shutil.which(candidate)

        if found:
            return found

    raise SystemExit(
        "aapt not found. Install Android build-tools and set AAPT_PATH."
    )


def github_session(token: Optional[str]) -> requests.Session:

    s = requests.Session()

    s.headers.update({
        "Accept": "application/vnd.github+json"
    })

    if token:
        s.headers.update({
            "Authorization": f"Bearer {token}"
        })

    return s


def get_release(session: requests.Session, repo: str, release: str):

    if release == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"

    else:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{release}"

    r = session.get(url, timeout=60)

    r.raise_for_status()

    return r.json()


def download_file(
    session: requests.Session,
    url: str,
    out_path: Path
):

    with session.get(url, stream=True, timeout=300) as r:

        r.raise_for_status()

        total = int(r.headers.get("content-length", 0))

        downloaded = 0

        with out_path.open("wb") as f:

            for chunk in r.iter_content(chunk_size=1024 * 1024):

                if chunk:

                    f.write(chunk)

                    downloaded += len(chunk)

                    if total > 0:

                        percent = downloaded / total * 100

                        print(
                            f"\r{out_path.name}: "
                            f"{downloaded // (1024*1024)}MB / "
                            f"{total // (1024*1024)}MB "
                            f"({percent:.1f}%)",
                            end="",
                            flush=True
                        )

        print()



def calculate_sha256(path: Path) -> str:

    sha256 = hashlib.sha256()

    with path.open("rb") as f:

        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def extract_badging(aapt: str, apk_path: Path):

    proc = subprocess.run(
        [aapt, "dump", "badging", str(apk_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())

    stdout = proc.stdout

    pkg_match = PKG_RE.search(stdout)

    if not pkg_match:
        raise RuntimeError("Package ID not found")

    version_match = VERSION_RE.search(stdout)
    label_match = LABEL_RE.search(stdout)

    package_id = pkg_match.group(1)

    version_name = (
        version_match.group(1)
        if version_match else "Unknown"
    )

    app_name = (
        label_match.group(1)
        if label_match else apk_path.stem
    )


    return (
        app_name,
        package_id,
        version_name,
    )


def generate_discoverium_config(
    repo,
    asset,
    row,
    all_assets
):

    primary_name = asset["name"]

    other_assets = []

    for a in all_assets:

        if a["name"] != primary_name:

            other_assets.append([
                a["name"],
                a["browser_download_url"]
            ])

    config = {

        "id": row.package_id,

        "url": f"https://github.com/{repo}",

        "author": repo.split("/")[0],

        "name": row.app_name,

        "installedVersion": "",

        "latestVersion": "",

        "apkUrls": json.dumps([
            [
                primary_name,
                row.download_url
            ]
        ]),

        "otherAssetUrls": json.dumps(
            other_assets
        ),

        "preferredApkIndex": 0,

        "additionalSettings": json.dumps({

            "includePrereleases": False,

            "fallbackToOlderReleases": True,

            "filterReleaseTitlesByRegEx": "",

            "filterReleaseNotesByRegEx": "",

            "verifyLatestTag": False,

            "sortMethodChoice": "date",

            "useLatestAssetDateAsReleaseDate": True,

            "releaseTitleAsVersion": False,

            "trackOnly": False,

            "versionExtractionRegEx": "",

            "matchGroupToUse": "",

            "versionDetection": False,

            "releaseDateAsVersion": True,

            "useVersionCodeAsOSVersion": False,

            "apkFilterRegEx": (
                "^" +
                re.escape(primary_name)
                    .replace("\\.apk", ".*\\.apk$")
            ),

            "invertAPKFilter": False,

            "autoApkFilterByArch": True,

            "appName": row.app_name,

            "appAuthor": repo.split("/")[0],

            "shizukuPretendToBeGooglePlay": False,

            "allowInsecure": False,

            "exemptFromBackgroundUpdates": False,

            "skipUpdateNotifications": False,

            "about": "",

            "refreshBeforeDownload": False,

            "dontSortReleasesList": False
        }),

        "lastUpdateCheck": int(
            time.time() * 1000000
        ),

        "pinned": False,

        "categories": [],

        "releaseDate": None,

        "changeLog": None,

        "overrideSource": None,

        "allowIdChange": False,
    }

    return config

def markdown_table(rows, repo, release):

    lines = []

    lines.append(f"# Android APK Package ID & Discoverium Config Generator for `{repo}`")
    lines.append("")

    lines.append(f"Release source: `{release}`")
    lines.append("")

    lines.append(
        "| App | Package ID | Asset Filename | Version | Play Store | Config  |"
    )

    lines.append(
        "|---|---|---|---|---|---|"
    )

    for row in rows:

        safe_asset_name = (
            row.asset_name
            .replace(".apk", "")
            .replace("/", "_")
            .replace("\\", "_")
        )

        safe_display_name = (
            row.asset_name
            .replace("|", "\\|")
        )
                
        lines.append(
            f"| **{row.app_name}** "
            f"| {row.package_id} "
            f"| {safe_display_name} "
            f"| {row.version_name} "
            f"| {'[Play Store](' + row.play_store_url + ')' if row.play_store_url else 'N/A'} "
            f"| [JSON Config](./discoverium/{row.package_id}__{safe_asset_name}.json) |"
        )

    lines.append("")
    lines.append("## SHA256")
    lines.append("")

    for row in rows:

        lines.append(
            f"- **{row.asset_name}**"
        )

        lines.append(
            f"  - `{row.sha256}`"
        )

    lines.append("")
    lines.append("_Automatically generated from GitHub APK release assets with package IDs, SHA256 hashes, and Discoverium import links._")

    return "\n".join(lines)

def generate_play_store_url(package_id: str) -> str:

    package_id = package_id.strip()

    return (
        "https://play.google.com/store/apps/details?id="
        + urllib.parse.quote(package_id)
    )


def play_store_exists(
    session: requests.Session,
    package_id: str
) -> bool:

    url = generate_play_store_url(package_id)

    try:

        r = session.get(
            url,
            timeout=15,
            allow_redirects=True
        )

        text = r.text.lower()

        return (
            r.status_code == 200
            and "/store/apps/details" in r.url
            and "item not found" not in text
            and "requested url was not found" not in text
        )

    except Exception:

        return False

def main() -> int:

    parser = argparse.ArgumentParser(
        description="Android APK Metadata & Discoverium Config Generator"
    )

    parser.add_argument(
        "--repo",
        help="GitHub repo in owner/repo format"
    )

    parser.add_argument(
        "--release",
        default="latest",
        help="Release tag or latest"
    )

    parser.add_argument(
        "--keep-downloads",
        action="store_true"
    )

    args = parser.parse_args()

    repo = args.repo

    if not repo:
        repo = input(
            "Enter GitHub repo (owner/repo or GitHub URL): "
        ).strip()

    try:
        repo = normalize_repo(repo)
    except SystemExit as e:
        print(f"Invalid input: {e}")
        return 1

    safe_repo_name = sanitize_filename(repo)

    repo_dir = (
        Path("docs/repos") / safe_repo_name
    )

    discoverium_dir = (
        repo_dir / "discoverium"
    )

    metadata_dir = (
        repo_dir / "metadata"
    )

    markdown_output = (
        repo_dir / "index.md"
    )

    json_output = (
        metadata_dir / "repo.json"
    )

    json_output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    repo_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    discoverium_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    metadata_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    token = os.environ.get("GITHUB_TOKEN")

    session = github_session(token)

    print(f"Fetching release data for {repo}...")

    release_data = get_release(
        session,
        repo,
        args.release
    )

    assets = release_data.get("assets", [])

    apk_assets = [
        a for a in assets
        if a.get("name", "").lower().endswith(".apk")
    ]

    if not apk_assets:

        print("No APK assets found.")

        return 1

    aapt = find_aapt()

    download_dir = Path("downloads")

    tmp_dir_obj = None

    if args.keep_downloads:

        download_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    else:

        tmp_dir_obj = tempfile.TemporaryDirectory()

        download_dir = Path(tmp_dir_obj.name)

    results = []

    def process_asset(asset):

        asset_name = asset["name"]

        url = asset["browser_download_url"]

        out_path = download_dir / asset_name

        start = time.time()

        print(f"\nDownloading: {asset_name}", flush=True)

        download_file(
            session,
            url,
            out_path
        )

        print(
            "Extracting metadata...",
            flush=True
        )

        (
            app_name,
            package_id,
            version_name
        ) = extract_badging(
            aapt,
            out_path
        )

        sha256 = calculate_sha256(out_path)

        safe_asset_name = (
            asset_name
            .replace(".apk", "")
            .replace("/", "_")
            .replace("\\", "_")
        )
        
        package_id = package_id.strip()

        if play_store_exists(session, package_id):

            play_store_url = generate_play_store_url(
                package_id
            )

        else:

            play_store_url = ""
        
        row_data = ApkInfo(
            asset_name=asset_name,
            app_name=app_name,
            package_id=package_id,
            version_name=version_name,
            sha256=sha256,
            size_bytes=int(asset.get("size", 0)),
            download_url=url,
            play_store_url=play_store_url,
        )

        discoverium_config = generate_discoverium_config(
            repo,
            asset,
            row_data,
            apk_assets
        )

        discoverium_path = (
            discoverium_dir /
            f"{package_id}__{safe_asset_name}.json"
        )

        discoverium_path.write_text(
            json.dumps(
                discoverium_config,
                indent=2,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )        

        elapsed = time.time() - start

        print(
            f"✓ {package_id} ({elapsed:.2f}s)",
            flush=True
        )

        return row_data

    try:

        with ThreadPoolExecutor(max_workers=6) as executor:

            futures = [
                executor.submit(process_asset, asset)
                for asset in sorted(
                    apk_assets,
                    key=lambda x: x["name"].lower()
                )
            ]

            for future in as_completed(futures):

                try:
                    results.append(
                        future.result()
                    )

                except Exception as e:
                    print(
                        f"✗ {e}",
                        flush=True
                    )

    finally:

        if tmp_dir_obj is not None:
            tmp_dir_obj.cleanup()

    results.sort(
        key=lambda x: x.app_name.lower()
    )

    markdown_output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    md = markdown_table(
        results,
        repo,
        args.release
    )

    markdown_output.write_text(
        md,
        encoding="utf-8"
    )

    json_output.write_text(
        json.dumps(
            [
                {
                    "app_name": r.app_name,
                    "asset_name": r.asset_name,
                    "package_id": r.package_id,
                    "version_name": r.version_name,
                    "sha256": r.sha256,
                    "play_store_url": r.play_store_url,
                    "download_url": r.download_url,
                    "discoverium_file": (
                        f"../discoverium/"
                        f"{r.package_id}__"
                        f"{r.asset_name.replace('.apk', '').replace('/', '_').replace('\\\\', '_')}.json"
                    ),
                }
                for r in results
            ],
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print("\nMarkdown updated:")
    print(markdown_output)

    print("\nJSON updated:")
    print(json_output)
    
    repo_list_path = Path(
        "docs/repos/repos.json"
    )

    repos_root = Path("docs/repos")

    repos = sorted([
        p.name
        for p in repos_root.iterdir()
        if (p / "index.md").exists()
    ])

    repo_list_path.write_text(
        json.dumps(repos, indent=2),
        encoding="utf-8"
    )

    print("\nDone.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())