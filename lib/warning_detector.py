"""
Warning Detector - Edge Case and Quality Analysis
==================================================

Detects 10 warning codes with severity levels for manuscript artifacts.

Warning Codes:
- DETECTED_IMAGES: Images found in manuscript
- DETECTED_TABLES: Tables found in manuscript
- DETECTED_FOOTNOTES: Footnotes/endnotes found
- LOW_CHAPTER_CONFIDENCE: Uncertain chapter detection
- POEM_LIKE_BLOCKS: Poetry-like formatting detected
- UNICODE_RISK: Non-standard Unicode characters
- EXCESSIVE_WHITESPACE: Unusual spacing patterns
- CENTERED_TEXT_BLOCKS: Centered text (poems, titles)
- OCR_ARTIFACTS: Likely OCR errors
- FORMATTING_INCONSISTENCY: Inconsistent styling

Author: Pronto Publishing
Version: 4.0.0
"""

import re
import logging
from typing import List, Dict, Any
from collections import Counter

logger = logging.getLogger(__name__)


class WarningDetector:
    """Detects warnings and edge cases in manuscript blocks."""
    
    # Unicode ranges to flag
    RISKY_UNICODE_RANGES = [
        (0x2000, 0x206F),  # General Punctuation
        (0x2100, 0x214F),  # Letterlike Symbols
        (0x2190, 0x21FF),  # Arrows
        (0x2200, 0x22FF),  # Mathematical Operators
        (0x2300, 0x23FF),  # Miscellaneous Technical
        (0x2500, 0x257F),  # Box Drawing
        (0x2580, 0x259F),  # Block Elements
        (0x25A0, 0x25FF),  # Geometric Shapes
    ]
    
    # OCR artifact patterns
    OCR_PATTERNS = [
        r'\b[Il1]\b',  # Isolated I/l/1 (common OCR confusion)
        r'[^\s]{20,}',  # Very long words without spaces
        r'[a-z][A-Z]',  # Mixed case within words
        r'\d[a-z]',    # Digit followed by lowercase (e.g., "1ike")
    ]
    
    def _get_block_text(self, block: Dict[str, Any]) -> str:
        """Extract text from block regardless of whether it has 'text' or 'spans'."""
        if 'text' in block:
            return block['text']
        elif 'spans' in block:
            return ''.join(span['text'] for span in block['spans'])
        else:
            return ''
    
    def detect(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Detect all warnings in manuscript blocks.
        
        Args:
            blocks: List of extracted blocks
            source_meta: Source file metadata
            
        Returns:
            List of warning objects
        """
        warnings = []
        
        # Run all detectors
        warnings.extend(self._detect_images(blocks, source_meta))
        warnings.extend(self._detect_tables(blocks, source_meta))
        warnings.extend(self._detect_footnotes(blocks))
        warnings.extend(self._detect_low_chapter_confidence(blocks, source_meta))
        warnings.extend(self._detect_poem_like_blocks(blocks))
        warnings.extend(self._detect_unicode_risk(blocks))
        warnings.extend(self._detect_excessive_whitespace(blocks))
        warnings.extend(self._detect_centered_text(blocks))
        warnings.extend(self._detect_ocr_artifacts(blocks))
        warnings.extend(self._detect_formatting_inconsistency(blocks))
        
        logger.info(f"Detected {len(warnings)} warnings across {len(blocks)} blocks")
        
        return warnings
    
    def _detect_images(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect if source document contains images."""
        warnings = []
        
        # For DOCX, we'd check doc.inline_shapes (not implemented in block extractor yet)
        # For now, heuristic: look for image-related text
        image_keywords = ['[image]', '[figure]', '[photo]', '[illustration]']
        
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            text_lower = text.lower()
            if any(kw in text_lower for kw in image_keywords):
                warnings.append({
                    'code': 'DETECTED_IMAGES',
                    'severity': 'error',
                    'message': 'Image placeholder detected in text',
                    'block_index': i,
                    'context': text[:100]
                })
        
        return warnings
    
    def _detect_tables(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect if source document contains tables."""
        warnings = []
        
        # Heuristic: look for table-like patterns (multiple tabs/pipes)
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            if text.count('\t') >= 3 or text.count('|') >= 3:
                warnings.append({
                    'code': 'DETECTED_TABLES',
                    'severity': 'error',
                    'message': 'Table-like structure detected',
                    'block_index': i,
                    'context': text[:100]
                })
        
        return warnings
    
    def _detect_footnotes(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect footnote/endnote markers."""
        warnings = []
        
        # Look for superscript numbers or footnote markers
        footnote_pattern = r'\[\d+\]|\(\d+\)|†|‡|§'
        
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            if re.search(footnote_pattern, text):
                warnings.append({
                    'code': 'DETECTED_FOOTNOTES',
                    'severity': 'warning',
                    'message': 'Footnote/endnote marker detected',
                    'block_index': i,
                    'context': text[:100]
                })
        
        return warnings
    
    def _detect_low_chapter_confidence(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect uncertain chapter detection."""
        warnings = []
        
        chapter_blocks = [b for b in blocks if b['type'] == 'chapter_heading']
        
        # Low confidence if:
        # - No chapters detected
        # - Very few chapters (< 3) in long manuscript
        # - Inconsistent chapter numbering
        
        if len(chapter_blocks) == 0:
            warnings.append({
                'code': 'LOW_CHAPTER_CONFIDENCE',
                'severity': 'warning',
                'message': 'No chapters detected in manuscript',
                'detected_chapters': 0
            })
        elif len(chapter_blocks) < 3 and len(blocks) > 100:
            warnings.append({
                'code': 'LOW_CHAPTER_CONFIDENCE',
                'severity': 'info',
                'message': 'Very few chapters detected in long manuscript',
                'detected_chapters': len(chapter_blocks),
                'total_blocks': len(blocks)
            })
        
        return warnings
    
    def _detect_poem_like_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect poetry-like formatting (short lines, stanzas)."""
        warnings = []
        
        # Heuristic: multiple consecutive short blocks (< 50 chars)
        short_block_runs = []
        current_run = []
        
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            if len(text) < 50 and block['type'] == 'paragraph':
                current_run.append(i)
            else:
                if len(current_run) >= 4:  # 4+ short lines = poem-like
                    short_block_runs.append(current_run)
                current_run = []
        
        if current_run and len(current_run) >= 4:
            short_block_runs.append(current_run)
        
        for run in short_block_runs:
            warnings.append({
                'code': 'POEM_LIKE_BLOCKS',
                'severity': 'warning',
                'message': 'Poetry-like formatting detected',
                'block_indices': run,
                'line_count': len(run)
            })
        
        return warnings
    
    def _detect_unicode_risk(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect risky Unicode characters."""
        warnings = []
        
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            risky_chars = []
            for char in text:
                code_point = ord(char)
                for start, end in self.RISKY_UNICODE_RANGES:
                    if start <= code_point <= end:
                        risky_chars.append((char, hex(code_point)))
                        break
            
            if risky_chars:
                warnings.append({
                    'code': 'UNICODE_RISK',
                    'severity': 'info',
                    'message': f'Non-standard Unicode characters detected ({len(risky_chars)} chars)',
                    'block_index': i,
                    'sample_chars': risky_chars[:5]  # First 5 examples
                })
        
        return warnings
    
    def _detect_excessive_whitespace(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect unusual spacing patterns."""
        warnings = []
        
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            
            # Multiple consecutive spaces
            if '  ' in text:
                space_count = text.count('  ')
                warnings.append({
                    'code': 'EXCESSIVE_WHITESPACE',
                    'severity': 'info',
                    'message': f'Multiple consecutive spaces detected ({space_count} occurrences)',
                    'block_index': i
                })
        
        return warnings
    
    def _detect_centered_text(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect centered text blocks (poems, titles, epigraphs)."""
        warnings = []
        
        # Heuristic: blocks with leading/trailing whitespace
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            if text != text.strip() and len(text.strip()) > 0:
                warnings.append({
                    'code': 'CENTERED_TEXT_BLOCKS',
                    'severity': 'info',
                    'message': 'Centered or indented text detected',
                    'block_index': i,
                    'context': text.strip()[:100]
                })
        
        return warnings
    
    def _detect_ocr_artifacts(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect likely OCR errors."""
        warnings = []
        
        for i, block in enumerate(blocks):
            text = self._get_block_text(block)
            
            for pattern in self.OCR_PATTERNS:
                matches = re.findall(pattern, text)
                if matches:
                    warnings.append({
                        'code': 'OCR_ARTIFACTS',
                        'severity': 'warning',
                        'message': f'Possible OCR errors detected (pattern: {pattern})',
                        'block_index': i,
                        'sample_matches': matches[:5]
                    })
                    break  # One warning per block
        
        return warnings
    
    def _detect_formatting_inconsistency(
        self,
        blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Detect inconsistent formatting across blocks."""
        warnings = []
        
        # Check chapter heading consistency
        chapter_blocks = [b for b in blocks if b['type'] == 'chapter_heading']
        if len(chapter_blocks) >= 3:
            # Check if chapter formats are consistent
            formats = [b['text'][:20] for b in chapter_blocks]
            format_counter = Counter(formats)
            
            if len(format_counter) > 2:  # More than 2 different formats
                warnings.append({
                    'code': 'FORMATTING_INCONSISTENCY',
                    'severity': 'info',
                    'message': 'Inconsistent chapter heading formats detected',
                    'format_variations': len(format_counter),
                    'sample_formats': list(format_counter.keys())[:3]
                })
        
        return warnings
