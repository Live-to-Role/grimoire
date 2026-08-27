"""What Grimoire may share with Codex.

Codex is for identifications of content somebody can buy elsewhere —
adventures, sourcebooks, zines and other play aids. It is not for collections
of images, maps or tokens.

⚠️ This lives in its own module on purpose. It is drafted in `sync_service` in
the plan, but `sync_service` already imports `contribution_service` at module
level, so importing the predicate back from there would close a cycle — and
the codebase's habit of working around that with a function-local import is a
poor home for a guard whose whole job is to be unbypassable. A deferred import
is one refactor away from being deferred right past the call. A leaf module
both sides import has no such failure mode, and a file named for the rule is
harder to dismantle by accident than a helper among sync internals.
"""
import logging

from grimoire.models import Product

logger = logging.getLogger(__name__)

#: `product_type` values that describe a collection of images rather than a
#: document. Compared case-insensitively, since these are free text written by
#: several different code paths — the live library holds "Map", "Art/Maps",
#: "Stock Art", "Token" and "Portrait" among others.
#:
#: Deliberately *not* here: "Character Sheet", "Handout", "GM Tools". Those are
#: page-light but they are play aids, which is exactly what Codex is for.
IMAGE_PRODUCT_TYPES = frozenset({
    "map",
    "maps",
    "art/maps",
    "art / maps",
    "stock art",
    "token",
    "tokens",
    "portrait",
    "portraits",
})


def is_codex_eligible(product: Product) -> tuple[bool, str]:
    """Whether this product may be contributed to Codex.

    Outbound only. Reading *from* Codex — `sync_product_from_codex`,
    enrichment, identification — sends nothing upstream and stays enabled for
    every product regardless of what this returns.

    Returns `(eligible, reason)`, where the reason names the rule that
    refused so a caller can tell the user something specific.

    ⚠️ Missing here, and only because the column does not exist yet:
    `product.file_type != "pdf"`. **Codex is PDF-only, permanently** — the
    multi-format work extends what Grimoire catalogues, never what it shares.
    `file_type` arrives in Phase 2 of the multi-format plan, and that clause
    must land in the same commit as the column, or ahead of the generalised
    discovery that can create a non-PDF product. There is no window in which
    a non-PDF product may reach this queue.
    """
    if product.is_image_content:
        return False, "image_content"

    product_type = (product.product_type or "").strip().lower()
    if product_type in IMAGE_PRODUCT_TYPES:
        return False, "image_content"

    return True, "eligible"


def may_share_cover(product: Product) -> bool:
    """Whether this product's cover image may be uploaded to Codex.

    Separate from `is_codex_eligible`, which governs whether the product may
    be contributed at all. A scanned book is perfectly contributable — its
    title, publisher and year are facts about a published work — but its cover
    is the publisher's artwork, and for scans of uncertain provenance that is
    the part not to republish.
    """
    return not product.is_scanned
