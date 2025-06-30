#!/usr/bin/env python3
"""
Simple sync script to test the core functionality
"""

import asyncio
import logging
from app.database import db
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def simple_sync():
    """Simple test sync"""
    try:
        await db.init_pools()
        logger.info("Database connected")
        
        # Clear popular items
        await db.execute_recommendations_command("DELETE FROM popular_items")
        logger.info("Cleared popular_items table")
        
        # Get just 5 items for testing
        query = """
            SELECT 
                hp.geo_id,
                COALESCE(hp.categories->>'gender', 'any') as gender,
                COALESCE(hp.categories->>'age', 'any') as age_group,
                COALESCE(hp.categories->>'category', 'any') as category,
                hp.id::text as item_id,
                3.0 as popularity_score
            FROM handpicked_presents hp
            WHERE hp.status = 'in_stock' AND hp.user_id IS NULL
            LIMIT 5
        """
        
        items = await db.execute_main_query(query)
        logger.info(f"Found {len(items)} items")
        
        # Insert them one by one
        insert_query = """
            INSERT INTO popular_items (geo_id, gender, age_group, category, item_id, popularity_score)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        
        for i, item in enumerate(items):
            logger.info(f"Inserting item {i}: {item['item_id']}")
            await db.execute_recommendations_command(
                insert_query,
                int(item['geo_id']),
                str(item['gender']),
                str(item['age_group']),
                str(item['category']),
                str(item['item_id']),
                float(item['popularity_score'])
            )
            logger.info(f"✅ Inserted item {i}")
        
        logger.info(f"🎉 Successfully inserted {len(items)} items!")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(simple_sync())