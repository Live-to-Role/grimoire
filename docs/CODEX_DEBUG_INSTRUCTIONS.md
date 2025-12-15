# Codex API Update Instructions

## Current Issue: FieldError in FileHash lookup

**Error from Railway logs:**
```
django.core.exceptions.FieldError: Cannot resolve keyword 'hash_value' into field. 
Choices are: contributed_by, contributed_by_id, created_at, file_name, file_size_bytes, 
hash_md5, hash_sha256, id, product, product_id, source
```

**Location:** `backend/apps/api/views.py` line 928

**Fix required:**
```python
# Change this (line 928):
existing_file_hash = FileHash.objects.filter(hash_value=file_hash).select_related("product").first()

# To this:
existing_file_hash = FileHash.objects.filter(hash_sha256=file_hash).select_related("product").first()
```

---

## Previous Issue (RESOLVED): Publisher field not accepted

## What Grimoire Sends
Here's an example payload Grimoire sends to `POST /api/v1/contributions/`:

```json
{
  "data": {
    "title": "#WIP - Work in Progress - 2023 - A monthly digital zine",
    "publisher": "Bloat Games",
    "product_type": "Zine",
    "publication_year": 2023,
    "page_count": 43,
    "game_system": "D&D 5e",
    "level_range_min": 1,
    "level_range_max": 5,
    "party_size_min": 3,
    "party_size_max": 6,
    "estimated_runtime": "4-6 hours"
  },
  "file_hash": "81f4c42e44e65c687b23251e87c812eb7c03d78aa023033994730eaf3a7993d3",
  "source": "grimoire",
  "contribution_type": "new_product"
}
```

## Fields Grimoire May Send
The `data` object can include any of these fields (all optional except `title`):
- `title` (string, required)
- `publisher` (string) - **Currently rejected, needs to be allowed**
- `game_system` (string)
- `product_type` (string)
- `publication_year` (integer)
- `page_count` (integer)
- `level_range_min` (integer)
- `level_range_max` (integer)
- `party_size_min` (integer)
- `party_size_max` (integer)
- `estimated_runtime` (string)

## Fix Required
In the Codex contribution serializer/validator, add `publisher` to the list of allowed fields.

---

# Previous Debug Issue (RESOLVED)

## Current Behavior
- Endpoint: `POST /api/v1/contributions/`
- Response: `400 Bad Request` with empty body
- No error details returned to client

## Test Results
```
# This WORKS (fake hash):
POST /api/v1/contributions/
{
  "data": {"title": "Test Product"},
  "file_hash": "abc123",
  "source": "grimoire",
  "contribution_type": "new_product"
}
Response: 200 OK - {"status": "pending", "contribution_id": "..."}

# This FAILS (real SHA-256 hash):
POST /api/v1/contributions/
{
  "data": {"title": "Test Product 2", "publisher": "Bloat Games"},
  "file_hash": "214c170e9b680eb893c1a7b44c7a2eb34dd4b215b9e67fd4a8e20d7101a5b6a2",
  "source": "grimoire",
  "contribution_type": "new_product"
}
Response: 400 Bad Request - (empty body)
```

## Requested Changes

### 1. Return detailed error responses
Instead of returning empty 400 responses, return JSON with error details:

```python
# Example for Django REST Framework
from rest_framework.response import Response
from rest_framework import status

# In your contribution view/serializer:
if error_condition:
    return Response({
        "error": "validation_error",
        "field": "file_hash",
        "message": "A product with this file hash already exists",
        "existing_product_id": existing.id  # if applicable
    }, status=status.HTTP_400_BAD_REQUEST)
```

### 2. Possible validation issues to check
The 400 error might be caused by:
1. **Duplicate file_hash** - Hash already exists in database
2. **Hash format validation** - Maybe expecting specific format?
3. **Rate limiting** - Too many contributions from same user/source
4. **Missing required field** - Some field validation failing silently

### 3. Add logging
Log incoming contribution requests and validation failures:

```python
import logging
logger = logging.getLogger(__name__)

def create_contribution(request):
    logger.info(f"Contribution request from {request.user}: {request.data}")
    
    # ... validation ...
    
    if validation_error:
        logger.warning(f"Contribution rejected: {validation_error}")
        return Response({"error": validation_error, ...}, status=400)
```

## Expected Response Format
For errors, please return:
```json
{
  "error": "error_code",
  "message": "Human readable message",
  "field": "field_name_if_applicable",
  "details": {}  // optional additional context
}
```

## Grimoire Client Code Reference
The Grimoire client sends requests like this (from `backend/grimoire/services/codex.py`):

```python
payload = {
    "data": product_data,      # dict with title, publisher, etc.
    "file_hash": file_hash,    # SHA-256 hash of PDF file
    "source": "grimoire",
    "contribution_type": "new_product"  # or "edit_product"
}

response = await client.post(
    f"{base_url}/contributions/",
    json=payload,
    headers={"Authorization": f"Token {api_key}"}
)
```
