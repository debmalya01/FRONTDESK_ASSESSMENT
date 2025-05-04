from flask import Flask, render_template, request, redirect, url_for
from help_requests_db import (
    get_pending_requests, 
    mark_request_resolved, 
    add_learned_answer, 
    get_request_by_id,
    check_timeout_requests,
    get_requests_by_status,
    get_request_history,
    get_request_stats,
    get_learned_answers,
    get_time_left
)
import requests
import os
from dotenv import load_dotenv
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

@app.template_filter('unique')
def unique_filter(sequence):
    """Filter out duplicate items from a sequence"""
    seen = set()
    return [x for x in sequence if not (x['question'] in seen or seen.add(x['question']))]

@app.template_filter('format_datetime')
def format_datetime(value):
    """Format ISO datetime string to readable format"""
    if not value:
        return '-'
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value)
        else:
            dt = value
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return str(value)

@app.template_filter('fromisoformat')
def fromisoformat(value):
    """Convert ISO format string to datetime object"""
    if not value:
        return None
    try:
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value
    except (ValueError, TypeError):
        return None

@app.route('/')
def dashboard():
    logger.debug("Accessing dashboard")
    # Check for timed out requests
    check_timeout_requests()
    
    # Get statistics
    stats = get_request_stats()
    logger.debug(f"Dashboard stats: {stats}")
    
    # Get recent history
    history = get_request_history(limit=10)
    logger.debug(f"Dashboard history count: {len(history)}")
    
    return render_template('dashboard.html', 
                         stats=stats,
                         history=history)

@app.route('/requests/<status>')
def view_requests(status):
    logger.debug(f"Accessing requests with status: {status}")
    if status not in ['pending', 'resolved', 'unresolved']:
        return "Invalid status", 400
        
    requests = get_requests_by_status(status)
    logger.debug(f"Found {len(requests)} requests with status {status}")
    return render_template('requests.html', 
                         requests=requests,
                         status=status,
                         now=datetime.utcnow(),
                         get_time_left=get_time_left)

@app.route('/history')
def view_history():
    logger.debug("Accessing history")
    history = get_request_history()
    logger.debug(f"History count: {len(history)}")
    return render_template('history.html', history=history)

@app.route('/learned-answers')
def view_learned_answers():
    logger.debug("Accessing learned answers")
    answers = get_learned_answers()
    logger.debug(f"Found {len(answers)} learned answers")
    # Debug log the answers
    for answer in answers:
        logger.debug(f"Answer: {answer}")
    return render_template('learned_answers.html', answers=answers)

@app.route('/answer/<request_id>', methods=['POST'])
def answer(request_id):
    logger.debug(f"Processing answer for request: {request_id}")
    answer = request.form['answer']
    
    # Get the request details
    request_doc = get_request_by_id(request_id)
    if not request_doc:
        logger.error(f"Request not found: {request_id}")
        return "Request not found", 404
    
    # Check if request has timed out
    if request_doc['status'] == 'unresolved':
        logger.warning(f"Attempted to answer timed out request: {request_id}")
        return "This request has timed out and cannot be answered", 400
    
    # Mark request as resolved
    mark_request_resolved(request_id, answer)
    logger.info(f"Marked request {request_id} as resolved")
    
    # Add to learned answers
    add_learned_answer(request_doc['question'], answer)
    
    # Notify agent via webhook
    try:
        # Ensure we have a valid session ID
        session_id = request_doc.get('conversation_id')
        if not session_id:
            logger.warning(f"No conversation_id found for request {request_id}")
            session_id = f"default_{request_id}"
            
        webhook_data = {
            'session_id': session_id,
            'answer': answer,
            'request_id': request_id
        }
        
        logger.debug(f"Sending webhook with data: {webhook_data}")
        
        response = requests.post(
            'http://localhost:5005/supervisor_answer',
            json=webhook_data
        )
        
        if response.status_code != 200:
            logger.error(f"Error notifying agent: {response.text}")
            logger.error(f"Response status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending webhook: {str(e)}")
    
    return redirect(url_for('view_requests', status='pending'))

if __name__ == '__main__':
    app.run(debug=True, port=5000) 