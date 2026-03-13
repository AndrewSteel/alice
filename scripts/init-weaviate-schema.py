#!/usr/bin/env python3
"""
Alice - Weaviate Schema Setup
=============================
Creates all collections for Alice in Weaviate.

Usage:
    python init-weaviate-schema.py [--url WEAVIATE_URL] [--reset]

Example:
    python init-weaviate-schema.py --url http://localhost:8080
    python init-weaviate-schema.py --url http://weaviate:8080 --reset
"""

import json
import sys
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed: pip install requests")
    sys.exit(1)

# Configuration
DEFAULT_WEAVIATE_URL = "http://weaviate:8080"
SCRIPT_DIR = Path(__file__).parent
SCHEMA_DIR = SCRIPT_DIR.parent / "schemas"

SCHEMAS = [
    "alice-memory.json",
    "invoice.json",
    "bank-statement.json",
    "security-settlement.json",
    "document.json",
    "email.json",
    "contract.json",
    "ha-intent.json",
]


def check_weaviate_connection(url: str) -> bool:
    """Check if Weaviate is reachable."""
    try:
        response = requests.get(f"{url}/v1/.well-known/ready", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def collection_exists(url: str, class_name: str) -> bool:
    """Check if a collection already exists."""
    try:
        response = requests.get(f"{url}/v1/schema/{class_name}", timeout=5)
        return response.status_code == 200 and "class" in response.json()
    except requests.RequestException:
        return False


def create_collection(url: str, schema: dict) -> tuple[bool, str]:
    """Create a collection in Weaviate."""
    class_name = schema.get("class", "Unknown")

    try:
        response = requests.post(
            f"{url}/v1/schema",
            json=schema,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code == 200:
            return True, "created"
        else:
            error = response.json().get("error", [{"message": "Unknown error"}])
            if isinstance(error, list):
                error_msg = error[0].get("message", str(error))
            else:
                error_msg = str(error)
            return False, error_msg

    except requests.RequestException as e:
        return False, str(e)


def delete_collection(url: str, class_name: str) -> bool:
    """Delete a collection from Weaviate."""
    try:
        response = requests.delete(f"{url}/v1/schema/{class_name}", timeout=10)
        return response.status_code in [200, 204]
    except requests.RequestException:
        return False


def get_all_collections(url: str) -> list[str]:
    """List all collections in Weaviate."""
    try:
        response = requests.get(f"{url}/v1/schema", timeout=5)
        if response.status_code == 200:
            return [c["class"] for c in response.json().get("classes", [])]
    except requests.RequestException:
        pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Alice Weaviate Schema Setup")
    parser.add_argument("--url", default=DEFAULT_WEAVIATE_URL, help="Weaviate URL")
    parser.add_argument("--reset", action="store_true", help="Delete existing collections")
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR, help="Schema directory")
    args = parser.parse_args()

    print("=" * 60)
    print("Alice - Weaviate Schema Setup")
    print("=" * 60)
    print(f"\nWeaviate URL: {args.url}")
    print(f"Schema Dir:   {args.schema_dir}\n")

    # Check connection
    print("Checking Weaviate connection... ", end="", flush=True)
    if not check_weaviate_connection(args.url):
        print("ERROR")
        print(f"   Weaviate is not reachable at {args.url}")
        sys.exit(1)
    print("OK")

    # Reset mode
    if args.reset:
        print("\nWARNING: RESET MODE — Deleting existing collections...\n")
        for schema_file in SCHEMAS:
            schema_path = args.schema_dir / schema_file
            if schema_path.exists():
                with open(schema_path) as f:
                    schema = json.load(f)
                class_name = schema.get("class")
                if class_name:
                    print(f"Deleting '{class_name}'... ", end="", flush=True)
                    if delete_collection(args.url, class_name):
                        print("OK")
                    else:
                        print("(did not exist)")

    # Create collections
    print("\nCreating collections...")
    print("-" * 60)

    success_count = 0
    error_count = 0

    for schema_file in SCHEMAS:
        schema_path = args.schema_dir / schema_file

        if not schema_path.exists():
            print(f"WARNING: Schema file not found: {schema_file}")
            error_count += 1
            continue

        with open(schema_path) as f:
            schema = json.load(f)

        class_name = schema.get("class", "Unknown")
        print(f"Creating '{class_name}'... ", end="", flush=True)

        # Check if already exists
        if collection_exists(args.url, class_name):
            print("already exists")
            success_count += 1
            continue

        # Create
        success, message = create_collection(args.url, schema)
        if success:
            print("OK")
            success_count += 1
        else:
            print(f"ERROR: {message}")
            error_count += 1

    # Summary
    print("\n" + "-" * 60)
    print("Summary")
    print("-" * 60)
    print(f"   Successful: {success_count}")
    print(f"   Errors:     {error_count}")

    # Show current collections
    print("\nCurrent collections in Weaviate:")
    print("-" * 60)
    for class_name in get_all_collections(args.url):
        print(f"   - {class_name}")

    print()
    if error_count == 0:
        print("Schema setup completed successfully!")
        sys.exit(0)
    else:
        print("Schema setup completed with warnings")
        sys.exit(1)


if __name__ == "__main__":
    main()
