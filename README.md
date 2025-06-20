# MySanta Recommendation Engine

AI-powered recommendation service for the MySanta Secret Santa platform.

## Features

- **Hybrid Recommendations**: Combines collaborative filtering, content-based filtering, and popularity
- **Real-time Filtering**: Always returns in-stock items filtered by geographic region
- **Performance Optimized**: Sub-500ms response times with intelligent caching
- **Direct Database Access**: Efficient SQL queries with connection pooling
- **Scalable Architecture**: FastAPI with async support

## Algorithms

### 1. Collaborative Filtering
- Finds users with similar preferences (item overlap)
- Recommends items liked by similar users
- Minimum 2 item overlap required for similarity

### 2. Content-Based Filtering  
- Analyzes user preference profile from interaction history
- Scores items based on category, price, and platform similarity
- 40% category + 30% price + 20% platform + 10% recency weighting

### 3. Popularity-Based
- Time-weighted popularity scoring
- Recent interactions (7 days) get 3x weight
- Medium-term (30 days) get 2x weight
- Combines likes (higher weight) and clicks

### 4. Hybrid Approach
- **3+ interactions**: 50% collaborative + 30% content + 20% popular
- **1-2 interactions**: 70% content + 30% popular  
- **New users**: 100% popular items

## API Endpoints

### `POST /recommendations`
Get personalized recommendations for a user.

```json
{
  "user_id": 123,
  "geo_id": 213,
  "limit": 10,
  "offset": 0,
  "price_from": 500,
  "price_to": 2000,
  "gender": "f",
  "category": "electronics"
}
```

### `POST /popular`
Get popular/trending items for a region.

```json
{
  "geo_id": 213,
  "limit": 10,
  "offset": 0,
  "user_id": 123
}
```

### `GET /similar-items/{item_id}`
Find items similar to a given item.

### `POST /similar-users`
Find users with similar preferences.

### `GET /health`
Service health check.

## Configuration

Environment variables:

```bash
DATABASE_URL=postgresql://user:pass@host:port/db
REDIS_URL=redis://host:port
DEBUG=false
LOG_LEVEL=info
CACHE_TTL_SIMILARITY=14400      # 4 hours
CACHE_TTL_POPULAR=900           # 15 minutes  
CACHE_TTL_RECOMMENDATIONS=7200  # 2 hours
MAX_SIMILAR_USERS=50
MAX_RECOMMENDATION_ITEMS=200
SIMILARITY_MIN_OVERLAP=2
```

## Performance

- **Query Limits**: All queries use LIMIT clauses to prevent heavy operations
- **Connection Pooling**: 2-10 async database connections
- **Multi-level Caching**: Redis caching with different TTLs per data type
- **Efficient Indexes**: Assumes proper database indexes exist

Expected performance:
- **Cache Hit**: 10-20ms
- **Cache Miss**: 50-200ms  
- **Memory Usage**: ~20-50MB per worker
- **CPU Usage**: Low (mostly I/O bound)

## Integration with Rails

### Add to main docker-compose.yml:
```yaml
recommendation_engine:
  build: 
    context: SantaRecommendationEngine
  ports:
    - "8001:8000"
  environment:
    - DATABASE_URL=postgresql://postgres:password@db:5432/postgres
    - REDIS_URL=redis://redis:6379
  depends_on:
    - db
    - redis
```

### Rails Integration:
```ruby
class RecommendationClient
  BASE_URL = ENV.fetch('RECOMMENDATION_SERVICE_URL', 'http://localhost:8001')
  
  def self.get_recommendations(user_id:, geo_id:, **options)
    response = HTTP.post("#{BASE_URL}/recommendations", json: {
      user_id: user_id,
      geo_id: geo_id,
      **options
    })
    
    response.parse['item_ids']
  end
end
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run with Docker
docker-compose up --build

# Run tests (add pytest later)
pytest tests/
```

## Database Requirements

Required indexes for optimal performance:

```sql
-- Essential indexes
CREATE INDEX idx_handpicked_likes_user_present ON handpicked_likes(user_id, handpicked_present_id);
CREATE INDEX idx_handpicked_likes_present_user ON handpicked_likes(handpicked_present_id, user_id);
CREATE INDEX idx_handpicked_present_clicks_present_created ON handpicked_present_clicks(handpicked_present_id, created_at);
CREATE INDEX idx_handpicked_presents_geo_status_user ON handpicked_presents(geo_id, status, user_id);

-- For category filtering
CREATE INDEX idx_handpicked_presents_categories_gin ON handpicked_presents USING gin(categories);

-- Partial indexes for better performance
CREATE INDEX idx_handpicked_presents_in_stock ON handpicked_presents(geo_id, created_at) 
  WHERE status = 'in_stock' AND user_id IS NULL;
```

## Monitoring

Service exposes metrics at `/stats` endpoint:
- Total items, likes, clicks
- Active users count
- Cache connection status
- Configuration values

Add application monitoring and alerting as needed.