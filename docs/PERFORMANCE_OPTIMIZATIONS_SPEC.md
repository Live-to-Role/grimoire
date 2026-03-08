# Performance Optimizations Specification

**Status:** Planning  
**Created:** 2026-01-04  
**Owner:** Backend & Frontend Teams

---

## Overview

This document specifies three major performance optimizations for Grimoire to handle large libraries (10,000+ products) efficiently.

## Problem Statement

Current performance bottlenecks:
- **Memory/rendering**: Loading 50+ product cards at once causes browser lag
- **Cover loading**: Full-size cover images (often 1-2MB) slow initial page render
- **Filter queries**: Sidebar filters query database for options on every page load

These issues compound with library size, making large collections (>5,000 products) sluggish.

---

## Feature 1: Virtual Scrolling

### What

Implement virtual scrolling (windowing) in the product grid to render only visible items instead of all items on the page.

### Why

- Current implementation renders all 24 products per page
- With large pages or infinite scroll, DOM nodes accumulate
- Virtual scrolling renders ~20 items (visible + buffer) regardless of total count
- **Expected impact**: 80% reduction in DOM nodes, smooth scrolling for 10,000+ products

### How

#### Technology Choice
- **Library**: `@tanstack/react-virtual` (lightweight, React Query compatible)
- **Alternative**: `react-window` (more mature, but heavier)

#### Implementation

**Frontend Changes:**

1. **ProductGrid.tsx**: Replace static grid with virtual grid
   ```typescript
   import { useVirtualizer } from '@tanstack/react-virtual'
   
   - Use parent ref for scroll container
   - Calculate item heights (grid mode: fixed 280px, list mode: fixed 80px)
   - Render only virtual items
   - Maintain current grid columns (responsive)
   ```

2. **Library.tsx**: Implement infinite scroll
   ```typescript
   - Track total items from API
   - Load next page when scrolling near bottom (80% threshold)
   - Append new items to existing list
   - Handle loading states
   ```

3. **State Management**:
   ```typescript
   - Convert pagination to cursor-based (page accumulation)
   - Cache all loaded products in React Query
   - Preserve scroll position on filter changes
   ```

#### Backend Changes

No changes needed - pagination already supports large offsets.

#### Acceptance Criteria

- [ ] Smooth scrolling with 10,000+ products
- [ ] Memory usage stays flat (not proportional to library size)
- [ ] Grid and list view modes both work
- [ ] Filter changes reset scroll position
- [ ] No visual jank during scroll

---

## Feature 2: Thumbnail Generation

### What

Generate optimized thumbnail images (300x400px, ~50KB) from cover images and serve those for grid view instead of full covers.

### Why

- Current: Serve full-resolution covers (often 1-2MB each)
- With 24 products: 24-48MB transferred per page
- Thumbnails: 24 × 50KB = 1.2MB per page
- **Expected impact**: 95% reduction in image data, 3-5x faster initial load

### How

#### Technology Choice
- **Library**: PIL/Pillow (Python) for thumbnail generation
- **Format**: WebP with JPEG fallback (better compression)
- **Storage**: Separate `thumbnails/` directory alongside `covers/`

#### Implementation

**Backend Changes:**

1. **New Service**: `thumbnail_service.py`
   ```python
   async def generate_thumbnail(
       cover_path: Path, 
       size: tuple[int, int] = (300, 400)
   ) -> Path:
       - Load cover image
       - Resize maintaining aspect ratio
       - Crop to fit (center)
       - Save as WebP (quality=85) and JPEG fallback
       - Return thumbnail path
   ```

2. **Queue Integration**: Add thumbnail generation to processing queue
   ```python
   - After cover extraction, queue thumbnail generation
   - Regenerate if cover changes
   - Batch process existing covers (migration)
   ```

3. **API Changes**: `products.py`
   ```python
   # Add thumbnail endpoint
   @router.get("/{product_id}/thumbnail")
   async def get_product_thumbnail(...):
       - Check if thumbnail exists
       - If not, generate on-demand (first access)
       - Return with aggressive caching (max-age=2592000)
   ```

