"""
FastAPI application for MySanta recommendation service
"""

import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import db
from app.models import (
    RecommendationRequest, 
    PopularItemsRequest, 
    RecommendationResponse,
    SimilarUsersRequest
)
from app.recommendation_service import RecommendationService

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting recommendation service...")
    await db.init_pool()
    logger.info("Recommendation service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down recommendation service...")
    await db.close()
    logger.info("Recommendation service shut down")


# Create FastAPI app
app = FastAPI(
    title="MySanta Recommendation Service",
    description="AI-powered gift recommendation engine for MySanta platform",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        await db.execute_query("SELECT 1")
        return {
            "status": "healthy",
            "service": "recommendation_engine",
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.post("/recommendations", response_model=RecommendationResponse)
async def get_recommendations(request: RecommendationRequest):
    """
    Get personalized recommendations for a user
    
    Uses hybrid approach:
    - Collaborative filtering (users with similar preferences)
    - Content-based filtering (item features matching user profile)
    - Popularity-based (trending items)
    
    Automatically filters by:
    - In-stock items only
    - Geographic region (geo_id)
    - Platform items only (user_id IS NULL)
    """
    try:
        logger.info(f"Getting recommendations for user {request.user_id}, geo {request.geo_id}")
        
        response = await RecommendationService.get_recommendations(request)
        
        logger.info(
            f"Returned {len(response.item_ids)} recommendations "
            f"(algorithm: {response.algorithm_used}, "
            f"time: {response.computation_time_ms:.2f}ms)"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/popular", response_model=RecommendationResponse)
async def get_popular_items(request: PopularItemsRequest):
    """
    Get popular/trending items for a geographic region
    
    Returns time-weighted popularity:
    - Recent interactions count more
    - Combines likes and clicks
    - Optionally personalized for specific user
    """
    try:
        logger.info(f"Getting popular items for geo {request.geo_id}")
        
        response = await RecommendationService.get_popular_items(request)
        
        logger.info(
            f"Returned {len(response.item_ids)} popular items "
            f"(time: {response.computation_time_ms:.2f}ms)"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting popular items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/similar-users")
async def get_similar_users(request: SimilarUsersRequest):
    """
    Find users with similar preferences to the given user
    
    Based on:
    - Item overlap (users who liked same items)
    - Demographic similarity
    """
    try:
        logger.info(f"Finding similar users for user {request.user_id}")
        
        similar_users = await RecommendationService.get_similar_users(
            request.user_id, 
            request.limit
        )
        
        logger.info(f"Found {len(similar_users)} similar users")
        
        return {
            "user_id": request.user_id,
            "similar_users": similar_users,
            "count": len(similar_users)
        }
        
    except Exception as e:
        logger.error(f"Error finding similar users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/similar-items/{item_id}")
async def get_similar_items(item_id: int, geo_id: int, limit: int = 20):
    """
    Find items similar to the given item
    
    Based on:
    - Category similarity
    - Price similarity  
    - Platform similarity
    """
    try:
        logger.info(f"Finding similar items for item {item_id}")
        
        similar_items = await RecommendationService.get_similar_items(
            item_id, 
            geo_id, 
            limit
        )
        
        logger.info(f"Found {len(similar_items)} similar items")
        
        return {
            "item_id": item_id,
            "similar_items": similar_items,
            "count": len(similar_items)
        }
        
    except Exception as e:
        logger.error(f"Error finding similar items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/user-profile/{user_id}")
async def get_user_profile(user_id: int):
    """
    Get user preference profile
    
    Returns:
    - Category preferences
    - Platform preferences  
    - Price range preferences
    - Interaction statistics
    """
    try:
        from app.algorithms.content_based import ContentBasedFilter
        
        logger.info(f"Getting profile for user {user_id}")
        
        profile = await ContentBasedFilter.get_user_profile(user_id)
        
        return {
            "user_id": user_id,
            "profile": profile
        }
        
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_service_stats():
    """Get service statistics and performance metrics"""
    try:
        # Get some basic stats
        stats_query = """
            SELECT 
                (SELECT COUNT(*) FROM handpicked_presents WHERE status = 'in_stock' AND user_id IS NULL) as total_items,
                (SELECT COUNT(*) FROM handpicked_likes) as total_likes,
                (SELECT COUNT(*) FROM handpicked_present_clicks) as total_clicks,
                (SELECT COUNT(DISTINCT user_id) FROM handpicked_likes) as active_users
        """
        
        stats = await db.execute_query_one(stats_query)
        
        return {
            "service": "recommendation_engine",
            "statistics": stats,
            "cache_info": {
                "redis_connected": db.redis_client is not None,
                "pool_size": db.pool._con._queue.qsize() if db.pool else 0
            },
            "configuration": {
                "max_similar_users": settings.max_similar_users,
                "max_recommendation_items": settings.max_recommendation_items,
                "similarity_min_overlap": settings.similarity_min_overlap
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level,
        reload=settings.debug
    )