"""
Background jobs for data refresh and cache maintenance
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)


class BackgroundJobs:
    """Background job manager for data refresh"""
    
    @staticmethod
    async def refresh_popular_items():
        """
        Refresh popular items table every 15 minutes
        This is the core job that keeps popular recommendations up to date
        """
        try:
            logger.info("Starting popular items refresh...")
            start_time = time.time()
            
            # Query main database for popular items data (all-time scoring like full_sync)
            # Note: Rails uses UUIDs for IDs, so we need to convert to string
            popular_items_query = """
                SELECT 
                    hp.geo_id,
                    COALESCE(hp.categories->>'gender', 'any') as gender,
                    COALESCE(hp.categories->>'age', 'any') as age_group,
                    COALESCE(hp.categories->>'category', 'any') as category,
                    hp.id::text as item_id,  -- Convert UUID to string
                    
                    -- All-time popularity score (same as full_sync)
                    COALESCE(click_scores.score, 0) + COALESCE(like_scores.score, 0) as popularity_score
                    
                FROM handpicked_presents hp
                LEFT JOIN (
                    -- All-time click scores (simplified)
                    SELECT 
                        handpicked_present_id,
                        COUNT(*) * 1.0 as score
                    FROM handpicked_present_clicks 
                    GROUP BY handpicked_present_id
                ) click_scores ON hp.id = click_scores.handpicked_present_id
                LEFT JOIN (
                    -- All-time like scores (higher weight than clicks)
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
                LIMIT 10000
            """
            
            popular_items = await db.execute_main_query(popular_items_query)
            logger.info(f"Found {len(popular_items)} popular items from main database")
            
            # Clear old popular items from recommendations database
            await db.execute_recommendations_command(
                "DELETE FROM popular_items WHERE updated_at < NOW() - INTERVAL '1 hour'"
            )
            
            # Insert new popular items into recommendations database
            if popular_items:
                insert_values = []
                params = []
                param_count = 0
                
                for item in popular_items:
                    param_count += 6
                    insert_values.append(f"(${param_count-5}, ${param_count-4}, ${param_count-3}, ${param_count-2}, ${param_count-1}, ${param_count}, CURRENT_TIMESTAMP)")
                    params.extend([
                        item['geo_id'],
                        item['gender'],
                        item['age_group'], 
                        item['category'],
                        str(item['item_id']) if item['item_id'] else None,  # Keep UUID as string
                        float(item['popularity_score']) if item['popularity_score'] else 0.0
                    ])
                
                if insert_values:
                    insert_query = f"""
                        INSERT INTO popular_items (geo_id, gender, age_group, category, item_id, popularity_score, updated_at)
                        VALUES {', '.join(insert_values)}
                        ON CONFLICT DO NOTHING
                    """
                    
                    await db.execute_recommendations_command(insert_query, *params)
                    logger.info(f"Inserted {len(popular_items)} popular items into recommendations database")
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"Popular items refreshed successfully in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"Error refreshing popular items: {e}")
            raise
    
    @staticmethod
    async def update_user_profiles():
        """
        Update user profiles for users with new interactions
        This builds content-based recommendation profiles
        """
        try:
            logger.info("Starting user profiles update...")
            start_time = time.time()
            
            # Get users with new likes since last profile update
            # Check for users with recent activity but analyze their complete history
            recent_likes_query = """
                SELECT DISTINCT user_id, MAX(created_at) as latest_like, COUNT(*) as total_likes
                FROM handpicked_likes 
                WHERE created_at > NOW() - INTERVAL '7 days'
                GROUP BY user_id
                ORDER BY total_likes DESC
                LIMIT 1000
            """
            
            recent_users = await db.execute_main_query(recent_likes_query)
            
            if not recent_users:
                logger.info("No users with recent likes found")
                return
            
            # Then check which ones need profile updates from recommendations DB
            user_ids = [str(user['user_id']) for user in recent_users]
            existing_profiles_query = """
                SELECT user_id, updated_at
                FROM user_profiles 
                WHERE user_id = ANY($1::varchar[])
            """
            
            existing_profiles = await db.execute_recommendations_query(existing_profiles_query, user_ids)
            existing_profile_map = {profile['user_id']: profile['updated_at'] for profile in existing_profiles}
            
            # Determine which users need updates
            users_to_update = []
            for user in recent_users:
                user_id = user['user_id']
                latest_like = user['latest_like']
                
                # Update if no profile exists or profile is older than latest like
                if (user_id not in existing_profile_map or 
                    existing_profile_map[user_id] < latest_like):
                    users_to_update.append({'user_id': user_id})
            
            if not users_to_update:
                logger.info("No user profiles need updating")
                return
            
            logger.info(f"Updating profiles for {len(users_to_update)} users")
            
            for user_row in users_to_update:
                user_id = user_row['user_id']
                await BackgroundJobs._update_single_user_profile(user_id)
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"User profiles updated successfully in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"Error updating user profiles: {e}")
            raise
    
    @staticmethod
    async def _update_single_user_profile(user_id: int):
        """Update profile for a single user"""
        try:
            # Get user's ALL interaction data from main DB (same as full_sync)
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
                'buying_patterns': {
                    'target_ages': {},
                    'relationships': {},
                    'gender_targets': {}
                },
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
                        import json
                        categories = json.loads(categories)
                    except (json.JSONDecodeError, TypeError):
                        categories = {}
                elif categories is None:
                    categories = {}
                
                # Extract product category preferences (what they like)
                product_category = categories.get('category')
                if product_category and product_category != 'unknown':
                    profile['category_preferences'][product_category] = profile['category_preferences'].get(product_category, 0) + 1
                
                # Extract buying patterns (who they buy for)
                target_age = categories.get('age')
                if target_age and target_age != 'unknown':
                    profile['buying_patterns']['target_ages'][target_age] = profile['buying_patterns']['target_ages'].get(target_age, 0) + 1
                
                suitable_for = categories.get('suitable_for')
                if suitable_for and suitable_for != 'unknown':
                    profile['buying_patterns']['relationships'][suitable_for] = profile['buying_patterns']['relationships'].get(suitable_for, 0) + 1
                
                gender_target = categories.get('gender')
                if gender_target and gender_target != 'unknown':
                    profile['buying_patterns']['gender_targets'][gender_target] = profile['buying_patterns']['gender_targets'].get(gender_target, 0) + 1
                
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
            
            # Upsert user profile to recommendations DB (Option 3: with buying patterns)
            upsert_query = """
                INSERT INTO user_profiles 
                (user_id, preferred_categories, preferred_platforms, avg_price, 
                 price_range_min, price_range_max, buying_patterns_target_ages, 
                 buying_patterns_relationships, buying_patterns_gender_targets,
                 interaction_count, last_interaction_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    preferred_categories = EXCLUDED.preferred_categories,
                    preferred_platforms = EXCLUDED.preferred_platforms,
                    avg_price = EXCLUDED.avg_price,
                    price_range_min = EXCLUDED.price_range_min,
                    price_range_max = EXCLUDED.price_range_max,
                    buying_patterns_target_ages = EXCLUDED.buying_patterns_target_ages,
                    buying_patterns_relationships = EXCLUDED.buying_patterns_relationships,
                    buying_patterns_gender_targets = EXCLUDED.buying_patterns_gender_targets,
                    interaction_count = EXCLUDED.interaction_count,
                    last_interaction_at = EXCLUDED.last_interaction_at,
                    updated_at = EXCLUDED.updated_at
            """
            
            await db.execute_recommendations_command(
                upsert_query,
                str(user_id),  # Convert UUID to string
                json.dumps(profile['category_preferences']),  # Serialize to JSON string
                json.dumps(profile['platform_preferences']),  # Serialize to JSON string
                profile['price_range']['avg'],
                profile['price_range']['min'] if profile['price_range']['min'] != float('inf') else None,
                profile['price_range']['max'],
                json.dumps(profile['buying_patterns']['target_ages']),  # Option 3
                json.dumps(profile['buying_patterns']['relationships']),  # Option 3
                json.dumps(profile['buying_patterns']['gender_targets']),  # Option 3
                profile['interaction_count'],
                latest_interaction
            )
            
        except Exception as e:
            logger.error(f"Error updating profile for user {user_id}: {e}")
    
    @staticmethod
    async def update_user_similarities():
        """
        Update user similarity matrix for collaborative filtering
        Runs hourly for active users
        """
        try:
            logger.info("Starting user similarities update...")
            start_time = time.time()
            
            # Get active users (users with recent interactions)
            active_users_query = """
                SELECT DISTINCT user_id
                FROM handpicked_likes
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY user_id
                LIMIT 500
            """
            
            active_users = await db.execute_main_query(active_users_query)
            
            if not active_users:
                logger.info("No active users found for similarity update")
                return
            
            logger.info(f"Updating similarities for {len(active_users)} active users")
            
            # Process users in batches
            for i in range(0, len(active_users), 50):
                batch = active_users[i:i+50]
                await BackgroundJobs._update_user_similarities_batch([str(u['user_id']) for u in batch])
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"User similarities updated successfully in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"Error updating user similarities: {e}")
            raise
    
    @staticmethod
    async def _update_user_similarities_batch(user_ids: List[str]):
        """Update similarities for a batch of users"""
        try:
            # Get user similarity data from main DB
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
            
            similarities = await db.execute_main_query(similarity_query, user_ids)
            
            if not similarities:
                return
            
            # Batch insert similarities to recommendations DB
            await db.execute_recommendations_command("DELETE FROM user_similarities WHERE user_id = ANY($1::varchar[])", user_ids)
            
            if similarities:
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
                    """
                    
                    await db.execute_recommendations_command(insert_query, *params)
            
        except Exception as e:
            logger.error(f"Error updating similarities batch: {e}")
    
    @staticmethod
    async def update_item_similarities():
        """
        Update item similarities for items with new interactions (incremental)
        Only processes items that had new likes in the last 24 hours
        """
        try:
            logger.info("Starting incremental item similarities update...")
            start_time = time.time()
            
            # Get items that had new interactions in last 24 hours
            recent_items_query = """
                SELECT DISTINCT handpicked_present_id::text as item_id
                FROM handpicked_likes 
                WHERE created_at > NOW() - INTERVAL '24 hours'
                LIMIT 100
            """
            
            recent_items = await db.execute_main_query(recent_items_query)
            
            if not recent_items:
                logger.info("No items with recent interactions found")
                return
            
            item_ids = [item['item_id'] for item in recent_items]
            logger.info(f"Updating similarities for {len(item_ids)} items with recent activity")
            
            # Calculate similarities for these items (lighter version of full_sync logic)
            similarity_query = """
                WITH recent_item_pairs AS (
                    SELECT 
                        l1.handpicked_present_id::text as item_a,
                        l2.handpicked_present_id::text as item_b,
                        COUNT(*) as co_occurrence_count
                    FROM handpicked_likes l1
                    JOIN handpicked_likes l2 ON l1.user_id = l2.user_id
                    WHERE (l1.handpicked_present_id::text = ANY($1::varchar[]) OR l2.handpicked_present_id::text = ANY($1::varchar[]))
                      AND l1.handpicked_present_id != l2.handpicked_present_id
                      AND l1.handpicked_present_id::text < l2.handpicked_present_id::text
                    GROUP BY l1.handpicked_present_id, l2.handpicked_present_id
                    HAVING COUNT(*) >= 2  -- Minimum 2 users (lighter threshold)
                ),
                item_totals AS (
                    SELECT 
                        handpicked_present_id::text as item_id,
                        COUNT(*) as total_likes
                    FROM handpicked_likes
                    WHERE handpicked_present_id::text = ANY($1::varchar[])
                       OR handpicked_present_id IN (
                           SELECT DISTINCT l2.handpicked_present_id 
                           FROM handpicked_likes l1 
                           JOIN handpicked_likes l2 ON l1.user_id = l2.user_id 
                           WHERE l1.handpicked_present_id::text = ANY($1::varchar[])
                       )
                    GROUP BY handpicked_present_id
                )
                SELECT 
                    rip.item_a,
                    rip.item_b,
                    rip.co_occurrence_count,
                    it1.total_likes as item_a_total_likes,
                    it2.total_likes as item_b_total_likes,
                    rip.co_occurrence_count::float / (it1.total_likes + it2.total_likes - rip.co_occurrence_count) as similarity_score
                FROM recent_item_pairs rip
                JOIN item_totals it1 ON rip.item_a = it1.item_id
                JOIN item_totals it2 ON rip.item_b = it2.item_id
                WHERE rip.co_occurrence_count::float / (it1.total_likes + it2.total_likes - rip.co_occurrence_count) >= 0.05
                ORDER BY similarity_score DESC
                LIMIT 5000
            """
            
            similarities = await db.execute_main_query(similarity_query, item_ids)
            
            if similarities:
                # Remove old similarities for these items
                await db.execute_recommendations_command(
                    "DELETE FROM item_similarities WHERE item_a = ANY($1::varchar[]) OR item_b = ANY($1::varchar[])", 
                    item_ids
                )
                
                # Insert new similarities in batches
                insert_query = """
                    INSERT INTO item_similarities 
                    (item_a, item_b, similarity_score, co_occurrence_count, item_a_total_likes, item_b_total_likes, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                """
                
                inserted_count = 0
                for sim in similarities:
                    try:
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
                        
                    except Exception as e:
                        logger.warning(f"Failed to insert similarity: {e}")
                
                logger.info(f"Updated {inserted_count} item similarities")
            
            computation_time = (time.time() - start_time) * 1000
            logger.info(f"Item similarities updated successfully in {computation_time:.2f}ms")
            
        except Exception as e:
            logger.error(f"Error updating item similarities: {e}")

    @staticmethod
    async def cleanup_old_data():
        """Clean up old cache data"""
        try:
            logger.info("Starting cache cleanup...")
            await db.cleanup_cache_data()
            logger.info("Cache cleanup completed")
        except Exception as e:
            logger.error(f"Error in cache cleanup: {e}")


class JobScheduler:
    """Simple job scheduler for background tasks"""
    
    def __init__(self):
        self.running = False
    
    async def start(self):
        """Start the job scheduler"""
        self.running = True
        logger.info("Background job scheduler started")
        
        # Start concurrent job loops
        await asyncio.gather(
            self._popular_items_loop(),
            self._user_profiles_loop(),
            self._item_similarities_loop(),
            self._cleanup_loop()
        )
    
    def stop(self):
        """Stop the job scheduler"""
        self.running = False
        logger.info("Background job scheduler stopped")
    
    async def _popular_items_loop(self):
        """Run popular items refresh every 15 minutes"""
        while self.running:
            try:
                await BackgroundJobs.refresh_popular_items()
                await asyncio.sleep(settings.popular_items_refresh_minutes * 60)
            except Exception as e:
                logger.error(f"Error in popular items loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry
    
    async def _user_profiles_loop(self):
        """Run user profiles update every 30 minutes"""
        while self.running:
            try:
                await BackgroundJobs.update_user_profiles()
                await asyncio.sleep(30 * 60)  # 30 minutes
            except Exception as e:
                logger.error(f"Error in user profiles loop: {e}")
                await asyncio.sleep(60)
    
    
    async def _item_similarities_loop(self):
        """Run item similarities update every hour"""
        while self.running:
            try:
                await BackgroundJobs.update_item_similarities()
                await asyncio.sleep(60 * 60)  # 1 hour
            except Exception as e:
                logger.error(f"Error in item similarities loop: {e}")
                await asyncio.sleep(60)

    async def _cleanup_loop(self):
        """Run cleanup every 6 hours"""
        while self.running:
            try:
                await BackgroundJobs.cleanup_old_data()
                await asyncio.sleep(6 * 60 * 60)  # 6 hours
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60)


# Global job scheduler instance
job_scheduler = JobScheduler()