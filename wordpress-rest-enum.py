# wordpress-rest-enum.py

import requests
import json
import argparse
import logging
import urllib3
import re
import os
import sys
import random
import datetime
import threading
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from urllib.parse import urlsplit, unquote

urllib3.disable_warnings()

# Argument parsing
parser = argparse.ArgumentParser()
# Argument group, select either website or input file
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument(
    "-w", "--website", help="Website to check.", action="store", type=str
)
group.add_argument(
    "-i", "--input-file", help="Input file containing list of websites", type=str
)
parser.add_argument_group(group)
parser.add_argument(
    "--log-level",
    default=logging.WARNING,
    type=lambda x: getattr(logging, x),
    help="Configure the logging level.",
)
parser.add_argument(
    "-m",
    "--media",
    help="Fetch media",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-dm",
    "--download-media",
    help=(
        "Download all discovered media files to a directory "
        "(default: ./downloaded_media). Implies --media."
    ),
    nargs="?",
    const="downloaded_media",
    default=None,
    type=str,
    required=False,
)
parser.add_argument(
    "-po",
    "--posts",
    help="Fetch posts",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-pa",
    "--pages",
    help="Fetch pages",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-u",
    "--users",
    help="Fetch users",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-c",
    "--comments",
    help="Fetch comments",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-im",
    "--ignoreImages",
    help="Filter out extensions commonly associated with images and video",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-be",
    "--block-extensions",
    help="Additional comma-separated file extensions to block (e.g. 'pdf,doc,docx')",
    type=str,
    required=False,
)
parser.add_argument(
    "-o",
    "--output-file",
    help="Output file to save the results.",
    type=str,
    required=False,
)

parser.add_argument(
    "-p",
    "--proxy",
    help="Address to the proxy server (e.g. socks5://127.0.0.1:9050)",
    type=str,
    required=False,
)

parser.add_argument(
    "--json",
    help="Output in JSON format",
    action="store_true",
    required=False,
)

parser.add_argument(
    "-t",
    "--threads",
    help=(
        "Maximum number of concurrent HTTP requests across all work "
        "(websites, fetches, and downloads). Default: 5."
    ),
    type=int,
    default=5,
    required=False,
)

cliArgs = parser.parse_args()

if cliArgs.threads < 1:
    parser.error("--threads must be at least 1")

# Logging
logging.basicConfig(level=cliArgs.log_level)

# Globals
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
# Create a single session for reuse
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.verify = False

if cliArgs.proxy:
    SESSION.proxies = {
        "http": cliArgs.proxy,
        "https": cliArgs.proxy,
    }

# Size the connection pool to the concurrency level so threads are not
# serialised waiting for a free connection.
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=cliArgs.threads,
    pool_maxsize=cliArgs.threads,
)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)

# Global cap on concurrent HTTP requests. Every request acquires this
# before hitting the network, so no matter how work nests (websites ->
# content types -> media downloads) at most `threads` requests are ever
# in flight at once. This is what makes "N at a time" true end to end.
REQUEST_SEMAPHORE = threading.BoundedSemaphore(cliArgs.threads)

# Serialises writes to stdout / the output file so concurrent websites
# don't interleave their result blocks.
OUTPUT_LOCK = threading.Lock()

# Set on Ctrl-C. Workers poll it and bail out instead of starting new
# network work, so the pools drain quickly and the process can exit.
STOP = threading.Event()


def _run_pool(workers, fn, items):
    """Map `fn` over `items` in a thread pool, Ctrl-C-aware.

    On KeyboardInterrupt the stop flag is set and pending tasks are
    cancelled *before* the pool is joined, so already-running workers
    return at their next stop check (bounded by the request timeout)
    and queued work never starts. Returns the list of results.
    """
    results = []
    ex = ThreadPoolExecutor(max_workers=workers)
    futures = [ex.submit(fn, item) for item in items]
    pending = set(futures)
    try:
        # Wait in short slices rather than one long blocking wait. On
        # Windows a KeyboardInterrupt is only raised in the main thread
        # when it returns from a wait, so the timeout is what lets Ctrl-C
        # take effect promptly instead of after all work finishes.
        while pending:
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for fut in done:
                results.append(fut.result())
    except KeyboardInterrupt:
        STOP.set()
        for f in futures:
            f.cancel()
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=False)
    return results

