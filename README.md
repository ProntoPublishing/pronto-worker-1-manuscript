# Pronto Worker 1 - Manuscript Processor v4.1.0

Extracts structured content from manuscript files (DOCX, PDF, TXT) and produces manuscript.v1.json artifacts.

## Version 4.1.0 - Canon-Compliant

This version implements the canonical Pronto Publishing architecture:

- Reads manuscript from linked `Manuscripts` table
- Writes to generic `Artifact URL` and `Artifact Key` fields
- Uses canonical Status lifecycle: Processing → Complete/Failed
- Uses canonical `Error Log` field
- Explicitly ignores non-canonical `Statuses` (plural) field

## Environment Variables

```bash
# Airtable
AIRTABLE_TOKEN=your_token_here
AIRTABLE_BASE_ID=your_base_id_here

# Cloudflare R2
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=pronto-artifacts
R2_PUBLIC_BASE_URL=https://artifacts.prontopublishing.com
```

## Usage

```bash
python3 pronto_worker_1.py <service_id>
```

## Deployment

Deployed on Railway: https://pronto-worker-1-manuscript-production.up.railway.app

## Author

Pronto Publishing  
Version: 4.1.0  
Date: 2026-01-06
