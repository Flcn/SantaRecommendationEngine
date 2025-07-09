#!/usr/bin/env python3
"""
Full sync script for MySanta Recommendation Engine
Run this script during deployment to fully populate recommendations database

This script:
1. Refreshes ALL popular items (regardless of time constraints)
2. Creates user profiles for ALL users with any interactions
3. Builds user similarities for ALL active users
4. Clears old cache data

Usage:
    python full_sync.py
    
    # Or with Docker:
    docker-compose exec recommendation_engine python full_sync.py
"""

import asyncio
import logging
import time
import json
import traceback
from datetime import datetime
from typing import Dict, List, Any
from app.config import settings
from app.database import db

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FullSyncManager:
    """Manages full synchronization of recommendations data"""
    
    @staticmethod
    async def run_full_sync():
        """Execute complete data synchronization"""
        start_time = time.time()
        logger.info("🚀 Starting FULL SYNC for MySanta Recommendation Engine")
        logger.info("=" * 60)
        
        # Print current timeout configuration
        logger.info(f"⏱️  Current timeout settings:")
        logger.info(f"   MAX_QUERY_TIME: {settings.max_query_time} seconds")
        logger.info(f"   FULL_SYNC_QUERY_TIMEOUT: {settings.full_sync_query_timeout} seconds")
        logger.info("=" * 60)
        
        try:
            # Initialize database connections
            await db.init_pools()
            logger.info("✅ Database connections initialized")
            
            # Step 1: Build item similarities FIRST (was causing timeout)
            logger.info("🔗 Starting with item similarity matrix step (reordered)...")
            await FullSyncManager._build_item_similarity_matrix()
            
            # Step 2: Clear old data
            await FullSyncManager._clear_old_data()
            
            # Step 3: Refresh popular items (ALL items)
            await FullSyncManager._full_popular_items_refresh()
            
            # Step 4: Create user profiles (ALL users)
            await FullSyncManager._full_user_profiles_sync()
            
            # Step 5: Cache cleanup
            await FullSyncManager._cleanup_cache()
            
            total_time = (time.time() - start_time)
            logger.info("=" * 60)
            logger.info(f"🎉 FULL SYNC COMPLETED SUCCESSFULLY in {total_time:.2f} seconds")
            logger.info("Recommendation engine is ready for production!")
            
        except Exception as e:
            logger.error(f"❌ FULL SYNC FAILED: {type(e).__name__}: {e}")
            logger.error("Full traceback:")
            logger.error(traceback.format_exc())
            raise
        finally:
            await db.close()
    
    @staticmethod
    async def _clear_old_data():
        """Clear old recommendations data"""
        logger.info("🧹 Step 1: Clearing old recommendations data...")
        
        try:
            # Clear popular items
            await db.execute_recommendations_command("DELETE FROM popular_items")
            logger.info("   ✅ Cleared popular_items table")
            
            # Clear user profiles  
            await db.execute_recommendations_command("DELETE FROM user_profiles")
            logger.info("   ✅ Cleared user_profiles table")
            
            # Clear item similarities (NEW)
            await db.execute_recommendations_command("DELETE FROM item_similarities")
            logger.info("   ✅ Cleared item_similarities table")
            
            logger.info("✅ Step 1 completed: Old data cleared")
            
        except Exception as e:
            logger.error(f"❌ Step 1 failed: {e}")
            raise
    
    @staticmethod
    async def _full_popular_items_refresh():
        """Refresh ALL popular items without time constraints"""
        logger.info("📈 Step 2: Full popular items refresh...")
        start_time = time.time()
        
        try:
            # Query ALL popular items (remove time constraints)
            popular_items_query = """
                SELECT 
                    hp.geo_id,
                    COALESCE(hp.categories->>'gender', 'any') as gender,
                    COALESCE(hp.categories->>'age', 'any') as age_group,
                    COALESCE(hp.categories->>'category', 'any') as category,
                    hp.id::text as item_id,
                    
                    -- Popularity score (all time, not time-weighted)
                    COALESCE(click_scores.score, 0) + COALESCE(like_scores.score, 0) as popularity_score
                    
                FROM handpicked_presents hp
                LEFT JOIN (
                    -- All-time click scores
                    SELECT 
                        handpicked_present_id,
                        COUNT(*) * 1.0 as score
                    FROM handpicked_present_clicks 
                    GROUP BY handpicked_present_id
                ) click_scores ON hp.id = click_scores.handpicked_present_id
                LEFT JOIN (
                    -- All-time like scores (higher weight)
                    SELECT 
                        handpicked_present_id,
                        COUNT(*) * 3.0 as score
                    FROM handpicked_likes 
                    GROUP BY handpicked_present_id
                ) like_scores ON hp.id = like_scores.handpicked_present_id

                WHERE hp.status = 'in_stock' 
                  AND hp.user_id IS NULL
                  AND (COALESCE(click_scores.score, 0) + COALESCE(like_scores.score, 0)) > 0
                ORDER BY popularity_score DESC
                LIMIT 50000
            """
            
            popular_items = await db.execute_main_query(popular_items_query)
            logger.info(f"   📊 Found {len(popular_items)} popular items from main database")
            
            # Insert into recommendations database
            if popular_items:
                insert_query = """
                    INSERT INTO popular_items (geo_id, gender, age_group, category, item_id, popularity_score, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                """
                
                inserted_count = 0
                for i, item in enumerate(popular_items):
                    try:
                        # Debug first few items
                        if i < 3:
                            logger.info(f"   🔍 Item {i}: {item}")
                            logger.info(f"   🔍 Types: geo_id={type(item['geo_id'])}, gender={type(item['gender'])}, item_id={type(item['item_id'])}, score={type(item['popularity_score'])}")
                        
                        await db.execute_recommendations_command(
                            insert_query,
                            int(item['geo_id']),
                            str(item['gender']),
                            str(item['age_group']), 
                            str(item['category']),
                            str(item['item_id']),
                            float(item['popularity_score']) if item['popularity_score'] is not None else 0.0
                        )
                        inserted_count += 1
                        
                        if inserted_count % 100 == 0:
                            logger.info(f"   📈 Inserted {inserted_count} items...")
                            
                    except Exception as e:
                        logger.warning(f"   ⚠️ Failed to insert item {i} ({item.get('item_id', 'unknown')}): {e}")
                        logger.warning(f"   🔍 Item data: {item}")
                
                logger.info(f"   ✅ Inserted {inserted_count} popular items into recommendations database")
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"✅ Step 2 completed in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"❌ Step 2 failed: {type(e).__name__}: {e}")
            logger.error("Full traceback:")
            logger.error(traceback.format_exc())
            raise
    
    @staticmethod
    async def _full_user_profiles_sync():
        """Create user profiles for ALL users with any interactions"""
        logger.info("👥 Step 3: Full user profiles synchronization...")
        start_time = time.time()
        
        try:
            # Get ALL users with ANY likes (no time constraint)
            all_users_query = """
                SELECT DISTINCT user_id, MAX(created_at) as latest_like, COUNT(*) as total_likes
                FROM handpicked_likes 
                GROUP BY user_id
                HAVING COUNT(*) >= 1
                ORDER BY total_likes DESC
            """
            
            all_users = await db.execute_main_query(all_users_query)
            logger.info(f"   👤 Found {len(all_users)} users with interactions")
            
            if not all_users:
                logger.info("   ℹ️ No users with interactions found")
                return
            
            # Process users in batches
            batch_size = 100
            processed_count = 0
            
            for i in range(0, len(all_users), batch_size):
                batch = all_users[i:i+batch_size]
                logger.info(f"   🔄 Processing user batch {i//batch_size + 1}/{(len(all_users) + batch_size - 1)//batch_size}")
                
                for user_row in batch:
                    user_id = user_row['user_id']
                    try:
                        await FullSyncManager._create_single_user_profile(user_id)
                        processed_count += 1
                    except Exception as e:
                        logger.warning(f"   ⚠️ Failed to create profile for user {user_id}: {e}")
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"   ✅ Created {processed_count} user profiles")
            logger.info(f"✅ Step 3 completed in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"❌ Step 3 failed: {e}")
            raise
    
    @staticmethod
    async def _create_single_user_profile(user_id: str):
        """Create profile for a single user"""
        # Get user's ALL interaction data (no time limit)
        profile_query = """
            SELECT 
                hp.categories,
                hp.price,
                hp.platform,
                hl.created_at as interaction_date
            FROM handpicked_likes hl
            JOIN handpicked_presents hp ON hl.handpicked_present_id = hp.id
            WHERE hl.user_id = $1
            ORDER BY hl.created_at DESC
            LIMIT 1000
        """
        
        interactions = await db.execute_main_query(profile_query, user_id)
        
        if not interactions:
            return
        
        # Build preference profile
        profile = {
            'category_preferences': {},
            'platform_preferences': {},
            'price_range': {'min': float('inf'), 'max': 0, 'avg': 0},
            'interaction_count': len(interactions)
        }
        
        total_price = 0
        valid_prices = 0
        
        for interaction in interactions:
            categories = interaction.get('categories', {})
            price = interaction.get('price', 0)
            platform = interaction.get('platform', '')
            
            # Parse categories if it's a JSON string
            if isinstance(categories, str):
                try:
                    categories = json.loads(categories)
                except (json.JSONDecodeError, TypeError):
                    categories = {}
            elif categories is None:
                categories = {}
            
            # Category preferences
            for cat_type, cat_value in categories.items():
                if cat_value and cat_type != 'unknown':
                    key = f"{cat_type}:{cat_value}"
                    profile['category_preferences'][key] = profile['category_preferences'].get(key, 0) + 1
            
            # Platform preferences
            if platform:
                profile['platform_preferences'][platform] = profile['platform_preferences'].get(platform, 0) + 1
            
            # Price preferences
            if price and price > 0:
                profile['price_range']['min'] = min(profile['price_range']['min'], price)
                profile['price_range']['max'] = max(profile['price_range']['max'], price)
                total_price += price
                valid_prices += 1
        
        # Calculate average price
        if valid_prices > 0:
            profile['price_range']['avg'] = total_price / valid_prices
        else:
            profile['price_range'] = {'min': 0, 'max': 0, 'avg': 0}
        
        # Normalize preference counts to percentages
        total_category_prefs = sum(profile['category_preferences'].values())
        if total_category_prefs > 0:
            for key in profile['category_preferences']:
                profile['category_preferences'][key] /= total_category_prefs
        
        total_platform_prefs = sum(profile['platform_preferences'].values())
        if total_platform_prefs > 0:
            for key in profile['platform_preferences']:
                profile['platform_preferences'][key] /= total_platform_prefs
        
        # Get latest interaction timestamp
        latest_interaction = interactions[0]['interaction_date'] if interactions else None
        
        # Insert user profile
        upsert_query = """
            INSERT INTO user_profiles 
            (user_id, preferred_categories, preferred_platforms, avg_price, 
             price_range_min, price_range_max, interaction_count, last_interaction_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                preferred_categories = EXCLUDED.preferred_categories,
                preferred_platforms = EXCLUDED.preferred_platforms,
                avg_price = EXCLUDED.avg_price,
                price_range_min = EXCLUDED.price_range_min,
                price_range_max = EXCLUDED.price_range_max,
                interaction_count = EXCLUDED.interaction_count,
                last_interaction_at = EXCLUDED.last_interaction_at,
                updated_at = EXCLUDED.updated_at
        """
        
        await db.execute_recommendations_command(
            upsert_query,
            str(user_id),
            json.dumps(profile['category_preferences']),
            json.dumps(profile['platform_preferences']),
            profile['price_range']['avg'],
            profile['price_range']['min'] if profile['price_range']['min'] != float('inf') else None,
            profile['price_range']['max'],
            profile['interaction_count'],
            latest_interaction
        )
    
    @staticmethod
    async def _build_item_similarity_matrix():
        """Build item-to-item similarity matrix"""
        logger.info("🔗 Step 4: Building item-to-item similarity matrix...")
        start_time = time.time()
        
        try:
            # Calculate item-to-item similarities using Jaccard similarity
            item_similarity_query = """
                WITH item_pairs AS (
                    SELECT 
                        l1.handpicked_present_id::text as item_a,
                        l2.handpicked_present_id::text as item_b,
                        COUNT(*) as co_occurrence_count
                    FROM handpicked_likes l1
                    JOIN handpicked_likes l2 ON l1.user_id = l2.user_id
                    WHERE l1.handpicked_present_id != l2.handpicked_present_id
                      AND l1.handpicked_present_id::text < l2.handpicked_present_id::text  -- Avoid duplicates
                    GROUP BY l1.handpicked_present_id, l2.handpicked_present_id
                    HAVING COUNT(*) >= 3  -- Minimum 3 users must like both items
                ),
                item_totals AS (
                    SELECT 
                        handpicked_present_id::text as item_id,
                        COUNT(*) as total_likes
                    FROM handpicked_likes
                    GROUP BY handpicked_present_id
                )
                SELECT 
                    ip.item_a,
                    ip.item_b,
                    ip.co_occurrence_count,
                    it1.total_likes as item_a_total_likes,
                    it2.total_likes as item_b_total_likes,
                    -- Jaccard similarity: intersection / union
                    ip.co_occurrence_count::float / (it1.total_likes + it2.total_likes - ip.co_occurrence_count) as similarity_score
                FROM item_pairs ip
                JOIN item_totals it1 ON ip.item_a = it1.item_id
                JOIN item_totals it2 ON ip.item_b = it2.item_id
                WHERE ip.co_occurrence_count::float / (it1.total_likes + it2.total_likes - ip.co_occurrence_count) >= 0.1  -- 10% minimum similarity
                ORDER BY similarity_score DESC
                LIMIT 100000  -- Limit to top 100k similarities
            """
            
            logger.info("   🔍 Executing item similarity calculation...")
            similarities = await db.execute_main_query(item_similarity_query, use_full_sync_timeout=True)
            logger.info(f"   📊 Found {len(similarities)} item similarities")
            
            # Insert item similarities
            if similarities:
                insert_query = """
                    INSERT INTO item_similarities 
                    (item_a, item_b, similarity_score, co_occurrence_count, item_a_total_likes, item_b_total_likes, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                """
                
                inserted_count = 0
                for i, sim in enumerate(similarities):
                    try:
                        # Debug first few similarities
                        if i < 3:
                            logger.info(f"   🔍 Similarity {i}: {sim}")
                        
                        await db.execute_recommendations_command(
                            insert_query,
                            str(sim['item_a']),
                            str(sim['item_b']),
                            float(sim['similarity_score']),
                            int(sim['co_occurrence_count']),
                            int(sim['item_a_total_likes']),
                            int(sim['item_b_total_likes'])
                        )
                        inserted_count += 1
                        
                        if inserted_count % 1000 == 0:
                            logger.info(f"   📈 Inserted {inserted_count} similarities...")
                            
                    except Exception as e:
                        logger.warning(f"   ⚠️ Failed to insert similarity {i}: {e}")
                        logger.warning(f"   🔍 Similarity data: {sim}")
                
                logger.info(f"   ✅ Inserted {inserted_count} item similarities")
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"✅ Step 4 completed in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"❌ Step 4 failed: {e}")
            raise
    
    
    @staticmethod
    async def _cleanup_cache():
        """Clean up cache data"""
        logger.info("🧽 Step 5: Cache cleanup...")
        
        try:
            await db.cleanup_cache_data()
            logger.info("✅ Step 5 completed: Cache cleaned up")
        except Exception as e:
            logger.error(f"❌ Step 5 failed: {e}")
            raise


async def main():
    """Main entry point"""
    try:
        await FullSyncManager.run_full_sync()
        print("\n🎉 Full sync completed successfully!")
        print("The recommendation engine is now ready for production.")
        
    except KeyboardInterrupt:
        logger.info("❌ Full sync interrupted by user")
    except Exception as e:
        logger.error(f"❌ Full sync failed: {e}")
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())