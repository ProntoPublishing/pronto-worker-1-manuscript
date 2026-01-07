"""
Block Extractor - Structured Content Extraction
================================================

Extracts blocks from manuscript files with inline styling marks.

Supports:
- 14 block types (front matter, chapters, paragraphs, scene breaks, back matter)
- 4 inline marks (italic, bold, smallcaps, code)
- DOCX, PDF, TXT formats

Author: Pronto Publishing
Version: 4.1.0 (Schema-compliant)
"""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph
from docx.oxml.text.paragraph import CT_P
import PyPDF2

logger = logging.getLogger(__name__)


class BlockExtractor:
    """Extracts structured blocks from manuscript files."""
    
    # Chapter heading patterns
    CHAPTER_PATTERNS = [
        r'^Chapter\s+\d+',
        r'^CHAPTER\s+\d+',
        r'^Ch\.\s+\d+',
        r'^\d+\.',  # "1.", "2.", etc.
        r'^Part\s+\d+',
        r'^PART\s+\d+',
    ]
    
    # Front matter keywords
    FRONT_MATTER_KEYWORDS = {
        'dedication': 'front_matter_dedication',
        'copyright': 'front_matter_copyright',
        'title': 'front_matter_title',
        'contents': 'toc_marker',
        'table of contents': 'toc_marker',
    }
    
    # Back matter keywords
    BACK_MATTER_KEYWORDS = {
        'about the author': 'back_matter_about_author',
        'about author': 'back_matter_about_author',
        'also by': 'back_matter_also_by',
    }
    
    # Scene break patterns
    SCENE_BREAK_PATTERNS = [
        r'^\s*\*\s*\*\s*\*\s*$',  # * * *
        r'^\s*#\s*$',              # #
        r'^\s*~\s*$',              # ~
        r'^\s*-{3,}\s*$',          # ---
    ]
    
    def __init__(self):
        """Initialize block extractor."""
        self.block_counter = 0
    
    def extract(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Extract blocks from manuscript file.
        
        Args:
            file_path: Path to manuscript file
            
        Returns:
            Tuple of (blocks, source_meta)
        """
        # Reset block counter for each file
        self.block_counter = 0
        
        ext = Path(file_path).suffix.lower()
        
        if ext == '.docx':
            return self._extract_docx(file_path)
        elif ext == '.pdf':
            return self._extract_pdf(file_path)
        elif ext in ['.txt', '.md']:
            return self._extract_txt(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")
    
    def _generate_block_id(self) -> str:
        """Generate unique block ID."""
        self.block_counter += 1
        return f"b_{self.block_counter:06d}"
    
    def _extract_docx(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract blocks from DOCX file with inline styling."""
        doc = Document(file_path)
        blocks = []
        
        # Track state
        in_front_matter = True
        in_back_matter = False
        chapter_count = 0
        
        for para_idx, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            
            if not text:
                continue  # Skip empty paragraphs
            
            # Detect block type
            block_type, meta = self._detect_block_type(
                text=text,
                style=para.style.name if para.style else None,
                in_front_matter=in_front_matter,
                in_back_matter=in_back_matter
            )
            
            # Update state
            if block_type == 'chapter_heading':
                chapter_count += 1
                in_front_matter = False
                meta['chapter_number'] = chapter_count
            
            if block_type.startswith('front_matter') or block_type == 'toc_marker':
                in_front_matter = True
            
            if block_type.startswith('back_matter'):
                in_back_matter = True
                in_front_matter = False
            
            # Extract spans with inline marks
            spans = self._extract_spans_from_para(para)
            
            # Build block
            block = {
                'id': self._generate_block_id(),
                'type': block_type
            }
            
            # Add text or spans (schema requires ONE OF, not both)
            if spans and len(spans) > 1:
                # Multiple spans with formatting
                block['spans'] = spans
            elif spans and len(spans) == 1 and spans[0]['marks']:
                # Single span with marks
                block['spans'] = spans
            else:
                # Plain text (no formatting or single span without marks)
                block['text'] = text
            
            # Add metadata if present
            if meta:
                block['meta'] = meta
            
            # Add source location
            block['source_loc'] = {
                'doc_paragraph_index': para_idx
            }
            
            blocks.append(block)
        
        # Source metadata
        source_meta = {
            'original_filename': Path(file_path).name,
            'original_format': 'docx',
            'total_paragraphs': len(doc.paragraphs),
            'detected_chapters': chapter_count,
            'has_front_matter': any(b['type'].startswith('front_matter') or b['type'] == 'toc_marker' for b in blocks),
            'has_back_matter': any(b['type'].startswith('back_matter') for b in blocks)
        }
        
        logger.info(f"Extracted {len(blocks)} blocks from DOCX ({chapter_count} chapters)")
        
        return blocks, source_meta
    
    def _extract_pdf(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract blocks from PDF file (text-only, no styling)."""
        blocks = []
        
        # Track state
        in_front_matter = True
        in_back_matter = False
        chapter_count = 0
        
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text()
                lines = text.split('\n')
                
                for line in lines:
                    line = line.strip()
                    
                    if not line:
                        continue
                    
                    # Detect block type
                    block_type, meta = self._detect_block_type(
                        text=line,
                        style=None,
                        in_front_matter=in_front_matter,
                        in_back_matter=in_back_matter
                    )
                    
                    # Update state
                    if block_type == 'chapter_heading':
                        chapter_count += 1
                        in_front_matter = False
                        meta['chapter_number'] = chapter_count
                    
                    if block_type.startswith('front_matter') or block_type == 'toc_marker':
                        in_front_matter = True
                    
                    if block_type.startswith('back_matter'):
                        in_back_matter = True
                        in_front_matter = False
                    
                    # Build block (no inline marks for PDF)
                    block = {
                        'id': self._generate_block_id(),
                        'type': block_type,
                        'text': line
                    }
                    
                    if meta:
                        block['meta'] = meta
                    
                    block['source_loc'] = {
                        'doc_page_number': page_num
                    }
                    
                    blocks.append(block)
        
        # Source metadata
        source_meta = {
            'original_filename': Path(file_path).name,
            'original_format': 'pdf',
            'total_pages': len(reader.pages),
            'detected_chapters': chapter_count,
            'has_front_matter': any(b['type'].startswith('front_matter') or b['type'] == 'toc_marker' for b in blocks),
            'has_back_matter': any(b['type'].startswith('back_matter') for b in blocks)
        }
        
        logger.info(f"Extracted {len(blocks)} blocks from PDF ({chapter_count} chapters)")
        
        return blocks, source_meta
    
    def _extract_txt(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract blocks from plain text file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        blocks = []
        
        # Track state
        in_front_matter = True
        in_back_matter = False
        chapter_count = 0
        
        for line_num, line in enumerate(lines, start=1):
            line = line.strip()
            
            if not line:
                continue
            
            # Detect block type
            block_type, meta = self._detect_block_type(
                text=line,
                style=None,
                in_front_matter=in_front_matter,
                in_back_matter=in_back_matter
            )
            
            # Update state
            if block_type == 'chapter_heading':
                chapter_count += 1
                in_front_matter = False
                meta['chapter_number'] = chapter_count
            
            if block_type.startswith('front_matter') or block_type == 'toc_marker':
                in_front_matter = True
            
            if block_type.startswith('back_matter'):
                in_back_matter = True
                in_front_matter = False
            
            # Build block
            block = {
                'id': self._generate_block_id(),
                'type': block_type,
                'text': line
            }
            
            if meta:
                block['meta'] = meta
            
            blocks.append(block)
        
        # Source metadata
        source_meta = {
            'original_filename': Path(file_path).name,
            'original_format': 'txt',
            'total_lines': len(lines),
            'detected_chapters': chapter_count,
            'has_front_matter': any(b['type'].startswith('front_matter') or b['type'] == 'toc_marker' for b in blocks),
            'has_back_matter': any(b['type'].startswith('back_matter') for b in blocks)
        }
        
        logger.info(f"Extracted {len(blocks)} blocks from TXT ({chapter_count} chapters)")
        
        return blocks, source_meta
    
    def _detect_block_type(
        self,
        text: str,
        style: Optional[str],
        in_front_matter: bool,
        in_back_matter: bool
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Detect block type from text and context.
        
        Returns:
            Tuple of (block_type, meta_dict)
        """
        text_lower = text.lower()
        meta = {}
        
        # Check for scene break
        for pattern in self.SCENE_BREAK_PATTERNS:
            if re.match(pattern, text):
                return 'scene_break', {'pattern': text}
        
        # Check for chapter heading
        for pattern in self.CHAPTER_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                # Extract chapter number if present
                match = re.search(r'\d+', text)
                if match:
                    meta['chapter_number'] = int(match.group())
                return 'chapter_heading', meta
        
        # Check for specific front matter types
        for keyword, block_type in self.FRONT_MATTER_KEYWORDS.items():
            if keyword in text_lower:
                return block_type, {'detected_keyword': keyword}
        
        # Check for specific back matter types
        for keyword, block_type in self.BACK_MATTER_KEYWORDS.items():
            if keyword in text_lower:
                return block_type, {'detected_keyword': keyword}
        
        # Generic front matter (fallback to dedication)
        if in_front_matter:
            return 'front_matter_dedication', {}
        
        # Generic back matter (fallback to about author)
        if in_back_matter:
            return 'back_matter_about_author', {}
        
        # Default to paragraph
        return 'paragraph', {}
    
    def _extract_spans_from_para(self, para: Paragraph) -> List[Dict[str, Any]]:
        """
        Extract spans with inline marks from DOCX paragraph.
        
        Returns list of span objects: [{text: str, marks: [str]}]
        """
        spans = []
        
        for run in para.runs:
            run_text = run.text
            
            if not run_text:
                continue
            
            # Collect marks for this span
            marks = []
            
            if run.italic:
                marks.append('italic')
            
            if run.bold:
                marks.append('bold')
            
            if run.font and run.font.small_caps:
                marks.append('smallcaps')
            
            # Code detection (monospace font)
            if run.font and run.font.name and 'mono' in run.font.name.lower():
                marks.append('code')
            
            # Create span
            spans.append({
                'text': run_text,
                'marks': marks
            })
        
        return spans
