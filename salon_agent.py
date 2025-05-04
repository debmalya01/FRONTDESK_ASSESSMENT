from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import (
    groq,
    cartesia,
    deepgram,
    silero,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from help_requests_db import add_help_request, get_learned_answer
import logging
import os
import asyncio
from webhook_server import run_webhook_server
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Log all messages at DEBUG level and above
    filename='salon_agent.log',  # Log file name
    filemode='a',  # Append to the log file (use 'w' to overwrite each run)
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'  # Log format)
)
logger = logging.getLogger(__name__)

load_dotenv()

def load_prompt(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

class SalonAgent(Agent):
    def __init__(self) -> None:
        instructions = load_prompt('salon_prompt.txt')
        super().__init__(instructions=instructions)
             
async def entrypoint(ctx: agents.JobContext):
    try:
        await ctx.connect()
        
        # Generate a unique conversation ID
        conversation_id = f"conv_{ctx.room.name}_{datetime.utcnow().isoformat()}"
        logger.info(f"Starting new conversation with ID: {conversation_id}")

        # Configure with explicit English language support
        session = AgentSession(
            stt=deepgram.STT(
                model="nova-3",
                language="en"  # Force English language
            ),
            llm=groq.LLM(
                model="llama3-8b-8192"
            ),
            tts=cartesia.TTS(),
            vad=silero.VAD.load(),
            turn_detection=MultilingualModel()
        )

        # Start webhook server as an async task with proper session handling
        webhook_task = asyncio.create_task(run_webhook_server(session))
        logger.info("Webhook server started as async task with LiveKit session")

        # Wait for the webhook server to start
        try:
            # Wait for the server to start, but don't wait for it to complete
            await asyncio.wait_for(asyncio.shield(webhook_task), timeout=2.0)
            logger.info("Webhook server initialized successfully")
        except asyncio.TimeoutError:
            # This is expected - we don't want to wait for the server to complete
            logger.info("Webhook server is running in background")
        except Exception as e:
            logger.error(f"Error initializing webhook server: {str(e)}")
            raise

        def on_conversation_item_added(event):
            message = event.item
            logger.debug(f"New conversation item added: {message}")

            if (
                getattr(message, "role", None) == "assistant"
                and isinstance(message.content, list)
            ):
                items = session._chat_ctx.items
                try:
                    idx = items.index(message)
                except ValueError:
                    idx = len(items) - 1  # fallback: use last

                user_question = None
                for m in reversed(items[:idx]):
                    if getattr(m, "role", None) == "user":
                        user_question = m.content[0] if m.content else None
                        break

                if user_question:
                    # First check if we have a learned answer
                    learned_answer = get_learned_answer(user_question)
                    if learned_answer:
                        logger.info(f"Found learned answer for: {user_question}")
                        asyncio.create_task(session.generate_reply(
                            instructions=learned_answer["answer"]
                        ))
                    # Only proceed with supervisor check if we don't have a learned answer
                    elif any("supervisor" in str(c).lower() for c in message.content):
                        add_help_request(user_question, conversation_id)
                        logger.info(f"Added help request for supervisor: {user_question}")
                else:
                    logger.warning("No user question found before assistant reply.")

        # Register the event handler
        session.on("conversation_item_added", on_conversation_item_added)
        logger.info("Registered conversation item handler")

        # Start the session
        await session.start(
            room=ctx.room,
            agent=SalonAgent(),
            room_input_options=RoomInputOptions()
        )
        logger.info("Session started successfully")

        # Send welcome message
        await session.generate_reply(
            instructions="Welcome to Glam Salon! How can I help you today?"
        )
        logger.info("Welcome message sent")

    except Exception as e:
        logger.error(f"Error in entrypoint: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise