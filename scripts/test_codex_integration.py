#!/usr/bin/env python3
"""Test script for Grimoire ↔ Codex API integration.

Standalone test - uses httpx directly without Grimoire imports.
"""

import asyncio
import sys

import httpx

CODEX_BASE_URL = "https://api.codex.livetorole.com/api/v1"


async def test_identify_endpoint():
    """Test the /identify endpoint."""
    print("\n=== Testing /identify Endpoint ===\n")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test 1: Check API root
        print("1. Checking Codex API availability...")
        try:
            response = await client.get(f"{CODEX_BASE_URL}/")
            if response.status_code == 200:
                print("   ✅ API is reachable")
            else:
                print(f"   ❌ API returned status {response.status_code}")
                return False
        except Exception as e:
            print(f"   ❌ API not reachable: {e}")
            return False
        
        # Test 2: Title lookup
        print("\n2. Testing title lookup...")
        try:
            response = await client.get(
                f"{CODEX_BASE_URL}/identify",
                params={"title": "Tomb of the Serpent Kings"}
            )
            data = response.json()
            print(f"   Match: {data.get('match')}")
            print(f"   Confidence: {data.get('confidence')}")
            if data.get('product'):
                print(f"   Product: {data['product'].get('title')}")
            else:
                print("   Product: None (expected if Codex has no matching products)")
        except Exception as e:
            print(f"   ❌ Title lookup failed: {e}")
            return False
        
        # Test 3: Hash lookup
        print("\n3. Testing hash lookup...")
        try:
            response = await client.get(
                f"{CODEX_BASE_URL}/identify",
                params={"hash": "abc123fakehash"}
            )
            data = response.json()
            print(f"   Match: {data.get('match')}")
            print(f"   Confidence: {data.get('confidence')}")
        except Exception as e:
            print(f"   ❌ Hash lookup failed: {e}")
            return False
    
    print("\n✅ /identify endpoint tests completed")
    return True


async def test_contribution_endpoint(api_key: str = None):
    """Test the /contributions endpoint."""
    print("\n=== Testing /contributions Endpoint ===\n")
    
    if not api_key:
        print("⚠️  No API key provided. Skipping contribution test.")
        print("   To test contributions, run with: --api-key YOUR_TOKEN")
        return True
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test contribution with Grimoire-style payload (backward compat)
        print("1. Testing Grimoire-style contribution (product_id: null)...")
        payload = {
            "product_id": None,  # Grimoire legacy format
            "data": {
                "title": "Test Product from Grimoire Integration",
                "publisher": "Test Publisher",
                "game_system": "OSR",
                "product_type": "adventure",
            },
            "source": "grimoire",
            "file_hash": "test_hash_grimoire_integration_001",
        }
        
        try:
            response = await client.post(
                f"{CODEX_BASE_URL}/contributions/",
                json=payload,
                headers={"Authorization": f"Token {api_key}"}
            )
            
            if response.status_code == 201:
                data = response.json()
                print(f"   ✅ Contribution created successfully")
                print(f"   Status: {data.get('status')}")
                print(f"   Message: {data.get('message')}")
                print(f"   Product ID: {data.get('product_id')}")
                print(f"   Contribution ID: {data.get('contribution_id')}")
            else:
                print(f"   ❌ Contribution failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print(f"   ❌ Contribution request failed: {e}")
            return False
        
        # Test 2: New Codex-style contribution
        print("\n2. Testing Codex-style contribution (contribution_type)...")
        payload = {
            "contribution_type": "new_product",
            "data": {
                "title": "Test Product Codex Style",
                "publisher": "Test Publisher",
            },
            "source": "grimoire",
        }
        
        try:
            response = await client.post(
                f"{CODEX_BASE_URL}/contributions/",
                json=payload,
                headers={"Authorization": f"Token {api_key}"}
            )
            
            if response.status_code == 201:
                data = response.json()
                print(f"   ✅ Contribution created successfully")
                print(f"   Status: {data.get('status')}")
            else:
                print(f"   ❌ Contribution failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print(f"   ❌ Contribution request failed: {e}")
            return False
    
    print("\n✅ /contributions endpoint tests completed")
    return True


async def main():
    """Run all integration tests."""
    print("=" * 50)
    print("Grimoire ↔ Codex Integration Test")
    print("=" * 50)
    print(f"Base URL: {CODEX_BASE_URL}")
    
    # Parse args for API key
    api_key = None
    if "--api-key" in sys.argv:
        idx = sys.argv.index("--api-key")
        if idx + 1 < len(sys.argv):
            api_key = sys.argv[idx + 1]
    
    # Run tests
    identify_ok = await test_identify_endpoint()
    contrib_ok = await test_contribution_endpoint(api_key)
    
    print("\n" + "=" * 50)
    print("Summary")
    print("=" * 50)
    print(f"/identify endpoint: {'✅ PASS' if identify_ok else '❌ FAIL'}")
    print(f"/contributions endpoint: {'✅ PASS' if contrib_ok else '❌ FAIL'}")
    
    return 0 if (identify_ok and contrib_ok) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
