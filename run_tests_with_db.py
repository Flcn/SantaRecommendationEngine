#!/usr/bin/env python3
"""
Run tests with real database cleanup and seeding
"""

import os
import sys
import subprocess

def main():
    """Run tests with database cleanup enabled"""
    # Set environment variable to enable real database testing
    os.environ['USE_REAL_DB_FOR_TESTS'] = 'true'
    
    # Default to all tests if no arguments provided
    test_args = sys.argv[1:] if len(sys.argv) > 1 else ['tests/']
    
    # Run pytest with the specified arguments
    cmd = ['python3', '-m', 'pytest'] + test_args + ['-v']
    
    print(f"Running tests with database cleanup: {' '.join(cmd)}")
    print("Database will be cleaned and seeded before each test")
    
    result = subprocess.run(cmd)
    sys.exit(result.returncode)

if __name__ == '__main__':
    main()