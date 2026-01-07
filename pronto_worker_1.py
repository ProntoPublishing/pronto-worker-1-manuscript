"""
Pronto Worker 1 - Manuscript Processor v4.1.0 (Canon-Compliant)
================================================================

Extracts structured content from manuscript files (DOCX, PDF, TXT) and produces
manuscript.v1.json artifacts conforming to the Pronto Artifacts Registry.

CANONICAL CHANGES IN v4.1.0:
- Reads manuscript from linked Manuscripts table (not direct URL field)
- Writes to generic Artifact URL and Artifact Key fields
- Uses canonical Status values: Processing → Complete/Failed
- Uses canonical Error Log field (not Error Message)
- Implements proper status lifecycle: claim → process → complete
- Ignores non-canonical Statuses (plural) field

Key Features:
- Blocks-based output (14 block types with inline marks)
- Warning detection (10 warning codes with severity levels)
- Schema validation before upload
- R2 storage with proper public URLs
- Lineage tracking and artifact hashing
- Airtable integration for status updates

Architecture:
- Input: Manuscript file from linked Manuscripts table
- Processing: Extract → Analyze → Structure → Validate
- Output: manuscript.v1.json artifact in R2
- Side effects: Update Airtable Service record

Author: Pronto Publishing
Version: 4.1.0
Date: 2026-01-05
"""

import os
import sys
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

# Third-party imports
import requests
from docx import Document
import PyPDF2
from pyairtable import Api

# Local imports
from lib.pronto_r2_client import ProntoR2Client
from lib.block_extractor import BlockExtractor
from lib.warning_detector import WarningDetector
from lib.artifact_builder import ArtifactBuilder
from lib.artifact_validator import validate_artifact

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
AIRTABLE_TOKEN = os.getenv('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.getenv('AIRTABLE_BASE_ID')
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'pronto-artifacts')
R2_PUBLIC_BASE_URL = os.getenv('R2_PUBLIC_BASE_URL')  # e.g., https://artifacts.prontopublishing.com

# Worker metadata
WORKER_VERSION = "4.1.0"
WORKER_NAME = "worker_1_manuscript_processor"


