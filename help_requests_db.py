from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from bson import ObjectId
import logging
from rapidfuzz import process, fuzz

# Configure logging
# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Get your MongoDB URI from environment variable for security
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "Frontdesk"
HELP_REQUESTS_COLLECTION = "help_requests"
LEARNED_ANSWERS_COLLECTION = "learned_answers"

# Request timeout in minutes
REQUEST_TIMEOUT_MINUTES = 2

# Fuzzy matching threshold (0-100)
FUZZY_MATCH_THRESHOLD = 80

# Create a new client and connect to the server using ServerApi
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))

# Optional: Ping the server to confirm a successful connection
try:
    client.admin.command('ping')
    logger.info("Successfully connected to MongoDB!")
except Exception as e:
    logger.error(f"MongoDB connection error: {e}")

db = client[DB_NAME]
help_requests = db[HELP_REQUESTS_COLLECTION]
learned_answers = db[LEARNED_ANSWERS_COLLECTION]

def add_help_request(question, conversation_id=None):
    doc = {
        "question": question,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "pending",
        "conversation_id": conversation_id,
        "notified": False,
        "timeout_at": (datetime.utcnow() + timedelta(minutes=REQUEST_TIMEOUT_MINUTES)).isoformat()
    }
    result = help_requests.insert_one(doc)
    logger.info(f"Added new help request: {doc}")
    return result.inserted_id

def get_pending_requests():
    """Get all pending requests that haven't timed out"""
    current_time = datetime.utcnow()
    logger.debug(f"Getting pending requests at {current_time}")
    
    # First, check for any timed out requests and mark them as unresolved
    check_timeout_requests()
    
    # Then return only non-timed-out pending requests
    pending = list(help_requests.find({
        "status": "pending"
    }).sort("timestamp", -1))
    
    # Filter out timed out requests
    valid_pending = []
    for request in pending:
        # Skip requests without timeout_at field
        if 'timeout_at' not in request:
            logger.warning(f"Request {request['_id']} missing timeout_at field, skipping")
            continue
            
        timeout_at = datetime.fromisoformat(request['timeout_at'])
        if timeout_at > current_time:
            valid_pending.append(request)
    
    logger.debug(f"Found {len(valid_pending)} valid pending requests out of {len(pending)} total pending")
    return valid_pending

def mark_request_resolved(request_id, answer):
    help_requests.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {
            "status": "resolved",
            "answer": answer,
            "resolved_at": datetime.utcnow().isoformat(),
            "notified": False
        }}
    )
    logger.info(f"Marked request {request_id} as resolved")

def mark_request_unresolved(request_id, reason=None):
    """Mark a request as unresolved with optional reason"""
    update_data = {
        "status": "unresolved",
        "unresolved_at": datetime.utcnow().isoformat(),
        "notified": False
    }
    if reason:
        update_data["unresolved_reason"] = reason
        
    help_requests.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": update_data}
    )
    logger.info(f"Marked request {request_id} as unresolved" + (f" with reason: {reason}" if reason else ""))

def mark_request_notified(request_id):
    help_requests.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {"notified": True}}
    )
    logger.info(f"Marked request {request_id} as notified")

def get_request_by_id(request_id):
    return help_requests.find_one({"_id": ObjectId(request_id)})

def add_learned_answer(question, answer):
    """Add a learned answer if it doesn't already exist"""
    # Check if we already have this question
    existing = learned_answers.find_one({"question": question})
    if existing:
        # Update the existing answer if it's different
        if existing['answer'] != answer:
            learned_answers.update_one(
                {"question": question},
                {"$set": {
                    "answer": answer,
                    "added_at": datetime.utcnow().isoformat()
                }}
            )
            logger.info(f"Updated learned answer for question: {question}")
    else:
        # Add new answer
        learned_answers.insert_one({
            "question": question,
            "answer": answer,
            "added_at": datetime.utcnow().isoformat()
        })
        logger.info(f"Added new learned answer for question: {question}")

def get_fuzzy_learned_answer(question, threshold=FUZZY_MATCH_THRESHOLD):
    """Get a learned answer using fuzzy matching"""
    all_answers = list(learned_answers.find({}))
    if not all_answers:
        return None
        
    # Extract questions for matching
    questions = [qa['question'] for qa in all_answers]
    
    # Find the best match using token sort ratio (handles word order changes)
    match, score, idx = process.extractOne(
        question, 
        questions, 
        scorer=fuzz.token_sort_ratio
    )
    
    logger.debug(f"Fuzzy match score: {score} for question: {question}")
    
    if score >= threshold:
        matched_answer = all_answers[idx]
        logger.info(f"Found fuzzy match (score: {score}): {matched_answer['question']}")
        return matched_answer['answer']
    return None

