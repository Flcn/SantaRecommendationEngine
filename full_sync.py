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
        
        try:
            # Initialize database connections
            await db.init_pools()
            logger.info("✅ Database connections initialized")
            
            # Step 1: Clear old data
            await FullSyncManager._clear_old_data()
            
            # Step 2: Refresh popular items (ALL items)
            await FullSyncManager._full_popular_items_refresh()
            
            # Step 3: Create user profiles (ALL users)
            await FullSyncManager._full_user_profiles_sync()
            
            # Step 4: Build user similarities (ALL users)
            await FullSyncManager._full_user_similarities_sync()
            
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
            
            # Clear user similarities
            await db.execute_recommendations_command("DELETE FROM user_similarities")
            logger.info("   ✅ Cleared user_similarities table")
            
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
                LIMIT 10000
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
    async def _full_user_similarities_sync():
        """Build user similarities for ALL users"""
        logger.info("🤝 Step 4: Full user similarities synchronization...")
        start_time = time.time()
        
        try:
            # Get ALL users with interactions (no time constraint)
            all_users_query = """
                SELECT DISTINCT user_id
                FROM handpicked_likes
                ORDER BY user_id
                LIMIT 5000
            """
            
            all_users = await db.execute_main_query(all_users_query)
            logger.info(f"   👥 Building similarities for {len(all_users)} users")
            
            if not all_users:
                logger.info("   ℹ️ No users found for similarity computation")
                return
            
            # Process users in batches (smaller batches due to CROSS JOIN complexity)
            batch_size = 10  # Reduced from 100 to avoid timeout with 10x10=100 combinations
            total_similarities_created = 0
            for i in range(0, len(all_users), batch_size):
                batch = all_users[i:i+batch_size]
                user_ids = [str(u['user_id']) for u in batch]
                
                logger.info(f"   🔄 Processing similarity batch {i//batch_size + 1}/{(len(all_users) + batch_size - 1)//batch_size}")
                logger.info(f"      🔍 DEBUG: Batch contains {len(user_ids)} users")
                
                batch_start_time = time.time()
                try:
                    await FullSyncManager._compute_user_similarities_batch(user_ids)
                    batch_time = (time.time() - batch_start_time) * 1000
                    logger.info(f"      ✅ Batch completed in {batch_time:.2f}ms")
                except Exception as e:
                    batch_time = (time.time() - batch_start_time) * 1000
                    logger.error(f"      ❌ Batch failed after {batch_time:.2f}ms: {e}")
                    # Continue with next batch instead of failing completely
                    continue
            
            # Check final results
            count_query = "SELECT COUNT(*) as total FROM user_similarities"
            final_count = await db.execute_recommendations_query_one(count_query)
            logger.info(f"   📊 Final user_similarities count: {final_count['total'] if final_count else 0}")
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"✅ Step 4 completed in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"❌ Step 4 failed: {e}")
            raise
    
    @staticmethod
    async def _compute_user_similarities_batch(user_ids: List[str]):
        """Compute similarities for a batch of users"""
        try:
            logger.info(f"      🔍 DEBUG: Processing {len(user_ids)} users for similarities")
            logger.info(f"      🔍 DEBUG: User IDs sample: {user_ids[:3]}...")
            
            # Get user similarity data
            similarity_query = """
                WITH user_items AS (
                    SELECT user_id::text, array_agg(handpicked_present_id) as liked_items
                    FROM handpicked_likes
                    WHERE user_id::text = ANY($1::varchar[])
                    GROUP BY user_id
                ),
                similarities AS (
                    SELECT 
                        u1.user_id as user_id,
                        u2.user_id as similar_user_id,
                        array_length(array(SELECT unnest(u1.liked_items) INTERSECT SELECT unnest(u2.liked_items)), 1) as overlap
                    FROM user_items u1
                    CROSS JOIN user_items u2
                    WHERE u1.user_id != u2.user_id
                      AND array_length(array(SELECT unnest(u1.liked_items) INTERSECT SELECT unnest(u2.liked_items)), 1) >= 2
                )
                SELECT 
                    user_id,
                    similar_user_id,
                    overlap::float / GREATEST(20, overlap) as similarity_score
                FROM similarities
                ORDER BY user_id, similarity_score DESC
            """
            
            logger.info(f"      🔍 DEBUG: Executing similarity query for {len(user_ids)} users")
            start_time = time.time()
            similarities = await db.execute_main_query(similarity_query, user_ids)
            query_time = (time.time() - start_time) * 1000
            logger.info(f"      🔍 DEBUG: Query completed in {query_time:.2f}ms, found {len(similarities)} similarities")
            
            if similarities:
                logger.info(f"      🔍 DEBUG: Processing {len(similarities)} similarity records for insertion")
                # Build batch insert query
                values_list = []
                params = []
                param_count = 0
                
                for sim in similarities:
                    param_count += 3
                    values_list.append(f"(${param_count-2}, ${param_count-1}, ${param_count})")
                    params.extend([sim['user_id'], sim['similar_user_id'], sim['similarity_score']])
                
                if values_list:
                    insert_query = f"""
                        INSERT INTO user_similarities (user_id, similar_user_id, similarity_score)
                        VALUES {', '.join(values_list)}
                        ON CONFLICT (user_id, similar_user_id) DO UPDATE SET
                            similarity_score = EXCLUDED.similarity_score
                    """
                    
                    logger.info(f"      🔍 DEBUG: Executing insert query with {len(params)} parameters")
                    start_time = time.time()
                    await db.execute_recommendations_command(insert_query, *params)
                    insert_time = (time.time() - start_time) * 1000
                    logger.info(f"      🔍 DEBUG: Insert completed in {insert_time:.2f}ms")
            else:
                logger.info(f"      🔍 DEBUG: No similarities found for this batch")
            
        except Exception as e:
            import traceback
            logger.error(f"Error computing similarities batch: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            logger.error(f"User IDs that caused error: {user_ids}")
    
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