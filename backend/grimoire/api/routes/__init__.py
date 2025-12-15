"""API routes."""

from fastapi import APIRouter

from grimoire.api.routes import products, collections, tags, folders, search, settings, health, bulk, ai, contributions, queue, extraction, semantic, structured, export, campaigns, duplicates, exclusions, library

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(collections.router, prefix="/collections", tags=["Collections"])
api_router.include_router(tags.router, prefix="/tags", tags=["Tags"])
api_router.include_router(folders.router, prefix="/folders", tags=["Folders"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(bulk.router, prefix="/bulk", tags=["Bulk Operations"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI Identification"])
api_router.include_router(contributions.router, prefix="/contributions", tags=["Contributions"])
api_router.include_router(queue.router, prefix="/queue", tags=["Processing Queue"])
api_router.include_router(extraction.router, prefix="/extraction", tags=["Extraction"])
api_router.include_router(semantic.router, prefix="/semantic", tags=["Semantic Search"])
api_router.include_router(structured.router, prefix="/structured", tags=["Structured Extraction"])
api_router.include_router(export.router, prefix="/export", tags=["Export"])
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["Campaigns"])
api_router.include_router(duplicates.router, prefix="/duplicates", tags=["Duplicates"])
api_router.include_router(exclusions.router, prefix="/exclusions", tags=["Exclusions"])
api_router.include_router(library.router, prefix="/library", tags=["Library"])