def get_learned_answer(question):
    """Get a learned answer using exact or fuzzy matching"""
    # Try exact match first
    exact_match = learned_answers.find_one({"question": question})
    if exact_match:
        logger.info(f"Found exact match for question: {question}")
        return exact_match['answer']
        
    # Try fuzzy match if no exact match found
    fuzzy_match = get_fuzzy_learned_answer(question)
    if fuzzy_match:
        return fuzzy_match
        
    return None

def get_resolved_requests():
    return list(help_requests.find({"status": "resolved", "notified": False}))

def check_timeout_requests():
    """Check and mark timed out requests as unresolved"""
    current_time = datetime.utcnow()
    logger.debug(f"Checking for timeouts at {current_time}")
    
    # Find all pending requests
    pending_requests = list(help_requests.find({"status": "pending"}))
    logger.debug(f"Found {len(pending_requests)} total pending requests")
    
    timed_out_count = 0
    for request in pending_requests:
        # Skip requests without timeout_at field
        if 'timeout_at' not in request:
            logger.warning(f"Request {request['_id']} missing timeout_at field, marking as unresolved")
            mark_request_unresolved(request['_id'])
            timed_out_count += 1
            continue
            
        timeout_at = datetime.fromisoformat(request['timeout_at'])
        if timeout_at <= current_time:
            logger.debug(f"Request {request['_id']} timed out at {timeout_at}")
            # Add timeout reason
            mark_request_unresolved(request['_id'], reason="Supervisor timeout")
            timed_out_count += 1
    
    logger.debug(f"Marked {timed_out_count} requests as timed out")
    return timed_out_count

def get_requests_by_status(status):
    """Get requests by their status (pending, resolved, unresolved)"""
    current_time = datetime.utcnow()
    logger.debug(f"Getting requests with status {status} at {current_time}")
    
    query = {"status": status}
    
    # For pending requests, also check timeout
    if status == "pending":
        # First check for timeouts
        check_timeout_requests()
        query["timeout_at"] = {"$gt": current_time.isoformat()}
    
    logger.debug(f"Status query: {query}")
    requests = list(help_requests.find(query).sort("timestamp", -1))
    logger.debug(f"Found {len(requests)} requests with status {status}")
    return requests

def get_request_history(limit=50):
    """Get recent request history, including all statuses"""
    # First check for any timeouts
    check_timeout_requests()
    history = list(help_requests.find().sort("timestamp", -1).limit(limit))
    logger.debug(f"Retrieved {len(history)} history records")
    return history

def get_request_stats():
    """Get statistics about requests"""
    current_time = datetime.utcnow()
    logger.debug(f"Getting request stats at {current_time}")
    
    # First check for any timeouts
    check_timeout_requests()
    
    # Get all pending requests
    pending_requests = list(help_requests.find({"status": "pending"}))
    
    # Count valid pending requests
    valid_pending = 0
    for request in pending_requests:
        # Skip requests without timeout_at field
        if 'timeout_at' not in request:
            logger.warning(f"Request {request['_id']} missing timeout_at field, skipping")
            continue
            
        timeout_at = datetime.fromisoformat(request['timeout_at'])
        if timeout_at > current_time:
            valid_pending += 1
    
    stats = {
        "pending": valid_pending,
        "resolved": help_requests.count_documents({"status": "resolved"}),
        "unresolved": help_requests.count_documents({"status": "unresolved"})
    }
    logger.debug(f"Request stats: {stats}")
    return stats

def get_learned_answers():
    """Get all learned answers sorted by most recent"""
    return list(learned_answers.find().sort("added_at", -1))

def get_time_left(request):
    """Calculate time left before timeout"""
    if 'timeout_at' not in request:
        return None
        
    try:
        timeout_at = datetime.fromisoformat(request['timeout_at'])
        current_time = datetime.utcnow()
        time_left = (timeout_at - current_time).total_seconds() / 60
        return max(0, time_left)
    except (ValueError, TypeError):
        return None