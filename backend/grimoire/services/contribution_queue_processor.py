"""Background processor for contribution queue with rate limiting."""

import asyncio
import logging
import time
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import ContributionQueue, ContributionStatus
from grimoire.services.contribution_service import submit_contribution
from grimoire.services.sync_service import get_codex_settings_from_db

logger = logging.getLogger(__name__)


class ContributionQueueProcessor:
    """
    Background processor for contribution queue with rate limiting.
    
    Respects Codex rate limits:
    - Burst: 30 per 5 minutes
    - Sustained: 60 per hour
    - Daily: 500 per day
    
    Default: 10 per minute (conservative, well under all limits)
    """
    
    def __init__(
        self,
        rate_per_minute: int = 10,
        max_retries: int = 3,
        idle_check_interval: int = 30,
    ):
        """
        Initialize the queue processor.
        
        Args:
            rate_per_minute: Maximum contributions per minute
            max_retries: Maximum retry attempts per contribution
            idle_check_interval: Seconds to wait when queue is empty
        """
        self.rate_per_minute = rate_per_minute
        self.min_interval = 60.0 / rate_per_minute
        self.max_retries = max_retries
        self.idle_check_interval = idle_check_interval
        self.last_send_time: float = 0
        self.is_running = False
        self._task: asyncio.Task | None = None
        
        # Statistics
        self.stats = {
            "submitted": 0,
            "failed": 0,
            "skipped": 0,
            "started_at": None,
        }
    
    async def start(self, db_session_factory) -> None:
        """
        Start background processing.
        
        Args:
            db_session_factory: Async context manager that yields AsyncSession
        """
        if self.is_running:
            logger.warning("Queue processor already running")
            return
        
        self.is_running = True
        self.stats["started_at"] = datetime.now(UTC)
        self._task = asyncio.create_task(
            self._process_loop(db_session_factory)
        )
        logger.info(f"Contribution queue processor started (rate: {self.rate_per_minute}/min)")
    
    def stop(self) -> None:
        """Stop background processing."""
        self.is_running = False
        if self._task:
            self._task.cancel()
        logger.info(
            f"Contribution queue processor stopped. "
            f"Stats: submitted={self.stats['submitted']}, "
            f"failed={self.stats['failed']}, skipped={self.stats['skipped']}"
        )
    
    def get_stats(self) -> dict:
        """Get current processing statistics."""
        return {
            **self.stats,
            "is_running": self.is_running,
            "rate_per_minute": self.rate_per_minute,
        }
    
    async def _process_loop(self, db_session_factory) -> None:
        """Main processing loop."""
        while self.is_running:
            try:
                async with db_session_factory() as db:
                    # Get pending contributions
                    pending = await self._get_pending_contributions(db)
                    
                    if not pending:
                        # No work to do - wait before checking again
                        await asyncio.sleep(self.idle_check_interval)
                        continue
                    
                    for contribution in pending:
                        if not self.is_running:
                            break
                        
                        # Skip if too many retries
                        if contribution.attempts >= self.max_retries:
                            self.stats["skipped"] += 1
                            continue
                        
                        # Rate limit - wait if needed
                        await self._wait_for_rate_limit()
                        
                        # Process the contribution
                        await self._process_one(db, contribution)
                        self.last_send_time = time.time()
                        
            except asyncio.CancelledError:
                logger.info("Queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Queue processor error: {e}", exc_info=True)
                # Back off on error before retrying
                await asyncio.sleep(60)
    
    async def _wait_for_rate_limit(self) -> None:
        """Wait if needed to respect rate limit."""
        if self.last_send_time == 0:
            return  # First request, no wait needed
        
        elapsed = time.time() - self.last_send_time
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
    
    async def _get_pending_contributions(
        self, 
        db: AsyncSession,
    ) -> list[ContributionQueue]:
        """Get pending contributions ordered by creation time."""
        query = (
            select(ContributionQueue)
            .where(ContributionQueue.status == ContributionStatus.PENDING)
            .where(ContributionQueue.attempts < self.max_retries)
            .order_by(ContributionQueue.created_at)
            .limit(50)  # Process in batches
        )
        result = await db.execute(query)
        return list(result.scalars().all())
    
    async def _process_one(
        self, 
        db: AsyncSession, 
        contribution: ContributionQueue,
    ) -> None:
        """Process a single contribution."""
        # Get API key from settings
        _, api_key = await get_codex_settings_from_db(db)
        
        if not api_key:
            logger.warning("No API key configured, pausing queue processing")
            await asyncio.sleep(300)  # Wait 5 minutes before checking again
            return
        
        try:
            success = await submit_contribution(db, contribution, api_key)
            
            if success:
                self.stats["submitted"] += 1
                logger.info(
                    f"Submitted contribution {contribution.id} "
                    f"(product_id={contribution.product_id})"
                )
            else:
                self.stats["failed"] += 1
                logger.warning(
                    f"Failed contribution {contribution.id}: "
                    f"{contribution.error_message}"
                )
        except Exception as e:
            self.stats["failed"] += 1
            logger.error(f"Error processing contribution {contribution.id}: {e}")


# Global processor instance
_processor: ContributionQueueProcessor | None = None


def get_queue_processor() -> ContributionQueueProcessor:
    """Get or create the global queue processor instance."""
    global _processor
    if _processor is None:
        _processor = ContributionQueueProcessor()
    return _processor


async def start_queue_processor(db_session_factory) -> None:
    """Start the global queue processor."""
    processor = get_queue_processor()
    await processor.start(db_session_factory)


def stop_queue_processor() -> None:
    """Stop the global queue processor."""
    global _processor
    if _processor:
        _processor.stop()
        _processor = None