API_TIMEOUT = 3  # 3 seconds timeout for API requests

# Compile regex patterns once
IMAGE_EXTENSIONS_PATTERN = re.compile(
    r"\.(jpg|gif|jpeg|png|svg|tiff|webm|webp|mp4|mov|avif|mp3|ttf|woff|eot|woff2|heic|tif|ogg|m4v|bmp|ico)$",
    re.IGNORECASE,
)

# Rate-limit handling. Retry 429 (Too Many Requests) and 503 (Service
# Unavailable); both commonly carry a Retry-After header.
RETRY_STATUSES = (429, 503)
MAX_RETRIES = 5            # attempts after the first try
RETRY_AFTER_CAP = 120.0    # never honour a Retry-After longer than this
BACKOFF_BASE = 1.0         # seconds, for exponential backoff when no header
BACKOFF_CAP = 30.0         # cap a single backoff wait


def _parse_retry_after(value):
    """Seconds to wait from a Retry-After header value, or None.

    Supports both the delta-seconds form ("120") and the HTTP-date form
    ("Wed, 21 Oct 2026 07:28:00 GMT").
    """
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    delta = (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return max(0.0, delta)


def _retry_wait(resp, attempt):
    """Seconds to wait before retrying `resp`, or None if it is not a
    retryable rate-limit response."""
    if resp.status_code not in RETRY_STATUSES:
        return None
    seconds = _parse_retry_after(resp.headers.get("Retry-After"))
    if seconds is not None:
        return min(seconds, RETRY_AFTER_CAP)
    # No header: exponential backoff with 50-100% jitter.
    backoff = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_CAP)
    return backoff * (0.5 + random.random() * 0.5)


def _interruptible_sleep(seconds):
    """Sleep up to `seconds`, waking immediately if STOP is set.

    Returns True if the full time elapsed, False if interrupted so the
    caller can abort instead of issuing another request.
    """
    return not STOP.wait(timeout=max(0.0, seconds))


def _get_with_retry(url, timeout):
    """Non-streaming GET that retries 429/503 honouring Retry-After.

    Returns the Response (the final one if retries are exhausted) or None
    if interrupted via STOP. Network exceptions propagate to the caller's
    existing handlers. The request semaphore is held only during each GET,
    never across the backoff wait.
    """
    resp = None
    for attempt in range(MAX_RETRIES + 1):
        if STOP.is_set():
            return None
        with REQUEST_SEMAPHORE:
            if STOP.is_set():
                return None
            resp = SESSION.get(url, timeout=timeout)
        wait_s = _retry_wait(resp, attempt)
        if wait_s is None:
            return resp
        if attempt >= MAX_RETRIES:
            logging.warning(
                f"Giving up after {MAX_RETRIES} retries (HTTP {resp.status_code}): {url}"
            )
            return resp
        logging.info(
            f"HTTP {resp.status_code} for {url}; backing off {wait_s:.1f}s "
            f"(retry {attempt + 1}/{MAX_RETRIES})"
        )
        if not _interruptible_sleep(wait_s):
            return None
    return resp


def requestRESTAPIComments(website: str, fetchPage: int, timeout=API_TIMEOUT) -> json:
    if STOP.is_set():
        return []
    perPage = 100
    apiRequest = (
        f"{website}/wp-json/wp/v2/comments?per_page={perPage}&page={str(fetchPage)}"
    )
    results = []
    try:
        download = _get_with_retry(apiRequest, timeout)
        if download is not None and download.status_code == 200:
            # WordPress API returns mixed HTML and JSON in the users API endpoint.
            # Remove all content to the first `[` indicating the beginning of JSON data.
            content = "[" + "[".join(download.text.split("[")[1:])
            comments = json.loads(content)
            for comment in comments:
                try:
                    newComment = {
                        "name": comment["author_name"],
                        "date": comment["date"],
                        "link": comment["link"],
                    }
                    results.append(newComment)
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    raise
            fetchPage = fetchPage + 1
            if len(comments) > 0:
                results += requestRESTAPIComments(website, fetchPage)
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout for comments API: {e}")
        return results  # Return partial results and continue
    except:
        raise

    return results


