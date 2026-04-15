"""Set required env vars before any app module is imported."""
import os
import sys

# Ensure the ingestion directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub all required env vars so config.py doesn't raise KeyError
os.environ.setdefault("FALKORDB_BOLT_URL", "bolt://falkordb.test:7687")
os.environ.setdefault("FALKORDB_USER", "")
os.environ.setdefault("FALKORDB_PASSWORD", "")
os.environ.setdefault("GRAPHITI_GROUP_ID", "test")
os.environ.setdefault("QDRANT_URL", "http://qdrant.test:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-qdrant-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("BLUEBUBBLES_URL", "http://bb.test:1234")
os.environ.setdefault("BLUEBUBBLES_PASSWORD", "test-password")
os.environ.setdefault("IMAP_HOST", "imap.test")
os.environ.setdefault("IMAP_USER", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test-imap-password")
os.environ.setdefault("NOTION_API_KEY", "test-notion-key")
os.environ.setdefault("CONTACT_SERVER_URL", "http://contacts.test:9876")
os.environ.setdefault("CONTACT_SERVER_TOKEN", "test-contacts-token")
