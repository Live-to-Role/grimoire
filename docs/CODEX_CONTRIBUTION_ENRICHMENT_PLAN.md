# Codex Contribution Enrichment Plan

**Status:** Planning  
**Date:** December 2024

## Vision

Codex becomes a comprehensive, crowdsourced TTRPG product database where:
- Users contribute product data via their local Grimoire installations
- New products are created automatically when no match exists
- Edits to existing products are queued for moderation
- Products have rich metadata including images and purchase links

---

## Decisions Made

| Question | Decision |
|----------|----------|
| Image Storage | Cloudflare R2 |
| Thumbnail Generation | On approval (when product is created/updated) |
| Affiliate Links | Auto-append affiliate codes to marketplace URLs |
| Rate Limits | See Rate Limiting section below |

---

## Phase 1: Image Upload Support

### Requirements
- Accept cover image uploads with contributions
- Auto-generate thumbnails on product approval (300x400 cards, 150x200 lists)
- Store images in Cloudflare R2
- Serve via Cloudflare CDN

### Codex Backend Changes

1. **Add Cloudflare R2 storage backend**
   ```python
   # settings/base.py
   STORAGES = {
       "default": {
           "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
           "OPTIONS": {
               "endpoint_url": env("R2_ENDPOINT_URL"),
               "access_key": env("R2_ACCESS_KEY_ID"),
               "secret_key": env("R2_SECRET_ACCESS_KEY"),
               "bucket_name": env("R2_BUCKET_NAME"),
               "default_acl": "public-read",
               "custom_domain": env("R2_CUSTOM_DOMAIN"),  # e.g., cdn.codex.livetorole.com
           },
       },
   }
   ```

2. **Update Product model**
   ```python
   cover_image = models.ImageField(upload_to="covers/", blank=True, null=True)
   thumbnail_small = models.ImageField(upload_to="thumbs/small/", blank=True, null=True)
   thumbnail_large = models.ImageField(upload_to="thumbs/large/", blank=True, null=True)
   ```

3. **Create image processing service**
   ```python
   from PIL import Image
   from io import BytesIO
   
   def generate_thumbnails(cover_image):
       """Generate thumbnail variants from cover image."""
       img = Image.open(cover_image)
       
       # Large thumbnail (300x400)
       large = img.copy()
       large.thumbnail((300, 400), Image.LANCZOS)
       
       # Small thumbnail (150x200)
       small = img.copy()
       small.thumbnail((150, 200), Image.LANCZOS)
       
       return large, small
   ```

4. **Add image upload endpoint**
   ```
   POST /api/v1/contributions/
   Content-Type: multipart/form-data
   
   - data: JSON contribution data
   - cover_image: image file (JPEG, PNG, WebP, max 5MB)
   ```

5. **Process images on approval**
   - When contribution is approved, save cover image to R2
   - Generate and save thumbnails
   - Update product with image URLs

### Contribution Data Schema Update
```python
ALLOWED_PRODUCT_FIELDS = {
    # ... existing fields ...
    "cover_image",      # Base64 encoded image data
    "cover_image_url",  # URL to existing image (for migration)
}
```

---

## Phase 2: Flexible Marketplace URLs

### Current State
- `dtrpg_url` - DriveThruRPG link
- `itch_url` - itch.io link

### New Schema
Replace with flexible `marketplace_urls` JSONField supporting up to 4 URLs:

```python
marketplace_urls = models.JSONField(default=list, blank=True)
# Schema: [
#   {"platform": "dtrpg", "url": "https://..."},
#   {"platform": "dmsguild", "url": "https://..."},
#   {"platform": "itch", "url": "https://..."},
#   {"platform": "other", "url": "https://...", "label": "Exalted Funeral"}
# ]
```

### Supported Platforms

| Platform Key | Display Name | Affiliate Program | Commission |
|-------------|--------------|-------------------|------------|
| `dtrpg` | DriveThruRPG | Yes | 5% (cashable) |
| `dmsguild` | Dungeon Masters Guild | Yes | 5% (OneBookShelf) |
| `itch` | itch.io | No | - |
| `other` | Custom (uses label) | Varies | - |

### Affiliate Link Auto-Generation

```python
AFFILIATE_CODES = {
    "dtrpg": "affiliate_id=XXXXX",
    "dmsguild": "affiliate_id=XXXXX",
}

def append_affiliate_code(platform: str, url: str) -> str:
    """Append affiliate code to marketplace URL."""
    if platform in AFFILIATE_CODES:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{AFFILIATE_CODES[platform]}"
    return url
```

### Migration
1. Create new `marketplace_urls` field
2. Migrate existing `dtrpg_url` and `itch_url` data
3. Deprecate old fields (remove in v2)

---

## Phase 3: Product Matching Logic

### On Contribution Submission

```python
def find_matching_product(contribution_data: dict, file_hash: str) -> Product | None:
    """
    Search for existing product that matches this contribution.
    
    Priority:
    1. Exact file_hash match (SHA256 of PDF)
    2. Exact title + publisher match
    3. Fuzzy title match (>90% similarity) - flag for review
    """
    
    # 1. File hash match
    if file_hash:
        existing = FileHash.objects.filter(hash_sha256=file_hash).first()
        if existing:
            return existing.product
    
    # 2. Exact title + publisher match
    title = contribution_data.get("title", "").strip()
    publisher_name = contribution_data.get("publisher", "").strip()
    
    if title and publisher_name:
        match = Product.objects.filter(
            title__iexact=title,
            publisher__name__iexact=publisher_name
        ).first()
        if match:
            return match
    
    # 3. Fuzzy matching (optional, flag for manual review)
    # Use difflib or rapidfuzz for similarity scoring
    
    return None
```

### Routing Logic

```python
existing_product = find_matching_product(contribution_data, file_hash)

if existing_product:
    # Create as edit contribution
    contribution_type = "edit_product"
    product = existing_product
else:
    # Create as new product contribution
    contribution_type = "new_product"
    product = None
```

---

## Phase 4: Rate Limiting

### Research: Wikipedia Bot Policy
- Maximum **20 edits per minute** without explicit approval
- Bots should adjust speed based on server load
- Unflagged/trial bots should edit slower for review

### Codex Rate Limits

| Tier | Rate | Use Case |
|------|------|----------|
| Burst | 30 per 5 minutes | Initial sync, batch processing |
| Sustained | 60 per hour | Normal operation |
| Daily | 500 per day | Prevent abuse |

### Implementation

```python
# Django REST Framework throttling
class ContributionBurstThrottle(UserRateThrottle):
    rate = '30/5min'
    scope = 'contribution_burst'

class ContributionSustainedThrottle(UserRateThrottle):
    rate = '60/hour'
    scope = 'contribution_sustained'

class ContributionDailyThrottle(UserRateThrottle):
    rate = '500/day'
    scope = 'contribution_daily'
```

### Bulk Import Considerations

For users with large libraries (10,000+ PDFs):

1. **Progressive Sync**: Grimoire queues locally, sends in batches
   - Process 100-200 per day
   - Full library sync takes ~2-3 months
   - Prioritize recently accessed/modified files

2. **Trust Escalation**: After 10+ approved contributions, enable auto-approval
   - See "Trust System & Account Security" section below

3. **Local-First Mode**: Grimoire can store all data locally
   - Only sync products user explicitly chooses to contribute
   - Or sync in background during idle time

### Grimoire-Side Throttling

Grimoire should implement client-side rate limiting:
```python
class ContributionQueue:
    """Queue contributions and send at controlled rate."""
    
    def __init__(self):
        self.queue = []
        self.rate_limit = 10  # per minute
        self.last_send_time = None
    
    async def process_queue(self):
        """Process queued contributions respecting rate limits."""
        while self.queue:
            # Wait if needed to respect rate limit
            if self.last_send_time:
                elapsed = time.time() - self.last_send_time
                min_interval = 60 / self.rate_limit
                if elapsed < min_interval:
                    await asyncio.sleep(min_interval - elapsed)
            
            contribution = self.queue.pop(0)
            await self.send_contribution(contribution)
            self.last_send_time = time.time()
```

### Progressive Sync User Messaging

Grimoire should display clear messaging about sync status and timing:

```
┌─────────────────────────────────────────────────────────────┐
│  📚 Library Sync Status                                     │
├─────────────────────────────────────────────────────────────┤
│  Your library: 12,847 PDFs                                  │
│  Already in Codex: 342                                      │
│  Queued for contribution: 1,205                             │
│  Pending moderation: 89                                     │
│                                                             │
│  ⏱️ Estimated sync time: ~2-3 weeks                         │
│     (Processing 100-200 items per day)                      │
│                                                             │
│  Sync runs automatically in the background when Grimoire    │
│  is open. You can continue using your library normally.     │
│                                                             │
│  [Pause Sync]  [Priority Queue Settings]                    │
└─────────────────────────────────────────────────────────────┘
```

**User-facing text options:**

- "Syncing your library to Codex. Large libraries may take several weeks."
- "Contributing [X] of [Y] products. Estimated completion: [date]"
- "Sync paused. [X] items remaining in queue."
- "Your contribution is pending moderator review."
- "Contribution approved! [Product Title] is now in Codex."

---

## Phase 4.5: Trust System & Account Security

### Auto-Approval for Trusted Contributors

After a user has **10+ approved contributions**, their future contributions are auto-approved:

```python
def should_auto_approve(user: User, contribution: Contribution) -> bool:
    """Determine if contribution should be auto-approved."""
    
    # Check trust threshold
    if user.approved_contribution_count < 10:
        return False
    
    # Check for security flags
    if user.is_flagged or user.trust_revoked:
        return False
    
    # Check recent rejection rate
    recent_rejections = Contribution.objects.filter(
        user=user,
        status="rejected",
        reviewed_at__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    if recent_rejections >= 3:
        return False  # Too many recent rejections
    
    # Check for anomalous behavior
    if detect_anomalous_activity(user):
        return False
    
    return True
```

### Compromised Account Defense

Protect against accounts that may be compromised or acting maliciously:

#### 1. Anomaly Detection

```python
def detect_anomalous_activity(user: User) -> bool:
    """Detect unusual contribution patterns that may indicate compromise."""
    
    now = timezone.now()
    last_hour = now - timedelta(hours=1)
    last_day = now - timedelta(days=1)
    
    # Check 1: Sudden spike in contribution volume
    hourly_count = Contribution.objects.filter(
        user=user, 
        created_at__gte=last_hour
    ).count()
    
    daily_average = user.avg_daily_contributions or 5
    if hourly_count > daily_average * 3:
        flag_for_review(user, "Volume spike detected")
        return True
    
    # Check 2: Contributions from new IP/location
    recent_ips = get_recent_ips(user, days=30)
    current_ip = get_current_request_ip()
    if current_ip not in recent_ips and len(recent_ips) > 0:
        # New IP - require manual review for first few contributions
        return True
    
    # Check 3: Unusual timing (user normally active 9-5, now active 3am)
    if is_unusual_activity_time(user):
        return True
    
    # Check 4: Content pattern change (e.g., suddenly different game systems)
    if detect_content_pattern_change(user):
        return True
    
    return False
```

#### 2. Rate Limit Reduction on Suspicious Activity

```python
class AdaptiveContributionThrottle(UserRateThrottle):
    """Reduce rate limits for suspicious accounts."""
    
    def get_rate(self):
        user = self.request.user
        
        if user.is_flagged:
            return '5/hour'  # Severely restricted
        
        if user.recent_rejection_count >= 3:
            return '20/hour'  # Reduced
        
        if user.approved_contribution_count >= 10:
            return '200/hour'  # Trusted
        
        return '60/hour'  # Default
```

#### 3. Automatic Trust Revocation

```python
def check_trust_status(user: User):
    """Revoke trust if abuse is detected."""
    
    # Revoke if 5+ rejections in 24 hours
    recent_rejections = Contribution.objects.filter(
        user=user,
        status="rejected",
        reviewed_at__gte=timezone.now() - timedelta(hours=24)
    ).count()
    
    if recent_rejections >= 5:
        user.trust_revoked = True
        user.trust_revoked_at = timezone.now()
        user.trust_revoked_reason = "Multiple rejections in 24 hours"
        user.save()
        
        # Notify moderators
        notify_moderators(
            f"Trust revoked for {user.email}: {recent_rejections} rejections in 24h"
        )
        
        # Queue recent auto-approved contributions for review
        Contribution.objects.filter(
            user=user,
            status="approved",
            reviewed_by__isnull=True,  # Auto-approved (no reviewer)
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).update(status="pending", needs_reReview=True)
```

#### 4. User Model Additions

```python
class User(AbstractUser):
    # ... existing fields ...
    
    # Trust system
    approved_contribution_count = models.PositiveIntegerField(default=0)
    trust_revoked = models.BooleanField(default=False)
    trust_revoked_at = models.DateTimeField(null=True, blank=True)
    trust_revoked_reason = models.CharField(max_length=255, blank=True)
    
    # Security tracking
    is_flagged = models.BooleanField(default=False)
    last_contribution_ip = models.GenericIPAddressField(null=True, blank=True)
    avg_daily_contributions = models.FloatField(null=True, blank=True)
```

---

## Phase 4.6: Batch Moderation Tools

### Admin Interface Enhancements

Add batch operations to Django Admin and frontend moderation UI:

#### 1. Django Admin Actions

```python
@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ["id", "title_preview", "user", "source", "status", "created_at"]
    list_filter = ["status", "source", "contribution_type"]
    search_fields = ["data__title", "user__email"]
    actions = [
        "approve_selected",
        "reject_selected", 
        "approve_all_from_trusted_users",
        "bulk_approve_by_source",
    ]
    
    @admin.action(description="Approve all from trusted users (10+ approved)")
    def approve_all_from_trusted_users(self, request, queryset):
        trusted_contributions = queryset.filter(
            status="pending",
            user__approved_contribution_count__gte=10,
            user__trust_revoked=False,
        )
        count = 0
        for contribution in trusted_contributions:
            self._approve_contribution(contribution, request.user)
            count += 1
        self.message_user(request, f"Approved {count} contributions from trusted users.")
    
    @admin.action(description="Bulk approve Grimoire contributions")
    def bulk_approve_by_source(self, request, queryset):
        grimoire_pending = queryset.filter(
            status="pending",
            source="grimoire",
        )
        # Show confirmation page with preview
        # ...
```