def requestRESTAPIUsers(website: str, fetchPage: int, timeout=API_TIMEOUT) -> json:
    if STOP.is_set():
        return []
    perPage = 100
    apiRequest = (
        f"{website}/wp-json/wp/v2/users?per_page={perPage}&page={str(fetchPage)}"
    )
    results = []
    try:
        download = _get_with_retry(apiRequest, timeout)
        if download is not None and download.status_code == 200:
            content = download.text
            users = json.loads(content)
            for user in users:
                try:
                    newUser = {"name": user["name"], "username": user["slug"]}
                    results.append(newUser)
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    raise
            fetchPage = fetchPage + 1
            if len(users) > 0:
                results += requestRESTAPIUsers(website, fetchPage)
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout for users API: {e}")
        return results  # Return partial results and continue
    except:
        raise
    return results


def requestRESTAPI(
    type: str, website: str, fetchPage: int, timeout=API_TIMEOUT
) -> list:
    if STOP.is_set():
        return []
    perPage = 100

    try:
        apiRequest = (
            f"{website}/wp-json/wp/v2/{type}?per_page={perPage}&page={str(fetchPage)}"
        )
        results = []
        download = _get_with_retry(apiRequest, timeout)
        if download is not None and download.status_code == 200:
            content = download.text
            if content is not None:
                apiResponse = json.loads(content)
                for typeReturn in apiResponse:
                    try:
                        results.append(typeReturn["guid"]["rendered"])
                    except Exception as err:
                        print(f"Unexpected {err=}, {type(err)=}")
                        raise
                fetchPage = fetchPage + 1
                if len(apiResponse) > 0:
                    results += requestRESTAPI(type, website, fetchPage)
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout for {type} API: {e}")
        return results  # Return partial results and continue
    except:
        raise

    return results


def _safe_filename_from_url(url: str) -> str:
    """Derive a safe local filename from a media URL.

    The URL comes from the (untrusted) target server, so the name is
    treated as hostile: percent-decoded first, then reduced to a single
    path component with no separators, traversal sequences, or leading
    dots. The caller still enforces containment before writing.
    """
    path = urlsplit(url).path
    # Decode BEFORE splitting so encoded separators (%2f, %5c) can't
    # smuggle a path through os.path.basename.
    decoded = unquote(path)
    # Normalise both separators, then take the last component.
    name = re.split(r"[\\/]", decoded.rstrip("/\\"))[-1]
    # Strip characters illegal on common filesystems.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Remove leading dots so names like "..", "." or ".bashrc" can't
    # point at the parent dir or hide as dotfiles.
    name = name.lstrip(". ").strip()
    # Cap length to stay within filesystem limits.
    if len(name) > 200:
        root, ext = os.path.splitext(name)
        name = root[: 200 - len(ext)] + ext
    return name or "unnamed"


def _target_dir(base_dir: str, website: str) -> str:
    """Per-host subdirectory so multiple targets don't collide."""
    host = urlsplit(website).netloc or "unknown_host"
    host = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", host)
    return os.path.join(base_dir, host)


