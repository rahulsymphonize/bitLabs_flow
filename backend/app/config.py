import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
# First sysAdmin is created at startup when the users table is empty.
SYSADMIN_EMAIL = os.getenv("SYSADMIN_EMAIL")
SYSADMIN_PASSWORD = os.getenv("SYSADMIN_PASSWORD")
