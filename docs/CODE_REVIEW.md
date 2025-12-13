# Grimoire Code Review

**Date:** December 12, 2025  
**Scope:** Security, Performance, Accessibility, Best Practices

---

## Executive Summary

The Grimoire codebase is **generally well-structured** with good separation of concerns, proper use of async patterns, and modern tooling. However, there are several areas that need attention before production deployment.

| Category | Grade | Priority Issues |
|----------|-------|-----------------|
| Security | B | Secret key, path traversal, rate limiting |
| Performance | B+ | Database indexing, caching, pagination |
| Accessibility | C | Missing ARIA labels, focus management |
| Code Quality | A- | Minor type hints, error handling |

---

## 1. Security Findings

### 🔴 Critical

#### 1.1 Hardcoded Secret Key
**File:** `backend/grimoire/config.py:37`
```python
secret_key: str = "change-this-in-production"
```
**Risk:** This default secret should never be used in production.  
**Fix:** Require environment variable with no default:
```python
secret_key: str = Field(..., env="SECRET_KEY")  # No default - must be set
```

#### 1.2 Path Traversal Risk in File Serving
**File:** `backend/grimoire/api/routes/products.py:220-256`
```python
cover_path = Path(product.cover_image_path)
pdf_path = Path(product.file_path)
```
**Risk:** If `file_path` or `cover_image_path` are manipulated, could serve arbitrary files.  
**Fix:** Validate paths are within allowed directories:
```python
def validate_path_in_library(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
```

### 🟡 Medium

#### 1.3 No Rate Limiting
**Risk:** API endpoints vulnerable to abuse, especially AI endpoints that incur costs.  
**Fix:** Add slowapi or similar:
```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

@router.post("/ai/identify")
@limiter.limit("10/minute")
async def identify_product(...):
```

#### 1.4 No Input Validation on AI Prompts
**File:** `backend/grimoire/processors/structured_extractor.py`
**Risk:** User-controlled text passed to AI could be manipulated.  
**Fix:** Sanitize and limit input text before sending to AI APIs.

#### 1.5 CORS Configuration Too Permissive
**File:** `backend/grimoire/main.py:37-43`
```python
allow_methods=["*"],
allow_headers=["*"],
```
**Fix:** Restrict to only needed methods and headers.

### 🟢 Good Practices Observed

- ✅ Security headers middleware (`X-Frame-Options`, `X-XSS-Protection`)
- ✅ No raw SQL - using SQLAlchemy ORM throughout
- ✅ No `eval()` or `exec()` usage
- ✅ No `dangerouslySetInnerHTML` in React
- ✅ API keys stored in environment variables

---

## 2. Performance Findings

### 🔴 Critical

#### 2.1 Missing Database Indexes
**File:** `backend/grimoire/models/product.py`
**Impact:** Slow queries as data grows.  
**Fix:** Add indexes on frequently queried columns:
```python
__table_args__ = (
    Index('ix_products_title', 'title'),
    Index('ix_products_game_system', 'game_system'),
    Index('ix_products_created_at', 'created_at'),
)
```

### 🟡 Medium

#### 2.2 N+1 Query Potential
**File:** `backend/grimoire/api/routes/products.py:89`
```python
query = select(Product).options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
```
**Status:** Good use of eager loading here, but verify all endpoints do this.

#### 2.3 No Response Caching
**Impact:** Repeated API calls for static data.  
**Fix:** Add cache headers for cover images (already done) and consider Redis for API responses.

#### 2.4 Text Extraction Memory Usage
**File:** `backend/grimoire/processors/text_extractor.py`
**Risk:** Large PDFs loaded entirely into memory.  
**Fix:** Process pages in batches for very large files.

#### 2.5 Embedding Generation is Synchronous
**File:** `backend/grimoire/services/embeddings.py`
**Impact:** Blocks event loop during embedding generation.  
**Fix:** Use `asyncio.to_thread()` for CPU-bound operations.

### 🟢 Good Practices Observed

- ✅ Async database sessions
- ✅ Pagination on list endpoints
- ✅ Lazy loading of images in frontend
- ✅ React Query caching on frontend

---

