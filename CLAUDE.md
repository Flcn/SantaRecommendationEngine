# CLAUDE.md - MySanta Recommendation Engine

This file provides guidance to Claude Code when working with the MySanta Recommendation Engine.

## Project Overview

**MySanta Recommendation Engine** is a standalone FastAPI service that provides AI-powered gift recommendations for the MySanta Secret Santa platform. It uses a dual database architecture with intelligent caching for high-performance recommendations.

## Architecture

### Core Components
- **FastAPI Application** (`app/main.py`) - REST API endpoints
- **Recommendation Service** (`app/recommendation_service_v2.py`) - Core business logic
- **Database Manager** (`app/database.py`) - Dual database connections
- **Background Jobs** (`app/background_jobs.py`) - Data refresh tasks
- **Models** (`app/models.py`) - Pydantic request/response models

### Database Architecture
```
Main Database (READ-ONLY)
├── handpicked_presents     # Gift items (ONLY user_id IS NULL are recommendable)
├── handpicked_likes        # User interactions
└── handpicked_present_clicks  # Click tracking

Recommendations Database (READ/WRITE)
├── popular_items          # Pre-computed popular gifts
├── user_similarities      # Collaborative filtering cache
└── user_profiles         # User preference profiles

Redis Database 1
└── Recommendation caching layer
```

**IMPORTANT: Recommendable Items Policy**
- **Public Presents**: `handpicked_presents` where `user_id IS NULL` (~16k items)
  - These are curated public gift items that can be recommended to users
  - All recommendation algorithms MUST filter `WHERE user_id IS NULL`
- **User-Added Presents**: `handpicked_presents` where `user_id IS NOT NULL` (~436k items) 
  - These are presents added by individual users for their own use
  - These should NEVER be recommended to other users
  - They are excluded from all recommendation algorithms

## Two Core APIs

### 1. Popular Items API
```bash
POST /popular
```
**Purpose:** Get popular items based on user demographics
**Algorithm:** Pre-computed popularity by demographics + real-time filtering
**Use Case:** New users, demographic-based recommendations

### 2. Personalized Recommendations API  
```bash
POST /personalized
```
**Purpose:** Get personalized recommendations based on user's interaction history
**Algorithm:** Smart algorithm selection based on interaction count:
- 0 interactions: Popular items fallback
- 1-2 interactions: Content-based filtering
- 3+ interactions: Collaborative filtering
**Use Case:** Returning users with interaction history

## Development Commands

**IMPORTANT: Do not modify docker-compose.yaml or restart Docker containers unless explicitly requested by the user.**

### Code Deployment Workflow

**For Kubernetes Staging/Production deployments:**

1. **Make code changes** locally
2. **Commit and push to staging branch**:
   ```bash
   git add .
   git commit -m "Description of changes"
   git push origin staging
   ```
3. **Wait for CI/CD** to build and push image (`recommendation_engine:staging`)
4. **Deploy to staging** namespace:
   ```bash
   kubectl rollout restart deployment recommendation-engine-staging -n staging
   ```
5. **Test staging deployment**
6. **For production**: Push to `master` or `main` branch:
   ```bash
   git checkout main  # or master
   git merge staging
   git push origin main  # or master
   ```
7. **Wait for CI/CD** to build production image (`recommendation_engine:main`)
8. **Deploy to production**:
   ```bash
   kubectl rollout restart deployment recommendation-engine-production -n default
   ```

**DO NOT** manually restart pods without going through CI/CD pipeline for code changes.

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run service locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run with environment variables
MAIN_DATABASE_URL=postgresql://... uvicorn app.main:app --reload

# Access API documentation
# http://localhost:8000/docs
```

### Docker Development
```bash
# Build and run with Docker Compose (hot reload enabled)
docker-compose up --build

# Run specific service
docker-compose up recommendation_engine

# View logs
docker-compose logs -f recommendation_engine

# Shell access
docker-compose exec recommendation_engine bash

# Restart after docker-compose.yaml changes
docker-compose restart recommendation_engine

# Test new demographics sync API (Phase 1)
curl -u "mysanta_service:mysanta_rec_dev_2024_secure!" -X PUT \
  "http://localhost:8001/user-profile/USER_ID" \
  -H "Content-Type: application/json" \
  -d '{"gender": "male", "age_group": "25-34", "locale": "ru", "geo_id": 213}'
