"""
queue_dispatcher.py — Asynchronous Job Runner
Handles batching for warm-up messages, daily follow-ups, and Friday cleanup.

Can be run as an independent background daemon: `python -m execution.queue_dispatcher`
"""

import os
import time
import random
import logging
from datetime import datetime, timezone
import asyncio

from dotenv import load_dotenv

from execution.manage_leads import get_leads_by_status
from execution.send_whatsapp import send_warm_up, config as wa_config

# Import conversational agent carefully in case it's missing
try:
    from execution.conversational_agent import generate_system_followup
except ImportError:
    def generate_system_followup(*args, **kwargs):
        pass

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

WARMUP_BLOCK_SIZE = int(os.getenv("WARMUP_BLOCK_SIZE", "25"))
WARMUP_GAP_MIN = int(os.getenv("WARMUP_BLOCK_GAP_MINUTES", "90"))
MIN_DELAY = int(os.getenv("WARMUP_MIN_DELAY_SECONDS", "45"))
MAX_DELAY = int(os.getenv("WARMUP_MAX_DELAY_SECONDS", "90"))
FOLLOWUP_THROTTLE_HOURS = int(os.getenv("FOLLOWUP_THROTTLE_HOURS", "24"))


def process_warmup_queue():
    """
    Finds up to WARMUP_BLOCK_SIZE leads in 'cover_generated' status.
    Sends warm_ups with randomized delays between MIN_DELAY and MAX_DELAY.
    """
    # Check if we are inside business hours to even bother starting a block
    if not wa_config["is_window_open"]():
        logger.info("Outside Send Window. Pausing warm-up dispatch.")
        return False

    queue = get_leads_by_status("cover_generated")
    if not queue:
        logger.debug("No leads in cover_generated status.")
        return False
        
    batch = queue[:WARMUP_BLOCK_SIZE]
    logger.info("Found %d leads. Starting warm-up batch of size %d.", len(queue), len(batch))
    
    for idx, lead in enumerate(batch):
        # Double check window because the batch might take a long time
        if not wa_config["is_window_open"]():
            logger.info("Send window closed mid-batch. Halting warm-ups.")
            break
            
        logger.info("Sending warm-up to lead %d (batch item %d/%d)", lead["id"], idx+1, len(batch))
        send_warm_up(lead["whatsapp_number"], lead["id"])
        
        # Delay before next message, unless it's the last one
        if idx < len(batch) - 1:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            logger.info("Sleeping %d seconds before next warm-up...", delay)
            time.sleep(delay)
            
    return True


def process_followup_queue():
    """
    Finds leads awaiting response and triggers the agent to follow-up.
    Only runs Tue-Fri. Checks if we haven't followed up today already.
    On Friday end-of-day, triggers friday_cleanup mode.
    """
    if not wa_config["is_window_open"]():
        return
        
    now = datetime.now()
    weekday = now.weekday() # 0 = Monday, 4 = Friday
    
    if weekday == 0 or weekday > 4:
        # No follow-ups on Monday or Weekends
        return
        
    is_friday = (weekday == 4)
    hour = now.hour
    
    # Are we in the last hour of the Friday send window? (Cleanup time)
    window_end_hour = int(os.getenv("WHATSAPP_SEND_WINDOW_END", "18:00").split(":")[0])
    is_friday_cleanup = is_friday and (hour >= window_end_hour - 1)
    
    if is_friday_cleanup:
        logger.info("Initiating Friday End-of-Week Cleanup...")
        
    # Get all active targets
    active_statuses = ["message_sent", "awaiting_response"]
    if is_friday_cleanup:
        # Also clean up dead warm-ups
        active_statuses.append("warm_up_sent")
        
    for status in active_statuses:
        leads = get_leads_by_status(status)
        for lead in leads:
            # Throttle: Check last_lead_reply_at and updated_at to ensure max 1 follow-up per day
            # (In a bulletproof app we'd track last_system_followup_at, but updated_at works for MVP)
            # If Friday cleanup, we force evaluation.
            
            updated_str = lead.get("updated_at")
            if updated_str:
                try:
                    updated_dt = datetime.fromisoformat(updated_str).replace(tzinfo=None)
                    hours_since_update = (now - updated_dt).total_seconds() / 3600
                    if hours_since_update < FOLLOWUP_THROTTLE_HOURS and not is_friday_cleanup:
                        continue # Already touched recently
                except:
                    pass
            
            logger.info("Triggering Agent Follow-Up for lead %d (status: %s)", lead["id"], status)
            generate_system_followup(lead["id"], is_friday_cleanup=is_friday_cleanup)
            time.sleep(random.randint(15, 30)) # Rate limit OpenAI + Z-API slightly

def main_loop():
    """
    Infinite daemon loop.
    Checks queues every minute. Handles batching logic.
    """
    logger.info("Queue Dispatcher started.")
    
    while True:
        try:
            # Run follow ups (checks its own internal rules)
            process_followup_queue()
            
            # Check warm up queue
            did_warmups = process_warmup_queue()
            
            if did_warmups:
                # We just processed a block. Sleep for gap time.
                logger.info("Warm-up batch finished. Sleeping %d minutes before next block.", WARMUP_GAP_MIN)
                time.sleep(WARMUP_GAP_MIN * 60)
            else:
                # Sleep briefly before checking again
                time.sleep(60)
                
        except KeyboardInterrupt:
            logger.info("Dispatcher stopped by user.")
            break
        except Exception as e:
            logger.error("Dispatcher loop error: %s", e)
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
