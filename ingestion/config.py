import os
from dotenv import load_dotenv

load_dotenv()

FALKORDB_HOST = os.environ.get("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.environ.get("FALKORDB_PORT", "6379"))
FALKORDB_PASSWORD = os.environ.get("FALKORDB_PASSWORD", "")
GRAPHITI_GROUP_ID = os.environ.get("GRAPHITI_GROUP_ID", "personal")

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_API_KEY = os.environ["QDRANT_API_KEY"]
QDRANT_COLLECTION = "documents"

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

BLUEBUBBLES_URL = os.environ["BLUEBUBBLES_URL"]
BLUEBUBBLES_PASSWORD = os.environ["BLUEBUBBLES_PASSWORD"]
BLUEBUBBLES_WEBHOOK_SECRET = os.environ.get("BLUEBUBBLES_WEBHOOK_SECRET", "")
BLUEBUBBLES_PULL_ENABLED = os.environ.get("BLUEBUBBLES_PULL_ENABLED", "false").lower() in ("true", "1", "yes")

CONTACT_SERVER_URL = os.environ.get("CONTACT_SERVER_URL", "http://desktop1.tail3d8f4.ts.net:9876")
CONTACT_SERVER_TOKEN = os.environ.get("CONTACT_SERVER_TOKEN", "")

IMAP_HOST = os.environ["IMAP_HOST"]
IMAP_PORT = int(os.environ.get("IMAP_PORT", 993))
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASSWORD = os.environ["IMAP_PASSWORD"]
IMAP_MAILBOX = os.environ.get("IMAP_MAILBOX", "INBOX")

NOTION_API_KEY = os.environ["NOTION_API_KEY"]
NOTION_WEBHOOK_SECRET = os.environ.get("NOTION_WEBHOOK_SECRET", "")

DEDUP_DB_PATH = os.environ.get("DEDUP_DB_PATH", "/db/dedup.sqlite")
DIGEST_PATH = os.environ.get("DIGEST_PATH", "/data/digest.txt")

# Chunk size for Qdrant document storage
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