```

**Note: Hot reloading is now enabled! Code changes will automatically reload the FastAPI server without needing to restart the container.**

### Testing
```bash
# Run all tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_popular_items.py -v

# Run cache key tests only
python3 -m pytest -k "cache_key" -v

# Run with test runner
python run_tests.py

# Run specific test category
python run_tests.py popular_items
python run_tests.py personalized_recommendations
```

### Database Operations
```bash
# Setup recommendations database
createdb mysanta_recommendations

# Apply schema
psql mysanta_recommendations < schema.sql

# Manual data refresh (via API)
curl -X POST http://localhost:8000/admin/refresh-popular-items
curl -X POST http://localhost:8000/admin/update-user-profiles
```

## Configuration

### Environment Variables
```bash
# Database connections
MAIN_DATABASE_URL=postgresql://user:pass@host:5432/mysanta_main
RECOMMENDATIONS_DATABASE_URL=postgresql://user:pass@host:5432/mysanta_recommendations  
RECOMMENDATIONS_REDIS_URL=redis://host:6379/1

# Performance settings
MAX_SIMILAR_USERS=20
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100
POPULAR_ITEMS_REFRESH_MINUTES=15

# Cache TTL settings (seconds)
CACHE_TTL_POPULAR=900           # 15 minutes
CACHE_TTL_PERSONALIZED=7200     # 2 hours
CACHE_TTL_USER_PROFILE=14400    # 4 hours

# Service settings
DEBUG=false
LOG_LEVEL=info

# HTTP Basic Authentication
BASIC_AUTH_USERNAME=mysanta_service
BASIC_AUTH_PASSWORD=your_secure_password_here
```

### Key Configuration Files
- `app/config.py` - Application settings
- `pytest.ini` - Test configuration
- `docker-compose.yml` - Container orchestration
- `requirements.txt` - Python dependencies

## API Endpoints

### Core Recommendation APIs
- `POST /popular` - Get popular items by demographics
- `POST /personalized` - Get personalized recommendations

### Utility APIs
- `GET /health` - Service health check
- `GET /stats` - Service statistics and metrics
- `GET /user-profile/{user_id}` - Get user preference profile

### Admin APIs
- `POST /admin/refresh-popular-items` - Manual popular items refresh
- `POST /admin/update-user-profiles` - Manual user profiles update

### User Profile Sync API (NEW - Phase 1)
- `PUT /user-profile/{user_id}` - Sync user demographics from Rails for immediate targeting

## Request/Response Format

### Popular Items Request
```json
{
  "user_params": {
    "gender": "f",
    "age": "25-34", 
    "category": "electronics",
    "geo_id": 213
  },
  "filters": {
    "price_from": 500,
    "price_to": 2000
  },
  "pagination": {
    "page": 1,
    "limit": 20
  }
}
```

### Personalized Request
```json
{
  "user_id": 123,
  "geo_id": 213,
  "filters": {
    "price_from": 500,
    "price_to": 2000,
    "category": "electronics"
  },
  "pagination": {
    "page": 1,
    "limit": 20
  }
}
```

### User Demographics Sync Request (NEW - Phase 1)
```json
{
  "gender": "male",
  "age_group": "25-34",
  "locale": "ru", 
  "geo_id": 213
}
```

### Response Format
```json
{
  "items": [123, 456, 789],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total_pages": 15,
    "has_next": true,
    "has_previous": false
  },
  "computation_time_ms": 23.4,
  "algorithm_used": "collaborative",
  "cache_hit": true
}
```

## Background Jobs

### Automated Data Refresh
- **Popular Items**: Every 15 minutes via `refresh_popular_items()`
- **User Profiles**: Every 30 minutes via `update_user_profiles()`
- **User Similarities**: Every hour via `update_user_similarities()`
- **Cache Cleanup**: Every 6 hours via `cleanup_cache_data()`

### Job Management
Jobs run automatically when the service starts. Manual triggers available via admin APIs.

## Performance Characteristics

### Expected Performance
- **Response Time**: 20-50ms (cache hits), 50-200ms (cache miss)
- **Throughput**: 1,000+ requests per second
- **Memory Usage**: ~50MB per worker
- **Database Load**: 70% reduction vs direct queries

### Scaling Capacity
- **Current Scale**: 16k presents, 800k clicks, 600k likes
- **Target Scale**: 100k presents, 5M interactions
- **Concurrent Users**: 10k+ supported

## Integration with Rails

### Rails Client Setup
```ruby
# app/services/recommendation_client.rb
class RecommendationClient
  BASE_URL = ENV.fetch('RECOMMENDATION_SERVICE_URL', 'http://localhost:8001')
  
  def self.get_popular_items(user_params:, **options)
    response = HTTP.post("#{BASE_URL}/popular", json: {
      user_params: user_params,
      **options
    })
    response.parse
  end
  
  def self.get_personalized_recommendations(user_id:, geo_id:, **options)
    response = HTTP.post("#{BASE_URL}/personalized", json: {
      user_id: user_id,
      geo_id: geo_id,
      **options
    })
    response.parse
  end
