"""
Popularity-based recommendations
Returns trending and popular items based on user interactions
"""

import logging
from typing import List, Tuple, Optional
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)


class PopularityRecommender:
    """Popularity-based recommendation system"""
    
    @staticmethod
    async def get_popular_items(
        geo_id: int, 
        limit: int = 50,
        user_id: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Get popular items for a geographic region
        Uses time-weighted popularity: recent interactions count more
        """
        cache_key = f"popular_items:{geo_id}:{limit}"
        if user_id:
            cache_key += f":user_{user_id}"
        
        # Check cache first
        cached_result = db.cache_get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # Exclude user's liked items if user_id provided
            excluded_items = []
            if user_id:
                user_likes_query = """
                    SELECT handpicked_present_id 
                    FROM handpicked_likes 
                    WHERE user_id = $1
                """
                user_likes = await db.execute_query(user_likes_query, user_id)
                excluded_items = [row['handpicked_present_id'] for row in user_likes]
            
            # Get popular items with time-weighted scoring
            popularity_query = """
                SELECT 
                    hp.id as item_id,
                    COALESCE(click_scores.score, 0) + COALESCE(like_scores.score, 0) as total_score,
                    COALESCE(click_scores.recent_clicks, 0) as recent_clicks,
                    COALESCE(like_scores.recent_likes, 0) as recent_likes
                FROM handpicked_presents hp
                LEFT JOIN (
                    SELECT 
                        handpicked_present_id,
                        SUM(
                            CASE 
                                WHEN created_at > NOW() - INTERVAL '7 days' THEN 3.0
                                WHEN created_at > NOW() - INTERVAL '30 days' THEN 2.0
                                ELSE 1.0
                            END
                        ) as score,
                        COUNT(*) as recent_clicks
                    FROM handpicked_present_clicks 
                    WHERE created_at > NOW() - INTERVAL '90 days'
                    GROUP BY handpicked_present_id
                ) click_scores ON hp.id = click_scores.handpicked_present_id
                LEFT JOIN (
                    SELECT 
                        handpicked_present_id,
                        SUM(
                            CASE 
                                WHEN created_at > NOW() - INTERVAL '7 days' THEN 5.0
                                WHEN created_at > NOW() - INTERVAL '30 days' THEN 3.0
                                ELSE 1.5
                            END
                        ) as score,
                        COUNT(*) as recent_likes
                    FROM handpicked_likes 
                    WHERE created_at > NOW() - INTERVAL '90 days'
                    GROUP BY handpicked_present_id
                ) like_scores ON hp.id = like_scores.handpicked_present_id
                WHERE hp.geo_id = $1
                  AND hp.status = 'in_stock'
                  AND hp.user_id IS NULL
                  AND ($2::int[] IS NULL OR hp.id != ALL($2::int[]))
                ORDER BY total_score DESC, hp.created_at DESC
                LIMIT $3
            """
            
            results = await db.execute_query(
                popularity_query,
                geo_id,
                excluded_items if excluded_items else None,
                limit
            )
            
            # Convert to list of tuples (item_id, score)
            popular_items = [(row['item_id'], float(row['total_score'])) for row in results]
            
            # Cache result
            db.cache_set(cache_key, popular_items, settings.cache_ttl_popular)
            
            return popular_items
            
        except Exception as e:
            logger.error(f"Error getting popular items for geo {geo_id}: {e}")
            return []
    
    @staticmethod
    async def get_trending_items(
        geo_id: int, 
        limit: int = 20,
        days: int = 7
    ) -> List[Tuple[int, float]]:
        """
        Get trending items (items with rapidly increasing popularity)
        """
        cache_key = f"trending_items:{geo_id}:{limit}:{days}"
        
        cached_result = db.cache_get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            trending_query = """
                WITH recent_activity AS (
                    SELECT 
                        hp.id as item_id,
                        COUNT(DISTINCT hl.id) as recent_likes,
                        COUNT(DISTINCT hpc.id) as recent_clicks
                    FROM handpicked_presents hp
                    LEFT JOIN handpicked_likes hl ON hp.id = hl.handpicked_present_id 
                        AND hl.created_at > NOW() - INTERVAL '%s days'
                    LEFT JOIN handpicked_present_clicks hpc ON hp.id = hpc.handpicked_present_id 
                        AND hpc.created_at > NOW() - INTERVAL '%s days'
                    WHERE hp.geo_id = $1
                      AND hp.status = 'in_stock'
                      AND hp.user_id IS NULL
                      AND hp.created_at > NOW() - INTERVAL '30 days'  -- Only recent items can trend
                    GROUP BY hp.id
                ),
                historical_activity AS (
                    SELECT 
                        hp.id as item_id,
                        COUNT(DISTINCT hl.id) as historical_likes,
                        COUNT(DISTINCT hpc.id) as historical_clicks
                    FROM handpicked_presents hp
                    LEFT JOIN handpicked_likes hl ON hp.id = hl.handpicked_present_id 
                        AND hl.created_at BETWEEN NOW() - INTERVAL '30 days' AND NOW() - INTERVAL '%s days'
                    LEFT JOIN handpicked_present_clicks hpc ON hp.id = hpc.handpicked_present_id 
                        AND hpc.created_at BETWEEN NOW() - INTERVAL '30 days' AND NOW() - INTERVAL '%s days'
                    WHERE hp.geo_id = $1
                      AND hp.status = 'in_stock'
                      AND hp.user_id IS NULL
                    GROUP BY hp.id
                )
                SELECT 
                    ra.item_id,
                    ra.recent_likes + ra.recent_clicks as recent_total,
                    COALESCE(ha.historical_likes, 0) + COALESCE(ha.historical_clicks, 0) as historical_total,
                    CASE 
                        WHEN COALESCE(ha.historical_likes, 0) + COALESCE(ha.historical_clicks, 0) = 0 
                        THEN ra.recent_likes + ra.recent_clicks
                        ELSE (ra.recent_likes + ra.recent_clicks) / 
                             GREATEST(COALESCE(ha.historical_likes, 0) + COALESCE(ha.historical_clicks, 0), 1)
                    END as trend_score
                FROM recent_activity ra
                LEFT JOIN historical_activity ha ON ra.item_id = ha.item_id
                WHERE ra.recent_likes + ra.recent_clicks > 0
                ORDER BY trend_score DESC, recent_total DESC
                LIMIT $2
            """ % (days, days, days, days)
            
            results = await db.execute_query(trending_query, geo_id, limit)
            
            trending_items = [(row['item_id'], float(row['trend_score'])) for row in results]
            
            # Cache result for shorter time since trends change quickly
            db.cache_set(cache_key, trending_items, settings.cache_ttl_popular // 3)
            
            return trending_items
            
        except Exception as e:
            logger.error(f"Error getting trending items for geo {geo_id}: {e}")
            return []
    
    @staticmethod
    async def get_category_popular_items(
        geo_id: int,
        category: str,
        limit: int = 20
    ) -> List[Tuple[int, float]]:
        """Get popular items within a specific category"""
        cache_key = f"popular_category:{geo_id}:{category}:{limit}"
        
        cached_result = db.cache_get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            category_query = """
                SELECT 
                    hp.id as item_id,
                    COUNT(DISTINCT hl.id) * 2 + COUNT(DISTINCT hpc.id) as score
                FROM handpicked_presents hp
                LEFT JOIN handpicked_likes hl ON hp.id = hl.handpicked_present_id 
                    AND hl.created_at > NOW() - INTERVAL '60 days'
                LEFT JOIN handpicked_present_clicks hpc ON hp.id = hpc.handpicked_present_id 
                    AND hpc.created_at > NOW() - INTERVAL '60 days'
                WHERE hp.geo_id = $1
                  AND hp.status = 'in_stock'
                  AND hp.user_id IS NULL
                  AND hp.categories ->> 'category' = $2
                GROUP BY hp.id
                HAVING COUNT(DISTINCT hl.id) + COUNT(DISTINCT hpc.id) > 0
                ORDER BY score DESC
                LIMIT $3
            """
            
            results = await db.execute_query(category_query, geo_id, category, limit)
            
            category_items = [(row['item_id'], float(row['score'])) for row in results]
            
            db.cache_set(cache_key, category_items, settings.cache_ttl_popular)
            
            return category_items
            
        except Exception as e:
            logger.error(f"Error getting category popular items: {e}")
            return []