def _download_one(url: str, out_dir: str, out_real: str, timeout) -> bool:
    """Download a single media URL into out_dir. Returns True on success.

    Safe to run from many threads at once: the exclusive-create open is
    the sole arbiter of filenames, so concurrent downloads can neither
    overwrite each other nor race, and no shared name bookkeeping is
    needed.
    """
    if STOP.is_set():
        return False
    base = _safe_filename_from_url(url)
    root, ext = os.path.splitext(base)
    try:
        for retry in range(MAX_RETRIES + 1):
            if STOP.is_set():
                return False
            with REQUEST_SEMAPHORE:
                if STOP.is_set():
                    return False
                with SESSION.get(url, timeout=timeout, stream=True) as resp:
                    wait_s = _retry_wait(resp, retry)
                    if wait_s is None:
                        # Not a retryable rate-limit: either success or a
                        # terminal non-200 we skip.
                        if resp.status_code != 200:
                            logging.warning(
                                f"Skipping {url}: HTTP {resp.status_code}"
                            )
                            return False
                        # Pick a name, verify it stays inside out_dir, and
                        # create it exclusively ("xb"): never overwrite an
                        # existing file, never follow a pre-planted symlink,
                        # no check-then-write race. On collision or an unsafe
                        # (symlinked) name, try the next suffix.
                        f = None
                        attempt = 0
                        dest = None
                        while f is None:
                            candidate = (
                                base if attempt == 0 else f"{root}_{attempt}{ext}"
                            )
                            dest = os.path.join(out_dir, candidate)
                            if os.path.dirname(os.path.realpath(dest)) != out_real:
                                logging.warning(
                                    f"Skipping unsafe target for {url}: {dest}"
                                )
                                attempt += 1
                                if attempt > 10000:
                                    return False
                                continue
                            try:
                                f = open(dest, "xb")
                            except FileExistsError:
                                attempt += 1
                                if attempt > 10000:
                                    logging.warning(
                                        f"Too many name collisions for {url}"
                                    )
                                    return False
                        with f:
                            for chunk in resp.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        logging.info(f"Downloaded {url} -> {dest}")
                        return True
                    # Rate-limited: give up if out of retries.
                    if retry >= MAX_RETRIES:
                        logging.warning(
                            f"Giving up on {url} after {MAX_RETRIES} retries "
                            f"(HTTP {resp.status_code})"
                        )
                        return False
                    status = resp.status_code
            # Semaphore released and response closed: back off, then retry.
            logging.info(
                f"HTTP {status} for {url}; backing off {wait_s:.1f}s "
                f"(retry {retry + 1}/{MAX_RETRIES})"
            )
            if not _interruptible_sleep(wait_s):
                return False
        return False
    except requests.exceptions.RequestException as e:
        logging.warning(f"Failed to download {url}: {e}")
        return False
    except OSError as e:
        logging.warning(f"Failed to write file for {url}: {e}")
        return False


def downloadMedia(
    urls, base_dir: str, website: str, timeout=API_TIMEOUT, threads: int = 1
) -> int:
    """Download all media URLs into base_dir/<host>/ concurrently.

    Returns the number downloaded. Up to `threads` downloads run at once,
    still bounded by the global request semaphore.
    """
    if not urls:
        return 0
    out_dir = _target_dir(base_dir, website)
    os.makedirs(out_dir, exist_ok=True)
    # Resolve the real output dir once so each worker can verify its
    # target stays inside it, defeating traversal regardless of quirks.
    out_real = os.path.realpath(out_dir)

    workers = max(1, min(threads, len(urls)))
    outcomes = _run_pool(
        workers,
        lambda url: _download_one(url, out_dir, out_real, timeout),
        urls,
    )
    downloaded = sum(1 for ok in outcomes if ok)

    logging.info(f"Downloaded {downloaded}/{len(urls)} media files to {out_dir}")
    return downloaded


def format_plain_text(result):
    lines = []
    lines.append(f"Website: {result['website']}")
    if "users" in result and result["users"]:
        lines.append("Users:")
        for user in result["users"]:
            lines.append(f"  Name: {user['name']}, Username: {user['username']}")
    if "posts" in result and result["posts"]:
        lines.append("Posts:")
        for post in result["posts"]:
            lines.append(f"  {post}")
    if "pages" in result and result["pages"]:
        lines.append("Pages:")
        for page in result["pages"]:
            lines.append(f"  {page}")
    if "media" in result and result["media"]:
        lines.append("Media:")
        for media in result["media"]:
            lines.append(f"  {media}")
    if "comments" in result and result["comments"]:
        lines.append("Comments:")
        for comment in result["comments"]:
            lines.append(f"  Name: {comment['name']}, Date: {comment['date']}, Link: {comment['link']}")
    return "\n".join(lines)


