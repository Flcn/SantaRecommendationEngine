"""
FastAPI application for MySanta recommendation service
"""

import logging
import asyncio
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.config import settings
from app.database import db
from app.models import (
    PopularItemsRequest, 
    PersonalizedRequest,
    RecommendationResponse,
    SimilarUsersRequest
)
from app.recommendation_service_v2 import RecommendationServiceV2

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Setup HTTP Basic Auth
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify HTTP Basic auth credentials"""
    correct_username = secrets.compare_digest(credentials.username, settings.basic_auth_username)
    correct_password = secrets.compare_digest(credentials.password, settings.basic_auth_password)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting recommendation service...")
    await db.init_pools()
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
        # Test both database connections
        await db.execute_main_query("SELECT 1")
        await db.execute_recommendations_query("SELECT 1")
        return {
            "status": "healthy",
            "service": "recommendation_engine_v2",
            "version": "2.0.0",
            "databases": ["main", "recommendations"]
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.post("/popular", response_model=RecommendationResponse)
async def get_popular_items(request: PopularItemsRequest, username: str = Depends(verify_credentials)):
    """
    Get popular items based on user demographics
    
    Takes user parameters (gender, age, category, geo) and finds 
    popular items matching those demographics.
    
    Uses pre-computed popular_items table for fast response.
    Applies real-time filters (price, category, etc.) from main DB.
    Excludes already liked items automatically.
    """
    try:
        logger.info(f"Getting popular items for geo {request.user_params.geo_id}, "
                   f"demographics: {request.user_params.gender}/{request.user_params.age}, "
                   f"page: {request.pagination.page}")
        
        response = await RecommendationServiceV2.get_popular_items(request)
        
        logger.info(
            f"Returned {len(response.items)} popular items "
            f"(algorithm: {response.algorithm_used}, "
            f"time: {response.computation_time_ms:.2f}ms, "
            f"cache_hit: {response.cache_hit})"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting popular items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/personalized", response_model=RecommendationResponse)
async def get_personalized_recommendations(request: PersonalizedRequest, username: str = Depends(verify_credentials)):
    """
    Get personalized recommendations based on user's likes
    
    Analyzes user's interaction history and finds suitable items:
    - Users with 3+ interactions: collaborative filtering
    - Users with 1-2 interactions: content-based filtering  
    - New users: popular items fallback
    
    Automatically excludes items user has already liked.
    Applies real-time filters (price, category, etc.).
    """
    try:
        logger.info(f"Getting personalized recommendations for user {request.user_id}, "
                   f"geo {request.geo_id}, page: {request.pagination.page}")
        
        response = await RecommendationServiceV2.get_personalized_recommendations(request)
        
        logger.info(
            f"Returned {len(response.items)} personalized items "
            f"(algorithm: {response.algorithm_used}, "
            f"time: {response.computation_time_ms:.2f}ms, "
            f"cache_hit: {response.cache_hit})"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting personalized recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/user-profile/{user_id}")
async def get_user_profile(user_id: int, username: str = Depends(verify_credentials)):
    """
    Get user preference profile from recommendations database
    
    Returns:
    - Category preferences
    - Platform preferences  
    - Price range preferences
    - Interaction statistics
    """
    try:
        logger.info(f"Getting profile for user {user_id}")
        
        # Get profile from recommendations DB
        query = """
            SELECT user_id, preferred_categories, preferred_platforms, 
                   avg_price, price_range_min, price_range_max,
                   interaction_count, last_interaction_at
            FROM user_profiles
            WHERE user_id = $1
        """
        
        profile = await db.execute_recommendations_query_one(query, user_id)
        
        if not profile:
            return {
                "user_id": user_id,
                "profile": None,
                "message": "Profile not found. User may be new or profile needs to be built."
            }
        
        return {
            "user_id": user_id,
            "profile": {
                "preferred_categories": profile['preferred_categories'],
                "preferred_platforms": profile['preferred_platforms'],
                "avg_price": profile['avg_price'],
                "price_range_min": profile['price_range_min'],
                "price_range_max": profile['price_range_max'],
                "interaction_count": profile['interaction_count'],
                "last_interaction_at": str(profile['last_interaction_at']) if profile['last_interaction_at'] else None
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_service_stats(username: str = Depends(verify_credentials)):
    """Get service statistics and performance metrics"""
    try:
        # Get stats from main database
        main_stats_query = """
            SELECT 
                (SELECT COUNT(*) FROM handpicked_presents WHERE status = 'in_stock' AND user_id IS NULL) as total_items,
                (SELECT COUNT(*) FROM handpicked_likes) as total_likes,
                (SELECT COUNT(*) FROM handpicked_present_clicks) as total_clicks,
                (SELECT COUNT(DISTINCT user_id) FROM handpicked_likes) as active_users
        """
        
        main_stats = await db.execute_main_query_one(main_stats_query)
        
        # Get stats from recommendations database
        rec_stats_query = """
            SELECT 
                COUNT(*) as cached_popular_items
            FROM popular_items
        """
        
        rec_stats = await db.execute_recommendations_query_one(rec_stats_query)
        
        # Get user profile stats
        profile_stats_query = """
            SELECT 
                COUNT(*) as cached_user_profiles,
                COUNT(*) FILTER (WHERE interaction_count >= 3) as users_with_collaborative,
                COUNT(*) FILTER (WHERE interaction_count BETWEEN 1 AND 2) as users_with_content_based
            FROM user_profiles
        """
        
        profile_stats = await db.execute_recommendations_query_one(profile_stats_query)
        
        return {
            "service": "recommendation_engine_v2",
            "version": "2.0.0",
            "main_database": main_stats,
            "recommendations_database": {
                **rec_stats,
                **profile_stats
            },
            "cache_info": {
                "redis_connected": db.redis_client is not None
            },
            "configuration": {
                "max_similar_users": settings.max_similar_users,
                "default_page_size": settings.default_page_size,
                "max_page_size": settings.max_page_size,
                "popular_items_refresh_minutes": settings.popular_items_refresh_minutes
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/refresh-popular-items")
async def manual_refresh_popular_items(username: str = Depends(verify_credentials)):
    """Manually trigger popular items refresh (admin endpoint)"""
    try:
        logger.info("Manual popular items refresh triggered")
        
        from app.background_jobs import BackgroundJobs
        await BackgroundJobs.refresh_popular_items()
        
        return {
            "status": "success",
            "message": "Popular items refreshed successfully"
        }
        
    except Exception as e:
        logger.error(f"Error in manual refresh: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/update-user-profiles")
async def manual_update_user_profiles():
    """Manually trigger user profiles update (admin endpoint)"""
    try:
        logger.info("Manual user profiles update triggered")
        
        from app.background_jobs import BackgroundJobs
        await BackgroundJobs.update_user_profiles()
        
        return {
            "status": "success",
            "message": "User profiles updated successfully"
        }
        
    except Exception as e:
        logger.error(f"Error in manual user profiles update: {e}")
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