class ManuscriptProcessor:
    """Main processor for manuscript files."""
    
    def __init__(self):
        """Initialize processor with clients and utilities."""
        self.airtable = Api(AIRTABLE_TOKEN)
        self.base = self.airtable.base(AIRTABLE_BASE_ID)
        self.services_table = self.base.table('Services')
        self.manuscripts_table = self.base.table('Manuscripts')
        
        self.r2_client = ProntoR2Client(
            account_id=R2_ACCOUNT_ID,
            access_key_id=R2_ACCESS_KEY_ID,
            secret_access_key=R2_SECRET_ACCESS_KEY,
            bucket_name=R2_BUCKET_NAME,
            public_base_url=R2_PUBLIC_BASE_URL
        )
        
        self.block_extractor = BlockExtractor()
        self.warning_detector = WarningDetector()
        self.artifact_builder = ArtifactBuilder(
            worker_name=WORKER_NAME,
            worker_version=WORKER_VERSION
        )
    
    def process_service(self, service_id: str) -> Dict[str, Any]:
        """
        Process a single service record.
        
        Args:
            service_id: Airtable record ID for the service
            
        Returns:
            Processing result with status and artifact URL
        """
        logger.info(f"Processing service: {service_id}")
        
        try:
            # 1. Fetch service record
            service = self.services_table.get(service_id)
            logger.info(f"Fetched service: {service['fields'].get('Service Type')}")
            
            # 2. CANONICAL: Claim the service by setting Status to Processing
            self._claim_service(service_id)
            
            # 3. CANONICAL: Get manuscript file URL from linked Manuscripts table
            file_url = self._get_manuscript_url(service)
            if not file_url:
                raise ValueError("No manuscript file found in linked Manuscripts record")
            
            logger.info(f"Found manuscript URL: {file_url}")
            
            # 4. Download manuscript file
            file_path = self._download_file(file_url)
            logger.info(f"Downloaded file: {file_path}")
            
            # 5. Extract blocks
            blocks, source_meta = self.block_extractor.extract(file_path)
            logger.info(f"Extracted {len(blocks)} blocks")
            
            # 6. Detect warnings
            warnings = self.warning_detector.detect(blocks, source_meta)
            logger.info(f"Detected {len(warnings)} warnings")
            
            # 7. Build artifact
            artifact = self.artifact_builder.build(
                blocks=blocks,
                warnings=warnings,
                source_meta=source_meta,
                service_id=service_id
            )
            
            # 8. Validate artifact
            validation_result = validate_artifact(artifact, "manuscript", "1.0")
            if not validation_result['valid']:
                raise ValueError(f"Artifact validation failed: {validation_result['errors']}")
            
            logger.info("Artifact validation passed")
            
            # 9. Upload to R2
            artifact_key = f"services/{service_id}/manuscript.v1.json"
            upload_result = self.r2_client.upload_json(artifact_key, artifact)
            
            logger.info(f"Uploaded artifact: {upload_result['public_url']}")
            
            # 10. CANONICAL: Update Airtable with Complete status
            self._complete_service(
                service_id=service_id,
                artifact_url=upload_result['public_url'],
                artifact_key=artifact_key,
                warnings=warnings
            )
            
            return {
                'success': True,
                'service_id': service_id,
                'artifact_url': upload_result['public_url'],
                'artifact_key': artifact_key,
                'warnings_count': len(warnings),
                'blocks_count': len(blocks)
            }
            
        except Exception as e:
            logger.error(f"Processing failed: {str(e)}")
            logger.error(traceback.format_exc())
            
            # CANONICAL: Update Airtable with Failed status
            self._fail_service(
                service_id=service_id,
                error_message=str(e)
            )
            
            return {
                'success': False,
                'service_id': service_id,
                'error': str(e)
            }
    
    def _get_manuscript_url(self, service: Dict[str, Any]) -> Optional[str]:
        """
        CANONICAL: Get manuscript file URL from linked Manuscripts table.
        
        Args:
            service: Service record from Airtable
            
        Returns:
            URL of the manuscript file, or None if not found
        """
        # Get linked Manuscripts record IDs
        manuscripts_links = service['fields'].get('Manuscripts', [])
        
        if not manuscripts_links:
            logger.error("No Manuscripts linked to this Service")
            return None
        
        # Get the first linked Manuscripts record
        manuscript_id = manuscripts_links[0]
        logger.info(f"Fetching Manuscripts record: {manuscript_id}")
        
        manuscript = self.manuscripts_table.get(manuscript_id)
        
        # Get the attachment URL from the Uploaded Manuscript File field
        attachments = manuscript['fields'].get('Uploaded Manuscript File', [])
        
        if not attachments:
            logger.error("No file attached to Manuscripts record")
            return None
        
        # Return the URL of the first attachment
        return attachments[0]['url']
    
    def _download_file(self, url: str) -> str:
        """Download file from URL to temp directory."""
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        # Determine file extension from URL or Content-Type
        ext = Path(url).suffix or '.bin'
        temp_path = f"/tmp/manuscript_{datetime.now().timestamp()}{ext}"
        
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return temp_path
    
    def _claim_service(self, service_id: str):
        """
        CANONICAL: Claim the service by setting Status to Processing.
        This provides operational visibility and prevents concurrent processing.
        """
        fields = {
            # NOTE: Only use 'Status' (singular), never 'Statuses' (plural)
            'Status': 'Processing',
            'Started At': datetime.now(timezone.utc).isoformat(),
            'Worker Version': WORKER_VERSION
        }
        
        self.services_table.update(service_id, fields)
        logger.info(f"Claimed service {service_id}: Status → Processing")
    
    def _complete_service(
        self,
        service_id: str,
        artifact_url: str,
        artifact_key: str,
        warnings: List[Dict]
    ):
        """
        CANONICAL: Mark service as Complete and store outputs.
        Uses generic Artifact URL and Artifact Key fields.
        """
        fields = {
            # NOTE: Only use 'Status' (singular), never 'Statuses' (plural)
            'Status': 'Complete',
            'Finished At': datetime.now(timezone.utc).isoformat(),
            # CANONICAL: Write to generic artifact fields
            'Artifact URL': artifact_url,
            'Artifact Key': artifact_key,
            'Artifact Type': 'manuscript_json'
        }
        
        if warnings:
            # Store warning summary
            warning_summary = {
                'total': len(warnings),
                'by_severity': {},
                'by_code': {}
            }
            for w in warnings:
                severity = w['severity']
                code = w['code']
                warning_summary['by_severity'][severity] = warning_summary['by_severity'].get(severity, 0) + 1
                warning_summary['by_code'][code] = warning_summary['by_code'].get(code, 0) + 1
            
            # Store warnings in Operator Notes field (human-readable)
            fields['Operator Notes'] = f"Warnings: {json.dumps(warning_summary, indent=2)}"
        
        self.services_table.update(service_id, fields)
        logger.info(f"Completed service {service_id}: Status → Complete")
    
    def _fail_service(self, service_id: str, error_message: str):
        """
        CANONICAL: Mark service as Failed and store error details.
        Uses canonical Error Log field (not Error Message).
        """
        fields = {
            # NOTE: Only use 'Status' (singular), never 'Statuses' (plural)
            'Status': 'Failed',
            'Finished At': datetime.now(timezone.utc).isoformat(),
            # CANONICAL: Use Error Log field
            'Error Log': error_message
        }
        
        self.services_table.update(service_id, fields)
        logger.info(f"Failed service {service_id}: Status → Failed")


def main():
    """Main entry point for Worker 1."""
    if len(sys.argv) < 2:
        print("Usage: python pronto_worker_1_v4.1.0_canonical.py <service_id>")
        sys.exit(1)
    
    service_id = sys.argv[1]
    
    # Validate environment
    required_vars = [
        'AIRTABLE_TOKEN',
        'AIRTABLE_BASE_ID',
        'R2_ACCOUNT_ID',
        'R2_ACCESS_KEY_ID',
        'R2_SECRET_ACCESS_KEY',
        'R2_PUBLIC_BASE_URL'
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    
    # Process service
    processor = ManuscriptProcessor()
    result = processor.process_service(service_id)
    
    # Print result
    print(json.dumps(result, indent=2))
    
    # Exit with appropriate code
    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