end
```

### Docker Compose Integration
```yaml
# In main docker-compose.yml
recommendation_engine:
  build: 
    context: SantaRecommendationEngine
  ports:
    - "8001:8000"
  environment:
    - MAIN_DATABASE_URL=postgresql://postgres:password@db:5432/mysanta_main
    - RECOMMENDATIONS_DATABASE_URL=postgresql://postgres:password@db:5432/mysanta_recommendations
    - RECOMMENDATIONS_REDIS_URL=redis://redis:6379/1
  depends_on:
    - db
    - redis
```

## Monitoring and Health

### Health Checks
- `GET /health` - Tests both database connections
- `GET /stats` - Service metrics and performance data

### Key Metrics
- Total items, likes, clicks from main database
- Cached popular items count
- User profile statistics
- Cache hit rates
- Response times per algorithm

### Logging
- Structured logging with timestamps
- Request/response logging with computation times
- Error logging with stack traces
- Background job execution logs

## Development Patterns

### Adding New Features
1. **Add models** in `app/models.py` if needed
2. **Implement logic** in `app/recommendation_service_v2.py`
3. **Add endpoints** in `app/main.py`
4. **Write tests** in `tests/`
5. **Update documentation**

### Code Conventions
- Use `async/await` for all database operations
- Implement comprehensive error handling
- Add proper logging for debugging
- Follow existing cache key patterns
- Include unit tests for new functionality

### Database Best Practices
- Use `execute_main_query()` for read-only operations on main DB
- Use `execute_recommendations_query()` for recommendations DB operations
- Always apply LIMIT clauses to prevent heavy queries
- Cache expensive computations with appropriate TTL

### Testing Guidelines
- Mock all database calls using `AsyncMock`
- Test both success and error scenarios
- Validate cache key generation
- Test pagination edge cases
- Ensure fast test execution (<5 seconds total)

## Troubleshooting

### Common Issues
1. **Service not starting**: Check database connection strings
2. **Slow responses**: Verify cache hit rates and database indexes
3. **Empty recommendations**: Check if popular items are refreshed
4. **Test failures**: Ensure all dependencies installed and async config correct

### Debug Commands
```bash
# Check service health
curl http://localhost:8000/health

# View service statistics
curl http://localhost:8000/stats

# Trigger manual data refresh
curl -X POST http://localhost:8000/admin/refresh-popular-items

# View logs
docker-compose logs recommendation_engine

# Database connection test
python3 -c "from app.database import db; import asyncio; asyncio.run(db.init_pools())"
```

### Performance Tuning
- Monitor cache hit rates via `/stats`
- Adjust TTL values based on usage patterns
- Scale database connections if needed
- Add database indexes for new query patterns

## Security Considerations

- **HTTP Basic Authentication** required for all API endpoints (except /health)
- **Input validation** via Pydantic models
- **SQL injection protection** via parameterized queries
- **Rate limiting** should be implemented at nginx/load balancer level
- **Sensitive data** not logged or cached
- **CORS enabled** for frontend requests

## Multi-Service Integration

### MySanta Platform Architecture
This recommendation engine is part of a **microservices-based Secret Santa platform**:

```
MySanta Platform Services:
├── SecretSanta/                    # Main Rails application (web, API, admin)
├── SantaRecommendationEngine/      # This FastAPI service (NEW)
├── SantaPresentRecomendation/      # Legacy Flask recommendation service
├── Santa-telegram-bot/             # Ruby Telegram bot for game management
├── SantaML/                       # Machine learning components
├── RecommendationEngineUI/         # Node.js monitoring dashboard
├── Santa-public-pages/            # Static landing pages (Caddy)
└── Shared Infrastructure:
    ├── PostgreSQL (main + recommendations DBs)
    ├── Redis (caching + ActionCable)
    └── Docker Compose orchestration
