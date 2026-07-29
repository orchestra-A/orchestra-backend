import os

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_WEBHOOK_SECRET_KEY = os.getenv("GITHUB_WEBHOOK_SECRET_KEY", "default_secret")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://orchestra-frontend-roan.vercel.app")

GRAPH_API_URL = os.getenv("GRAPH_API_URL", "https://orchestra-ai-36zm.onrender.com")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "https://orchestra-ai-36zm.onrender.com")

DISCORD_ALLOWED_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "1509182463493013526"))
