"""SQLAlchemy models."""

from grimoire.models.product import Product
from grimoire.models.collection import Collection, CollectionProduct
from grimoire.models.tag import Tag, ProductTag
from grimoire.models.folder import WatchedFolder
from grimoire.models.queue import ProcessingQueue
from grimoire.models.settings import Setting
from grimoire.models.contribution import ContributionQueue, ContributionStatus
from grimoire.models.embedding import ProductEmbedding
from grimoire.models.campaign import Campaign, Session
from grimoire.models.run_note import RunNote
from grimoire.models.exclusion import ExclusionRule, ExclusionRuleType, DEFAULT_EXCLUSION_RULES
from grimoire.models.scan_job import ScanJob, ScanJobStatus
from grimoire.models.deleted_duplicate import DeletedDuplicate

__all__ = [
    "Product",
    "Collection",
    "CollectionProduct",
    "Tag",
    "ProductTag",
    "WatchedFolder",
    "ProcessingQueue",
    "Setting",
    "ContributionQueue",
    "ContributionStatus",
    "ProductEmbedding",
    "Campaign",
    "Session",
    "RunNote",
    "ExclusionRule",
    "ExclusionRuleType",
    "DEFAULT_EXCLUSION_RULES",
    "ScanJob",
    "ScanJobStatus",
    "DeletedDuplicate",
]
