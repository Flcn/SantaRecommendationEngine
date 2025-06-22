#!/usr/bin/env python3
"""
Background worker for MySanta Recommendation Engine
Runs scheduled jobs to populate recommendations database
"""

import asyncio
import logging
import signal
import sys
from app.config import settings
from app.database import db
from app.background_jobs import job_scheduler

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WorkerManager:
    def __init__(self):
        self.running = False
        self.scheduler_task = None

    async def start(self):
        """Start the background worker"""
        logger.info("Starting MySanta Recommendation Engine Worker...")
        
        try:
            # Initialize database connections
            await db.init_pools()
            logger.info("Database connections initialized")
            
            # Start job scheduler
            self.running = True
            self.scheduler_task = asyncio.create_task(job_scheduler.start())
            logger.info("Background job scheduler started")
            
            # Wait for scheduler to complete (runs indefinitely)
            await self.scheduler_task
            
        except Exception as e:
            logger.error(f"Error starting worker: {e}")
            raise
        finally:
            await self.cleanup()

    async def stop(self):
        """Stop the background worker"""
        logger.info("Stopping background worker...")
        
        self.running = False
        job_scheduler.stop()
        
        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                logger.info("Background job scheduler stopped")

    async def cleanup(self):
        """Clean up resources"""
        try:
            await db.close()
            logger.info("Database connections closed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# Global worker instance
worker = WorkerManager()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    asyncio.create_task(worker.stop())

async def main():
    """Main worker entry point"""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        await worker.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        sys.exit(1)
    finally:
        await worker.stop()

if __name__ == "__main__":
    asyncio.run(main())