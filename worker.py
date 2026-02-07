"""
Job Worker - Processes jobs from Redis queue.

This worker polls Redis for pending jobs and executes them.
"""

import os
import sys
import time
import signal
import logging
from uuid import UUID
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from database import SessionLocal
from agents.job_manager import JobManager
from agents.llm_proxy import LLMProxy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    logger.info("Shutdown signal received, finishing current job...")
    running = False


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def process_job(job_id: str, job_type: str) -> bool:
    """
    Process a single job.

    Args:
        job_id: Job UUID
        job_type: Job type

    Returns:
        True if successful, False otherwise
    """
    db = SessionLocal()

    try:
        job_manager = JobManager(db)

        # Get job details
        job = job_manager.get_job(UUID(job_id))

        if not job:
            logger.error(f"Job {job_id} not found")
            return False

        # Update to RUNNING
        job_manager.update_job_status(
            job_id=UUID(job_id),
            new_status="RUNNING"
        )
        db.commit()

        logger.info(f"Processing job {job_id} (type: {job_type}, attempt: {job['attempt_count']})")

        # Process based on job type
        if job_type == "llm_call":
            result = process_llm_job(db, job)
        elif job_type == "data_analysis":
            result = process_analysis_job(db, job)
        else:
            logger.warning(f"Unknown job type: {job_type}, marking as completed")
            result = {"status": "completed", "message": f"Job type {job_type} processed"}

        # Mark as completed
        job_manager.update_job_status(
            job_id=UUID(job_id),
            new_status="COMPLETED",
            result=result
        )
        db.commit()

        logger.info(f"✅ Job {job_id} completed successfully")
        return True

    except Exception as e:
        logger.error(f"❌ Job {job_id} failed: {e}")

        try:
            # Mark as failed
            job_manager.update_job_status(
                job_id=UUID(job_id),
                new_status="FAILED",
                result={"error": str(e)}
            )
            db.commit()
        except Exception as update_error:
            logger.error(f"Failed to update job status: {update_error}")
            db.rollback()

        return False

    finally:
        db.close()


def process_llm_job(db, job) -> dict:
    """Process LLM call job."""
    payload = job["payload"]

    # Extract parameters
    messages = payload.get("messages", [])
    model_id = payload.get("model_id")
    model_config = payload.get("model_config")

    if not messages:
        raise ValueError("No messages in job payload")

    # Call LLM
    llm_proxy = LLMProxy(db)

    response = llm_proxy.call(
        session_id=UUID(job["session_id"]),
        messages=messages,
        model_id=model_id,
        model_config=model_config
    )

    return {
        "type": "llm_response",
        "content": response["content"],
        "model": response["model_id"],
        "usage": response["usage"],
        "latency_ms": response["latency_ms"]
    }


def process_analysis_job(db, job) -> dict:
    """Process data analysis job (mock implementation)."""
    payload = job["payload"]

    # Simulate analysis
    time.sleep(2)

    return {
        "type": "analysis_result",
        "dataset": payload.get("dataset"),
        "analysis_type": payload.get("analysis_type"),
        "summary": "Analysis completed successfully",
        "insights": ["Mock insight 1", "Mock insight 2"],
        "processed_at": time.time()
    }


def worker_loop():
    """Main worker loop."""
    logger.info("🚀 Worker started - polling for jobs...")

    import redis
    redis_password = os.getenv('REDIS_PASSWORD')
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', '6379')),
        password=redis_password if redis_password else None,
        db=0,
        decode_responses=True
    )

    # Job types to poll (in priority order)
    job_types = ["llm_call", "data_analysis", "general-query"]

    poll_count = 0

    while running:
        try:
            # Round-robin through job types
            for job_type in job_types:
                if not running:
                    break

                # Try to dequeue from the correct queue
                queue_name = f"job_queue:{job_type}"

                result = redis_client.blpop(queue_name, timeout=1)

                if result:
                    import json
                    _, job_json = result
                    job_message = json.loads(job_json)

                    logger.info(f"Dequeued job {job_message['job_id']} from {queue_name}")

                    # Process the job
                    success = process_job(
                        job_id=job_message["job_id"],
                        job_type=job_message["job_type"]
                    )

                    if success:
                        poll_count = 0  # Reset counter on successful processing

                    break  # Restart loop to prioritize new jobs
            else:
                # No jobs found, sleep briefly
                poll_count += 1

                if poll_count % 10 == 0:
                    logger.debug(f"No jobs found, still polling... ({poll_count} attempts)")

                time.sleep(1)

        except Exception as e:
            logger.error(f"Worker error: {e}")
            time.sleep(5)

    logger.info("👋 Worker stopped gracefully")


if __name__ == "__main__":
    try:
        worker_loop()
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
        sys.exit(0)
