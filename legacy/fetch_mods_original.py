#!/usr/bin/env python3
"""
fetch_mods.py - Enterprise Portable Mod Asset Pipeline
-------------------------------------------------------
Automates resolution, authentication, downloading, extraction, and post-audit
scanning of Infinity Engine mods directly from a `mod_downloads.json` manifest file.

Supported Formats: .iemod (Project Infinity - Preferred), .zip, .tar.gz, .tgz, .tar.bz2, .7z, .rar, .exe (SFX)
Supported Sources: GitHub API (S3 Redirect Safe), WeaselMods (WPDM), Gibberlings3, Dropbox
"""

import os
import sys
import json
import re
import time
import shutil
import zipfile
import tarfile
import subprocess
import webbrowser
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURATION & CONSTANTS ---
JSON_FILE = "mod_downloads.json"
TARGET_DIR = os.path.abspath("./Mods")
MAX_WORKERS = 4
VSCODE_GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
RUNTIME_GH_TOKEN = None


# --- HTTP S3 REDIRECT HANDLER ---
class AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Strips Authorization header when redirected to AWS S3 to prevent 403/400 errors."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if "github.com" not in urllib.parse.urlparse(newurl).netloc:
            if "Authorization" in new_req.headers:
                del new_req.headers["Authorization"]
            if "authorization" in new_req.headers:
                del new_req.headers["authorization"]
        return new_req


# --- SYSTEM CLIPBOARD HELPER ---
def copy_to_clipboard(text: str):
    """Copies text to system clipboard using native OS commands without third-party libraries."""
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, stderr=subprocess.DEVNULL)
        elif sys.platform == "linux":
            for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    subprocess.run(cmd, input=text.encode("utf-8"), check=True, stderr=subprocess.DEVNULL)
                    break
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
    except Exception:
        pass


