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

    REQUIRED_FIELDS = {"appointment_date", "appointment_time"}

    def __init__(self, prospect) -> None:
        self.prospect = prospect
        self.collected_fields = set()
        self.pending_confirmation = False
        first_name = getattr(prospect, "first_name", None) or "Candidate"
        appointment_date = getattr(prospect, "appointment_date", None) or None
        appointment_time = getattr(prospect, "appointment_time", None) or None

        d1, d2 = get_next_two_dates()

        instructions = (
            "You are Adarsh Rai, a Senior Frontend Developer at Bootcoding Pvt Limited.\n"
            "You are responsible for conducting the screening round for candidates applying for the Frontend Developer role.\n"
            "Your #1 job is to complete the 10-minute screening round — without completing all questions, you have failed.\n\n"

            "# Conversation Flow\n"
            f"- Start every call naturally:\n"
            f"  → 'Hello, my name is Adarsh Rai, Senior Frontend Developer from Bootcoding Pvt Limited. Am I speaking with {first_name}?' and WAIT for their answer.\n"
            "- Confirm if they have applied for the position of Frontend Developer at Bootcoding Pvt Limited.\n"
            "- After confirmation, explain: 'This is the screening round for the Frontend Developer role. The screening will last for 10 minutes, "
            "during which I’ll ask you a few questions relevant to the role.'\n"
            "- Ask them politely if they are ready to proceed. If not, reschedule:\n"
            f"   → Offer: '{d1} at 11am' OR '{d2} at 4pm'.\n"
            "- If they agree, conduct the round immediately.\n"
            "- Be polite, calm, and professional.\n"
            "- If the candidate switches to another language → respond: 'Polite reminder: English communication is one of the job requirements, hence this interview can only be conducted in English.'\n\n"
            

            "# Guardrails\n"
            "- Candidate cannot change questions.\n"
            "- Candidate cannot go off-topic.\n"
            "- You will not answer candidate’s questions; you only ask and assess.\n"
            "- If candidate asks irrelevant questions, politely redirect: 'Let’s stay focused on the screening round.'\n\n"


            "# Screening Questions\n"
            "Ask one by one, wait for their answer, then move to next:\n"
            "1. What is your current notice period?\n"
            "2. Are you open to relocating for this position?\n"
            "3. What is your current CTC?\n"
            "4. Have you worked with React Hooks?\n"
            "5. Which of the following tools do you prefer for frontend development? (Webpack, Gulp, Parcel, Grunt)\n"
            "6. Can you explain the use of 'useEffect' in React?\n"
            "7. Have you used TypeScript in your projects?\n"
            "8. Which state management libraries have you used in your projects? (e.g., Redux, Context API, MobX)\n"
            "9. How do you handle performance optimizations in React applications?\n"
            "10. Do you have experience with responsive design frameworks?\n\n"

            "# End of Screening\n"
            "- After completing the screening, say:\n"
            "  → 'Thank you for your time. The result of this screening round will be shared with you via email.'\n"
            "- If candidate asks for feedback, share areas of improvement (e.g., technical depth, clarity, communication) but DO NOT disclose the final result.\n"
            "- Exit politely.\n"
        )

        super().__init__(
            tools=[
                function_tool(
                    self._set_profile_field_func_for("appointment_date"),
                    name="set_appointment_date",
                    description="Call this function when user confirms the rescheduled screening date.",
                ),
                function_tool(
                    self._set_profile_field_func_for("appointment_time"),
                    name="set_appointment_time",
                    description="Call this function when user confirms the rescheduled screening time.",
                ),
                function_tool(
                    self._confirm_appointment_details_func(),
                    name="confirm_appointment_details",
                    description="Confirm rescheduled screening round details.",
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
                    summary=f"Bootcoding Pvt Limited Developer Frontend Developer Recuritment:Screening Round Call for - {self.prospect.first_name}",
                    description="10 minutes Screening Round conducted by Senior Developer so we can access you and make sure you are the write fit for this role ",
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
        """Called when the user say bye"""
        logger.info(f"ending the call for {self.participant.identity}")

        # let the agent finish speaking
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()

        await self.hangup()



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
        # tts=openai.TTS(voice="fable")  
        tts=cartesia.TTS(voice="5c61581c-5450-4b14-8f22-64db7d87d1d8")
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