4. **Database**: Add `thumbnail_path` column to Product model
   ```python
   thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
   ```

**Frontend Changes:**

1. **ProductCard.tsx**: Use thumbnail endpoint
   ```typescript
   // Grid view
   src={getCoverUrl(product.id, 'thumbnail')}
   
   // List view (smaller, use thumbnail)
   src={getCoverUrl(product.id, 'thumbnail')}
   
   // Detail view (full size)
   src={getCoverUrl(product.id, 'cover')}
   ```

2. **API**: Add thumbnail URL helper
   ```typescript
   export function getCoverUrl(
     productId: number, 
     size: 'thumbnail' | 'cover' = 'cover'
   ): string
   ```

#### Migration Strategy

1. **Phase 1**: Add thumbnail generation to queue (new covers)
2. **Phase 2**: Background job to generate thumbnails for existing covers
3. **Phase 3**: Frontend switches to thumbnails
4. **Fallback**: If thumbnail missing, serve full cover (graceful degradation)

#### Acceptance Criteria

- [ ] Thumbnails auto-generated for new covers
- [ ] Grid view uses thumbnails
- [ ] Detail view uses full covers
- [ ] Thumbnail generation takes <500ms per image
- [ ] Fallback to full cover if thumbnail missing
- [ ] WebP served to supporting browsers, JPEG to others

---

## Feature 3: Redis Caching for Filter Options

### What

Cache frequently-accessed filter options (game systems, publishers, authors, genres) in Redis to avoid repeated database queries.

### Why

- Current: Every sidebar render queries database for filter options
- Queries scan thousands of products for unique values
- These values change infrequently (only when products added/updated)
- **Expected impact**: 90% reduction in filter query time, <10ms response

### How

#### Technology Choice
- **Cache**: Redis (in-memory, persistent, fast invalidation)
- **TTL Strategy**: Hybrid (time + event-based invalidation)
- **Library**: `redis-py` with async support

#### Implementation

**Infrastructure:**

1. **docker-compose.yml**: Add Redis service
   ```yaml
   redis:
     image: redis:7-alpine
     ports:
       - "6379:6379"
     volumes:
       - redis_data:/data
     command: redis-server --appendonly yes
   ```

2. **Environment**: Add Redis connection URL
   ```env
   REDIS_URL=redis://redis:6379/0
   ```

**Backend Changes:**

1. **New Service**: `cache_service.py`
   ```python
   class CacheService:
       async def get_filter_options(
           self, 
           field: str
       ) -> list[str]:
           # Check Redis cache
           # If miss, query database
           # Store in Redis (TTL: 1 hour)
           # Return results
       
       async def invalidate_filter_options(self):
           # Clear all filter caches
           # Called when products added/updated/deleted
   ```

2. **Cache Keys**:
   ```
   filters:game_systems -> ["D&D 5e", "Pathfinder", ...]
   filters:publishers -> ["Wizards of the Coast", ...]
   filters:authors -> [...]
   filters:genres -> [...]
   filters:product_types -> [...]
   ```

3. **Invalidation Strategy**:
   ```python
   # Triggers:
   - Product created/updated/deleted
   - Bulk import completed
   - Manual cache clear (admin endpoint)
   
   # Method: Delete specific keys
   await redis.delete("filters:*")
   ```

4. **API Integration**: Update filter endpoints
   ```python
   @router.get("/filters/game-systems")
   async def get_game_systems(
       cache: Depends(get_cache_service)
   ):
       return await cache.get_filter_options("game_system")
   ```

**Frontend Changes:**

1. **Sidebar.tsx**: Fetch filter options from cache endpoints
   ```typescript
   // Replace direct queries with cached endpoints
   const { data: gameSystems } = useQuery(
     ['filters', 'game-systems'],
     () => api.get('/filters/game-systems'),
     { staleTime: 300000 } // 5 min cache in React Query too
   )
   ```

2. **No state change handling**: Cache invalidation is backend-only

#### Fallback Strategy