```

### Service Communication
- **Rails ↔ Recommendation Engine**: HTTP API calls with Basic Auth
- **Internal Network**: `http://recommendation_engine:8000` (Docker service name)
- **External Access**: `http://localhost:8001` (development port mapping)
- **Background Jobs**: Independent processing via Solid Queue (Rails) + async workers (FastAPI)

### Integration Points
1. **Primary API Route**: `/handpicked_presents/to_like` (Rails) → `/personalized` (FastAPI)
2. **Popular Items**: Demographic-based recommendations for new users
3. **Collaborative Filtering**: User similarity-based recommendations for active users
4. **Real-time Filters**: Price, category, platform filtering with live inventory
5. **Mobile Apps**: Capacitor-based apps consume same API endpoints

## Critical Issues Fixed

### 1. UUID Type Casting Error (RESOLVED ✅)
**Problem:** `operator does not exist: uuid = integer` errors in collaborative filtering
**Root Cause:** Type mismatch between:
- `user_similarities` table: stores user IDs as `character varying` (strings)
- Main database tables: use `uuid` type for user_id and handpicked_present_id fields
- AsyncPG driver: returns UUID objects from database queries

**Solution Applied:**
```python
# Before (BROKEN):
WHERE hl.user_id = ANY($1::int[])

# After (FIXED):
WHERE hl.user_id::text = ANY($1::text[])
```

**Files Modified:**
- `app/recommendation_service_v2.py`: Fixed user_likes queries and collaborative filtering
- `app/algorithms/collaborative.py`: Updated array type casting
- `app/models.py`: Changed UserProfile.user_id from int to str

### 2. Hot Reload Development (ENHANCED ✅)
**Problem:** Manual container restarts required after every code change
**Solution Applied:**
- **Volume mounting**: `./SantaRecommendationEngine:/app` in docker-compose.yaml
- **Auto-reload**: `uvicorn --reload` flag in Dockerfile
- **Instant feedback**: Code changes automatically restart FastAPI server

### 3. JSON Parsing Issues (FIXED ✅)
**Problem:** User profile JSON fields stored as strings but expected as dictionaries
**Solution:** Added proper JSON parsing in `_get_user_profile()`:
```python
if isinstance(preferred_categories, str):
    preferred_categories = json.loads(preferred_categories)
```

## Performance Metrics (Real Data)

### Actual Production Stats
- **Active Users**: 896 user similarity records computed
- **User Interactions**: 33+ likes per active user (real user had 33 likes)
- **Similar Users**: 8+ similar users found per active user
- **Collaborative Results**: 100 recommendations generated from similar users
- **Filtering**: 77 items passed price filters (100-12000 range)
- **Response Time**: 59.52ms end-to-end (including filtering)
- **Algorithm Selection**: Successfully uses "collaborative" for users with 3+ interactions

### Cache Performance
- **Cache Keys**: Versioned with `v3:` prefix for safe invalidation
- **TTL Settings**: 5s (personalized, for testing), 900s (popular items)
- **Hit Rates**: ~70% reduction in database queries
- **Cache Miss Recovery**: 50-200ms for fresh data computation

### Database Load
- **Main DB Queries**: Read-only, optimized with proper indexes
- **Recommendations DB**: Lightweight cache tables with batch operations
- **Background Sync**: Periodic refresh without blocking API requests

## Deployment & Operations

### Container Configuration
```yaml
# docker-compose.yaml (main project)
recommendation_engine:
  build: 
    context: SantaRecommendationEngine
  ports:
    - "8001:8000"
  volumes:
    - ./SantaRecommendationEngine:/app  # Hot reload
  environment:
    - MAIN_DATABASE_URL=postgresql://postgres:...@db:5432/SecretSanta_development
    - RECOMMENDATIONS_DATABASE_URL=postgresql://postgres:...@db:5432/mysanta_recommendations
    - RECOMMENDATIONS_REDIS_URL=redis://redis:6379/5
    - BASIC_AUTH_USERNAME=mysanta_service
    - BASIC_AUTH_PASSWORD=mysanta_rec_dev_2024_secure!
  depends_on:
    - db
    - redis
```

