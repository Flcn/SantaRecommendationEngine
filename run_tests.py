#!/usr/bin/env python3
"""
Simple test runner for the recommendation engine
"""

import subprocess
import sys
import os

def run_tests():
    """Run all tests with coverage reporting"""
    print("🧪 Running MySanta Recommendation Engine Tests")
    print("=" * 50)
    
    # Change to project directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Run pytest with coverage
    cmd = [
        "python", "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short",
        "-x",  # Stop on first failure
        "--disable-warnings"
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print("\n✅ All tests passed!")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Tests failed with exit code {e.returncode}")
        return e.returncode
    except FileNotFoundError:
        print("❌ pytest not found. Install test dependencies:")
        print("pip install -r requirements.txt")
        return 1

def run_specific_test(test_file):
    """Run specific test file"""
    print(f"🧪 Running {test_file}")
    print("=" * 50)
    
    cmd = [
        "python", "-m", "pytest",
        f"tests/{test_file}",
        "-v",
        "--tb=short",
        "--disable-warnings"
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print(f"\n✅ {test_file} tests passed!")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {test_file} tests failed with exit code {e.returncode}")
        return e.returncode

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        if not test_file.startswith("test_"):
            test_file = f"test_{test_file}"
        if not test_file.endswith(".py"):
            test_file = f"{test_file}.py"
        
        exit_code = run_specific_test(test_file)
    else:
        exit_code = run_tests()
    
    sys.exit(exit_code)