#### 2. Frontend Batch Operations

Add to ModerationPage.tsx:

```typescript
interface BatchActions {
  approveAll: () => void;
  rejectAll: () => void;
  approveFromTrusted: () => void;
  approveBySource: (source: string) => void;
}

// Batch action buttons
<div className="batch-actions">
  <button onClick={() => batchApprove(selectedIds)}>
    Approve Selected ({selectedIds.length})
  </button>
  <button onClick={() => approveAllTrusted()}>
    Approve All from Trusted Users
  </button>
  <button onClick={() => approveBySource("grimoire")}>
    Approve All Grimoire
  </button>
</div>

// Quick filters
<div className="quick-filters">
  <button onClick={() => setFilter({ source: "grimoire", status: "pending" })}>
    Grimoire Pending ({counts.grimoire})
  </button>
  <button onClick={() => setFilter({ trusted: true, status: "pending" })}>
    Trusted Users ({counts.trusted})
  </button>
</div>
```

#### 3. Batch Review API Endpoint

```python
@action(detail=False, methods=["post"], permission_classes=[CanModerateContribution])
def batch_review(self, request):
    """Approve or reject multiple contributions at once."""
    
    serializer = BatchReviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    contribution_ids = serializer.validated_data["contribution_ids"]
    action = serializer.validated_data["action"]  # "approve" or "reject"
    review_notes = serializer.validated_data.get("review_notes", "")
    
    # Limit batch size
    if len(contribution_ids) > 100:
        return Response(
            {"error": "Maximum 100 contributions per batch"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    contributions = Contribution.objects.filter(
        id__in=contribution_ids,
        status="pending"
    )
    
    results = {"approved": 0, "rejected": 0, "errors": []}
    
    for contribution in contributions:
        try:
            if action == "approve":
                self._approve_contribution(contribution, request.user, review_notes)
                results["approved"] += 1
            else:
                self._reject_contribution(contribution, request.user, review_notes)
                results["rejected"] += 1
        except Exception as e:
            results["errors"].append({
                "id": str(contribution.id),
                "error": str(e)
            })
    
    return Response(results)
```

#### 4. Moderator Concurrency Handling

Prevent multiple moderators from working on the same contributions simultaneously.

**Approach: Claim-Based Locking**

```python
# Add to Contribution model
class Contribution(models.Model):
    # ... existing fields ...
    
    # Concurrency control
    claimed_by = models.ForeignKey(
        User, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        related_name="claimed_contributions"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    
    # Claims expire after 10 minutes of inactivity
    CLAIM_EXPIRY_MINUTES = 10
    
    @property
    def is_claimed(self) -> bool:
        if not self.claimed_by or not self.claimed_at:
            return False
        expiry = self.claimed_at + timedelta(minutes=self.CLAIM_EXPIRY_MINUTES)
        return timezone.now() < expiry
    
    def claim(self, user: User) -> bool:
        """Attempt to claim this contribution for review."""
        if self.is_claimed and self.claimed_by != user:
            return False  # Already claimed by someone else
        
        self.claimed_by = user
        self.claimed_at = timezone.now()
        self.save(update_fields=["claimed_by", "claimed_at"])
        return True
    
    def release_claim(self):
        """Release the claim on this contribution."""
        self.claimed_by = None
        self.claimed_at = None
        self.save(update_fields=["claimed_by", "claimed_at"])
```

**API Endpoints for Claims**

```python
@action(detail=True, methods=["post"], permission_classes=[CanModerateContribution])
def claim(self, request, pk=None):
    """Claim a contribution for review."""
    contribution = self.get_object()
    
    if contribution.status != "pending":
        return Response(
            {"error": "Only pending contributions can be claimed"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if contribution.is_claimed and contribution.claimed_by != request.user:
        return Response({
            "error": "already_claimed",
            "message": f"This contribution is being reviewed by {contribution.claimed_by.public_name}",
            "claimed_by": contribution.claimed_by.public_name,
            "expires_at": (contribution.claimed_at + timedelta(minutes=10)).isoformat(),
        }, status=status.HTTP_409_CONFLICT)
    
    contribution.claim(request.user)
    return Response({"status": "claimed", "expires_in_minutes": 10})


@action(detail=True, methods=["post"], permission_classes=[CanModerateContribution])
def release(self, request, pk=None):
    """Release a claim on a contribution."""
    contribution = self.get_object()
    
    if contribution.claimed_by == request.user:
        contribution.release_claim()
    
    return Response({"status": "released"})


@action(detail=False, methods=["post"], permission_classes=[CanModerateContribution])
def claim_batch(self, request):
    """Claim multiple contributions for batch review."""
    count = request.data.get("count", 20)
    count = min(count, 50)  # Max 50 at a time
    
    # Get unclaimed pending contributions
    available = Contribution.objects.filter(
        status="pending"
    ).filter(
        Q(claimed_by__isnull=True) | 
        Q(claimed_at__lt=timezone.now() - timedelta(minutes=10))  # Expired claims
    ).order_by("created_at")[:count]
    
    claimed_ids = []
    for contribution in available:
        if contribution.claim(request.user):
            claimed_ids.append(str(contribution.id))
    
    return Response({
        "claimed_count": len(claimed_ids),
        "contribution_ids": claimed_ids,
        "expires_in_minutes": 10,
    })
```

**Frontend Integration**

```typescript
// ModerationPage.tsx

// Auto-claim when viewing details
const handleExpand = async (id: string) => {
  try {
    await claimContribution(id);
    setExpandedId(id);
  } catch (error) {
    if (error.response?.data?.error === "already_claimed") {
      toast.error(`Being reviewed by ${error.response.data.claimed_by}`);
      return;
    }
  }
};

// Claim batch for review
const handleClaimBatch = async () => {
  const result = await claimBatch(20);
  setClaimedIds(result.contribution_ids);
  toast.success(`Claimed ${result.claimed_count} contributions`);
  
  // Start expiry timer
  setExpiresAt(Date.now() + 10 * 60 * 1000);
};

// Visual indicator for claimed items
{contribution.claimed_by && contribution.claimed_by.id !== currentUser.id && (
  <span className="badge-warning">
    Being reviewed by {contribution.claimed_by.public_name}
  </span>
)}

// Heartbeat to extend claim while actively reviewing
useEffect(() => {
  if (!expandedId) return;
  
  const interval = setInterval(async () => {
    await extendClaim(expandedId);
  }, 5 * 60 * 1000); // Refresh every 5 minutes
  
  return () => clearInterval(interval);
}, [expandedId]);
```

**Optimistic Locking Fallback**

Even with claims, use optimistic locking as a safety net:

```python
def _approve_contribution(self, contribution, reviewer, notes=""):
    """Approve with optimistic locking."""
    
    # Check contribution hasn't been modified
    if contribution.status != "pending":
        raise ValidationError(
            f"Contribution already {contribution.status} by {contribution.reviewed_by}"
        )
    
    # Use select_for_update to prevent race conditions
    with transaction.atomic():
        locked = Contribution.objects.select_for_update().get(id=contribution.id)
        
        if locked.status != "pending":
            raise ValidationError("Contribution was already reviewed")
        
        # Proceed with approval
        if locked.contribution_type == "new_product":
            product = self._create_product_from_data(locked.data, locked.user)
            locked.product = product
        elif locked.product:
            self._apply_changes_to_product(locked.product, locked.data, locked.user)
        
        locked.status = "approved"
        locked.reviewed_by = reviewer
        locked.review_notes = notes
        locked.reviewed_at = timezone.now()
        locked.claimed_by = None  # Release claim
        locked.claimed_at = None
        locked.save()
```

**Cleanup Job**

```python
# management/commands/cleanup_expired_claims.py
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Release expired contribution claims"
    
    def handle(self, *args, **options):
        expiry_threshold = timezone.now() - timedelta(minutes=10)
        
        expired = Contribution.objects.filter(
            claimed_at__lt=expiry_threshold,
            status="pending"
        ).update(claimed_by=None, claimed_at=None)
        
        self.stdout.write(f"Released {expired} expired claims")
```

Run via cron every 5 minutes or use Celery beat.

---

## Phase 4.7: No-Change Contribution Detection

Skip contributions that add nothing new to an existing product:

### Grimoire-Side Detection (Before Sending)