If Redis unavailable:
- Log warning
- Fall back to database queries
- Don't fail requests

#### Acceptance Criteria

- [ ] Filter options load in <10ms (cache hit)
- [ ] Cache automatically invalidates when products change
- [ ] Redis failure doesn't break the app (graceful degradation)
- [ ] All filter fields cached (game_system, publisher, author, genre, product_type)
- [ ] Admin endpoint to manually clear cache

---

## Implementation Order

### Phase 1: Thumbnail Generation (Highest Impact)
- Immediate 95% reduction in image bandwidth
- Improves initial page load most significantly
- Backend-only, low frontend risk

**Estimated Effort:** 2-3 days  
**Priority:** HIGH

### Phase 2: Redis Caching (Quick Win)
- Simple implementation
- Reduces server load
- Improves sidebar responsiveness

**Estimated Effort:** 1-2 days  
**Priority:** MEDIUM

### Phase 3: Virtual Scrolling (Complex, High Value)
- Most complex frontend change
- Biggest UX improvement for large libraries
- Requires testing across devices

**Estimated Effort:** 3-4 days  
**Priority:** MEDIUM (only needed for libraries >5,000 products)

---

## Testing Strategy

### Thumbnail Generation
- Unit tests: Thumbnail generation with various image sizes
- Integration: Queue processing, API serving
- Load test: Generate 1,000 thumbnails, measure time
- Visual test: Verify quality at different screen sizes

### Redis Caching
- Unit tests: Cache hit/miss scenarios
- Integration: Invalidation triggers
- Failover test: Redis down, verify fallback
- Load test: 1,000 concurrent filter requests

### Virtual Scrolling
- Unit tests: Virtualizer calculations
- Integration: Infinite scroll pagination
- Performance: Profile memory with 10,000 items
- Cross-browser: Test Safari, Firefox, Chrome
- Accessibility: Keyboard navigation, screen readers

---

## Monitoring & Metrics

### Key Metrics
- **Thumbnail Generation**: Time per image, queue depth
- **Cache Hit Rate**: Redis hits vs misses (target: >90%)
- **Page Load Time**: Time to first meaningful paint (target: <2s)
- **Memory Usage**: Browser heap size with virtual scrolling
- **API Response Times**: Filter endpoints (target: <50ms)

### Dashboards
- Grafana dashboard tracking cache hit rates
- Frontend performance metrics in Sentry
- Queue processing stats in Huey dashboard

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Thumbnail quality loss | Medium | Configurable quality settings, user testing |
| Redis single point of failure | High | Graceful degradation, monitoring alerts |
| Virtual scroll breaks existing UI | High | Feature flag, thorough testing, gradual rollout |
| Thumbnail storage costs | Low | WebP compression, cleanup job for deleted products |
| Cache invalidation bugs | Medium | Conservative TTLs, manual clear endpoint |

---

## Success Criteria

### Thumbnail Generation
- ✅ Initial page load 3-5x faster
- ✅ Image bandwidth reduced by 90%+
- ✅ No visible quality degradation

### Redis Caching
- ✅ Filter loading <50ms (currently 200-500ms)
- ✅ Cache hit rate >90%
- ✅ Zero downtime if Redis fails

### Virtual Scrolling
- ✅ Smooth scrolling with 10,000+ products
- ✅ Memory usage flat (not proportional to count)
- ✅ Works on mobile devices
- ✅ Accessibility maintained

---

## Future Enhancements

- **Image CDN**: Serve thumbnails from CDN (Cloudflare, AWS S3)
- **Lazy loading**: Blur placeholder → thumbnail → full cover
- **Smart caching**: Prefetch likely filter combinations
- **WebP AVIF**: Next-gen formats for even better compression
- **Cluster mode**: Redis cluster for high availability

---

## References

- [TanStack Virtual Docs](https://tanstack.com/virtual/latest)
- [Pillow Thumbnail Documentation](https://pillow.readthedocs.io/)
- [Redis Caching Best Practices](https://redis.io/docs/manual/patterns/)
- [Web Performance Working Group](https://www.w3.org/webperf/)
