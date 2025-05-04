from aiohttp import web
import asyncio
import logging
from help_requests_db import mark_request_notified, get_request_by_id, add_learned_answer
from bson import ObjectId
from livekit.agents import AgentSession

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    filename='webhook_server.log',
    filemode='a',
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Global variable to store the active session
active_session: AgentSession = None

async def supervisor_answer(request):
    try:
        data = await request.json()
        session_id = data.get("session_id")
        answer = data.get("answer")
        request_id = data.get("request_id")
        
        logger.debug(f"Received supervisor answer - Session: {session_id}, Request: {request_id}")
        
        if not all([session_id, answer, request_id]):
            logger.error("Missing required fields in webhook request")
            return web.Response(status=400, text="Missing required fields")
            
        # Get the request details
        request_doc = get_request_by_id(request_id)
        if not request_doc:
            logger.error(f"Request not found: {request_id}")
            return web.Response(status=404, text="Request not found")
            
        # Check if request has timed out
        if request_doc['status'] == 'unresolved':
            logger.warning(f"Attempted to answer timed out request: {request_id}")
            return web.Response(status=400, text="This request has timed out")
            
        # Add to learned answers
        add_learned_answer(request_doc["question"], answer)
        
        # Mark request as notified
        mark_request_notified(request_id)
        
        # If we have an active session, generate a reply with the answer
        if active_session and isinstance(active_session, AgentSession):
            try:
                # Format the response to be more natural
                formatted_response = f"I've checked with my supervisor. {answer}"
                logger.info(f"Sending formatted response: {formatted_response}")
                
                # Use the session's generate_reply method
                await active_session.generate_reply(instructions=formatted_response)
                logger.info(f"Successfully generated reply for request {request_id}")
            except Exception as e:
                logger.error(f"Error generating reply: {str(e)}")
                return web.Response(status=500, text=f"Error generating reply: {str(e)}")
        else:
            error_msg = f"No valid LiveKit session found. Active session: {type(active_session)}"
            logger.error(error_msg)
            return web.Response(status=500, text=error_msg)
            
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Error in supervisor_answer: {str(e)}")
        return web.Response(status=500, text=str(e))

async def run_webhook_server(session: AgentSession = None):
    global active_session
    if session and isinstance(session, AgentSession):
        active_session = session
        logger.info("LiveKit session successfully initialized in webhook server")
    else:
        logger.error(f"Invalid LiveKit session provided to webhook server: {type(session)}")
        return
    
    app = web.Application()
    app.router.add_post("/supervisor_answer", supervisor_answer)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, port=5005)
    await site.start()
    print("Webhook server started on port 5005")
    logger.info("Webhook server started on port 5005")

# If you want to run this as a standalone server for testing:
if __name__ == "__main__":
    asyncio.run(run_webhook_server())