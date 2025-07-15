import os
from dotenv import load_dotenv

load_dotenv()

class Config: 
    MONGO_URI = os.getenv("MONGO_URI")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
    MONGO_CV_COLLECTION = os.getenv("MONGO_CV_COLLECTION")
    MONGO_INTERVIEW_COLLECTION = os.getenv("MONGO_INTERVIEW_COLLECTION")
    MODEL_API_URL=os.getenv("MODEL_API_URL")
    MODEL_API_URL = os.environ.get("MODEL_API_URL")
    
    JOB_API_URL = os.getenv("JOB_API_URL")
    API_TIMEOUT = int(os.getenv("API_TIMEOUT"))  

    DATABASE_URL = os.getenv("DATABASE_URL")
    PG_USER = os.getenv("PG_USER")

    GMAIL_USER = os.getenv("GMAIL_USER")
    GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
    
config = Config()
