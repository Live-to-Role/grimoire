# Grimoire ↔ Codex Synchronization Plan

> **Version:** 1.0  
> **Date:** December 14, 2025  
> **Status:** Ready for Review

## Overview

This document identifies discrepancies between the Grimoire planning document (`grimoire_planning_with_codex.md`) and the actual Codex implementation, then outlines changes needed to ensure compatibility.

---

## Summary of Discrepancies

| Area | Grimoire Expects | Codex Implements | Impact |
|------|------------------|------------------|--------|
| Contribution field | `product_id` (null=new) | `contribution_type` + `product` | **Breaking** |
| Contribution response | Simple success | `status`, `message`, `product_id` | Non-breaking (additive) |
| Authentication | Bearer API key | DRF Token Auth | Compatible |
| `/identify` endpoint | As documented | ✅ Matches | None |

---

## Detailed Analysis

### 1. Contribution API (`POST /contributions`)

#### Grimoire Planning Document Expects:
```json
{
  "product_id": "uuid | null",
  "data": {...},
  "source": "grimoire",
  "file_hash": "sha256"
}
```
- `product_id: null` indicates a new product submission
- `product_id: uuid` indicates an edit to existing product

#### Codex Currently Implements:
```json
{
  "contribution_type": "new_product | edit_product | new_publisher | new_system",
  "product": "uuid | null",
  "data": {...},
  "source": "grimoire | web | api",
  "file_hash": "sha256"
}
```
- Uses explicit `contribution_type` field
- Uses `product` instead of `product_id`

#### Impact: **BREAKING CHANGE**
Grimoire clients will fail when submitting contributions because:
1. They send `product_id`, not `product`
2. They don't send `contribution_type`

#### Resolution Options:

**Option A: Codex adds backward compatibility (Recommended)**
- Accept both `product_id` and `product` fields
- Auto-infer `contribution_type` from presence of `product`/`product_id`:
  - If null → `new_product`
  - If present → `edit_product`

**Option B: Update Grimoire client**
- Modify Grimoire's `CodexClient.contribute()` to use new field names
- Requires Grimoire code changes

### 2. Contribution Response Format

#### Grimoire Expects:
Simple success/failure (boolean return)

#### Codex Returns:
```json
{
  "status": "applied | pending",
  "message": "string",
  "product_id": "uuid",  // or contribution_id
  "product_slug": "string"
}
```

#### Impact: **Non-breaking**
This is additive - Grimoire can ignore extra fields. However, Grimoire should be updated to:
- Check `status` field to know if contribution was applied directly or queued
- Use returned `product_id` for cache updates

### 3. Authentication

#### Grimoire Planning Document:
```python
headers={"Authorization": f"Bearer {api_key}"}
```

#### Codex Implements:
Django REST Framework Token Authentication:
```python
headers={"Authorization": f"Token {token}"}
```

#### Impact: **Potentially Breaking**
- If Grimoire sends `Bearer` prefix, Codex may reject it
- Need to verify DRF token auth accepts `Bearer` or only `Token` prefix

#### Resolution:
- Codex should accept both `Bearer` and `Token` prefixes for flexibility
- OR document that Grimoire must use `Token` prefix

### 4. `/identify` Endpoint

#### Grimoire Expects:
```
GET /identify?hash=<sha256>&title=<string>&filename=<string>

Response:
{
  "match": "exact | fuzzy | none",
  "confidence": 0.0-1.0,
  "product": {...} | null,
  "suggestions": [...]
}
```

#### Codex Implements:
✅ **Matches the specification**

The `/identify` endpoint in Codex follows the documented format.

### 5. Product Data Model

#### Fields documented in Grimoire planning:
- `dtrpg_id` (DriveThruRPG product ID)
- `dtrpg_url`
- `itch_id`
- `other_urls[]`
- `themes[]`
- `content_warnings[]`
- `related_products[]`
- `average_rating`

#### Codex Current Product Model:
- `dtrpg_url` ✅
- `itch_url` ✅
- `tags[]` ✅
- Missing: `dtrpg_id`, `itch_id`, `other_urls`, `themes`, `content_warnings`, `average_rating`

#### Impact: **Non-critical**
These are optional enrichment fields. Grimoire can still function without them.

---

## Recommended Changes

### Phase 1: Critical Compatibility (Codex Backend)

**Priority: HIGH - Required for Grimoire integration**

#### 1.1 Update `ContributionCreateSerializer` for backward compatibility

```python
# backend/apps/api/serializers.py

class ContributionCreateSerializer(serializers.ModelSerializer):
    # Accept both field names for compatibility
    product_id = serializers.UUIDField(required=False, write_only=True)
    
    class Meta:
        model = Contribution
        fields = ["contribution_type", "product", "product_id", "data", "file_hash", "source"]
    
    def validate(self, attrs):
        # Handle product_id → product mapping (Grimoire compatibility)
        product_id = attrs.pop("product_id", None)
        if product_id and not attrs.get("product"):
            from apps.catalog.models import Product
            try:
                attrs["product"] = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                raise serializers.ValidationError({"product_id": "Product not found"})
        
        # Auto-infer contribution_type if not provided
        if not attrs.get("contribution_type"):
            if attrs.get("product"):
                attrs["contribution_type"] = "edit_product"
            else:
                attrs["contribution_type"] = "new_product"
        
        # Existing validation
        contribution_type = attrs.get("contribution_type")
        product = attrs.get("product")
        
        if contribution_type == "edit_product" and not product:
            raise serializers.ValidationError({
                "product": "Product is required for edit contributions."
            })
        
        if contribution_type == "new_product" and product:
            raise serializers.ValidationError({
                "product": "Product should not be provided for new product contributions."
            })
        
        return attrs
```

