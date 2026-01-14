# AGENTS.md - Codebase Guidelines

This document provides guidelines for agentic coding agents operating in this repository.

## Project Overview

Flask-based OSS file upload and URL conversion service.

- **Language**: Python 3.14+
- **Framework**: Flask 2.3+
- **Cloud**: AWS S3 / Alist OSS via boto3
- **Dependencies**: flask, boto3, botocore, requests, werkzeug

## Build & Run Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run (dev mode, port 5001)
python app.py

# Environment variables required:
# ALIST_ENDPOINT, ALIST_ACCESS_KEY, ALIST_SECRET_KEY, ALIST_BUCKET, URL_EXPIRES
```

## Testing

```bash
pytest                    # Run all tests
pytest tests/test_*.py    # Run test files
pytest --cov=.           # With coverage
```

## Code Style

### Imports (standard → third-party → local)

```python
import os
import json
from typing import Dict, List, Optional

import requests
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from oss_client import oss_client
```

### Formatting

- Max line length: 120 chars
- Two blank lines between top-level definitions
- One blank line between class methods
- Use triple quotes for all public function/class docstrings

### Type Annotations

```python
def upload_file(self, file_path: str, object_key: str = None) -> dict:
    """Upload file to OSS."""
    pass

def extract_urls(self, text: str) -> List[str]:
    """Extract URLs from text."""
    pass
```

### Naming Conventions

| Component | Convention | Example |
|-----------|------------|---------|
| Classes | PascalCase | `OSSClient` |
| Functions/variables | snake_case | `upload_file` |
| Constants | UPPER_SNAKE_CASE | `MAX_CONTENT_LENGTH` |
| Private methods | leading underscore | `_extract_filename` |

### Error Handling

**Never use bare except.** Return consistent error dicts with `'success': False`:

```python
try:
    do_something()
except ValueError as e:
    return {'success': False, 'error': str(e)}
except Exception as e:
    return {'success': False, 'error': str(e)}

# Flask error handlers
@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'success': False, 'error': 'File too large'}), 413
```

### API Responses

```python
# Success
return jsonify({'success': True, 'url': result_url, 'filename': filename})

# Error
return jsonify({'success': False, 'error': 'Human-readable error'}), 400
```

### File Structure

- `app.py`: Flask routes
- `oss_client.py`: OSS client class and utilities
- `templates/`: Jinja2 templates
- `requirements.txt`: Dependencies

## Critical Patterns

**Global client initialization:**
```python
oss_client = OSSClient()  # Application lifetime
```

**OSS operations always return dict with 'success' key:**
```python
def upload_operation(self, ...) -> dict:
    try:
        return {'success': True, 'url': url}
    except Exception as e:
        return {'success': False, 'error': str(e)}
```

**URL extraction regex:**
```python
url_pattern = r'https?://[^\s<>"\')\]]+(?:\.[^\s<>"\')\]]+)*'
urls = re.findall(url_pattern, text)
```

**Concurrent URL processing:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(process, item): item for item in items}
    for future in as_completed(futures):
        yield future.result()
```

**SSE streaming response:**
```python
return Response(generate(), mimetype='text/event-stream',
    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
```

## Security

- Never commit real credentials; use environment variables
- Validate and sanitize all user inputs
- Use `secure_filename()` for file uploads
