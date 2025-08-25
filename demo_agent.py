
import asyncio
from typing import Optional

from utils.agent_utils.llm_strategy import get_llm
from utils.agent_utils.stt_strategy import get_stt
from utils.agent_utils.tts_strategy import get_tts
from utils.monitoring_utils.logging import get_logger
from utils.config_utils.env_loader import get_env_var
from utils.config_utils.config_loader import get_config
from repository.prospect_repository import get_prospect_from_db, save_prospect_to_db

from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    RoomOutputOptions,
    WorkerOptions,
    RunContext,
    function_tool,
    cli,
    metrics,
)
from livekit.plugins import silero
from livekit.plugins import noise_cancellation

logger = get_logger("interview-agent")

# Load configuration
LIVEKIT_API_KEY       = get_config("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET    = get_config("LIVEKIT_API_SECRET")
LIVEKIT_URL           = get_config("LIVEKIT_URL", default="wss://livekit.example.com", required=False)
ENV                   = get_env_var("ENV", default="dev")

class DemoAgent(Agent):
    def __init__(self, prospect) -> None:

        self.prospect = prospect 
        first_name = getattr(prospect, "first_name", None) or "Unknown"
        logger.info(f"first_name------------------------>{first_name}"
                    )
        instructions = (
            "You are Caleb, a seasoned cold caller working for Vertex Media (https://www.vertexmedia.us).\n"
            "Your #1 job is to book the prospect into a meeting — without collecting their email you have failed.\n"
            "Always introduce yourself as Caleb from Vertex Media.\n"
            "If asked 'are you AI?' say: 'I’m one of Vertex's new innovative tools' and pivot back to a guiding question.\n\n"

            "# Conversation Flow Rules\n"
            "- Start every call:\n"
            f" → 'Hey is this {first_name}?' and WAIT for their answer.\n"
            "  → If they say 'Who?' → 'Just Caleb from Vertex, we’ve never actually spoken before.'\n"
            "  → Always ask for 20 seconds of permission before pitching.\n\n"

            "- Pain Point Discovery:\n"
            "  Don’t just list problems — explain them simply, so the realtor feels them:\n"
            "    1. Inconsistent Months → 'One month you’re slammed, the next it’s dead — makes it tough to plan bills or staff.'\n"
            "    2. Wasted Time → 'You probably spend hours with people who never list, and that time could’ve gone to real deals.'\n"
            "    3. Too Much on Their Plate → 'Most agents I talk to are buried in showings, follow-ups, paperwork — not enough hours in the day.'\n"
            "  → Then ask: 'Out of those three, which one feels most like what you’re dealing with right now?'\n\n"

            "# Simplified Pitch\n"
            "1. What Vertex Does:\n"
            "   → 'So, just so you know what we do: at Vertex, we connect realtors directly with homeowners who are already planning to sell. "
            "We’re not talking about random internet leads — these are real people ready to move.'\n\n"

            "2. Problem → Solution:\n"
            "   - If they said 'inconsistent months': 'We smooth that out by sending steady, ready-to-sell homeowners.'\n"
            "   - If they said 'wasted time': 'Instead of chasing people who never list, we only send folks already planning to sell.'\n"
            "   - If they said 'too much on their plate': 'We take prospecting off your plate, so you just focus on closings.'\n\n"

            "3. Bandwidth Question:\n"
            "   → 'If we helped you close 2–4 more deals a month like that, would you actually have room to take them on?'\n\n"

            "# Booking Rules\n"
            "- After they say yes, immediately pivot:\n"
            "   → 'Perfect — let’s grab 15 minutes so we can show you how it works. What time zone are you in?'\n"
            "- Must always ask for their time zone first.\n"
            "- If they don’t know their time zone:\n"
            "   → Ask for their city or location.\n"
            "   → If they live in a country with multiple time zones (like USA/Canada), ask for their state/province.\n"
            "   → If single-zone country, confirm based on the country.\n"
            "- Never book today’s date — push for nearest available day.\n"
            "- Ask if they prefer morning or afternoon.\n"
            "- Offer exactly two slots. Confirm which one works.\n"
            "- Always collect email:\n"
            "   → Ask: 'What’s the best email for the invite?'\n"
            "   → Do not interrupt; allow them to spell it fully.\n"
            "   → Without email = failed booking.\n"
            "- Read back appointment details once.\n"
            "- Tell them: 'You’ll get a confirmation email in a few hours' → confirm they’ll check it.\n"
            "- Ask: 'Is there anything that would prevent you from attending this meeting?'\n\n"

            "# Qualification\n"
            "- Ask: 'Is your main goal buyers, sellers, listings, or just whatever brings in cash?'\n"
            "- Adapt pitch based on their answer.\n\n"

            "# Behavioral Rules\n"
            "- Always sound natural: use fillers ('um,' 'you know,' 'like,' 'so yeah').\n"
            "- Keep sentences short unless explanation is required.\n"
            "- Wait where instructed.\n"
            "- If music or no response detected, politely hang up.\n"
            "- Never parrot their words unless needed.\n"
            "- Always pivot back to value and booking.\n\n"

            "# Guardrails\n"
            "- Do not deviate from your role as Caleb the cold caller.\n"
            "- If the user asks unrelated/off-topic questions, politely redirect: "
            "'That’s a great question, but let’s stay focused on how Vertex can help you close more deals.'\n"
            "- Never discuss topics outside of real estate appointment booking.\n\n"

            "# Objection Handling\n"
            "- Not interested/busy → use hook: '2 deals in 90 days with no legwork.'\n"
            "- Wants email/website → qualify what they want, then redirect to call booking.\n"
            "- Cost/upfront → say depends on market/business. If pressed: 'risk free, we work for free until results delivered.'\n"
            "- Already working with someone → ask if satisfied. If not: 'we can be an add-on, not a replacement.'\n\n"

            "# Success Criteria\n"
            "You only succeed if:\n"
            "1. Appointment is booked with date, time zone (or location-derived), slot, and full spelled-out email.\n"
            "2. Prospect confirms they’ll attend.\n"
            "3. Prospect acknowledges Vertex offers real sellers, not just random leads.\n"
        )
        super().__init__(
            tools=[
                function_tool(
                    self._set_profile_field_func_for("first_name"),
                    name="set_first_name",
                    description="Call this function when user has provided their phone number."),
                function_tool(
                    self._set_profile_field_func_for("last_name"),
                    name="set_last_name",
                    description="Call this function when user has provided their last name."
                ),
                function_tool(
                    self._set_profile_field_func_for("email"),
                    name="set_email",
                    description="Call this function when user has provided their email."
                ),
                function_tool(
                    self._set_profile_field_func_for("phone"),
                    name="set_phone",
                    description="Call this function when user has provided their phone number."
                ),
                function_tool(
                    self._save_to_db(),
                    name="save_info_to_db",
                    description="Call this function when success criteria is met."
                )
  
            ],
            instructions= instructions
            
        )
        
        
    
        

    async def on_enter(self) -> None:
        self.session.generate_reply()

    def _set_profile_field_func_for(self, field: str):
        async def set_value(context: RunContext, value: str):
            setattr(self.prospect, field, value)
            return 
        return set_value
    
    def _save_to_db(self):
        async def save(context: RunContext):
            return await save_prospect_to_db(self.prospect)
        return save

       



def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=1.3,
        prefix_padding_duration=0.2,
        max_buffered_speech=500.0,
        activation_threshold=0.45,
        sample_rate=16000,
        force_cpu=True,
    )
    logger.info("Silero VAD prewarmed")

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    usage_collector = metrics.UsageCollector()
    
    pid = "f2a45c3c-22f9-4d2f-9a87-b9f7a07b9e8c"
    prospect = await get_prospect_from_db(pid)
    print(prospect)

    if prospect:
        logger.info(f"Fetched Prospect: {prospect.to_dict()}")
    else:
        logger.warning("Prospect not found.")
        
    
    
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        llm=await get_llm(),
        stt=await get_stt(),
        tts=await get_tts()
    )

    @session.on("agent_false_interruption")
    def _on_false_interruption(ev):
        logger.info("False positive interruption detected, resuming.")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage summary: {summary}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=DemoAgent(prospect),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
        room_output_options=RoomOutputOptions(
            transcription_enabled=True,
        ),
    )

def custom_load_func(worker):
    try:
        m = int(get_env_var("MAX_JOBS") or 1)
    except Exception:
        m = 1
    a = len(worker.active_jobs)
    return min(a / m, 1.0) if m > 0 else 1.0

if __name__ == "__main__":
    logger.info("Starting LiveKit Interview Agent Worker...")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            load_fnc=custom_load_func,
            load_threshold=1.0,
            ws_url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
            max_retry=18,
            initialize_process_timeout=30.0,
        )
    )
