from __future__ import annotations
import datetime
import asyncio
import logging
from dotenv import load_dotenv
import json
import os
from typing import Any,Optional
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
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    get_job_context,
    cli,
    WorkerOptions,
    RoomInputOptions,
)
from livekit.plugins import (
    deepgram,
    openai,
    cartesia,
    silero,
    aws,
    noise_cancellation,  # noqa: F401
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel


# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")


class DemoAgent(Agent):

    REQUIRED_FIELDS = {"appointment_date", "appointment_time", "email", "timezone"}

    def __init__(self,prospect)->None:
        
        self.prospect = prospect 
        self.collected_fields = set()
        self.pending_confirmation = False # New flag to track confirmation state
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
            "- Always ask for their time zone in IANA Time Zone Database (tzdb) format.\n"
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
                    description="Call this function when user has booked appointment date.",
                ),
                function_tool(
                    self._set_profile_field_func_for("appointment_time"),
                    name="set_appointment_time",
                    description="Call this function when user has booked appointment time.",
                ),
                function_tool(
                    self._set_profile_field_func_for("email"),
                    name="set_email",
                    description="Call this function when user has provided their email.",
                ),
                function_tool(
                    self._set_profile_field_func_for("timezone"),
                    name="set_timezone",
                    description="Call this function when user has provided their timezone.",
                ),
                function_tool(
                    self._set_profile_field_func_for("address"),
                    name="set_address",
                    description="Call this function when user has provided their address.",
                ),
                function_tool(
                    self._confirm_appointment_details_func(),
                    name="confirm_appointment_details",
                    description="Call this function when user confirms the appointment details are correct. This will schedule the actual appointment.",
                ),
            ],
            instructions=instructions,
        )

            # keep reference to the participant for transfers
        self.participant: rtc.RemoteParticipant | None = None

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant

    async def on_enter(self) -> None:
        self.session.generate_reply()
    
    def _set_profile_field_func_for(self, field: str):
        async def set_value(context: RunContext, value: str):
            if self.prospect is None:
                self.prospect = Prospect()

            if field == "appointment_date":
                setattr(self.prospect, field, parse_date(value))
            elif field == "appointment_time":
                setattr(self.prospect, field, parse_time_str(value))
            else:
                setattr(self.prospect, field, value)

            # Do NOT save to DB here
            self.collected_fields.add(field)

            # Check if all required fields are gathered
            if self.collected_fields >= self.REQUIRED_FIELDS and not self.pending_confirmation:
                self.pending_confirmation = True
                confirmation_msg = (
                    f"Great! Here's what I have:\n"
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
    
    
    async def hangup(self):
        """Helper function to hang up the call by deleting the room"""

        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(
                room=job_ctx.room.name,
            )
        )

    
    @function_tool()
    async def transfer_call(self, ctx: RunContext):
        """Transfer the call to a human agent, called after confirming with the user"""

        transfer_to = self.dial_info["transfer_to"]
        if not transfer_to:
            return "cannot transfer call"

        logger.info(f"transferring call to {transfer_to}")

        # let the message play fully before transferring
        await ctx.session.generate_reply(
            instructions="let the user know you'll be transferring them"
        )

        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=self.participant.identity,
                    transfer_to=f"tel:{transfer_to}",
                )
            )

            logger.info(f"transferred call to {transfer_to}")
        except Exception as e:
            logger.error(f"error transferring call: {e}")
            await ctx.session.generate_reply(
                instructions="there was an error transferring the call."
            )
            await self.hangup()

    @function_tool()
    async def end_call(self, ctx: RunContext):
        """Called when the user wants to end the call"""
        logger.info(f"ending the call for {self.participant.identity}")

        # let the agent finish speaking
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()

        await self.hangup()

    @function_tool()
    async def look_up_availability(
        self,
        ctx: RunContext,
        date: str,
    ):
        """Called when the user asks about alternative appointment availability

        Args:
            date: The date of the appointment to check availability for
        """
        logger.info(
            f"looking up availability for {self.participant.identity} on {date}"
        )
        await asyncio.sleep(3)
        return {
            "available_times": ["1pm", "2pm", "3pm"],
        }

    @function_tool()
    async def confirm_appointment(
        self,
        ctx: RunContext,
        date: str,
        time: str,
    ):
        """Called when the user confirms their appointment on a specific date.
        Use this tool only when they are certain about the date and time.

        Args:
            date: The date of the appointment
            time: The time of the appointment
        """
        logger.info(
            f"confirming appointment for {self.participant.identity} on {date} at {time}"
        )
        return "reservation confirmed"

    @function_tool()
    async def detected_answering_machine(self, ctx: RunContext):
        """Called when the call reaches voicemail. Use this tool AFTER you hear the voicemail greeting"""
        logger.info(f"detected answering machine for {self.participant.identity}")
        await self.hangup()


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
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()


    dial_info = json.loads(ctx.job.metadata)
    participant_identity = phone_number = dial_info["phone_number"]

    pid = "f2a45c3c-22f9-4d2f-9a87-b9f7a07b9e8c"
    prospect = get_prospect_from_db(pid)
    print(prospect)

    agent=DemoAgent(prospect)
    
    session = AgentSession(
        allow_interruptions=True,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        
        llm=openai.realtime.RealtimeModel(
            modalities=["text"]
        ),
        tts=openai.TTS(voice="fable")  
    )

    # start the session first before dialing, to ensure that when the user picks up
    # the agent does not miss anything the user says
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )

    # `create_sip_participant` starts dialing the user
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                wait_until_answered=True,
            )
        )

        # wait for the agent session start and participant join
        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"participant joined: {participant.identity}")

        agent.set_participant(participant)

    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()


def custom_load_func(worker):
    try:
        m = int(get_env_var("MAX_JOBS") or 1)
    except Exception:
        m = 1
    a = len(worker.active_jobs)
    return min(a / m, 1.0) if m > 0 else 1.0

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            agent_name="outbound-caller",
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            load_fnc=custom_load_func,
            load_threshold=1.0,
            max_retry=18,
            initialize_process_timeout=30.0,
        )
    )