```python
def should_contribute(local_data: dict, existing_product: dict | None) -> bool:
    """
    Determine if this contribution adds value.
    Returns False if the contribution would add nothing new.
    """
    
    if existing_product is None:
        # New product - always contribute
        return True
    
    # Compare fields that can be updated
    dominated_fields = [
        "title", "description", "page_count", "publication_year",
        "game_system", "product_type", "cover_image"
    ]
    
    dominated_fields = [
        "title", "description", "page_count", "publication_year",
        "game_system", "product_type", "cover_image"
    ]
    
    has_new_data = False
    
    for field in dominated_fields:
        local_value = local_data.get(field)
        existing_value = existing_product.get(field)
        
        if local_value and not existing_value:
            # We have data they don't - contribute
            has_new_data = True
            break
        
        if field == "description":
            # Longer description is better
            if local_value and existing_value:
                if len(local_value) > len(existing_value) * 1.5:
                    has_new_data = True
                    break
        
        if field == "cover_image":
            # We have an image they don't
            if local_value and not existing_value:
                has_new_data = True
                break
    
    return has_new_data


def prepare_contribution(pdf_path: str, file_hash: str) -> dict | None:
    """Prepare contribution, returning None if not needed."""
    
    local_data = extract_pdf_metadata(pdf_path)
    
    # Check if product exists in Codex
    existing = fetch_product_by_hash(file_hash)
    
    if not should_contribute(local_data, existing):
        logger.info(f"Skipping {pdf_path}: no new data to contribute")
        return None
    
    return build_contribution_payload(local_data, file_hash)
```

### Codex-Side Validation

```python
def validate_contribution_adds_value(contribution_data: dict, existing_product: Product) -> bool:
    """
    Server-side check that contribution adds meaningful data.
    Rejects contributions that don't improve the product.
    """
    
    dominated_fields = {
        "title", "description", "page_count", "publication_year",
        "game_system_id", "product_type", "cover_image"
    }
    
    dominated_fields_in_contribution = dominated_fields & set(contribution_data.keys())
    
    for field in dominated_fields_in_contribution:
        new_value = contribution_data.get(field)
        existing_value = getattr(existing_product, field, None)
        
        # New value where none existed
        if new_value and not existing_value:
            return True
        
        # Description: accept if significantly longer
        if field == "description" and new_value and existing_value:
            if len(new_value) > len(existing_value) * 1.3:
                return True
    
    return False
```

### API Response for No-Change

```python
# In ContributionViewSet.create()
if existing_product and not validate_contribution_adds_value(contribution_data, existing_product):
    return Response({
        "status": "no_change",
        "message": "Product already has complete data. No contribution needed.",
        "existing_product_id": str(existing_product.id),
    }, status=status.HTTP_200_OK)  # Not an error, just informational
```

---

## Phase 5: Enhanced Contribution Data Schema

### Required Fields (for new products)
| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Product title |
| `publisher` | string | Publisher name (matched or created) |

### Recommended Fields
| Field | Type | Description |
|-------|------|-------------|
| `description` | string | Product description/summary |
| `cover_image` | base64 | Cover image data |
| `page_count` | integer | Number of pages |
| `publication_year` | integer | Year published |
| `game_system` | string | Game system name (matched or created) |
| `product_type` | string | adventure, supplement, sourcebook, etc. |

### Optional Fields
| Field | Type | Description |
|-------|------|-------------|
| `marketplace_urls` | array | Platform/URL objects |
| `level_range_min` | integer | Minimum character level |
| `level_range_max` | integer | Maximum character level |
| `tags` | array | Descriptive tags |
| `isbn` | string | ISBN if available |

---

## Grimoire Agent Instructions

**For the AI agent working on Grimoire:** Update the Grimoire codebase to send richer contribution data to Codex.

### Task 1: Extract More Metadata from PDFs

Enhance PDF metadata extraction to capture all available information:

```python
def extract_pdf_metadata(pdf_path: str) -> dict:
    """Extract comprehensive metadata from PDF."""
    import fitz  # PyMuPDF
    
    doc = fitz.open(pdf_path)
    metadata = doc.metadata
    
    return {
        "title": metadata.get("title") or extract_title_from_filename(pdf_path),
        "publisher": metadata.get("author") or metadata.get("creator") or "Unknown",
        "description": metadata.get("subject") or extract_first_page_summary(doc),
        "page_count": len(doc),
        "publication_year": extract_year_from_metadata(metadata),
        "game_system": detect_game_system(doc),
        "product_type": classify_product_type(doc),
    }
```

### Task 2: Cover Image Extraction

Extract the first page as cover image:

```python
from pdf2image import convert_from_path
import base64
from io import BytesIO

def extract_cover_image(pdf_path: str, max_size_kb: int = 500) -> str | None:
    """
    Extract first page as cover image, return base64.
    Optimize for reasonable file size.
    """
    try:
        images = convert_from_path(
            pdf_path, 
            first_page=1, 
            last_page=1, 
            dpi=150  # Balance quality vs size
        )
        
        if not images:
            return None
        
        cover = images[0]
        
        # Resize if too large (max 800px width)
        if cover.width > 800:
            ratio = 800 / cover.width
            new_size = (800, int(cover.height * ratio))
            cover = cover.resize(new_size, Image.LANCZOS)
        
        # Compress to target size
        buffer = BytesIO()
        quality = 85
        while quality > 30:
            buffer.seek(0)
            buffer.truncate()
            cover.save(buffer, format='JPEG', quality=quality, optimize=True)
            if buffer.tell() <= max_size_kb * 1024:
                break
            quality -= 10
        
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
        
    except Exception as e:
        logger.warning(f"Failed to extract cover from {pdf_path}: {e}")
        return None
```

