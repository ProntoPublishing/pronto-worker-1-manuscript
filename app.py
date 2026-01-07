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
from flask import Flask, request, jsonify
from pronto_worker_1 import ManuscriptProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'worker_1_manuscript_processor',
        'version': '4.1.0'
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

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
