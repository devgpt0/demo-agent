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



# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")


class DemoAgent(Agent):

    REQUIRED_FIELDS = {"appointment_date", "appointment_time", "email", "timezone"}

    def __init__(self,prospect)->None:
        
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
            "  → 'Perfect — let’s grab 5 minutes so we can show you how it works. What time zone are you in?'\n"
            "- Must always ask for their time zone first and always store in IANA Time Zone Database format(tzdb).\n"
            "- If unknown, ask for city/state. Deduce timezone in IANA Time Zone Database (tzdb) format if possible.\n"
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
            "   → Include timezone strictly in IANA Time Zone Database (tzdb) format\n"
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
        # keep reference to the participant for transfers
        self.participant: rtc.RemoteParticipant | None = None

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant

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
                schedule_appointment(
                    summary=f"Vertex Media Discovery Call-{self.prospect.first_name}",
                    description="Intro call to show how Vertex helps realtors with consistent seller leads.",
                    start_time= f"{prospect.appointment_date} {prospect.appointment_time}",
                    attendee_email=prospect.email,
                    duration=30,
                    timezone=prospect.timezone
                )
                await context.session.generate_reply(instructions=confirmation_msg)
            
            
            return
        return set_value

    
    
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
    logger.info(f"dial info from json:{dial_info}")
    participant_identity = phone_number = dial_info["phone_number"]

    pid = "f2a45c3c-22f9-4d2f-9a87-b9f7a07b9e8c"
    prospect = get_prospect_from_db(pid)
    print(prospect)

    agent=DemoAgent(prospect)
    
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        llm=openai.LLM(model="gpt-4o"),
        stt=deepgram.STT(),
        tts=cartesia.TTS(voice="8fb675e3-6c4c-4074-8266-18594a45c34e")
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