### Task 3: Game System Detection

Implement heuristics to detect game system from PDF content:

```python
SYSTEM_PATTERNS = {
    "dnd5e": [
        "5th edition", "5e", "d&d 5", "fifth edition", 
        "dungeons & dragons", "player's handbook", "dungeon master's guide",
        "armor class", "hit points", "saving throw", "ability score"
    ],
    "pf2e": [
        "pathfinder 2", "pf2e", "pathfinder second edition",
        "paizo", "golarion"
    ],
    "pf1e": [
        "pathfinder 1", "pf1e", "pathfinder rpg",
        "pathfinder roleplaying game"
    ],
    "osr": [
        "old school", "osr", "basic/expert", "b/x", 
        "old-school essentials", "ose", "labyrinth lord",
        "thac0", "descending ac"
    ],
    "coc": [
        "call of cthulhu", "coc", "chaosium",
        "sanity", "mythos", "keeper"
    ],
    "dcc": [
        "dungeon crawl classics", "dcc", "goodman games"
    ],
    "swn": [
        "stars without number", "swn", "sine nomine"
    ],
    "motw": [
        "monster of the week", "motw", "powered by the apocalypse"
    ],
    "pbta": [
        "powered by the apocalypse", "pbta", "apocalypse world",
        "moves", "playbook"
    ],
}

def detect_game_system(doc) -> str | None:
    """Detect game system from PDF content."""
    # Sample first 10 pages for detection
    text = ""
    for page_num in range(min(10, len(doc))):
        text += doc[page_num].get_text().lower()
    
    # Count pattern matches per system
    scores = {}
    for system, patterns in SYSTEM_PATTERNS.items():
        score = sum(1 for p in patterns if p in text)
        if score > 0:
            scores[system] = score
    
    if scores:
        return max(scores, key=scores.get)
    return None
```

### Task 4: Product Type Classification

Classify product type based on content indicators:

```python
TYPE_INDICATORS = {
    "adventure": [
        "adventure", "module", "campaign", "quest", "dungeon",
        "encounter", "map", "room", "area", "location"
    ],
    "sourcebook": [
        "sourcebook", "setting", "world", "gazetteer",
        "history", "geography", "faction", "kingdom"
    ],
    "supplement": [
        "supplement", "expansion", "options", "rules",
        "variant", "optional"
    ],
    "bestiary": [
        "bestiary", "monsters", "creatures", "enemies",
        "stat block", "challenge rating", "cr "
    ],
    "character_options": [
        "class", "subclass", "race", "ancestry", "archetype",
        "feat", "spell", "background"
    ],
    "rules": [
        "core rules", "rulebook", "system reference",
        "srd", "basic rules"
    ],
    "zine": [
        "zine", "issue", "volume", "magazine"
    ],
}

def classify_product_type(doc) -> str:
    """Classify product type from content."""
    text = ""
    for page_num in range(min(20, len(doc))):
        text += doc[page_num].get_text().lower()
    
    scores = {}
    for ptype, indicators in TYPE_INDICATORS.items():
        score = sum(text.count(ind) for ind in indicators)
        scores[ptype] = score
    
    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 5:  # Minimum confidence threshold
            return best
    
    return "other"
```

### Task 5: Build Complete Contribution Payload

```python
def build_contribution_payload(pdf_path: str, file_hash: str) -> dict:
    """Build complete contribution payload for Codex API."""
    
    metadata = extract_pdf_metadata(pdf_path)
    cover_image = extract_cover_image(pdf_path)
    
    payload = {
        "contribution_type": "new_product",
        "source": "grimoire",
        "file_hash": file_hash,
        "data": {
            "title": metadata["title"],
            "publisher": metadata["publisher"],
            "description": metadata.get("description", ""),
            "page_count": metadata.get("page_count"),
            "publication_year": metadata.get("publication_year"),
            "game_system": metadata.get("game_system"),
            "product_type": metadata.get("product_type", "other"),
        }
    }
    
    # Add cover image if extracted
    if cover_image:
        payload["data"]["cover_image"] = cover_image
    
    return payload
```

### Task 6: Handle Codex API Responses

Update response handling for matching and rate limiting:

