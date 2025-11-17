#!/usr/bin/env python3
"""
Test runner for Multi-Coin Grid Trading Strategy

Run all unit tests.
"""

import sys
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    """Run all tests"""
    print("=" * 80)
    print("Running Multi-Coin Grid Strategy Tests")
    print("=" * 80)

    # Run pytest with verbose output
    exit_code = pytest.main([
        str(Path(__file__).parent),
        "-v",
        "--tb=short",
        "--color=yes"
    ])

    if exit_code == 0:
        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("❌ SOME TESTS FAILED")
        print("=" * 80)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
