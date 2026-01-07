"""
Warning Detector - Edge Case and Quality Analysis
==================================================

Detects warning codes with severity levels for manuscript artifacts.

Schema-compliant warning codes:
- DETECTED_IMAGES: Images found in manuscript
- DETECTED_TABLES: Tables found in manuscript
- DETECTED_FOOTNOTES: Footnotes/endnotes found
- HEAVY_CENTERING: Centered text (poems, titles)
- UNICODE_RISK: Non-standard Unicode characters
- POEM_LIKE_BLOCKS: Poetry-like formatting detected
- UNKNOWN_STYLES_DROPPED: Unsupported formatting
- LOW_CHAPTER_CONFIDENCE: Uncertain chapter detection
- OCR_QUALITY_ISSUES: Likely OCR errors
- PARSING_ERRORS: Parsing issues

Author: Pronto Publishing
Version: 4.2.0 (Schema-compliant)
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
            List of schema-compliant warning objects
        """
        warnings = []
        
        # Run all detectors
        warnings.extend(self._detect_images(blocks, source_meta))
        warnings.extend(self._detect_tables(blocks, source_meta))
        warnings.extend(self._detect_footnotes(blocks))
        warnings.extend(self._detect_low_chapter_confidence(blocks, source_meta))
        warnings.extend(self._detect_poem_like_blocks(blocks))
        warnings.extend(self._detect_unicode_risk(blocks))
        warnings.extend(self._detect_heavy_centering(blocks))
        warnings.extend(self._detect_ocr_quality_issues(blocks))
        
        logger.info(f"Detected {len(warnings)} warnings across {len(blocks)} blocks")
        
        return warnings
    
    def _detect_images(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect if source document contains images."""
        image_keywords = ['[image]', '[figure]', '[photo]', '[illustration]']
        
        count = 0
        for block in blocks:
            text = self._get_block_text(block)
            text_lower = text.lower()
            if any(kw in text_lower for kw in image_keywords):
                count += 1
        
        if count > 0:
            return [{
                'code': 'DETECTED_IMAGES',
                'severity': 'high',
                'count': count
            }]
        return []
    
    def _detect_tables(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect if source document contains tables."""
        count = 0
        for block in blocks:
            text = self._get_block_text(block)
            if text.count('\t') >= 3 or text.count('|') >= 3:
                count += 1
        
        if count > 0:
            return [{
                'code': 'DETECTED_TABLES',
                'severity': 'high',
                'count': count
            }]
        return []
    
    def _detect_footnotes(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect footnote/endnote markers."""
        footnote_pattern = r'\[\d+\]|\(\d+\)|†|‡|§'
        
        count = 0
        for block in blocks:
            text = self._get_block_text(block)
            if re.search(footnote_pattern, text):
                count += 1
        
        if count > 0:
            return [{
                'code': 'DETECTED_FOOTNOTES',
                'severity': 'medium',
                'count': count
            }]
        return []
    
    def _detect_low_chapter_confidence(
        self,
        blocks: List[Dict[str, Any]],
        source_meta: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Detect if chapter detection confidence is low."""
        chapter_count = sum(1 for b in blocks if b.get('type') == 'chapter_heading')
        
        # Heuristic: if no chapters detected in a long manuscript, confidence is low
        if chapter_count == 0 and len(blocks) > 50:
            return [{
                'code': 'LOW_CHAPTER_CONFIDENCE',
                'severity': 'medium'
            }]
        
        # Heuristic: if very few chapters in a very long manuscript
        if chapter_count > 0 and len(blocks) / chapter_count > 500:
            return [{
                'code': 'LOW_CHAPTER_CONFIDENCE',
                'severity': 'low'
            }]
        
        return []
    
    def _detect_poem_like_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect poetry-like formatting (many short lines)."""
        short_block_count = 0
        
        for block in blocks:
            text = self._get_block_text(block)
            if len(text) < 50 and block.get('type') == 'paragraph':
                short_block_count += 1
        
        # If more than 20% of paragraphs are very short, likely poetry
        paragraph_count = sum(1 for b in blocks if b.get('type') == 'paragraph')
        if paragraph_count > 0 and short_block_count / paragraph_count > 0.2:
            return [{
                'code': 'POEM_LIKE_BLOCKS',
                'severity': 'medium',
                'count': short_block_count
            }]
        
        return []
    
    def _detect_unicode_risk(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect risky Unicode characters."""
        risky_block_count = 0
        
        for block in blocks:
            text = self._get_block_text(block)
            for char in text:
                code_point = ord(char)
                for start, end in self.RISKY_UNICODE_RANGES:
                    if start <= code_point <= end:
                        risky_block_count += 1
                        break
                if risky_block_count > 0:
                    break
        
        if risky_block_count > 0:
            return [{
                'code': 'UNICODE_RISK',
                'severity': 'low',
                'count': risky_block_count
            }]
        
        return []
    
    def _detect_heavy_centering(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect centered text blocks (poems, titles, epigraphs)."""
        centered_count = 0
        
        for block in blocks:
            text = self._get_block_text(block)
            # Heuristic: leading/trailing whitespace suggests centering
            if text != text.strip() and len(text.strip()) > 0:
                centered_count += 1
        
        # If more than 10% of blocks are centered, flag it
        if len(blocks) > 0 and centered_count / len(blocks) > 0.1:
            return [{
                'code': 'HEAVY_CENTERING',
                'severity': 'low',
                'count': centered_count
            }]
        
        return []
    
    def _detect_ocr_quality_issues(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect likely OCR errors."""
        issue_count = 0
        
        for block in blocks:
            text = self._get_block_text(block)
            
            for pattern in self.OCR_PATTERNS:
                if re.search(pattern, text):
                    issue_count += 1
                    break
        
        if issue_count > 5:  # Only flag if multiple issues
            return [{
                'code': 'OCR_QUALITY_ISSUES',
                'severity': 'medium',
                'count': issue_count
            }]
        
        return []
