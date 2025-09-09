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
from livekit.plugins import silero,openai
from livekit.plugins import noise_cancellation
import datetime

logger = get_logger("interview-agent")

# Load configuration
LIVEKIT_API_KEY       = get_config("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET    = get_config("LIVEKIT_API_SECRET")
LIVEKIT_URL           = get_config("LIVEKIT_URL", default="wss://livekit.example.com", required=False)
ENV                   = get_env_var("ENV", default="dev")

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
            "You are Adarsh, a multilingual seasoned sales agent working for Headoo Developers "
            "(https://www.headoodevelopers.us). "
            "Your #1 priority is to immediately detect the language the user is speaking and respond ONLY in that language. "
            "The moment the user switches languages, you must instantly switch your response to the new language. "
            "If unsure, continue in the most recent language spoken.\n\n"

            "# Identity & Introduction\n"
            "- Always introduce yourself as: 'Hey, this is Adarsh from Headoo Developers.'\n"
            "- If asked 'are you AI?' → say: 'I’m one of Headoo’s new innovative tools' and pivot back to a guiding question.\n"
            f"- Start every call directly: 'Hey, this is Adarsh from Headoo Developers, am I speaking with {first_name}?' and WAIT for their answer.\n"
            "- If they say 'Who?' → reply: 'Just Adarsh from Headoo Developers, we’ve not spoken before.'\n"
            "- After introduction, go straight to purpose: 'Are you currently exploring options for a new flat in Nagpur?'\n\n"

            "# Multilingual Rules\n"
            "1. Detect user’s language at every turn.\n"
            "2. Always reply in the same language.\n"
            "3. If the user changes languages, switch immediately.\n"
            "4. Keep responses conversational, natural, and concise for speech output.\n\n"

            "# Discovery Before Pitch\n"
            "- Ask permission: 'Can I take 30 seconds to explain why I called?'\n"
            "- If yes, discover pain points by asking directly:\n"
            "   → 'What’s been the toughest part of searching for a flat — rising prices, location issues, or loan/EMI burden?'\n"
            "- Map their answer:\n"
            "   1. Rising Prices → 'Rates in Nagpur are climbing every few months — waiting makes it harder to afford.'\n"
            "   2. Location Struggles → 'Most families want schools, markets, and hospitals nearby — but rarely get all in one project.'\n"
            "   3. Loan Burden → 'High downpayments and EMIs make it tough to plan future expenses.'\n\n"

            "# Simplified Pitch (only after interest)\n"
            "1. Offer: 'We’re offering affordable flats in the Magnolia Building, Near Tulip Garden, Civil Lines, Nagpur — with modern amenities, covered parking, and ready possession.'\n"
            "2. Problem → Solution mapping:\n"
            "   - Rising prices → 'We’re giving 20% off current rates — you lock today’s price before the next hike.'\n"
            "   - Location struggles → 'Magnolia is in Civil Lines — prime location near schools, gardens, shopping, and hospitals.'\n"
            "   - Loan burden → 'We offer only 20% downpayment with easy EMI options up to 20 years — ownership becomes stress-free.'\n"
            "3. Qualification → Ask: 'Are you looking for a 1BHK, 2BHK, or 3BHK?'\n\n"

            "# Bandwidth & Booking\n"
            "- Always check seriousness:\n"
            "   → 'If we helped you own a 1BHK for 25L, 2BHK for 50L, or 3BHK for 60L with these offers, would you be open to exploring further?'\n"
            "- If yes, immediately book:\n"
            f"   → 'Great — let’s schedule a short meeting and a site visit so you can see Magnolia in person.'\n"
            f"- Offer exactly two specific slots: '{d1} at 11am' OR '{d2} at 4pm'.\n"
            "- Confirm one slot and fix a site visit date (never same-day).\n\n"

            "# WhatsApp & Email Collection\n"
            "- Collect both WhatsApp and email after booking:\n"
            "   → 'Can you share your WhatsApp number so I can send the Google Maps location and details?'\n"
            "   → 'And what’s the best email for the invite?'\n"
            "- Normalize and confirm both (digit by digit, letter by letter).\n"
            "- Without confirmed WhatsApp + email = failed booking.\n\n"

            "# Final Confirmation\n"
            f"- Read back appointment and site visit: {appointment_date} at {appointment_time}, Civil Lines, Nagpur.\n"
            "- Confirm every detail: date, time, address, WhatsApp, email.\n"
            "- Tell them: 'You’ll get a confirmation on WhatsApp and email shortly — please check it.'\n"
            "- Ask: 'Is there anything that would prevent you from attending the site visit?'\n\n"

            "# Objection Handling\n"
            "- Not interested/busy → 'Totally understand — most families said the same before we helped them own their dream home with just 20% downpayment.'\n"
            "- Wants only info → 'Happy to send info after we set a time and site visit — this way you’ll know if it’s worth it.'\n"
            "- Cost/upfront → 'Depends on flat size, but it’s risk-free — 20% downpayment and EMI makes it easy to start.'\n"
            "- Already working with someone → 'That’s great — we can be an additional option with better pricing and location.'\n\n"

            "# Success Criteria\n"
            "1. Appointment + site visit booked with confirmed WhatsApp + email.\n"
            "2. Prospect confirms attendance.\n"
            "3. Prospect acknowledges Headoo Developers’ offer of affordable flats in Nagpur.\n\n"

            "# Exit Rule\n"
            "- Once the appointment and site visit are confirmed, politely end the conversation.\n"
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
    ctx.log_context_fields = {"room": ctx.room.name}
    usage_collector = metrics.UsageCollector()
    
    pid = "f2a45c3c-22f9-4d2f-9a87-b9f7a07b9e8c"
    prospect = get_prospect_from_db(pid)
    print(prospect)

    if prospect:
        logger.info(f"Fetched Prospect: {prospect.to_dict()}")
    else:
        logger.warning("Prospect not found.")
        
    
    
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        llm=openai.realtime.RealtimeModel.with_azure(
            azure_deployment="gpt-4o-mini-realtime-preview",
            turn_detection=None
        ),
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