def _filter_media(media_urls):
    """Drop media URLs whose extension matches the ignore/block filters."""
    extensions_to_ignore = (
        IMAGE_EXTENSIONS_PATTERN if cliArgs.ignoreImages else None
    )
    if cliArgs.block_extensions:
        additional_extensions = "|".join(
            ext.strip() for ext in cliArgs.block_extensions.split(",")
        )
        if extensions_to_ignore:
            extensions_to_ignore = re.compile(
                f"({extensions_to_ignore.pattern}|{additional_extensions})$",
                re.IGNORECASE,
            )
        else:
            extensions_to_ignore = re.compile(
                rf"\.({additional_extensions})$", re.IGNORECASE
            )

    filtered = []
    for url in media_urls:
        # Remove trailing slash if present before checking extension
        if not extensions_to_ignore.search(url.rstrip("/")):
            filtered.append(url)
    return filtered


def _safe_fetch(key, fn):
    """Run one fetch task, isolating its failure from the other types."""
    try:
        return fn()
    except Exception as e:
        logging.warning(f"Failed to fetch {key} ({type(e).__name__}): {e}")
        return []


def process_website(website):
    """Fetch everything requested for one site. Returns (result, found).

    The enabled content types are fetched concurrently; media is then
    filtered and (optionally) downloaded.
    """
    logging.info(f"Processing {website}")
    result = {"website": website}

    tasks = {}
    if cliArgs.posts:
        tasks["posts"] = lambda w=website: requestRESTAPI("posts", w, 1)
    if cliArgs.pages:
        tasks["pages"] = lambda w=website: requestRESTAPI("pages", w, 1)
    if cliArgs.comments:
        tasks["comments"] = lambda w=website: requestRESTAPIComments(w, 1)
    if cliArgs.media or cliArgs.download_media:
        tasks["media"] = lambda w=website: requestRESTAPI("media", w, 1)
    if cliArgs.users:
        tasks["users"] = lambda w=website: requestRESTAPIUsers(w, 1)

    if tasks:
        workers = max(1, min(len(tasks), cliArgs.threads))
        for key, value in _run_pool(
            workers,
            lambda item: (item[0], _safe_fetch(item[0], item[1])),
            list(tasks.items()),
        ):
            result[key] = value

    found = any(result.get(k) for k in ("posts", "pages", "comments", "users"))

    if "media" in result:
        if cliArgs.ignoreImages or cliArgs.block_extensions:
            result["media"] = _filter_media(result["media"])
        if result["media"]:
            found = True
        if cliArgs.download_media:
            count = downloadMedia(
                result["media"],
                cliArgs.download_media,
                website,
                threads=cliArgs.threads,
            )
            logging.info(f"Saved {count} media file(s) for {website}")

    return result, found


def main():
    websites = []
    if cliArgs.input_file:
        with open(cliArgs.input_file, "r") as f:
            for website in f.readlines():
                website = website.strip()
                if website:
                    websites.append(website)
    else:
        websites.append(cliArgs.website)

    written = 0

    def handle(website):
        nonlocal written
        try:
            result, found = process_website(website)
        except Exception as e:
            logging.warning(f"Unexpected error for {website}: {e=}, {type(e)=}")
            return
        if not found:
            logging.info(json.dumps({"message": "no results", "target": website}))
            return
        output = json.dumps(result) if cliArgs.json else format_plain_text(result)
        # Serialise output so concurrent sites don't interleave blocks.
        with OUTPUT_LOCK:
            if cliArgs.output_file:
                with open(cliArgs.output_file, "a") as f:
                    if written > 0:
                        f.write("\n")
                    f.write(output)
            else:
                print(output)
            written += 1

    try:
        if len(websites) > 1 and cliArgs.threads > 1:
            workers = min(len(websites), cliArgs.threads)
            _run_pool(workers, handle, websites)
        else:
            for website in websites:
                handle(website)
    except KeyboardInterrupt:
        STOP.set()
        logging.warning("Interrupted, shutting down (finishing in-flight requests)...")
        SESSION.close()
        sys.exit(130)
    finally:
        SESSION.close()


if __name__ == "__main__":
    main()
