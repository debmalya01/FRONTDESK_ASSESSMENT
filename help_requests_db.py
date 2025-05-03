from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Get your MongoDB URI from environment variable for security
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "Frontdesk"
COLLECTION_NAME = "help_requests"

# Create a new client and connect to the server using ServerApi
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))

# Optional: Ping the server to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print("MongoDB connection error:", e)

db = client[DB_NAME]
collection = db[COLLECTION_NAME]

def add_help_request(question, conversation_id=None):
    doc = {
        "question": question,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "pending",
        "conversation_id": conversation_id
    }
    result = collection.insert_one(doc)
    return result.inserted_id

def get_pending_requests():
    return list(collection.find({"status": "pending"}))