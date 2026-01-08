import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-super-secret-key-here')
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/college_helpdesk')
    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
    OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    JWT_SECRET_KEY = os.getenv('SECRET_KEY')