"""
Collaborative filtering algorithms
Finds users with similar preferences and recommends items they liked
"""

import logging
from typing import List, Dict, Tuple
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)


class CollaborativeFilter:
    """Collaborative filtering using user-item interactions"""
    
    @staticmethod
    async def find_similar_users(user_id: int, limit: int = None) -> List[int]:
        """
        Find users with similar item preferences
        Uses efficient query with limits to avoid heavy computation
        """
        limit = limit or settings.max_similar_users
        cache_key = f"similar_users:{user_id}"
        
        # Check cache first
        cached_result = db.cache_get(cache_key)
        if cached_result:
            return cached_result[:limit]
        
        try:
            # Get user's liked items (limit to recent ones for performance)
            user_likes_query = """
                SELECT handpicked_present_id 
                FROM handpicked_likes 
                WHERE user_id = $1 
                ORDER BY created_at DESC 
                LIMIT 20
            """
            user_likes = await db.execute_query(user_likes_query, user_id)
            
            if not user_likes:
                return []
            
            liked_item_ids = [row['handpicked_present_id'] for row in user_likes]
            
            # Find users who liked similar items
            similarity_query = """
                SELECT user_id, COUNT(*) as overlap_count
                FROM handpicked_likes 
                WHERE handpicked_present_id = ANY($1::int[])
                  AND user_id != $2
                GROUP BY user_id 
                HAVING COUNT(*) >= $3
                ORDER BY overlap_count DESC, user_id ASC
                LIMIT $4
            """
            
            similar_users = await db.execute_query(
                similarity_query, 
                liked_item_ids, 
                user_id,
                settings.similarity_min_overlap,
                limit
            )
            
            result = [row['user_id'] for row in similar_users]
            
            # Cache result
            db.cache_set(cache_key, result, settings.cache_ttl_similarity)
            
            return result
            
        except Exception as e:
            logger.error(f"Error finding similar users for {user_id}: {e}")
            return []
    
    @staticmethod
    async def get_collaborative_recommendations(
        user_id: int, 
        geo_id: int, 
        limit: int = 50
    ) -> List[Tuple[int, float]]:
        """
        Get recommendations based on similar users' preferences
        Returns list of (item_id, score) tuples
        """
        try:
            # Get similar users
            similar_users = await CollaborativeFilter.find_similar_users(user_id)
            
            if not similar_users:
                return []
            
            # Get user's already liked items to exclude
            user_likes_query = """
                SELECT handpicked_present_id 
                FROM handpicked_likes 
                WHERE user_id = $1
            """
            user_likes = await db.execute_query(user_likes_query, user_id)
            excluded_items = [row['handpicked_present_id'] for row in user_likes]
            
            # Get items liked by similar users
            recommendations_query = """
                SELECT 
                    hl.handpicked_present_id as item_id,
                    COUNT(*) as like_count,
                    COUNT(DISTINCT hl.user_id) as user_count
                FROM handpicked_likes hl
                JOIN handpicked_presents hp ON hl.handpicked_present_id = hp.id
                WHERE hl.user_id = ANY($1::int[])
                  AND hp.geo_id = $2
                  AND hp.status = 'in_stock'
                  AND hp.user_id IS NULL
                  AND ($3::int[] IS NULL OR hl.handpicked_present_id != ALL($3::int[]))
                GROUP BY hl.handpicked_present_id
                ORDER BY like_count DESC, user_count DESC
                LIMIT $4
            """
            
            recommendations = await db.execute_query(
                recommendations_query,
                similar_users,
                geo_id,
                excluded_items if excluded_items else None,
                limit
            )
            
            # Calculate scores (normalized by number of similar users)
            total_similar_users = len(similar_users)
            results = []
            
            for row in recommendations:
                # Score = (likes / total_similar_users) * confidence_boost
                score = (row['like_count'] / total_similar_users) * (row['user_count'] / total_similar_users)
                results.append((row['item_id'], score))
            
            return results
            
        except Exception as e:
            logger.error(f"Error getting collaborative recommendations for user {user_id}: {e}")
            return []
    
    @staticmethod
    async def get_user_interaction_count(user_id: int) -> int:
        """Get total number of user interactions"""
        try:
            query = """
                SELECT COUNT(*) as total
                FROM handpicked_likes 
                WHERE user_id = $1
            """
            result = await db.execute_query_one(query, user_id)
            return result['total'] if result else 0
        except Exception as e:
            logger.error(f"Error getting user interaction count: {e}")
            return 0