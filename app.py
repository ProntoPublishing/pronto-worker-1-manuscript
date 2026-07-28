"""
Worker 1 Web Server Wrapper
============================

Simple Flask server that exposes Worker 1 as a webhook endpoint.
This allows Railway to deploy it as a web service.

Endpoints:
- GET /health - Health check
- POST /process - Process a service (expects {"service_id": "recXXX"})
"""

import os
import json
import logging
import threading
from flask import Flask, request, jsonify
from pronto_worker_1 import ManuscriptProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Queue poller arm state (order 9N2x9xK). ARMED by default since
# 2026-07-28: the stale Paid+Met backlog (8Najakz-MANUSCRIPT) was
# dispositioned to Pending at the mapping sitting. Exactly 'true'
# arms; env QUEUE_POLL_ENABLED overrides either way.
QUEUE_POLL_DEFAULT = 'true'


def _queue_poll_enabled():
    return os.getenv('QUEUE_POLL_ENABLED',
                     QUEUE_POLL_DEFAULT).lower() == 'true'


def _list_ready_services(processor):
    """Queue-poll doorbell (order 9N2x9xK, W6 Finding-7 pattern):
    MANUSCRIPT services at Status=Paid with dependencies Met. W1 has
    no lib client — the query rides the processor's Services table.
    Returns [(record_id, fields), ...]."""
    formula = ("AND({Status}='Paid', {Met}=1, "
               "FIND('-MANUSCRIPT', {Service Instance ID}))")
    try:
        records = processor.services_table.all(formula=formula)
    except Exception as e:
        logger.error(f"queue poll failed: {e}")
        return []
    return [(r["id"], r.get("fields", {})) for r in records]


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    from pronto_worker_1 import WORKER_VERSION, RULES_VERSION
    return jsonify({
        'status': 'healthy',
        'service': 'worker_1_manuscript_processor',
        'version': WORKER_VERSION,
        'rules_version': RULES_VERSION,
        'queue_poll': _queue_poll_enabled(),
    })

@app.route('/process', methods=['POST'])
def process():
    """
    Process a service record.
    
    Expects JSON body:
    {
        "service_id": "recXXXXXXXXXXXXXX"
    }
    """
    # Doc 08 secret contract (retrofit 2026-07-19): 503 when the server
    # has no secret configured, 401 on missing or wrong header. Same
    # gap as W2 — the header was never checked.
    secret = os.getenv('WEBHOOK_SECRET')
    if not secret:
        logger.error("WEBHOOK_SECRET is not configured")
        return jsonify({'success': False,
                        'error': 'Server missing WEBHOOK_SECRET configuration'}), 503
    if request.headers.get('X-Webhook-Secret') != secret:
        return jsonify({'success': False, 'error': 'Invalid webhook secret'}), 401

    try:
        data = request.get_json()

        if not data or 'service_id' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing service_id in request body'
            }), 400

        service_id = data['service_id']
        logger.info(f"Processing service: {service_id}")

        # Initialize processor and process service
        processor = ManuscriptProcessor()
        result = processor.process_service(service_id)
        
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 500
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ---------------------------------------------------------------------------
# Order 9N2x9xK: the QUEUE POLLER — W6's Finding-7 doorbell, fleet-wide.
# Every QUEUE_POLL_SECONDS, pick up any MANUSCRIPT service at Status=Paid
# with Met=1 and run it through process_service, which enforces its own
# already-Complete/Processing guard + claim; a concurrent POST claim
# flips Status first and the loser no-ops.
# ---------------------------------------------------------------------------

def _queue_poller():
    interval = int(os.getenv('QUEUE_POLL_SECONDS', '120'))
    import time
    time.sleep(15)                       # let boot settle
    logger.info(f"queue poller up: every {interval}s "
                f"(Status=Paid + Met=1 + -MANUSCRIPT)")
    processor = None
    while True:
        try:
            if processor is None:
                processor = ManuscriptProcessor()
            ready = _list_ready_services(processor)
            for service_id, fields in ready:
                instance = fields.get('Service Instance ID', service_id)
                logger.info(f"queue poll: picking up {instance} "
                            f"({service_id})")
                result = processor.process_service(service_id)
                logger.info(f"queue poll: {instance} -> "
                            f"{result.get('status', result)}")
        except Exception:
            logger.exception("queue poller iteration failed")
            processor = None             # rebuild clients next round
        time.sleep(interval)


if _queue_poll_enabled():
    threading.Thread(target=_queue_poller, daemon=True,
                     name="queue-poller").start()
else:
    logger.info("queue poller present but DISARMED "
                "(set QUEUE_POLL_ENABLED=true to arm)")


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