## 3. Accessibility Findings

### 🔴 Critical

#### 3.1 Missing ARIA Labels on Interactive Elements
**File:** `frontend/src/components/Sidebar.tsx`
```tsx
<button onClick={() => setCollectionsExpanded(!collectionsExpanded)}>
```
**Fix:** Add descriptive ARIA labels:
```tsx
<button 
  onClick={() => setCollectionsExpanded(!collectionsExpanded)}
  aria-expanded={collectionsExpanded}
  aria-label="Toggle collections section"
>
```

#### 3.2 Modal Focus Management
**File:** `frontend/src/components/ProductDetail.tsx`
**Issue:** Focus not trapped in modal, no focus restoration on close.  
**Fix:** Use a focus trap library or implement focus management:
```tsx
import { FocusTrap } from '@headlessui/react';
```

### 🟡 Medium

#### 3.3 Missing Skip Links
**Fix:** Add skip to main content link at top of page.

#### 3.4 Color Contrast
**Issue:** Some gray text on white may not meet WCAG AA.  
**Example:** `text-neutral-400` on white background.  
**Fix:** Use `text-neutral-600` minimum for body text.

#### 3.5 Form Labels Not Associated
**File:** `frontend/src/pages/Library.tsx:134-142`
**Fix:** Use `htmlFor` attribute or wrap inputs in labels properly.

### 🟢 Good Practices Observed

- ✅ ProductCard uses `role="button"` and `tabIndex={0}`
- ✅ Keyboard navigation on cards (`onKeyDown`)
- ✅ Semantic HTML (`<article>`, `<header>`, `<main>`, `<nav>`)
- ✅ Alt text on images

---

## 4. Code Quality & Best Practices

### 🟡 Medium

#### 4.1 Inconsistent Error Handling
**Issue:** Some endpoints catch exceptions broadly.  
**Fix:** Use specific exception types and custom error responses.

#### 4.2 Deprecated `datetime.utcnow()`
**Files:** Multiple  
**Fix:** Use `datetime.now(datetime.UTC)` instead.

#### 4.3 Missing Type Hints
**Files:** Some service functions lack return type hints.  
**Fix:** Add complete type annotations.

#### 4.4 TODO Comments in Production Code
**File:** `frontend/src/pages/Library.tsx:24-27`
```tsx
// TODO: Use selectedCollection and selectedTag to filter products
void _selectedCollection;
void _selectedTag;
```
**Fix:** Implement or remove unused props.

#### 4.5 Magic Numbers
**Example:** `per_page: int = Query(default=50, ge=1, le=100)`  
**Fix:** Move to config constants.

### 🟢 Good Practices Observed

- ✅ Clean project structure with separation of concerns
- ✅ Proper dependency injection with FastAPI
- ✅ Pydantic models for validation
- ✅ React Query for data fetching
- ✅ TypeScript with proper types
- ✅ Tailwind CSS with consistent design system

---

## 5. Recommended Actions

### Immediate (Before Production)

1. **Generate proper secret key** - Use `secrets.token_urlsafe(32)`
2. **Add path validation** - Prevent serving files outside library
3. **Add rate limiting** - Especially on AI endpoints
4. **Add database indexes** - On frequently queried columns
5. **Fix accessibility** - Add ARIA labels to all interactive elements

### Short-term (Next Sprint)

6. Implement focus trap in modals
7. Add skip links
8. Review and fix color contrast
9. Replace deprecated `datetime.utcnow()`
10. Complete TODO implementations or remove dead code

### Long-term (Backlog)

11. Add comprehensive test suite
12. Set up CI/CD with security scanning
13. Add API documentation with OpenAPI examples
14. Consider Content Security Policy headers
15. Add audit logging for sensitive operations

---

## 6. Security Checklist for Deployment

- [ ] Secret key is set via environment variable (not default)
- [ ] Database is backed up regularly
- [ ] HTTPS is enforced
- [ ] Rate limiting is configured
- [ ] CORS origins are restricted to known domains
- [ ] API keys are rotated periodically
- [ ] Logs do not contain sensitive data
- [ ] File upload paths are validated

---

*Review conducted by Cascade AI Assistant*
