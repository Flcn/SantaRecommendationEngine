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
├── handpicked_presents     # Original gift items
├── handpicked_likes        # User interactions
└── handpicked_present_clicks  # Click tracking

Recommendations Database (READ/WRITE)
├── popular_items          # Pre-computed popular gifts
├── user_similarities      # Collaborative filtering cache
└── user_profiles         # User preference profiles

Redis Database 1
└── Recommendation caching layer
```

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
# Build and run with Docker Compose
docker-compose up --build

# Run specific service
docker-compose up recommendation_engine

# View logs
docker-compose logs -f recommendation_engine

# Shell access
docker-compose exec recommendation_engine bash
```

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

- No authentication required (internal service)
- Input validation via Pydantic models
- SQL injection protection via parameterized queries
- Rate limiting should be implemented at nginx/load balancer level
- Sensitive data not logged or cached

This recommendation engine is designed for high performance, scalability, and reliability in the MySanta ecosystem.