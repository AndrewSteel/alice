#!/usr/bin/env python3
"""
Alice - Weaviate Schema Setup
=============================
Erstellt alle Collections für Alice in Weaviate.

Verwendung:
    python init-weaviate-schema.py [--url WEAVIATE_URL] [--reset]

Beispiel:
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
    print("❌ requests nicht installiert: pip install requests")
    sys.exit(1)

# Konfiguration
DEFAULT_WEAVIATE_URL = "http://weaviate:8080"
SCRIPT_DIR = Path(__file__).parent
SCHEMA_DIR = SCRIPT_DIR.parent / "schemas"

SCHEMAS = [
    "alice-memory.json",
    "rechnung.json",
    "kontoauszug.json",
    "wertpapier-abrechnung.json",
    "dokument.json",
    "email.json",
    "vertrag.json",
    "ha-intent.json",
]


def check_weaviate_connection(url: str) -> bool:
    """Prüft ob Weaviate erreichbar ist."""
    try:
        response = requests.get(f"{url}/v1/.well-known/ready", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def collection_exists(url: str, class_name: str) -> bool:
    """Prüft ob eine Collection bereits existiert."""
    try:
        response = requests.get(f"{url}/v1/schema/{class_name}", timeout=5)
        return response.status_code == 200 and "class" in response.json()
    except requests.RequestException:
        return False


def create_collection(url: str, schema: dict) -> tuple[bool, str]:
    """Erstellt eine Collection in Weaviate."""
    class_name = schema.get("class", "Unknown")
    
    try:
        response = requests.post(
            f"{url}/v1/schema",
            json=schema,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            return True, "erstellt"
        else:
            error = response.json().get("error", [{"message": "Unbekannter Fehler"}])
            if isinstance(error, list):
                error_msg = error[0].get("message", str(error))
            else:
                error_msg = str(error)
            return False, error_msg
            
    except requests.RequestException as e:
        return False, str(e)


def delete_collection(url: str, class_name: str) -> bool:
    """Löscht eine Collection aus Weaviate."""
    try:
        response = requests.delete(f"{url}/v1/schema/{class_name}", timeout=10)
        return response.status_code in [200, 204]
    except requests.RequestException:
        return False


def get_all_collections(url: str) -> list[str]:
    """Listet alle Collections in Weaviate."""
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
    parser.add_argument("--reset", action="store_true", help="Bestehende Collections löschen")
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR, help="Schema-Verzeichnis")
    args = parser.parse_args()

    print("=" * 60)
    print("Alice - Weaviate Schema Setup")
    print("=" * 60)
    print(f"\nWeaviate URL: {args.url}")
    print(f"Schema Dir:   {args.schema_dir}\n")

    # Verbindung prüfen
    print("🔍 Prüfe Weaviate-Verbindung... ", end="", flush=True)
    if not check_weaviate_connection(args.url):
        print("❌ FEHLER")
        print(f"   Weaviate ist nicht erreichbar unter {args.url}")
        sys.exit(1)
    print("✅ OK")

    # Reset-Modus
    if args.reset:
        print("\n⚠️  RESET-MODUS: Lösche bestehende Collections...\n")
        for schema_file in SCHEMAS:
            schema_path = args.schema_dir / schema_file
            if schema_path.exists():
                with open(schema_path) as f:
                    schema = json.load(f)
                class_name = schema.get("class")
                if class_name:
                    print(f"🗑️  Lösche '{class_name}'... ", end="", flush=True)
                    if delete_collection(args.url, class_name):
                        print("✅")
                    else:
                        print("⚠️ (existierte nicht)")

    # Collections erstellen
    print("\n📚 Erstelle Collections...")
    print("-" * 60)

    success_count = 0
    error_count = 0

    for schema_file in SCHEMAS:
        schema_path = args.schema_dir / schema_file
        
        if not schema_path.exists():
            print(f"⚠️  Schema-Datei nicht gefunden: {schema_file}")
            error_count += 1
            continue

        with open(schema_path) as f:
            schema = json.load(f)
        
        class_name = schema.get("class", "Unknown")
        print(f"📦 Erstelle '{class_name}'... ", end="", flush=True)

        # Prüfe ob bereits existiert
        if collection_exists(args.url, class_name):
            print("⏭️  existiert bereits")
            success_count += 1
            continue

        # Erstellen
        success, message = create_collection(args.url, schema)
        if success:
            print("✅")
            success_count += 1
        else:
            print(f"❌ {message}")
            error_count += 1

    # Zusammenfassung
    print("\n" + "-" * 60)
    print("📊 Zusammenfassung")
    print("-" * 60)
    print(f"   Erfolgreich: {success_count}")
    print(f"   Fehler:      {error_count}")

    # Aktuelle Collections anzeigen
    print("\n📋 Aktuelle Collections in Weaviate:")
    print("-" * 60)
    for class_name in get_all_collections(args.url):
        print(f"   • {class_name}")

    print()
    if error_count == 0:
        print("✅ Schema-Setup erfolgreich abgeschlossen!")
        sys.exit(0)
    else:
        print("⚠️  Schema-Setup mit Warnungen abgeschlossen")
        sys.exit(1)


if __name__ == "__main__":
    main()
