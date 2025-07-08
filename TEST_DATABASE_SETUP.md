# Test Database Setup

This document explains how to run tests with database cleanup and seeding.

## Overview

The recommendation engine tests can run in two modes:

1. **Mock Mode (default)**: All database calls are mocked using `unittest.mock`
2. **Real Database Mode**: Tests run against actual PostgreSQL and Redis databases with automatic cleanup and seeding

## Running Tests

### Mock Mode (Default)
```bash
# Via Docker (recommended)
sudo docker-compose --profile test up recommendation_engine_test --abort-on-container-exit

# Or directly in container
sudo docker-compose exec recommendation_engine python3 -m pytest tests/ -v
```

### Real Database Mode with Cleanup
```bash
# Via Docker (recommended)
sudo docker-compose --profile test-db up recommendation_engine_test_with_db --abort-on-container-exit

# Or directly in container  
sudo docker-compose exec recommendation_engine python run_tests_with_db.py
```

## Database Cleanup Process

When `USE_REAL_DB_FOR_TESTS=true` is set, the test suite:

1. **Drops and recreates** all recommendation database tables before each test
2. **Seeds test data** including:
   - Sample popular items for different demographics
   - User profiles with preferences 
   - User similarities for collaborative filtering
   - Item similarities for item-based recommendations
3. **Flushes Redis cache** to ensure clean state
4. **Runs the test** with fresh, consistent data

## Test Data Structure

### Popular Items
```sql
-- Sample data seeded for testing
(213, 'f', '25-34', 'electronics', '101', 0.9),
(213, 'f', '25-34', 'electronics', '102', 0.8),
(213, 'm', '25-34', 'electronics', '104', 0.6),
-- etc...
```

### User Profiles  
```sql
-- Users with different preference patterns
('123', '{"category:electronics": 0.6, "category:books": 0.4}', '{"ozon": 0.7}', 1500.0, 200.0, 5000.0, 5),
('456', '{"category:sports": 0.8, "category:music": 0.2}', '{"amazon": 0.5}', 800.0, 100.0, 2000.0, 3),
```

### Item/User Similarities
```sql
-- Pre-computed similarity matrices for testing collaborative filtering
INSERT INTO user_similarities (user_id, similar_user_id, similarity_score) VALUES ('123', '456', 0.75);
INSERT INTO item_similarities (item_a, item_b, similarity_score) VALUES ('101', '102', 0.8);
```

## Database Configuration

### Test Database Settings
- **Database**: `rec_db_test` (PostgreSQL)
- **Redis Database**: `6` (isolated from other environments)
- **Schema**: Uses `schema_minimal.sql` for table structure

### Environment Variables
```bash
USE_REAL_DB_FOR_TESTS=true                    # Enable real database mode
TEST_DATABASE_URL=postgresql://...            # Test database connection
RECOMMENDATIONS_DATABASE_URL=postgresql://... # Same as test DB for tests
RECOMMENDATIONS_REDIS_URL=redis://redis:6379/6  # Test Redis database
```

## Benefits of Real Database Testing

1. **Integration Testing**: Validates actual SQL queries and database interactions
2. **Schema Validation**: Ensures database schema matches application models
3. **Performance Testing**: Real query performance under controlled conditions  
4. **Consistency**: Every test runs with identical, fresh data
5. **Debugging**: Easier to debug database-related issues

## When to Use Each Mode

### Use Mock Mode When:
- Running unit tests for business logic
- Testing error handling and edge cases
- Fast CI/CD pipeline runs
- Developing without database dependencies

### Use Real Database Mode When:
- Testing database migrations or schema changes
- Validating complex SQL queries
- Integration testing before deployment
- Investigating database performance issues
- Testing with actual data structures

## Files Modified

- `tests/conftest.py`: Added `clean_test_db` fixture and seeding functions
- `run_tests_with_db.py`: Script to enable real database testing
- `docker-compose.yaml`: Added `recommendation_engine_test_with_db` service
- Environment variable `USE_REAL_DB_FOR_TESTS` controls testing mode

## Notes

- Database cleanup runs before **each test function** (not once per test session)
- All tables are dropped and recreated from `schema_minimal.sql`
- Redis cache is completely flushed for each test
- Tests remain isolated - no test can affect another test's data
- Performance: Real database tests take ~0.3s vs ~0.1s for mocked tests