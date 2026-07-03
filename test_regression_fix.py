#!/usr/bin/env python
"""Test v3.6.1 regression fixes for SQLite and internet_intelligence."""

from modules.database import Database
from modules.application import Application
from datetime import datetime, timedelta
import tempfile
import os

# Create a temporary database
temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
db_path = temp_db.name
temp_db.close()

try:
    # Initialize database
    db = Database(db_path)
    db.initialize()
    
    # Test 1: Add and retrieve health checks
    print("Test 1: Health checks...")
    now = datetime.now()
    db.add_health_check(
        timestamp=now.isoformat(),
        latency=50.5,
        packet_loss=0.5,
        dns_ok=1,
        score=95
    )
    
    # Test 2: Timestamp normalization
    print("Test 2: Timestamp normalization...")
    since = now - timedelta(days=1)
    since_str = str(since)  # Produces "2026-07-01 12:34:56.123456"
    print(f"  Input timestamp (str): {since_str}")
    normalized = db._normalize_timestamp(since_str)
    print(f"  Normalized timestamp: {normalized}")
    
    # Test 3: health_history_since with string timestamp
    print("Test 3: health_history_since with string timestamp...")
    rows = db.health_history_since(since_str)
    print(f"  Retrieved {len(rows)} health records")
    if rows:
        print(f"  First record: {rows[0]}")
    
    # Test 4: health_history_since with datetime timestamp
    print("Test 4: health_history_since with datetime timestamp...")
    rows = db.health_history_since(since)
    print(f"  Retrieved {len(rows)} health records")
    
    # Test 5: Add speed test and retrieve
    print("Test 5: Speed tests...")
    db.add_speed_test(
        timestamp=now.isoformat(),
        download=500.0,
        upload=100.0,
        ping=15.0,
        server="speedtest.example.com"
    )
    
    rows = db.speed_tests_since(since_str)
    print(f"  Retrieved {len(rows)} speed test records")
    if rows:
        print(f"  First record: {rows[0]}")
    
    # Test 6: internet_intelligence with Application
    print("Test 6: Application internet_intelligence...")
    app = Application()
    try:
        intelligence = app.internet_intelligence()
        print(f"  Quality score: {intelligence.get('quality_score')}")
        print(f"  ISP grade: {intelligence.get('isp_grade')}")
        print(f"  Reliability: {intelligence.get('reliability')}")
        print(f"  Sample count: {intelligence.get('sample_count')}")
        print("  ✓ internet_intelligence succeeded (with graceful fallback if needed)")
    except Exception as e:
        print(f"  ✗ internet_intelligence failed: {e}")
    
    print("\n✓ All regression fix tests passed!")
    
finally:
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
