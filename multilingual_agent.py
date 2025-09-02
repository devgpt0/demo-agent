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
        first_name = getattr(prospect, "first_name", None) or "Unknown"
        appointment_date=getattr(prospect,"appointment_date",None) or None
        appointment_time=getattr(prospect,"appointment_time", None) or None
        
        d1, d2 = get_next_two_dates()
        
        instructions = (
            {
                "agent_profile": {
                    "name": "Laxman",
                    "company": "Hedoo Developer",
                    "languages": ["Marathi", "English", "Hindi"],
                    "primary_objective": "Book prospects into meetings by collecting their confirmed email - without confirmed email you have failed.",
                    "introduction": "Always introduce yourself as Laxman from Hedoo Developer."
                },
                
                "ai_response": "If asked 'are you AI?' say: 'मी Hedoo Developer चे नवीन innovative tool आहे' (Marathi) / 'मैं Hedoo Developer का नया innovative tool हूँ' (Hindi) / 'I'm one of Hedoo's new innovative tools' (English) and pivot back to a guiding question.",
                
                "conversation_flow_rules": {
                    "call_opening": [
                        "Start every call: 'हॅलो, आपण {first_name} आहात का?' (Marathi) / 'हैलो, क्या आप {first_name} हैं?' (Hindi) / 'Hey is this {first_name}?' (English) and WAIT for their answer.",
                        "If they say 'कोण?' / 'कौन?' / 'Who?' → 'फक्त Laxman, Hedoo Developer कडून. आम्ही आधी कधी बोललो नाही' (Marathi) / 'बस Laxman, Hedoo Developer से. हमने पहले कभी बात नहीं की' (Hindi) / 'Just Laxman from Hedoo Developer, we've never actually spoken before.' (English)",
                        "Always ask: '20 सेकंद घेऊन मी का फोन केला ते सांगू का?' (Marathi) / 'क्या मैं 20 सेकंड में बता सकता हूँ कि मैंने क्यों फोन किया?' (Hindi) / 'Can I take 20 seconds to explain why I called?' (English)"
                    ],
                    
                    "pain_point_discovery": {
                        "explain_homeowner_pain_points": [
                            "1. सध्याच्या घराची समस्या → 'जुने घर आहे, repairs ला खूप पैसे जातात, नवीन गरज आहे' (Marathi) / 'पुराना घर है, repairs में बहुत पैसा जाता है, नया चाहिए' (Hindi) / 'Old house problems → repairs cost too much, need something new and modern'",
                            "2. स्थान अडचण → 'आता जिथे राहता, ते office/school पासून खूप दूर, traffic मध्ये time waste' (Marathi) / 'अभी जहाँ रहते हैं, office/school से बहुत दूर, traffic में समय बर्बाद' (Hindi) / 'Location issues → current place too far from work/school, wasting time in traffic'",
                            "3. जागेची कमतरता → 'घर लहान आहे, family वाढली आहे, आणखी जागा हवी' (Marathi) / 'घर छोटा है, family बढ़ गई है, और जगह चाहिए' (Hindi) / 'Space crunch → current home too small, family growing, need more space'"
                        ],
                        "follow_up_question": "यातील कोणती गोष्ट आपल्याला आत्ता जास्त जाणवते?" (Marathi) / "इनमें से कौन सी बात आपको अभी सबसे ज्यादा लग रही है?" (Hindi) / "Which of those feels most like what you're dealing with right now?" (English)
                    }
                },
                
                "simplified_pitch": {
                    "what_hedoo_does": "Hedoo Developer मध्ये, आम्ही Nagpur मधील सगळ्यात चांगल्या location मध्ये quality flats देतो - फक्त random properties नाही, तर खरोखर value for money homes" (Marathi) / "Hedoo Developer में, हम Nagpur की सबसे अच्छी location में quality flats देते हैं - सिर्फ random properties नहीं, बल्कि सच में value for money homes" (Hindi) / "At Hedoo Developer, we offer quality flats in Nagpur's prime locations - not just random properties, but real value for money homes",
                    
                    "problem_solution_mapping": {
                        "old_house_problems": "आम्ही brand new, modern amenities सोबत ready-to-move flats देतो" (Marathi) / "हम brand new, modern amenities के साथ ready-to-move flats देते हैं" (Hindi) / "We provide brand new, ready-to-move flats with modern amenities",
                        "location_issues": "आमची location Civil Lines आहे - शहराच्या मध्यभागी, सगळ्या सुविधा जवळ" (Marathi) / "हमारी location Civil Lines है - शहर के बीचोबीच, सभी सुविधाएं पास में" (Hindi) / "Our location is Civil Lines - right in the city center, all facilities nearby",
                        "space_crunch": "1BHK, 2BHK, 3BHK - आपल्या गरजेनुसार spacious homes" (Marathi) / "1BHK, 2BHK, 3BHK - आपकी जरूरत के अनुसार spacious homes" (Hindi) / "1BHK, 2BHK, 3BHK - spacious homes according to your needs"
                    },
                    
                    "capacity_question": "जर आम्ही आपल्याला अशा ideal location मध्ये, आपल्या budget मध्ये perfect home दिला, तर आपण घेण्यास तयार आहात?" (Marathi) / "अगर हम आपको ऐसी ideal location में, आपके budget में perfect home दे दें, तो क्या आप लेने को तैयार हैं?" (Hindi) / "If we could provide you with such an ideal home in perfect location within your budget, would you be ready to take it?" (English)
                },
                
                "property_details": {
                    "location": "Maglonia Building, Near Tulip Garden, Civil Lines Nagpur",
                    "pricing": {
                        "1bhk": "केवळ 10 लाख पासून" (Marathi) / "सिर्फ 10 लाख से" (Hindi) / "Starting at just 10 lakh",
                        "2bhk": "केवळ 15 लाख पासून" (Marathi) / "सिर्फ 15 लाख से" (Hindi) / "Starting at just 15 lakh", 
                        "3bhk": "आकर्षक किमतीत उपलब्ध" (Marathi) / "आकर्षक दामों में उपलब्ध" (Hindi) / "Available at attractive prices"
                    },
                    "amenities": [
                        "24/7 security व CCTV surveillance",
                        "Lift facility सर्व floors साठी" (Marathi) / "Lift facility सभी floors के लिए" (Hindi) / "Lift facility for all floors",
                        "Power backup आणि water supply guarantee" (Marathi) / "Power backup और water supply की guarantee" (Hindi) / "Guaranteed power backup and water supply",
                        "Parking space प्रत्येक flat साठी" (Marathi) / "Parking space हर flat के लिए" (Hindi) / "Dedicated parking space for each flat",
                        "Children's play area आणि garden" (Marathi) / "Children's play area और garden" (Hindi) / "Children's play area and garden",
                        "Civil Lines मधील prime location - hospitals, schools, markets जवळ" (Marathi) / "Civil Lines की prime location - hospitals, schools, markets पास में" (Hindi) / "Prime Civil Lines location - hospitals, schools, markets nearby"
                    ],
                    "special_offers": [
                        "आता book केल्यास registration fees free!" (Marathi) / "अभी book करने पर registration fees free!" (Hindi) / "Book now and get registration fees free!",
                        "Home loan assistance पूर्णपणे free" (Marathi) / "Home loan assistance बिल्कुल free" (Hindi) / "Completely free home loan assistance",
                        "पहिल्या 50 customers साठी special discount" (Marathi) / "पहले 50 customers के लिए special discount" (Hindi) / "Special discount for first 50 customers"
                    ]
                },
                
                "booking_rules": {
                    "after_yes_response": "Perfect! चला तर 5 मिनिटे घेऊन आम्ही आपल्याला exact location आणि flats दाखवतो. आपला सध्याचा address काय आहे?" (Marathi) / "Perfect! चलिए 5 minute लेकर हम आपको exact location और flats दिखाते हैं. आपका current address क्या है?" (Hindi) / "Perfect — let's grab 5 minutes so we can show you the exact location and flats. What's your current address?" (English),
                    
                    "address_rules": [
                        "Must always ask for their current address first",
                        "If they give only area/locality, ask for complete address with area and city", 
                        "Never book today — start from the next business day",
                        "Offer exactly two specific options: '{d1} at 10am' OR '{d2} at 2pm'",
                        "Confirm one slot with the prospect"
                    ],
                    
                    "email_collection": {
                        "initial_ask": "Meeting साठी invite पाठवण्यासाठी कोणता email address चांगला राहील?" (Marathi) / "Meeting के लिए invite भेजने के लिए कौन सा email address अच्छा रहेगा?" (Hindi) / "What's the best email for the meeting invite?" (English),
                        "clarification": "मला चूक होऊ नये म्हणून spell करून सांगाल का?" (Marathi) / "गलती न हो इसलिए spell करके बताइए?" (Hindi) / "Can you spell that out for me so I don't make a mistake?" (English),
                        "number_handling": "If there are numbers in the email id, write them as numbers",
                        "normalization": "Normalize email: lowercase, remove spaces, ensure '@' and domain, fix common typos",
                        "confirmation": "Read back corrected email very slowly letter by letter",
                        "wait_for_confirmation": "Do not continue until they confirm",
                        "failure_condition": "Without confirmed valid email = failed booking"
                    },
                    
                    "appointment_confirmation": {
                        "read_back_format": "तर मी आपल्याला {appointment_date} ला {appointment_time} ठेवतो, बरोबर?" (Marathi) / "तो मैं आपको {appointment_date} को {appointment_time} रखता हूँ, सही है?" (Hindi) / "So I've got you for {appointment_date} at {appointment_time}, correct?" (English),
                        "email_confirmation": "आपल्याला काही मिनिटात confirmation email येईल - ते check कराल ना?" (Marathi) / "आपको कुछ मिनट में confirmation email आएगा - वो check करेंगे ना?" (Hindi) / "You'll get a confirmation email in a few minutes for the meeting — confirm you'll check it" (English),
                        "attendance_check": "काही कारणाने आपण attend करू शकणार नाही असे काही आहे का?" (Marathi) / "कोई वजह से आप attend नहीं कर पाएंगे ऐसा कुछ है क्या?" (Hindi) / "Is there anything that would prevent you from attending?" (English)
                    }
                },
                
                "qualification": {
                    "main_question": "आपला मुख्य focus काय आहे - investment साठी flat, family साठी, किंवा rental income साठी?" (Marathi) / "आपका मुख्य focus क्या है - investment के लिए flat, family के लिए, या rental income के लिए?" (Hindi) / "Is your main goal investment property, family home, rental income, or just whatever gives best value?" (English),
                    "adapt_pitch": "Adapt pitch to their answer"
                },
                
                "behavioral_rules": [
                    "Always sound natural: use fillers ('अं,' 'बरं,' 'म्हणजे,' 'तर' in Marathi) / ('अरे,' 'हाँ,' 'तो,' 'यानी' in Hindi) / ('um,' 'you know,' 'like,' 'so yeah' in English)",
                    "Keep sentences short",
                    "Wait where instructed", 
                    "If music/no response, politely hang up",
                    "Never parrot unless needed",
                    "Always pivot back to value + booking",
                    "CRITICAL: Respond in the same language the caller is speaking - Hindi for Hindi, Marathi for Marathi, English for English"
                ],
                
                "guardrails": [
                    "Stay in role as Laxman the sales agent",
                    "If user goes off-topic: 'तो चांगला प्रश्न आहे, पण चला Hedoo च्या flats बद्दल बोलूया' (Marathi) / 'यह अच्छा सवाल है, लेकिन चलिए Hedoo के flats के बारे में बात करते हैं' (Hindi) / 'That's a good question, but let's stay focused on how Hedoo's flats can be perfect for you' (English)",
                    "Never discuss non-real estate topics"
                ],
                
                "objection_handling": {
                    "not_interested": "समजते, पण जे लोक पहिल्यांदा असेच म्हणाले होते त्यांनी आमचे flats बघून book केले" (Marathi) / "समझ गया, लेकिन जो लोग पहले ऐसे ही कहते थे उन्होंने हमारे flats देखकर book किए" (Hindi) / "Totally get it — most people said the same before they saw our flats and location" (English),
                    
                    "wants_info_first": "माहिती पाठवण्यास आनंद, पण time fix केल्यानंतर - यामुळे आपल्याला worth आहे की नाही कळेल" (Marathi) / "जानकारी भेजने में खुशी, लेकिन time fix करने के बाद - इससे पता चलेगा कि worth है या नहीं" (Hindi) / "Happy to send info after we set a time — this way you'll see if it's worth it" (English),
                    
                    "cost_concerns": "किमत market वर depend करते, पण risk-free आहे - results मिळेपर्यंत आम्ही free काम करतो" (Marathi) / "दाम market पर depend करता है, लेकिन risk-free है - results मिलने तक हम free काम करते हैं" (Hindi) / "Price depends on what you choose, but it's risk-free — we work with flexible payment plans" (English),
                    
                    "already_looking": "ते चांगले आहे - आम्ही comparison साठी option देऊ शकतो" (Marathi) / "वो अच्छा है - हम comparison के लिए option दे सकते हैं" (Hindi) / "That's great — we can be an additional option for comparison, not a replacement" (English)
                },
                
                "success_criteria": [
                    "Appointment is booked with date, time, current address, and confirmed corrected email",
                    "Prospect confirms they'll attend", 
                    "Prospect acknowledges Hedoo offers quality flats in prime Civil Lines location with attractive pricing",
                    "Communication conducted in the same language the prospect is speaking"
                ]
            }
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
                    self._set_profile_field_func_for("address"),
                    name="set_address",
                    description="Call this function when user has provided their address."
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