### Background Workers
- **recommendation_worker**: Continuous data sync and cache refresh
- **recommendation_worker_oneshot**: One-time data migration tasks
- **Full Sync Script**: `python full_sync.py` for complete data rebuild

### Monitoring & Health
- **Health Endpoint**: Tests both main and recommendations database connections
- **Stats Endpoint**: Real-time metrics on cache performance and recommendation quality
- **Structured Logging**: JSON format with request tracing and performance metrics

## Future Development Notes

### Scaling Considerations
- **Stateless Design**: Ready for horizontal scaling with load balancers
- **Database Separation**: Main DB can scale independently from recommendations cache
- **Redis Clustering**: Cache layer can be distributed for high availability
- **Background Jobs**: Workers can run on separate containers/nodes

### Algorithm Improvements
- **Machine Learning Integration**: Ready for SantaML component integration
- **A/B Testing**: Algorithm selection can be feature-flagged
- **Real-time Learning**: User similarity computation can be incremental
- **Hybrid Approaches**: Content + collaborative filtering combination

## Phase 1: Real-time Demographics Integration (NEW - 2025-07-04)

### Overview
Phase 1 adds **immediate demographic targeting** for new users by syncing user profile data from Rails to the recommendation engine in real-time.

### Key Features
- **Instant Profile Sync**: Rails automatically syncs user demographics (gender, birthday, locale) on profile changes
- **Demographic Targeting**: New users get popular items targeted to their demographics instead of generic fallback
- **Intelligent Fallback**: Exact demographics → gender only → age only → generic popular items
- **Performance**: 4-hour cache TTL, non-blocking failures, ~16ms response times
- **Graceful Degradation**: Service failures don't affect user experience

### Implementation Details

#### Rails Integration
- **User Model Callbacks**: `after_update :sync_to_recommendation_engine, if: :recommendation_relevant_changes?`
- **Background Job**: `RecommendationSyncJob` handles async HTTP requests to recommendation engine
- **Error Handling**: Service downtime logged but doesn't block user flows

#### Recommendation Engine
- **New API Endpoint**: `PUT /user-profile/{user_id}` accepts demographic data
- **UserDemographicsUpdate Model**: Pydantic validation with gender normalization (male→m, female→f)
- **Enhanced Fallback Logic**: `_get_fallback_popular_items()` tries demographic-specific queries first
- **Redis Caching**: User demographics cached for 4 hours for fast lookups

#### Demographics Targeting Flow
1. **User updates profile** in Rails (gender/birthday/locale change)
2. **Model callback triggers** → `RecommendationSyncJob.perform_later(user.id)`
3. **Background job executes** → `RecommendationClient.sync_user_profile(...)`
4. **HTTP PUT request** → `/user-profile/{user_id}` with demographics
5. **Recommendation engine** caches demographics in Redis
6. **Next recommendation request** uses cached demographics for targeting

#### Fallback Chain Example
For a 25-34 male user:
1. Try: `gender=m AND age_group=25-34 AND category=any`
2. Try: `gender=m AND age_group=any AND category=any`
3. Try: `gender=any AND age_group=25-34 AND category=any`
4. Fallback: `gender=any AND age_group=any AND category=any`

### Benefits
- **Immediate Personalization**: New users get relevant recommendations from first visit
- **Better Engagement**: Demographic-targeted items increase interaction likelihood
- **Improved Conversion**: More relevant initial recommendations drive user activation
- **Scalable**: Works with existing infrastructure, minimal performance impact

### Testing
- ✅ API endpoint working with HTTP Basic Auth
- ✅ Demographics correctly cached in Redis
- ✅ Fallback chain working (demographic → generic)
- ✅ Non-blocking failures
- ✅ Performance: 16ms response times

This recommendation engine represents a modern, scalable approach to personalized recommendations in the MySanta ecosystem, replacing the legacy Flask service with improved performance, reliability, and developer experience.