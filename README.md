# wordpress-rest-enum
A WordPress rest-enumeration script

# Install
- Pro Tip: utilize Python venv: `python -m venv .\venv;source .\venv\bin\activate`

`pip install -r requirements.txt`

# Usage
Enumerate users and media files: `python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m `

Output in JSON format: `python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m --json`

Download all discovered media files (implies `-m`): `python ./wordpress-rest-enum.py -w https://targetwebsite.com -dm`

Download to a specific directory: `python ./wordpress-rest-enum.py -w https://targetwebsite.com -dm ./loot`

Files are saved under `<dir>/<host>/`, filenames derived from each media URL. Combine with `-im`/`-be` to skip extensions you do not want to download.

## Concurrency

Work runs concurrently: websites from `-i`, the content types per site, and media downloads. A single global limit caps the number of HTTP requests in flight at once, so it stays polite against a live target.

Set it with `-t` / `--threads` (default 5):

`python ./wordpress-rest-enum.py -i targets.txt -po -pa -u -m -dm -t 5`

Use `-t 1` for fully sequential behaviour.

## Rate limiting (HTTP 429)

Both enumeration and downloads respect rate limiting. On an HTTP 429 (or 503) the tool honours the `Retry-After` header (seconds or HTTP-date form, capped at 120s) and retries, falling back to exponential backoff with jitter when no header is sent. It retries up to 5 times per request before giving up on that item. Backoff waits are interruptible with Ctrl-C.

This matters for enumeration: a rate-limited page is retried rather than being mistaken for the end of the results, so pagination is not silently truncated.