```python
async def submit_to_codex(payload: dict) -> dict:
    """Submit contribution to Codex API with proper error handling."""
    
    response = await codex_client.post("/api/v1/contributions/", json=payload)
    
    if response.status_code == 429:
        # Rate limited - back off and retry
        retry_after = int(response.headers.get("Retry-After", 60))
        logger.info(f"Rate limited, waiting {retry_after}s")
        await asyncio.sleep(retry_after)
        return await submit_to_codex(payload)  # Retry
    
    data = response.json()
    
    if response.status_code == 400:
        error = data.get("error")
        
        if error == "file_hash_exists":
            # Product already exists
            return {
                "status": "exists",
                "product_id": data["existing_product_id"],
                "product_title": data["existing_product_title"],
            }
        
        if error == "duplicate_pending":
            # Already submitted, pending review
            return {
                "status": "pending",
                "contribution_id": data["existing_contribution_id"],
            }
        
        # Other validation error
        logger.error(f"Contribution rejected: {data}")
        return {"status": "error", "details": data}
    
    if response.status_code == 201:
        return {
            "status": data.get("status"),  # "pending" or "applied"
            "contribution_id": data.get("contribution_id"),
            "product_id": data.get("product_id"),
        }
    
    return {"status": "error", "details": response.text}
```

### Task 7: Implement Client-Side Queue

For bulk imports, queue contributions locally:

```python
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime

@dataclass
class QueuedContribution:
    payload: dict
    pdf_path: str
    added_at: datetime
    attempts: int = 0

class ContributionQueue:
    """
    Queue contributions and send at controlled rate.
    Persists queue to disk for resume after restart.
    """
    
    def __init__(self, rate_per_minute: int = 10):
        self.queue: deque[QueuedContribution] = deque()
        self.rate_per_minute = rate_per_minute
        self.min_interval = 60 / rate_per_minute
        self.last_send: float = 0
        self.is_processing = False
    
    def add(self, payload: dict, pdf_path: str):
        """Add contribution to queue."""
        self.queue.append(QueuedContribution(
            payload=payload,
            pdf_path=pdf_path,
            added_at=datetime.now(),
        ))
        self.save_queue()
    
    async def process(self):
        """Process queue respecting rate limits."""
        self.is_processing = True
        
        while self.queue and self.is_processing:
            # Respect rate limit
            elapsed = time.time() - self.last_send
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            
            item = self.queue[0]
            
            try:
                result = await submit_to_codex(item.payload)
                
                if result["status"] in ("pending", "applied", "exists"):
                    # Success - remove from queue
                    self.queue.popleft()
                    self.save_queue()
                    self.on_success(item, result)
                else:
                    # Error - retry later or remove
                    item.attempts += 1
                    if item.attempts >= 3:
                        self.queue.popleft()
                        self.on_failure(item, result)
                    else:
                        # Move to back of queue
                        self.queue.rotate(-1)
                
            except Exception as e:
                logger.error(f"Failed to submit {item.pdf_path}: {e}")
                item.attempts += 1
            
            self.last_send = time.time()
        
        self.is_processing = False
    
    def pause(self):
        """Pause queue processing."""
        self.is_processing = False
    
    def save_queue(self):
        """Persist queue to disk."""
        # Implementation: save to JSON/SQLite
        pass
    
    def load_queue(self):
        """Load queue from disk."""
        # Implementation: load from JSON/SQLite
        pass
```

---

## Migration Plan

### Database Changes
1. Add `marketplace_urls` JSONField to Product
2. Add `cover_image`, `thumbnail_small`, `thumbnail_large` ImageFields
3. Migrate existing `dtrpg_url`, `itch_url`, `cover_url`, `thumbnail_url` data
4. Deprecate old fields

### API Changes
- All changes are additive (backward compatible)
- Existing Grimoire clients continue to work
- Enhanced clients can send richer data

### Deployment Order
1. Deploy Codex backend changes (accepts new fields, stores images)
2. Update Grimoire to send enhanced data
3. Roll out progressively

---

## Success Metrics

- **Contribution volume**: Track contributions per day/week
- **Approval rate**: % of contributions approved vs rejected
- **Data quality**: % of products with images, descriptions
- **Matching accuracy**: % of edit contributions correctly matched
- **User engagement**: Number of active contributors

---

## Open Items

1. [ ] Set up Cloudflare R2 bucket for image storage
2. [ ] Configure R2 public access and CDN
3. [ ] Obtain DriveThruRPG and DMsGuild affiliate codes
4. [x] Design moderation batch tools for high-volume approval (see Phase 4.6)
5. [x] Implement trust system for auto-approval (see Phase 4.5)
6. [x] Add compromised account defense (see Phase 4.5)
7. [x] Design progressive sync user messaging (see Phase 4 Rate Limiting)
8. [x] Add no-change contribution detection (see Phase 4.7)
