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
========================================
Website: https://targetwebsite.com
========================================

--- Users ---
  John Doe (johndoe)
  Jane Smith (janesmith)

--- Media ---
  https://targetwebsite.com/wp-content/uploads/doc.pdf
```

### JSON (`--json`)
```json
{"website": "https://targetwebsite.com", "users": [{"name": "John Doe", "username": "johndoe"}], "media": ["https://targetwebsite.com/wp-content/uploads/doc.pdf"]}
```
