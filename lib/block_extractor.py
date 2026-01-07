"""
Block Extractor - Structured Content Extraction
================================================

Extracts blocks from manuscript files with inline styling marks.

Supports:
- 14 block types (front matter, chapters, paragraphs, scene breaks, back matter)
- 4 inline marks (italic, bold, smallcaps, code)
- DOCX, PDF, TXT formats

Author: Pronto Publishing
Version: 4.0.0
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
    FRONT_MATTER_KEYWORDS = [
        'dedication', 'acknowledgments', 'acknowledgements', 'preface',
        'foreword', 'introduction', 'prologue', 'table of contents',
        'contents', 'epigraph'
    ]
    
    # Back matter keywords
    BACK_MATTER_KEYWORDS = [
        'epilogue', 'afterword', 'appendix', 'glossary', 'bibliography',
        'references', 'notes', 'about the author', 'also by', 'acknowledgments',
        'acknowledgements'
    ]
    
    # Scene break patterns
    SCENE_BREAK_PATTERNS = [
        r'^\s*\*\s*\*\s*\*\s*$',  # * * *
        r'^\s*#\s*$',              # #
        r'^\s*~\s*$',              # ~
        r'^\s*-{3,}\s*$',          # ---
    ]
    
    def extract(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Extract blocks from manuscript file.
        
        Args:
            file_path: Path to manuscript file
            
        Returns:
            Tuple of (blocks, source_meta)
        """
        ext = Path(file_path).suffix.lower()
        
        if ext == '.docx':
            return self._extract_docx(file_path)
        elif ext == '.pdf':
            return self._extract_pdf(file_path)
        elif ext in ['.txt', '.md']:
            return self._extract_txt(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")
    
    def _extract_docx(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract blocks from DOCX file with inline styling."""
        doc = Document(file_path)
        blocks = []
        
        # Track state
        in_front_matter = True
        in_back_matter = False
        chapter_count = 0
        
        for para in doc.paragraphs:
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
            
            if block_type in ['front_matter_heading', 'front_matter_text']:
                in_front_matter = True
            
            if block_type in ['back_matter_heading', 'back_matter_text']:
                in_back_matter = True
                in_front_matter = False
            
            # Extract inline marks
            marks = self._extract_marks_from_para(para)
            
            # Build block
            block = {
                'type': block_type,
                'text': text,
                'marks': marks if marks else []
            }
            
            if meta:
                block['meta'] = meta
            
            blocks.append(block)
        
        # Source metadata
        source_meta = {
            'original_filename': Path(file_path).name,
            'original_format': 'docx',
            'total_paragraphs': len(doc.paragraphs),
            'detected_chapters': chapter_count,
            'has_front_matter': any(b['type'].startswith('front_matter') for b in blocks),
            'has_back_matter': any(b['type'].startswith('back_matter') for b in blocks)
        }
        
        logger.info(f"Extracted {len(blocks)} blocks from DOCX ({chapter_count} chapters)")
        
        return blocks, source_meta
    
    def _extract_pdf(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract blocks from PDF file (text-only, no styling)."""
        blocks = []
        
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            
            in_front_matter = True
            in_back_matter = False
            chapter_count = 0
            
            for page in reader.pages:
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
                    
                    if block_type in ['back_matter_heading', 'back_matter_text']:
                        in_back_matter = True
                        in_front_matter = False
                    
                    # Build block (no inline marks for PDF)
                    block = {
                        'type': block_type,
                        'text': line,
                        'marks': []
                    }
                    
                    if meta:
                        block['meta'] = meta
                    
                    blocks.append(block)
        
        # Source metadata
        source_meta = {
            'original_filename': Path(file_path).name,
            'original_format': 'pdf',
            'total_pages': len(reader.pages),
            'detected_chapters': chapter_count,
            'has_front_matter': any(b['type'].startswith('front_matter') for b in blocks),
            'has_back_matter': any(b['type'].startswith('back_matter') for b in blocks)
        }
        
        logger.info(f"Extracted {len(blocks)} blocks from PDF ({chapter_count} chapters)")
        
        return blocks, source_meta
    
    def _extract_txt(self, file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Extract blocks from plain text file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        blocks = []
        in_front_matter = True
        in_back_matter = False
        chapter_count = 0
        
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
            
            if block_type in ['back_matter_heading', 'back_matter_text']:
                in_back_matter = True
                in_front_matter = False
            
            # Build block
            block = {
                'type': block_type,
                'text': line,
                'marks': []
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
            'has_front_matter': any(b['type'].startswith('front_matter') for b in blocks),
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
        
        # Check for front matter
        if in_front_matter or any(kw in text_lower for kw in self.FRONT_MATTER_KEYWORDS):
            if style and 'heading' in style.lower():
                return 'front_matter_heading', {'detected_keyword': text_lower}
            return 'front_matter_text', {}
        
        # Check for back matter
        if in_back_matter or any(kw in text_lower for kw in self.BACK_MATTER_KEYWORDS):
            if style and 'heading' in style.lower():
                return 'back_matter_heading', {'detected_keyword': text_lower}
            return 'back_matter_text', {}
        
        # Check for title page elements
        if len(text.split()) <= 10 and not in_front_matter and not in_back_matter:
            if style and 'title' in style.lower():
                return 'title_page', {'style': style}
        
        # Default to paragraph
        return 'paragraph', {}
    
    def _extract_marks_from_para(self, para: Paragraph) -> List[Dict[str, Any]]:
        """
        Extract inline marks from DOCX paragraph.
        
        Returns list of mark objects with start/end positions.
        """
        marks = []
        position = 0
        
        for run in para.runs:
            run_text = run.text
            run_length = len(run_text)
            
            if not run_text:
                continue
            
            # Detect marks
            if run.italic:
                marks.append({
                    'type': 'italic',
                    'start': position,
                    'end': position + run_length
                })
            
            if run.bold:
                marks.append({
                    'type': 'bold',
                    'start': position,
                    'end': position + run_length
                })
            
            if run.font.small_caps:
                marks.append({
                    'type': 'smallcaps',
                    'start': position,
                    'end': position + run_length
                })
            
            # Code detection (monospace font)
            if run.font.name and 'mono' in run.font.name.lower():
                marks.append({
                    'type': 'code',
                    'start': position,
                    'end': position + run_length
                })
            
            position += run_length
        
        return marks
