"""
Pronto R2 Client - Cloudflare R2 Storage Interface
===================================================

Handles uploads/downloads to Cloudflare R2 with proper public URL generation.

CRITICAL FIX (v4.0.0):
- Separates API endpoint URL from public URL
- Uses R2_PUBLIC_BASE_URL for accessible artifact URLs
- Computes artifact hashes for lineage tracking

Author: Pronto Publishing
Version: 4.0.0
"""

import json
import hashlib
import logging
from typing import Dict, Any, Optional
from datetime import datetime

import boto3
from botocore.client import Config

logger = logging.getLogger(__name__)


class ProntoR2Client:
    """Client for Cloudflare R2 storage operations."""
    
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        public_base_url: Optional[str] = None
    ):
        """
        Initialize R2 client.
        
        Args:
            account_id: Cloudflare account ID
            access_key_id: R2 access key ID
            secret_access_key: R2 secret access key
            bucket_name: R2 bucket name
            public_base_url: Public URL base (e.g., https://pub-xxxxx.r2.dev)
                            If None, bucket is assumed private (use presigned URLs)
        """
        self.bucket_name = bucket_name
        self.public_base_url = public_base_url
        
        # API endpoint (for uploads/downloads)
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        
        # S3-compatible client
        self.s3_client = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )
        
        logger.info(f"R2 client initialized: bucket={bucket_name}, public={bool(public_base_url)}")
    
    def upload_json(
        self,
        object_key: str,
        data: Dict[str, Any],
        content_type: str = 'application/json'
    ) -> Dict[str, str]:
        """
        Upload JSON data to R2.
        
        Args:
            object_key: Object key in R2 (e.g., "services/recXXX/manuscript.v1.json")
            data: JSON-serializable data
            content_type: MIME type
            
        Returns:
            Dict with 'public_url' and 'artifact_hash'
        """
        # Serialize JSON (canonical format for hashing)
        json_bytes = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
        
        # Compute artifact hash
        artifact_hash = self._compute_hash(json_bytes)
        
        # Upload to R2
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=object_key,
            Body=json_bytes,
            ContentType=content_type,
            Metadata={
                'artifact_hash': artifact_hash,
                'uploaded_at': datetime.utcnow().isoformat()
            }
        )
        
        # Generate public URL
        public_url = self._get_public_url(object_key)
        
        logger.info(f"Uploaded {object_key} ({len(json_bytes)} bytes, hash={artifact_hash[:16]}...)")
        
        return {
            'public_url': public_url,
            'artifact_hash': artifact_hash,
            'object_key': object_key,
            'size_bytes': len(json_bytes)
        }
    
    def upload_file(
        self,
        object_key: str,
        file_path: str,
        content_type: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Upload file to R2.
        
        Args:
            object_key: Object key in R2
            file_path: Local file path
            content_type: MIME type (auto-detected if None)
            
        Returns:
            Dict with 'public_url' and 'file_hash'
        """
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
        
        # Compute file hash
        file_hash = self._compute_hash(file_bytes)
        
        # Upload to R2
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=object_key,
            Body=file_bytes,
            ContentType=content_type or 'application/octet-stream',
            Metadata={
                'file_hash': file_hash,
                'uploaded_at': datetime.utcnow().isoformat()
            }
        )
        
        # Generate public URL
        public_url = self._get_public_url(object_key)
        
        logger.info(f"Uploaded {object_key} ({len(file_bytes)} bytes, hash={file_hash[:16]}...)")
        
        return {
            'public_url': public_url,
            'file_hash': file_hash,
            'object_key': object_key,
            'size_bytes': len(file_bytes)
        }
    
    def download_json(self, object_key: str) -> Dict[str, Any]:
        """
        Download JSON data from R2.
        
        Args:
            object_key: Object key in R2
            
        Returns:
            Parsed JSON data
        """
        response = self.s3_client.get_object(
            Bucket=self.bucket_name,
            Key=object_key
        )
        
        json_bytes = response['Body'].read()
        data = json.loads(json_bytes.decode('utf-8'))
        
        logger.info(f"Downloaded {object_key} ({len(json_bytes)} bytes)")
        
        return data
    
    def get_presigned_url(
        self,
        object_key: str,
        expires_in: int = 86400
    ) -> str:
        """
        Generate presigned URL for private bucket access.
        
        Args:
            object_key: Object key in R2
            expires_in: Expiration time in seconds (default: 24 hours)
            
        Returns:
            Presigned URL
        """
        url = self.s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket_name,
                'Key': object_key
            },
            ExpiresIn=expires_in
        )
        
        logger.info(f"Generated presigned URL for {object_key} (expires in {expires_in}s)")
        
        return url
    
    def _get_public_url(self, object_key: str) -> str:
        """
        Generate public URL for object.
        
        If public_base_url is set, returns public URL.
        Otherwise, generates presigned URL.
        """
        if self.public_base_url:
            # Public bucket - construct direct URL
            return f"{self.public_base_url}/{object_key}"
        else:
            # Private bucket - generate presigned URL
            return self.get_presigned_url(object_key)
    
    def _compute_hash(self, data: bytes) -> str:
        """Compute SHA-256 hash of data."""
        return f"sha256:{hashlib.sha256(data).hexdigest()}"