#### 1.2 Verify Token Authentication Accepts Both Prefixes

Check if DRF token auth works with both:
- `Authorization: Token <token>`
- `Authorization: Bearer <token>`

If not, add custom authentication class to accept both.

### Phase 2: Grimoire Client Updates

**Priority: MEDIUM - Enhances integration**

#### 2.1 Update `CodexClient.contribute()` response handling

```python
# grimoire/services/codex.py

async def contribute(
    self,
    product_data: dict,
    file_hash: str = None,
    api_key: str = None
) -> ContributionResult:
    """Contribute new or corrected product data back to Codex."""
    if not api_key:
        return ContributionResult(success=False, reason="no_api_key")
    
    response = await self.post(
        "/contributions",
        json={
            "data": product_data,
            "file_hash": file_hash,
            "source": "grimoire"
        },
        headers={"Authorization": f"Token {api_key}"}
    )
    
    # Handle new response format
    return ContributionResult(
        success=True,
        status=response.get("status"),  # "applied" or "pending"
        product_id=response.get("product_id"),
        contribution_id=response.get("contribution_id"),
        message=response.get("message")
    )
```

#### 2.2 Add `contribution_type` field for explicit control

```python
async def contribute(
    self,
    product_data: dict,
    file_hash: str = None,
    api_key: str = None,
    existing_product_id: str = None  # If editing existing
) -> ContributionResult:
    payload = {
        "data": product_data,
        "file_hash": file_hash,
        "source": "grimoire"
    }
    
    if existing_product_id:
        payload["contribution_type"] = "edit_product"
        payload["product"] = existing_product_id
    else:
        payload["contribution_type"] = "new_product"
    
    # ... rest of method
```

### Phase 3: Documentation Updates

**Priority: LOW - Consistency**

#### 3.1 Update `grimoire_planning_with_codex.md`

Update Section 4A.3 API Endpoints to reflect actual Codex API:

```yaml
# Contributions (authenticated)
POST /contributions
  Request Body:
    {
      # New format (preferred)
      "contribution_type": "new_product" | "edit_product",
      "product": UUID | null,
      
      # Legacy format (still supported)
      "product_id": UUID | null,  # Auto-infers contribution_type
      
      "data": {...},
      "source": "grimoire" | "web" | "api",
      "file_hash": string | null
    }
  Response: 201 Created
    {
      "status": "applied" | "pending",
      "message": string,
      "product_id": UUID,      # If status=applied
      "product_slug": string,  # If status=applied
      "contribution_id": UUID  # If status=pending
    }
```

---

## Implementation Checklist

### Codex Changes (Required)

- [ ] Update `ContributionCreateSerializer` to accept `product_id` field
- [ ] Auto-infer `contribution_type` when not provided
- [ ] Test `/contributions` endpoint with Grimoire-style payload
- [ ] Verify token auth accepts both `Token` and `Bearer` prefixes
- [ ] Update API documentation

### Grimoire Changes (Recommended)

- [ ] Update `CodexClient` to handle new response format
- [ ] Add support for `contribution_type` field
- [ ] Update token auth header to use `Token` prefix (if needed)
- [ ] Add `ContributionResult` dataclass for typed responses
- [ ] Update tests for new API contract

### Documentation Changes

- [ ] Update `grimoire_planning_with_codex.md` with actual API spec
- [ ] Add migration notes for existing Grimoire installations
- [ ] Document authentication requirements

---

## Testing Plan

### Integration Tests

1. **Grimoire-style contribution (new product)**
   ```bash
   curl -X POST https://api.codex.livetorole.com/api/v1/contributions/ \
     -H "Authorization: Token <token>" \
     -H "Content-Type: application/json" \
     -d '{"product_id": null, "data": {"title": "Test"}, "source": "grimoire"}'
   ```

2. **Grimoire-style contribution (edit product)**
   ```bash
   curl -X POST https://api.codex.livetorole.com/api/v1/contributions/ \
     -H "Authorization: Token <token>" \
     -H "Content-Type: application/json" \
     -d '{"product_id": "<uuid>", "data": {"title": "Updated"}, "source": "grimoire"}'
   ```

3. **New Codex-style contribution**
   ```bash
   curl -X POST https://api.codex.livetorole.com/api/v1/contributions/ \
     -H "Authorization: Token <token>" \
     -H "Content-Type: application/json" \
     -d '{"contribution_type": "new_product", "data": {"title": "Test"}, "source": "web"}'
   ```

4. **Test `/identify` endpoint**
   ```bash
   curl "https://api.codex.livetorole.com/api/v1/identify?hash=<sha256>"
   curl "https://api.codex.livetorole.com/api/v1/identify?title=Tomb%20of%20the%20Serpent%20Kings"
   ```

---

## Notes

1. **Backward Compatibility Priority**: Codex should maintain backward compatibility since Grimoire is already documented/planned with the original API spec.

2. **Versioning Consideration**: If breaking changes are unavoidable in the future, consider API versioning (`/v2/contributions`).

3. **Contribution Type Benefits**: The new `contribution_type` field is useful for:
   - New Publisher submissions
   - New Game System submissions
   - Clearer intent in the API

4. **Timeline**: Phase 1 changes should be implemented before any Grimoire integration testing begins.
