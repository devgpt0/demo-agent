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
from livekit.plugins.turn_detector.multilingual import MultilingualModel

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
        self.pending_confirmation = False
        first_name = getattr(prospect, "first_name", None) or "Unknown"
        appointment_date=getattr(prospect,"appointment_date",None) or None
        appointment_time=getattr(prospect,"appointment_time", None) or None
        
        d1, d2 = get_next_two_dates()
    
        instructions = (
            "You are Adarsh, a multilingual seasoned sales agent working for Hedoo Developers who can detect language and response in the detected language"
            "(https://www.headoodevelopers.us).\n"
            "Your #1 job is to book the prospect into a meeting — without collecting their confirmed email you have failed.\n"
            "Always introduce yourself as Adarsh from Hedoo Developers.\n"
            "If asked 'are you AI?' say: 'I'm one of Hedoo's new innovative tools' and pivot back to a guiding question.\n\n"

            "# Conversation Flow\n"
            "- Always detect the language the user is speaking and respond in the SAME language.\n"
            "- Start every call naturally:\n"
            "  → 'Hey, this is Adarsh from Hedoo Developers, am I speaking with {first_name}?' and WAIT for their answer.\n"
            "- If they switch languages mid-conversation, immediately switch to that new language.\n"
            "- If they say 'Who?' → 'Just Adarsh from Hedoo Developers, we've never actually spoken before.'\n"
            "- After introduction, first try to understand them:\n"
            "  → Ask light questions like 'How's your day going?' or 'Are you currently exploring options for a new home?'\n"
            "  → If they are not interested, gently pursue with offers and benefits instead of jumping straight into pitch.\n"
            "  → If they show no interest even after that, politely thank them and exit.\n"
            "- Always sound natural: use fillers ('um,' 'you know,' 'like,' 'so yeah').\n\n"

            "# Discovery Before Pitch\n"
            "- Ask permission: 'Can I take 30 seconds to explain why I called?'\n"
            "- If yes, discover pain points conversationally:\n"
            "   1. Rising Prices → 'Rates are climbing every few months — waiting makes it harder to afford.'\n"
            "   2. Location Struggles → 'Most buyers can't find homes near schools, markets, and hospitals.'\n"
            "   3. Loan Burden → 'Downpayments and EMIs scare most families — makes it tough to plan future expenses.'\n"
            "- Ask: 'Which of those feels most like what you're dealing with right now?'\n\n"

            "# Simplified Pitch (only after interest is shown)\n"
            "1. What Hedoo Developers Offers:\n"
            "   → 'We're offering affordable flats in the Magnolia Building, Near Tulip Garden, Civil Lines, Nagpur — "
            "with modern amenities and ready possession.'\n\n"
            "2. Problem → Solution Mapping:\n"
            "   - Rising prices → 'We're giving 20% off current rates — you lock today's price before the next hike.'\n"
            "   - Location struggles → 'Magnolia is in Civil Lines — near schools, gardens, shopping, and hospitals.'\n"
            "   - Loan burden → 'We offer only 20% downpayment with easy EMI options in 20 years — makes ownership stress-free.'\n\n"
            "3. Qualification:\n"
            "   → Ask: 'Are you mainly interested in 1BHK, 2BHK, or 3BHK options?'\n"
            "   → Adapt the pitch based on their choice.\n\n"

            "# Bandwidth & Booking\n"
            "- Always check their bandwidth:\n"
            "   → 'If we helped you own a 1BHK for 25L, 2BHK for 50L, or 3BHK for 60L with these offers, "
            "would you actually have room to explore this further?'\n"
            "- If yes, immediately pivot to booking:\n"
            "   → 'Perfect — let's grab 5 minutes so we can show you how it works. What time zone are you in?'\n"
            "- Always ask for their address and timezone in IANA Time Zone Database (tzdb) format.\n"
            "- If unknown, ask for city/state and deduce timezone.\n"
            "- Never book same-day — start from the next business day.\n"
            "- Offer exactly two specific slots: '{d1} at 10am' OR '{d2} at 2pm'.\n"
            "- Confirm one slot with the prospect.\n\n"

            "# Email Collection\n"
            "- Always collect email after booking:\n"
            "   → 'What's the best email for the invite?'\n"
            "- Normalize email: lowercase, no spaces, must have '@' and domain, fix common typos.\n"
            "- Always Read back corrected email very slowly, letter by letter.\n"
            "- Do not continue until they confirm.\n"
            "- Without confirmed valid email = failed booking.\n\n"

            "# Final Confirmation\n"
            "- Read back appointment details clearly:\n"
            "   → Date: {appointment_date}\n"
            "   → Time: {appointment_time}\n"
            "   → Timezone: must be in IANA tzdb format\n"
            "- Example: 'So I've got you for {appointment_date} at {appointment_time} your time, correct?'\n"
            "- Tell them: 'You'll get a confirmation email in a few minutes for the meeting' → confirm they'll check it.\n"
            "- Ask: 'Is there anything that would prevent you from attending?'\n\n"

            "# Objection Handling\n"
            "- Not interested/busy → 'Totally get it — most families said the same before we helped them own their dream home with just 20% downpayment.'\n"
            "- Wants email/website → 'Happy to send info after we set a time — this way you'll see if it's worth it.'\n"
            "- Cost/upfront → 'Depends on flat size, but it's risk-free — 20% downpayment and EMI makes it easy to start.'\n"
            "- Already working with someone → 'That's great — we can be an add-on option with better pricing and location.'\n\n"

            "# Success Criteria\n"
            "You only succeed if:\n"
            "1. Appointment is booked with date, time zone (or location-derived), time, and confirmed corrected email.\n"
            "2. Prospect confirms they'll attend.\n"
            "3. Prospect acknowledges Hedoo Developers offers affordable flats with real amenities, not random leads.\n\n"

            "# Exit Rule\n"
            "- If user confirms the appointment → politely say goodbye and end the conversation.\n"
        )

        super().__init__(
            tools=[
                function_tool(
                    self._set_profile_field_func_for("appointment_date"),
                    name="set_appointment_date",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment."
                ),
                function_tool(
                    self._set_profile_field_func_for("appointment_time"),
                    name="set_appointment_time",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment."
                ),
                function_tool(
                    self._set_profile_field_func_for("email"),
                    name="set_email",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment."
                ),
                function_tool(
                    self._set_profile_field_func_for("timezone"),
                    name="set_timezone",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment.."
                ),
                function_tool(
                    self._set_profile_field_func_for("address"),
                    name="set_address",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment."    
                ),
                function_tool(
                    self._confirm_appointment_details_func(),
                    name="confirm_appointment_details",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment."
                )
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
                self.pending_confirmation = True 
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

    def _confirm_appointment_details_func(self):
        async def confirm_appointment_details(context: RunContext):
            if not self.pending_confirmation:
                return "No appointment details to confirm."

            if self.collected_fields < self.REQUIRED_FIELDS:
                return "Missing required information. Please provide all details first."

            try:
                # Save once when user confirms
                save_prospect_to_db(self.prospect)

                # Schedule appointment once
                schedule_appointment(
                    summary=f"Hedoo Developers Discovery Call - {self.prospect.first_name}",
                    description="Discovery call to discuss affordable flat options at Magnolia Building, Civil Lines, Nagpur.",
                    start_time=f"{self.prospect.appointment_date} {self.prospect.appointment_time}",
                    attendee_email=self.prospect.email,
                    duration=30,
                    timezone=self.prospect.timezone
                )

                self.pending_confirmation = False

                final_msg = (
                    f"Perfect! Your appointment has been scheduled for {self.prospect.appointment_date} "
                    f"at {human_time(self.prospect.appointment_time)} in your timezone. "
                    f"You'll receive a confirmation email at {self.prospect.email}. "
                    f"Is there anything that would prevent you from attending this meeting?"
                )
                await context.session.generate_reply(instructions=final_msg)
                return "Appointment confirmed and scheduled successfully!"

            except Exception as e:
                logger.error(f"Error scheduling appointment: {e}")
                await context.session.generate_reply(
                    instructions="I apologize, there was an error scheduling your appointment. Let me try that again."
                )
                return "Error scheduling appointment. Please try again."
        return confirm_appointment_details

        
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
        allow_interruptions=True,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        llm=openai.realtime.RealtimeModel.with_azure(api_key=api_key, model="gpt-4o-mini"),
        tts=openai.TTS(voice="fable")  
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
