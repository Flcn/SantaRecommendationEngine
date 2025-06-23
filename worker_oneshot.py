#!/usr/bin/env python3
"""
One-shot worker for MySanta Recommendation Engine
Runs all background jobs once and exits for testing/debugging
"""

import asyncio
import logging
import sys
from app.config import settings
from app.database import db
from app.background_jobs import BackgroundJobs

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def run_oneshot():
    """Run all background jobs once and exit"""
    logger.info("Starting MySanta Recommendation Engine Worker (One-shot mode)...")
    
    try:
        # Initialize database connections
        await db.init_pools()
        logger.info("✅ Database connections initialized")
        
        # Run each job once
        logger.info("🔄 Running background jobs once...")
        
        # 1. Clean up old data first
        logger.info("1️⃣ Running cache cleanup...")
        try:
            await BackgroundJobs.cleanup_old_data()
            logger.info("✅ Cache cleanup completed successfully")
        except Exception as e:
            logger.error(f"❌ Cache cleanup failed: {e}")
        
        # 2. Refresh popular items
        logger.info("2️⃣ Running popular items refresh...")
        try:
            await BackgroundJobs.refresh_popular_items()
            logger.info("✅ Popular items refresh completed successfully")
        except Exception as e:
            logger.error(f"❌ Popular items refresh failed: {e}")
        
        # 3. Update user profiles
        logger.info("3️⃣ Running user profiles update...")
        try:
            await BackgroundJobs.update_user_profiles()
            logger.info("✅ User profiles update completed successfully")
        except Exception as e:
            logger.error(f"❌ User profiles update failed: {e}")
        
        # 4. Update user similarities
        logger.info("4️⃣ Running user similarities update...")
        try:
            await BackgroundJobs.update_user_similarities()
            logger.info("✅ User similarities update completed successfully")
        except Exception as e:
            logger.error(f"❌ User similarities update failed: {e}")
        
        logger.info("🎉 All background jobs completed!")
        
    except Exception as e:
        logger.error(f"💥 Fatal error during worker execution: {e}")
        raise
    finally:
        # Clean up database connections
        try:
            await db.close()
            logger.info("🔒 Database connections closed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

async def main():
    """Main entry point"""
    try:
        await run_oneshot()
        logger.info("👋 Worker completed successfully, exiting...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Worker failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())