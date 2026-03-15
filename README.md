# wordpress-rest-enum
A WordPress rest-enumeration script

# Install
- Pro Tip: utilize Python venv: `python -m venv .\venv;source .\venv\bin\activate`

`pip install -r requirements.txt`

# Usage
Enumerate users and media files (plain-text output, default):

`python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m`

Enumerate users and media files with JSON output:

`python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m --json`

Save results to a file:

`python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m -o results.txt`

Save results as JSON to a file:

`python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m --json -o results.json`
