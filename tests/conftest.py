import os

os.environ.setdefault("APP_API_KEY", "test-api-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