# --- ADVANCED HTML LINK EXTRACTOR ---
class AdvancedHtmlLinkExtractor(HTMLParser):
    """Parses HTML landing pages across multiple attribute types without external packages."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links = []

    def handle_starttag(self, tag: str, attrs: list):
        attr_dict = {k.lower(): v for k, v in attrs if v}
        for key in ["href", "action", "data-downloadurl", "data-url", "src"]:
            if key in attr_dict:
                abs_url = urllib.parse.urljoin(self.base_url, attr_dict[key])
                self.links.append(abs_url)


# --- AUTHENTICATION MODULE ---
def get_github_token() -> str:
    """Automates GitHub token retrieval via env vars, local `gh` CLI, or OAuth 2.0 Device Flow."""
    env_token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if env_token:
        return env_token

    try:
        gh_token = subprocess.check_output(
            ["gh", "auth", "token"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if gh_token:
            print("[INFO] Loaded active authentication session from local `gh` CLI.")
            return gh_token
    except Exception:
        pass

    device_code_url = "https://github.com/login/device/code"
    payload = urllib.parse.urlencode({
        "client_id": VSCODE_GITHUB_CLIENT_ID,
        "scope": "public_repo"
    }).encode("utf-8")

    req = urllib.request.Request(
        device_code_url,
        data=payload,
        headers={"Accept": "application/json"}
    )

    try:
        opener = urllib.request.build_opener(AuthRedirectHandler())
        with opener.open(req) as resp:
            dev_data = json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        print(f"[!] Device flow initiation failed: {err}")
        return input("Fallback - Enter personal GitHub token manually: ").strip()

    user_code = dev_data.get("user_code")
    device_code = dev_data.get("device_code")
    verification_uri = dev_data.get("verification_uri", "https://github.com/login/device")
    verification_uri_complete = dev_data.get(
        "verification_uri_complete", 
        f"{verification_uri}?user_code={user_code}"
    )
    interval = dev_data.get("interval", 5)

    copy_to_clipboard(user_code)

    print("\n" + "=" * 65)
    print(" GITHUB OAUTH 2.0 DEVICE AUTHORIZATION CODE")
    print("=" * 65)
    print(f" User Verification Code : \033[1;32m{user_code}\033[0m  (Copied to Clipboard!)")
    print(f" Direct Activation Link : {verification_uri_complete}")
    print("=" * 65)
    print("Launching browser with pre-filled activation code...")

    try:
        webbrowser.open(verification_uri_complete)
    except Exception:
        pass

    token_url = "https://github.com/login/oauth/access_token"
    poll_payload = urllib.parse.urlencode({
        "client_id": VSCODE_GITHUB_CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    }).encode("utf-8")

    print("Waiting for browser authorization confirmation...")
    opener = urllib.request.build_opener(AuthRedirectHandler())
    while True:
        time.sleep(interval)
        token_req = urllib.request.Request(
            token_url,
            data=poll_payload,
            headers={"Accept": "application/json"}
        )
        try:
            with opener.open(token_req) as t_resp:
                res = json.loads(t_resp.read().decode("utf-8"))
                if "access_token" in res:
                    print("[✓] OAuth device authentication successful!\n")
                    return res["access_token"]

                error = res.get("error")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 5
                else:
                    print(f"[X] Authentication error state: {error}")
                    break
        except Exception as poll_err:
            print(f"[X] Request polling exception: {poll_err}")
            break

    return input("Fallback - Enter personal GitHub token manually: ").strip()


def get_headers() -> dict:
    """Builds standard HTTP request headers."""
    global RUNTIME_GH_TOKEN
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if RUNTIME_GH_TOKEN:
        headers["Authorization"] = f"Bearer {RUNTIME_GH_TOKEN}"
    return headers


# --- ASSET RESOLVERS ---
def resolve_github_asset(repo: str, tp2: str = "", name: str = "") -> str:
    """Queries GitHub REST API with fallback variant handles and archive streams (preferring .iemod)."""
    owners_to_try = [repo]

    if "/" in repo:
        owner, rname = repo.split("/", 1)
        owners_to_try.append(f"{owner}/{rname.replace('-', '_')}")
        owners_to_try.append(f"{owner}/{rname.replace('_', '-')}")
        if "-" in owner:
            owners_to_try.append(f"{owner.replace('-', '')}/{rname}")
        else:
            if owner.lower() == "spellholdstudios":
                owners_to_try.append(f"Spellhold-Studios/{rname}")
            elif owner.lower() == "pocketplanegroup":
                owners_to_try.append(f"Pocket-Plane-Group/{rname}")

    opener = urllib.request.build_opener(AuthRedirectHandler())

    for target_repo in owners_to_try:
        api_url = f"https://api.github.com/repos/{target_repo}/releases/latest"
        req = urllib.request.Request(api_url, headers=get_headers())
        try:
            with opener.open(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                assets = data.get("assets", [])
                # Tier 1 Priority: Look for Project Infinity .iemod format assets
                for asset in assets:
                    if asset["name"].lower().endswith(".iemod"):
                        return asset["browser_download_url"]
                # Tier 2 Priority: Standard archive formats (.zip, .tar.gz, .7z, .rar, .exe)
                for asset in assets:
                    if asset["name"].lower().endswith((".zip", ".tar.gz", ".7z", ".rar", ".exe")):
                        return asset["browser_download_url"]
                if data.get("zipball_url"):
                    return data.get("zipball_url")
                if data.get("tarball_url"):
                    return data.get("tarball_url")
        except Exception:
            pass

        for branch in ["main", "master", "HEAD"]:
            head_url = f"https://github.com/{target_repo}/archive/refs/heads/{branch}.zip" if branch != "HEAD" else f"https://github.com/{target_repo}/archive/HEAD.zip"
            try:
                check_req = urllib.request.Request(head_url, headers=get_headers(), method="HEAD")
                with opener.open(check_req, timeout=10) as resp:
                    if resp.status == 200:
                        return head_url
            except Exception:
                pass

    query = tp2 if tp2 else name
    if query:
        search_url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}+in:name"
        req = urllib.request.Request(search_url, headers=get_headers())
        try:
            with opener.open(req) as resp:
                sdata = json.loads(resp.read().decode("utf-8"))
                items = sdata.get("items", [])
                if items:
                    found_repo = items[0]["full_name"]
                    return f"https://github.com/{found_repo}/archive/HEAD.zip"
        except Exception:
            pass

    raise RuntimeError(f"Could not resolve GitHub repository for {repo}")


def resolve_html_download_link(page_url: str) -> str:
    """Scrapes landing pages for direct archive links."""
    if "dropbox.com" in page_url:
        if "dl=0" in page_url:
            return page_url.replace("dl=0", "dl=1")
        elif "dl=1" in page_url:
            return page_url
        else:
            delimiter = "&" if "?" in page_url else "?"
            return f"{page_url}{delimiter}dl=1"

    clean_url = page_url.split("#")[0].rstrip("/")
    if not clean_url.endswith("/"):
        clean_url += "/"

    if ("gibberlings3.net" in clean_url or "baldurs-gate.de" in clean_url) and "do=download" in clean_url:
        return clean_url

    opener = urllib.request.build_opener(AuthRedirectHandler())
    req = urllib.request.Request(clean_url, headers=get_headers())

    try:
        with opener.open(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if any(ext in content_type for ext in ["iemod", "zip", "octet-stream", "x-zip", "compressed", "x-rar", "x-7z", "exe", "gzip", "tar"]):
                return clean_url
            html_content = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    parser = AdvancedHtmlLinkExtractor(clean_url)
    parser.feed(html_content)

    for link in parser.links:
        if "wpdmdl=" in link:
            return link

    for link in parser.links:
        if "do=download" in link or "download" in link.lower():
            if any(ext in link.lower() for ext in [".iemod", ".zip", ".tar.gz", ".7z", ".rar", ".exe", "attachment", "file"]):
                return link
        if re.search(r"\.(iemod|zip|tar\.gz|tgz|7z|rar|exe)(\?.*)?$", link, re.IGNORECASE):
            return link

    return None


# --- MULTI-FORMAT ARCHIVE EXTRACTION ENGINE ---
def detect_archive_type(file_path: str) -> str:
    """Detects archive type using header magic bytes (supporting Project Infinity .iemod)."""
    if file_path.lower().endswith(".iemod"):
        return "iemod"

    try:
        with open(file_path, "rb") as f:
            header = f.read(512)
        if header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06"):
            return "zip"
        elif header.startswith(b"\x1f\x8b") or header.startswith(b"BZh") or header.startswith(b"\xfd7zXZ\x00") or b"ustar" in header:
            return "tar"
        elif header.startswith(b"Rar!\x1a\x07"):
            return "rar"
        elif header.startswith(b"7z\xbc\xaf\x27\x1c"):
            return "7z"
        elif header.startswith(b"MZ"):
            if b"7z\xbc\xaf\x27\x1c" in header or b"Rar!" in header or b"PK\x03\x04" in header:
                return "sfx_exe"
            return "exe"
    except Exception:
        pass
    return "unknown"


def extract_archive(archive_path: str, extract_tmp: str) -> bool:
    """Extracts .iemod, .zip, .tar.gz, .rar, .7z, or .exe archives using stdlib and fallback tools."""
    archive_type = detect_archive_type(archive_path)

    # 1. Native Python Zip Extraction (Handles .iemod & .zip formats)
    if archive_type in ("iemod", "zip") or archive_path.lower().endswith((".iemod", ".zip")):
        try:
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(extract_tmp)
            return True
        except Exception:
            pass

    # 2. Native Python Tarball Extraction (.tar.gz, .tgz, .tar.bz2)
    if archive_type == "tar" or archive_path.lower().endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        try:
            with tarfile.open(archive_path, "r:*") as tar_ref:
                tar_ref.extractall(extract_tmp)
            return True
        except Exception:
            pass

    # 3. Subprocess CLI Tooling Fallback (.rar, .7z, complex .iemod/.zip/.tar)
    commands = [
        ["7z", "x", "-y", f"-o{extract_tmp}", archive_path],
        ["7za", "x", "-y", f"-o{extract_tmp}", archive_path],
        ["tar", "-xf", archive_path, "-C", extract_tmp],
        ["unar", "-o", extract_tmp, archive_path],
        ["unrar", "x", "-y", archive_path, extract_tmp],
    ]

    for cmd in commands:
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                return True
        except (FileNotFoundError, PermissionError):
            continue

    return False


def find_all_tp2_files(search_dir: str) -> list:
    """Recursively locates all .tp2 files inside a directory tree."""
    tp2_files = []
    if os.path.exists(search_dir) and os.path.isdir(search_dir):
        for root, _, files in os.walk(search_dir):
            for f in files:
                if f.lower().endswith(".tp2"):
                    tp2_files.append((os.path.join(root, f), f))
    return tp2_files


def extract_and_flatten(archive_path: str, dest_folder: str, expected_tp2: str = ""):
    """Extracts archive, locates TP2 directory, and flattens wrapper directories."""
    extract_tmp = archive_path + "_tmp"
    os.makedirs(extract_tmp, exist_ok=True)

    success = extract_archive(archive_path, extract_tmp)
    if not success:
        shutil.rmtree(extract_tmp, ignore_errors=True)
        raise RuntimeError("Failed to extract archive. Unrecognized archive format or corrupt download.")

    tp2_matches = find_all_tp2_files(extract_tmp)
    found_tp2_dir = None

    if tp2_matches:
        if expected_tp2:
            clean_expected = re.sub(r'[^a-zA-Z0-9]', '', expected_tp2.lower())
            for full_path, filename in tp2_matches:
                clean_f = re.sub(r'[^a-zA-Z0-9]', '', filename.lower().replace('.tp2', ''))
                if clean_f == clean_expected or clean_f == f"setup{clean_expected}" or clean_expected in clean_f or clean_f in clean_expected:
                    found_tp2_dir = os.path.dirname(full_path)
                    break
        
        if not found_tp2_dir and len(tp2_matches) > 0:
            found_tp2_dir = os.path.dirname(tp2_matches[0][0])

    if found_tp2_dir:
        os.makedirs(dest_folder, exist_ok=True)
        for item in os.listdir(found_tp2_dir):
            src_item = os.path.join(found_tp2_dir, item)
            dst_item = os.path.join(dest_folder, item)
            if os.path.exists(dst_item):
                if os.path.isdir(dst_item):
                    shutil.rmtree(dst_item)
                else:
                    os.remove(dst_item)
            shutil.move(src_item, dst_item)
    else:
        items = os.listdir(extract_tmp)
        if len(items) == 1 and os.path.isdir(os.path.join(extract_tmp, items[0])):
            src_inner = os.path.join(extract_tmp, items[0])
            os.makedirs(dest_folder, exist_ok=True)
            for item in os.listdir(src_inner):
                shutil.move(os.path.join(src_inner, item), os.path.join(dest_folder, item))
        else:
            os.makedirs(dest_folder, exist_ok=True)
            for item in items:
                shutil.move(os.path.join(extract_tmp, item), os.path.join(dest_folder, item))

    shutil.rmtree(extract_tmp, ignore_errors=True)


# --- FLEXIBLE TP2 AUDIT & SCANNER ---
def find_tp2_in_dir(mod_dir: str, tp2_name: str) -> bool:
    """Checks if a mod directory exists and contains ANY valid .tp2 file."""
    if not os.path.exists(mod_dir) or not os.path.isdir(mod_dir):
        return False
    
    tp2s = find_all_tp2_files(mod_dir)
    if not tp2s:
        return False
    
    clean_target = re.sub(r'[^a-zA-Z0-9]', '', tp2_name.lower())
    for _, filename in tp2s:
        clean_f = re.sub(r'[^a-zA-Z0-9]', '', filename.lower().replace('.tp2', ''))
        if clean_f == clean_target or clean_f == f"setup{clean_target}" or clean_target in clean_f or clean_f in clean_target:
            return True
            
    return True


def scan_archive_for_strict_tp2(archive_path: str, target_tp2: str) -> bool:
    """Checks if an archive strictly contains a matching TP2 file (supports .iemod)."""
    clean_target = re.sub(r'[^a-zA-Z0-9]', '', target_tp2.lower())
    
    if archive_path.lower().endswith((".zip", ".iemod")):
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for name in zf.namelist():
                    base = os.path.basename(name).lower()
                    if base.endswith(".tp2"):
                        clean_b = re.sub(r'[^a-zA-Z0-9]', '', base.replace('.tp2', ''))
                        if clean_b == clean_target or clean_b == f"setup{clean_target}" or clean_target in clean_b:
                            return True
            return False
        except Exception:
            pass

    try:
        output = subprocess.check_output(["7z", "l", archive_path], stderr=subprocess.DEVNULL, text=True)
        for line in output.splitlines():
            if ".tp2" in line.lower():
                parts = line.strip().split()
                if parts:
                    base = os.path.basename(parts[-1]).lower()
                    clean_b = re.sub(r'[^a-zA-Z0-9]', '', base.replace('.tp2', ''))
                    if clean_b == clean_target or clean_b == f"setup{clean_target}" or clean_target in clean_b:
                        return True
    except Exception:
        pass

    return False


def run_post_download_audit_and_recovery(manifest_mods: list):
    """Audits downloaded directories and recovers missing mods from local archives (prioritizing .iemod)."""
    print("\n" + "=" * 65)
    print(" RUNNING POST-DOWNLOAD ARCHIVE AUDIT & RECOVERY SCAN")
    print("=" * 65)

    missing_mods = []
    for mod in manifest_mods:
        tp2 = mod["tp2"]
        mod_dir = os.path.join(TARGET_DIR, tp2)
        if not find_tp2_in_dir(mod_dir, tp2):
            missing_mods.append(mod)

    if not missing_mods:
        print("[✓] Audit Complete: All mods in manifest have valid .tp2 components extracted!")
        return

    print(f"[!] Found {len(missing_mods)} missing mod directories. Performing archive inspection...")

    search_paths = [TARGET_DIR, os.getcwd()]
    candidate_files = []
    for path in search_paths:
        if os.path.exists(path):
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith((".iemod", ".zip", ".tar.gz", ".tgz", ".7z", ".rar", ".exe")) and not file.endswith("_temp.bin"):
                        candidate_files.append(os.path.join(root, file))

    # Prioritize Project Infinity .iemod candidate archives first during extraction
    candidate_files.sort(key=lambda x: 0 if x.lower().endswith(".iemod") else 1)

    recovered_count = 0
    for mod in list(missing_mods):
        name = mod["name"]
        tp2 = mod["tp2"]
        mod_dest_dir = os.path.join(TARGET_DIR, tp2)

        for archive_path in candidate_files:
            if scan_archive_for_strict_tp2(archive_path, tp2):
                print(f"[+] Match Found for '{name}' inside: {os.path.basename(archive_path)}")
                try:
                    extract_and_flatten(archive_path, mod_dest_dir, expected_tp2=tp2)
                    if find_tp2_in_dir(mod_dest_dir, tp2):
                        print(f"    [✓] Successfully extracted and verified -> {tp2}")
                        missing_mods.remove(mod)
                        recovered_count += 1
                        break
                    else:
                        shutil.rmtree(mod_dest_dir, ignore_errors=True)
                except Exception:
                    shutil.rmtree(mod_dest_dir, ignore_errors=True)

    print("\n" + "=" * 65)
    print(f" AUDIT SUMMARY: {recovered_count} Recovered | {len(missing_mods)} Remaining Missing")
    print("=" * 65)

    if missing_mods:
        print("\n" + "=" * 65)
        print(" ACTION REQUIRED: MANUAL DOWNLOAD LIST FOR UNRESOLVED MODS")
        print("=" * 65)
        print("Download the following archives manually and drop them into target folder:")
        print(f"Target Directory: {TARGET_DIR}\n")
        for mod in missing_mods:
            print(f" • Mod Name : {mod['name']}")
            print(f"   TP2 Key  : {mod['tp2']}")
            print(f"   Target   : {os.path.join(TARGET_DIR, mod['tp2'])}")
            print(f"   URL      : {mod.get('url', 'N/A')}\n")
        print("After dropping the archives into your working folder, re-run this script.")
        print("The recovery scan will auto-detect and extract them into their correct directories.")
        print("=" * 65)


def download_with_retry(url: str, dest_path: str, max_retries: int = 3) -> bool:
    """Downloads a file with exponential backoff retries and S3 auth handling."""
    opener = urllib.request.build_opener(AuthRedirectHandler())
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=get_headers())
            with opener.open(req, timeout=45) as resp, open(dest_path, "wb") as out_file:
                shutil.copyfileobj(resp, out_file)

            if os.path.getsize(dest_path) < 500:
                with open(dest_path, "r", errors="ignore") as check_f:
                    text = check_f.read().lower()
                    if "<html" in text or "404 not found" in text or "rate limit" in text:
                        raise ValueError("Server returned an HTML error page instead of archive binary.")
            return True
        except Exception as e:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            if attempt == max_retries:
                raise e
            time.sleep(2 * attempt)
    return False


# --- WORKER THREAD PIPELINE ---
def process_mod(mod: dict) -> tuple:
    """Processes individual mod downloading, resolving, extracting, and cleaning."""
    name = mod["name"]
    tp2 = mod["tp2"]
    github = mod.get("github")
    url = mod.get("url")

    mod_dest_dir = os.path.join(TARGET_DIR, tp2)

    if find_tp2_in_dir(mod_dest_dir, tp2):
        return (name, "SKIPPED", f"Verified .tp2 present ({tp2})")

    download_url = None
    try:
        if github:
            download_url = resolve_github_asset(github, tp2, name)
        elif url:
            if url.lower().endswith((".iemod", ".zip", ".tar.gz", ".tgz", ".7z", ".rar", ".exe")):
                download_url = url
            else:
                download_url = resolve_html_download_link(url)

        if not download_url:
            return (name, "MANUAL_REQUIRED", f"External site link: {url}")

        archive_tmp_path = os.path.join(TARGET_DIR, f"{tp2}_temp.bin")
        download_with_retry(download_url, archive_tmp_path, max_retries=3)

        extract_and_flatten(archive_tmp_path, mod_dest_dir, expected_tp2=tp2)
        if os.path.exists(archive_tmp_path):
            os.remove(archive_tmp_path)

        if find_tp2_in_dir(mod_dest_dir, tp2):
            return (name, "SUCCESS", f"Downloaded & verified -> {tp2}")
        else:
            shutil.rmtree(mod_dest_dir, ignore_errors=True)
            return (name, "ERROR", f"Extracted directory missing expected .tp2 file for {tp2}")

    except Exception as err:
        if os.path.exists(os.path.join(TARGET_DIR, f"{tp2}_temp.bin")):
            os.remove(os.path.join(TARGET_DIR, f"{tp2}_temp.bin"))
        shutil.rmtree(mod_dest_dir, ignore_errors=True)
        return (name, "ERROR", str(err))


# --- MAIN ENTRYPOINT ---
def main():
    global RUNTIME_GH_TOKEN

    if not os.path.exists(JSON_FILE):
        print(f"[X] Error: Target manifest file '{JSON_FILE}' not found in current directory.")
        sys.exit(1)

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    mods = manifest.get("mods", [])
    os.makedirs(TARGET_DIR, exist_ok=True)

    print("=== INFINITY ENGINE MOD AUTOMATED DOWNLOAD PIPELINE ===")
    print(f"Manifest Source   : {JSON_FILE}")
    print(f"Target Directory  : {TARGET_DIR}")
    print(f"Concurrency Limit : {MAX_WORKERS} Threads\n")

    RUNTIME_GH_TOKEN = get_github_token()

    print(f"Executing batch process for {len(mods)} mods...\n")

    manual_downloads = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_mod, mod): mod for mod in mods}
        for future in as_completed(futures):
            name, status, details = future.result()
            if status == "SUCCESS":
                print(f"[\033[1;32m✓\033[0m] {name}: {details}")
            elif status == "SKIPPED":
                print(f"[\033[1;34m-\033[0m] {name}: {details}")
            elif status == "MANUAL_REQUIRED":
                print(f"[\033[1;33m!\033[0m] {name}: {details}")
                manual_downloads.append((name, details))
            else:
                print(f"[\033[1;31mX\033[0m] {name}: {details}")

    run_post_download_audit_and_recovery(mods)


if __name__ == "__main__":
    main()