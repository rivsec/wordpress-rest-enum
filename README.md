# wordpress-rest-enum
A WordPress rest-enumeration script

# Install
- Pro Tip: utilize Python venv: `python -m venv .\venv;source .\venv\bin\activate`

`pip install -r requirements.txt`

# Usage
Enumerate users and media files (plain-text output): `python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m`

Enumerate users and media files (JSON output): `python ./wordpress-rest-enum.py -w https://targetwebsite.com -u -m --json`

## Output Formats

### Plain Text (default)
```
===== https://targetwebsite.com =====

[Users]
  Name: John Doe
  Username: johndoe
  ---

[Media]
  https://targetwebsite.com/wp-content/uploads/2024/01/doc.pdf
```

### JSON (`--json` / `-j`)
```json
{"website": "https://targetwebsite.com", "users": [{"name": "John Doe", "username": "johndoe"}], "media": ["https://targetwebsite.com/wp-content/uploads/2024/01/doc.pdf"]}
```
