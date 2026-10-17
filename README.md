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
