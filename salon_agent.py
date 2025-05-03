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
from help_requests_db import add_help_request
import logging
import os

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

##Implementation 1
        # def on_conversation_item_added(event):
        #     message = event.item
        #     # Only check assistant replies
        #     if (
        #         getattr(message, "role", None) == "assistant"
        #         and isinstance(message.content, list)
        #         and any("supervisor" in str(c).lower() for c in message.content)
        #     ):
        #         logger.info(f"Request help triggered for user input: {message}")

        # session.on("conversation_item_added", on_conversation_item_added)

##Implementation 2        
        # def on_conversation_item_added(event):
        #     message = event.item

        #     if (
        #         getattr(message, "role", None) == "assistant"
        #         and isinstance(message.content, list)
        #         and any("supervisor" in str(c).lower() for c in message.content)
        #     ):
        #         user_question = None
        #         if hasattr(session, "_chat_ctx") and hasattr(session._chat_ctx, "items"):
        #             for m in reversed(session._chat_ctx.items):
        #                 if getattr(m, "role", None) == "user":
        #                     user_question = m.content[0] if m.content else None
        #                     break
        #         if user_question:
        #             add_help_request(user_question)
        #             print(f"Hey, I need help answering: {user_question}")
        #             logger.info(f"Request help triggered for user input: {message}")
                
        # session.on("conversation_item_added", on_conversation_item_added)

##Implementation 3
        def on_conversation_item_added(event):
            message = event.item

            if (
                getattr(message, "role", None) == "assistant"
                and isinstance(message.content, list)
                and any("supervisor" in str(c).lower() for c in message.content)
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
                    add_help_request(user_question)
                    logger.info(f"Hey, I need help answering: {user_question}")
                else:
                    logger.warning("No user question found before supervisor reply.")

                logger.info(f"Request help triggered for assistant reply: {message}")   

        session.on("conversation_item_added", on_conversation_item_added)  

        await session.start(
            room=ctx.room,
            agent=SalonAgent(),
            room_input_options=RoomInputOptions()
        )

        await session.generate_reply(
            instructions="Welcome to Glam Salon! How can I help you today?"
        )

    except Exception as e:
        logger.error(f"Error in entrypoint: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise