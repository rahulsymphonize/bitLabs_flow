import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
# First sysAdmin is created at startup when the users table is empty.
SYSADMIN_EMAIL = os.getenv("SYSADMIN_EMAIL")
SYSADMIN_PASSWORD = os.getenv("SYSADMIN_PASSWORD")

# Graph RAG. The model ids are config because Gemini names change often.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_TIMEOUT_S = int(os.getenv("GEMINI_TIMEOUT_S", "60"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "100"))
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "200"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "1000"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.5"))
EXTRACT_WORKERS = int(os.getenv("EXTRACT_WORKERS", "4"))
EXTRACT_DEADLINE_S = int(os.getenv("EXTRACT_DEADLINE_S", "300"))
GRAPH_HOPS = int(os.getenv("GRAPH_HOPS", "2"))
GRAPH_MAX_NODES = int(os.getenv("GRAPH_MAX_NODES", "60"))
GRAPH_MAX_EDGES = int(os.getenv("GRAPH_MAX_EDGES", "120"))
GRAPH_PER_NODE = int(os.getenv("GRAPH_PER_NODE", "15"))
CONTEXT_CHARS = int(os.getenv("CONTEXT_CHARS", "12000"))
# Max graph write requests per company per minute.
GRAPH_WRITES_PER_MIN = int(os.getenv("GRAPH_WRITES_PER_MIN", "10"))
VECTOR_MIN_SIM = float(os.getenv("VECTOR_MIN_SIM", "0.6"))
VECTOR_TOP = int(os.getenv("VECTOR_TOP", "5"))
# Must match the vector column size; changing it needs a migration.
EMBED_DIM = 768
