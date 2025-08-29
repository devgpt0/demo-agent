import asyncio
from typing import Optional
from models.prospect import Prospect
from utils.agent_utils.llm_strategy import get_llm
from utils.agent_utils.stt_strategy import get_stt
from utils.agent_utils.tts_strategy import get_tts
from utils.monitoring_utils.logging import get_logger
from utils.config_utils.env_loader import get_env_var
from utils.config_utils.config_loader import get_config
from utils.data_utils.date_utils import parse_date,get_next_two_dates
from utils.data_utils.time_utils import parse_time_str,human_time
from repository.prospect_repository import get_prospect_from_db, save_prospect_to_db
from book_appointment import schedule_appointment
from livekit import rtc, api
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
    get_job_context,
    function_tool,
    cli,
    metrics,
)
from livekit.plugins import silero
from livekit.plugins import noise_cancellation
import datetime

logger = get_logger("interview-agent")

# Load configuration
LIVEKIT_API_KEY       = get_config("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET    = get_config("LIVEKIT_API_SECRET")
LIVEKIT_URL           = get_config("LIVEKIT_URL", default="wss://livekit.example.com", required=False)
ENV                   = get_env_var("ENV", default="dev")
OUTBOUND_TRUNK_ID     = get_env_var("SIP_OUTBOUND_TRUNK_ID")

class DemoAgent(Agent):
    
    REQUIRED_FIELDS = {"appointment_date", "appointment_time", "email", "timezone"}
    
    def __init__(self, prospect) -> None:

        self.prospect = prospect 
        self.collected_fields = set()
        first_name = getattr(prospect, "first_name", None) or "Unknown"
        appointment_date=getattr(prospect,"appointment_date",None) or None
        appointment_time=getattr(prospect,"appointment_time", None) or None
        
        d1, d2 = get_next_two_dates()
    
        instructions = (
            "You are Caleb, a seasoned cold caller working for Vertex Media (https://www.vertexmedia.us).\n"
            "Your #1 job is to book the prospect into a meeting — without collecting their confirmed email you have failed.\n"
            "Always introduce yourself as Caleb from Vertex Media.\n"
            "If asked 'are you AI?' say: 'I’m one of Vertex's new innovative tools' and pivot back to a guiding question.\n\n"

            "# Conversation Flow Rules\n"
            f"- Start every call:\n"
            f"  → 'Hey is this {first_name}?' and WAIT for their answer.\n"
            "  → If they say 'Who?' → 'Just Caleb from Vertex, we’ve never actually spoken before.'\n"
            "  → Always ask: 'Can I take 20 seconds to explain why I called?'\n\n"

            "- Pain Point Discovery:\n"
            "  Explain realtor pain points in plain words so they feel understood:\n"
            "    1. Inconsistent Months → 'One month slammed, the next dead — makes it tough to plan bills or staff.'\n"
            "    2. Wasted Time → 'You probably spend hours with people who never list — that time could’ve gone to real deals.'\n"
            "    3. Too Much on Their Plate → 'Most agents I talk to are buried in showings, follow-ups, paperwork — never enough hours in the day.'\n"
            "  → Then ask: 'Which of those feels most like what you’re dealing with right now?'\n\n"

            "# Simplified Pitch\n"
            "1. What Vertex Does:\n"
            "   → 'At Vertex, we connect realtors with homeowners already planning to sell — not random internet leads, but real sellers.'\n\n"

            "2. Problem → Solution:\n"
            "   - If inconsistent months: 'We smooth that out with steady, ready-to-sell homeowners.'\n"
            "   - If wasted time: 'Instead of chasing, you only talk to sellers already planning to list.'\n"
            "   - If too busy: 'We take prospecting off your plate so you focus on closings.'\n\n"

            "3. Bandwidth Question:\n"
            "   → 'If we helped you close 2–4 more deals a month like that, would you actually have room to take them on?'\n\n"

            "# Booking Rules\n"
            "- After they say yes, immediately pivot:\n"
            "   → 'Perfect — let’s grab 5 minutes so we can show you how it works. What time zone are you in?'\n"
            "- Must always ask for their time zone first.\n"
            "- If unknown, ask for city/state. Deduce timezone if possible.\n"
            "- Never book today — start from the next business day.\n"
            f"- Offer exactly two specific options: '{d1} at 10am' OR '{d2} at 2pm'.\n"
            "- Confirm one slot with the prospect.\n\n"

            "- Always collect email:\n"
            "   → Ask: 'What’s the best email for the invite?'\n"
            "   → Do not interrupt; allow them to finish.\n"
            "   → If unclear: 'Can you spell that out for me so I don’t make a mistake?'\n"
            "   ->If there are numbers in the email id ,write them as numbers"
            "   → Normalize email: lowercase, remove spaces, ensure '@' and domain, fix common typos.\n"
            "   → Read back corrected email very slowly letter by letter.'\n"
            "   → Do not continue until they confirm.\n"
            "   → Without confirmed valid email = failed booking.\n\n"

            "- Read back appointment details once in clear format:\n"
            f"   → Date: {appointment_date}\n"
            f"   → Time: {appointment_time}\n"
            "   → Include timezone.\n"
            f"- Example: 'So I’ve got you for {appointment_date} at {appointment_time} your time, correct?'\n"
            "- Tell them: 'You’ll get a confirmation email in a few minutes for a meeting' → confirm they’ll check it.\n"
            "- Ask: 'Is there anything that would prevent you from attending?'\n\n"

            "# Qualification\n"
            "- Ask: 'Is your main goal buyers, sellers, listings, or just whatever brings in cash?'\n"
            "- Adapt pitch to their answer.\n\n"

            "# Behavioral Rules\n"
            "- Always sound natural: use fillers ('um,' 'you know,' 'like,' 'so yeah').\n"
            "- Keep sentences short.\n"
            "- Wait where instructed.\n"
            "- If music/no response, politely hang up.\n"
            "- Never parrot unless needed.\n"
            "- Always pivot back to value + booking.\n\n"

            "# Guardrails\n"
            "- Stay in role as Caleb the cold caller.\n"
            "- If user goes off-topic: 'That’s a good question, but let’s stay focused on how Vertex can help you close more deals.'\n"
            "- Never discuss non–real estate topics.\n\n"

            "# Objection Handling\n"
            "- Not interested/busy → 'Totally get it — most agents said the same before we helped them close 2 extra deals in 90 days.'\n"
            "- Wants email/website → 'Happy to send info after we set a time — this way you’ll see if it’s worth it.'\n"
            "- Cost/upfront → 'Depends on market, but it’s risk-free — we work for free until results are delivered.'\n"
            "- Already working with someone → 'That’s great — we can be an add-on, not a replacement.'\n\n"

            "# Success Criteria\n"
            "You only succeed if:\n"
            "1. Appointment is booked with date, time zone (or location-derived), time, and confirmed corrected email.\n"
            "2. Prospect confirms they’ll attend.\n"
            "3. Prospect acknowledges Vertex offers real sellers, not just random leads.\n"
        )
       
        
        super().__init__(
            tools=[
                function_tool(
                    self._set_profile_field_func_for("appointment_date"),
                    name="set_appointment_date",
                    description="Call this function when user has booked appointement date."),
                function_tool(
                    self._set_profile_field_func_for("appointment_time"),
                    name="set_appointment_time",
                    description="Call this function when user has booked appointment time."
                ),
                function_tool(
                    self._set_profile_field_func_for("email"),
                    name="set_email",
                    description="Call this function when user has provided their email."
                ),
                function_tool(
                    self._set_profile_field_func_for("timezone"),
                    name="set_timezone",

                    description="Call this function when user has provided their location or timezone."
                ),
               

            ],
            instructions= instructions
        )
        
    
    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant
        
    async def hangup(self):
        """Helper function to hung up the call by deleting the room"""
        job_ctx = get_job_context()
        
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(
                room = job_ctx.room.name
            )
        )
        
    
    
    @function_tool()
    async def end_call(self, ctx:RunContext):
        """Called when the user wants to end the call"""
        logger.info(f"ending the call for {self.participant.identity}")
        
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()
            
        await self.hangup()
        
    
    @function_tool()
    async def detected_answering_machine(self, ctx:RunContext):
        """Called when the call reaches voicemail.Use this tool after you hear the voice mail greeting"""
        logger.info(f"detected answering machine for {self.participant.identity}")
        await self.hangup()
    
    async def on_enter(self) -> None:
        self.session.generate_reply()

    
    def _set_profile_field_func_for(self, field: str):
        async def set_value(context: RunContext, value: str):
            # Ensure self.prospect exists
            if self.prospect is None:
                self.prospect = Prospect()

            if field == "appointment_date":
                setattr(self.prospect, field, parse_date(value))
            elif field == "appointment_time":
                setattr(self.prospect, field, parse_time_str(value))
            else:
                setattr(self.prospect, field, value)

            # Save to DB
            save_prospect_to_db(self.prospect)

            # Track completion
            self.collected_fields.add(field)

            # If all required fields collected, confirm with user
            if self.collected_fields >= self.REQUIRED_FIELDS:
                confirmation_msg = (
                    f"Great! I've noted everything down.\n"
                    f"Here's what I have:\n"
                    f"- Date: {self.prospect.appointment_date}\n"
                    f"- Time: {human_time(self.prospect.appointment_time)}\n"
                    f"- Timezone: {self.prospect.timezone}\n"
                    f"- Email: {self.prospect.email}\n\n"
                    f"Can you confirm these details are correct?"
                )
                await context.session.generate_reply(instructions=confirmation_msg)

            return
        return set_value


        
    def _save_to_db(self):
        def save(context: RunContext):
            return save_prospect_to_db(self.prospect)
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
    logger.info(f"Connecting to room {ctx.room.name}")
    ctx.log_context_fields = {"room": ctx.room.name}
    await ctx.connect()
    
    usage_collector = metrics.UsageCollector()
    
    pid = "f2a45c3c-22f9-4d2f-9a87-b9f7a07b9e8c"
    prospect = get_prospect_from_db(pid)
    logger.info(prospect)
    
    participant_identity=prospect.phone

    if prospect:
        logger.info(f"Fetched Prospect: {prospect.to_dict()}")
    else:
        logger.warning("Prospect not found.")
        
    participant_identity=prospect.phone
    
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        llm=await get_llm(),
        stt=await get_stt(),
        tts=await get_tts()
    )
    
    
    session_started = asyncio.create_task(
        session.start(
            agent=DemoAgent(prospect),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVC(),
            ),
            room_output_options=RoomOutputOptions(
                transcription_enabled=True,
            ),
        )
    )
    
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbount_trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                wait_until_answered=True
            )
        )

        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"participant joined:{participant_identity}")
        agent.set_participant(participant)
    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant:{e.message},"
            f"SIP status:{e.metadata.get('sip_status_code')}"
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()
    
    
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


    async def cleanup():
        pid = "f2a45c3c-22f9-4d2f-9a87-b9f7a07b9e8c"
        prospect = get_prospect_from_db(pid)

        schedule_appointment(
            summary="Vertex Media Discovery Call",
            description="Intro call to show how Vertex helps realtors with consistent seller leads.",
            start_time= f"{prospect.appointment_date} {prospect.appointment_time}",
            attendee_email=prospect.email,
            duration=30,
            timezone=prospect.timezone
        )

    ctx.add_shutdown_callback(cleanup)



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
