"""
PDF text extraction module.
Adapted from markdown-extractor project with multiple extraction backends.
"""

import re
from pathlib import Path

import pdfplumber

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False

MARKER_AVAILABLE = False
MARKER_MODELS = None
MARKER_CONVERTER = None


def init_marker(use_gpu: bool = True):
    """
    Initialize Marker models (call once at startup if needed).
    
    Args:
        use_gpu: Whether to attempt GPU acceleration. If True and GPU is available,
                 models will use CUDA for faster processing.
    """
    global MARKER_AVAILABLE, MARKER_MODELS, MARKER_CONVERTER

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.config.parser import ConfigParser

        # Check for GPU availability
        gpu_available = False
        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available() and use_gpu:
                gpu_available = True
                device = "cuda"
                print(f"✓ GPU detected: {torch.cuda.get_device_name(0)}")
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available() and use_gpu:
                gpu_available = True
                device = "mps"
                print("✓ Apple Metal GPU detected")
        except ImportError:
            pass

        print(f"Loading Marker models on {device}... (this may take a moment)")
        MARKER_MODELS = create_model_dict()

        config_dict = {
            "disable_multiprocessing": True,
        }
        
        # Add device configuration if GPU available
        if gpu_available:
            config_dict["device"] = device
            
        config_parser = ConfigParser(config_dict)
        MARKER_CONVERTER = PdfConverter(
            artifact_dict=MARKER_MODELS,
            config=config_parser.generate_config_dict()
        )
        MARKER_AVAILABLE = True
        print(f"✓ Marker models loaded successfully on {device}!")
    except ImportError as e:
        print(f"✗ Marker not available: {e}")
        MARKER_AVAILABLE = False
    except Exception as e:
        print(f"✗ Marker models failed to load: {e}")
        MARKER_AVAILABLE = False


def get_gpu_status() -> dict:
    """Get GPU availability status for ML operations."""
    status = {
        "cuda_available": False,
        "mps_available": False,
        "device_name": None,
        "device_in_use": "cpu",
    }
    
    try:
        import torch
        if torch.cuda.is_available():
            status["cuda_available"] = True
            status["device_name"] = torch.cuda.get_device_name(0)
            status["device_in_use"] = "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            status["mps_available"] = True
            status["device_name"] = "Apple Metal"
            status["device_in_use"] = "mps"
    except ImportError:
        pass
    
    return status


def clean_text(text: str) -> str:
    """Clean and normalize extracted text."""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)
    text = re.sub(r'([a-z])\s*\n\s*([a-z])', r'\1\2', text)
    text = re.sub(r'  +', ' ', text)
    text = re.sub(r'\n\n+', '\n\n', text)
    return text.strip()


def detect_heading(line: str, next_line: str | None = None) -> bool:
    """Detect if a line is likely a heading."""
    line = line.strip()
    if not line:
        return False
    if len(line) >= 3 and line.isupper() and not line.endswith('.'):
        return True
    if len(line) < 60 and next_line is not None and not next_line.strip():
        if line[0].isupper() and not line.endswith((',', ';', ':')):
            return True
    return False


def is_list_item(line: str) -> bool:
    """Check if a line is a list item."""
    line = line.strip()
    if not line:
        return False
    if re.match(r'^[•●\-\*]\s+', line):
        return True
    if re.match(r'^\d+[\.\)]\s+', line):
        return True
    return False


def format_line_as_markdown(line: str, is_heading: bool = False, heading_level: int = 3) -> str:
    """Format a line as markdown."""
    line = line.strip()
    if not line:
        return ''
    if re.match(r'^[•●\-\*]\s+', line):
        line = re.sub(r'^[•●\-\*]\s+', '- ', line)
        return line
    if re.match(r'^\d+[\.\)]\s+', line):
        return line
    if is_heading:
        return f"{'#' * heading_level} {line}"
    return line


def extract_text_with_layout(page) -> str:
    """Extract text from a pdfplumber page with layout awareness."""
    try:
        words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
        if not words:
            return page.extract_text() or ""

        page_width = page.width

        all_x_positions = sorted(set([int(w['x0']) for w in words] + [int(w['x1']) for w in words]))

        gaps = []
        for i in range(len(all_x_positions) - 1):
            gap_size = all_x_positions[i + 1] - all_x_positions[i]
            if gap_size > 40:
                gap_center = (all_x_positions[i] + all_x_positions[i + 1]) / 2
                if page_width * 0.25 < gap_center < page_width * 0.75:
                    gaps.append((gap_size, gap_center))

        if gaps:
            gaps.sort(reverse=True)
            column_gap = gaps[0][1]
            column_boundaries = [
                (0, column_gap, 0),
                (column_gap, page_width, 1)
            ]
        else:
            column_boundaries = [(0, page_width, 0)]

        for word in words:
            word_center_x = (word['x0'] + word['x1']) / 2
            assigned = False
            for min_x, max_x, col_idx in column_boundaries:
                if min_x <= word_center_x <= max_x:
                    word['column'] = col_idx
                    assigned = True
                    break
            if not assigned:
                distances = [(abs(word_center_x - (min_x + max_x) / 2), col_idx)
                             for min_x, max_x, col_idx in column_boundaries]
                word['column'] = min(distances)[1]

        result_lines = []
        for col_idx in range(len(column_boundaries)):
            column_words = [w for w in words if w.get('column') == col_idx]
            if not column_words:
                continue

            column_words.sort(key=lambda w: (w['top'], w['x0']))

            lines_in_column = []
            current_line_words = []
            last_top = None
            y_tolerance = 5

            for word in column_words:
                if last_top is None or abs(word['top'] - last_top) <= y_tolerance:
                    current_line_words.append(word)
                    if last_top is None:
                        last_top = word['top']
                else:
                    if current_line_words:
                        line_text = ' '.join([w['text'] for w in current_line_words])
                        lines_in_column.append((current_line_words[0]['top'], line_text))
                    current_line_words = [word]
                    last_top = word['top']

            if current_line_words:
                line_text = ' '.join([w['text'] for w in current_line_words])
                lines_in_column.append((current_line_words[0]['top'], line_text))

            lines_in_column.sort(key=lambda x: x[0])
            result_lines.extend([line_text for _, line_text in lines_in_column])

        return '\n'.join(result_lines)

    except Exception:
        try:
            text = page.extract_text(layout=True, x_tolerance=3, y_tolerance=3)
            if text:
                return text
        except Exception:
            pass
        return page.extract_text() or ""


def extract_with_pymupdf(pdf_path: str | Path, start_page: int = 1, end_page: int | None = None) -> str:
    """Extract text using PyMuPDF with good column detection."""
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF not available")

    doc = fitz.open(str(pdf_path))
    markdown_content = []

    try:
        total_pages = len(doc)
        if end_page is None:
            end_page = total_pages

        for page_num in range(start_page - 1, min(end_page, total_pages)):
            page = doc[page_num]
            blocks = page.get_text("blocks")

            markdown_content.append(f"## Page {page_num + 1}\n\n")

            for block in blocks:
                if len(block) >= 5:
                    text = block[4].strip()
                    if text:
                        markdown_content.append(text + '\n\n')

            markdown_content.append('\n---\n\n')

        return ''.join(markdown_content)
    finally:
        doc.close()


def extract_with_marker(pdf_path: str | Path, start_page: int = 1, end_page: int | None = None) -> str:
    """Extract text using Marker (ML-based, best for complex layouts)."""
    if not MARKER_AVAILABLE or not MARKER_CONVERTER:
        raise ImportError("Marker not available")

    from marker.converters.pdf import PdfConverter
    from marker.output import text_from_rendered
    from marker.config.parser import ConfigParser

    marker_start = start_page - 1
    if end_page:
        marker_end = end_page - 1
        page_range = f"{marker_start}-{marker_end}"
    else:
        page_range = f"{marker_start}-"

    config_dict = {
        "disable_multiprocessing": True,
        "page_range": page_range
    }
    config_parser = ConfigParser(config_dict)
    converter = PdfConverter(
        artifact_dict=MARKER_MODELS,
        config=config_parser.generate_config_dict()
    )

    rendered = converter(str(pdf_path))
    full_text, _, _ = text_from_rendered(rendered)
    return full_text


def extract_with_markitdown(pdf_path: str | Path) -> str:
    """Extract text using MarkItDown."""
    if not MARKITDOWN_AVAILABLE:
        raise ImportError("MarkItDown not available")

    md = MarkItDown()
    result = md.convert(str(pdf_path))
    return result.text_content


def extract_with_pdfplumber(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
    include_page_numbers: bool = True,
    include_page_breaks: bool = True,
    filter_headers_footers: bool = True,
    preserve_formatting: bool = True,
) -> str:
    """Extract text using pdfplumber with layout awareness."""
    from collections import Counter

    markdown_content = []
    common_footers = set()

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        if end_page is None:
            end_page = total_pages

        if start_page < 1 or end_page > total_pages or start_page > end_page:
            raise ValueError(f"Invalid page range. PDF has {total_pages} pages.")

        if filter_headers_footers:
            page_last_lines = []
            for page_num in range(start_page - 1, end_page):
                text = pdf.pages[page_num].extract_text()
                if text:
                    lines = text.split('\n')
                    if lines:
                        page_last_lines.extend([l.strip() for l in lines[-3:] if l.strip()])

            line_counts = Counter(page_last_lines)
            common_footers = {line for line, count in line_counts.items()
                             if count > 2 and len(line) < 100}

        for page_num in range(start_page - 1, end_page):
            page = pdf.pages[page_num]
            text = extract_text_with_layout(page)

            if text:
                if include_page_numbers:
                    markdown_content.append(f"## Page {page_num + 1}\n\n")

                text = clean_text(text)
                lines = text.split('\n')

                i = 0
                paragraph_buffer = []
                in_list = False
                list_buffer = []

                while i < len(lines):
                    line = lines[i].strip()
                    next_line = lines[i + 1].strip() if i + 1 < len(lines) else None

                    if filter_headers_footers and line in common_footers:
                        i += 1
                        continue

                    if filter_headers_footers and re.match(r'^Page\s+\d+\s*$', line, re.IGNORECASE):
                        i += 1
                        continue

                    if not line:
                        if in_list and list_buffer:
                            for list_item in list_buffer:
                                markdown_content.append(list_item + '\n')
                            markdown_content.append('\n')
                            list_buffer = []
                            in_list = False
                        elif paragraph_buffer:
                            markdown_content.append(' '.join(paragraph_buffer) + '\n\n')
                            paragraph_buffer = []
                        i += 1
                        continue

                    is_heading_line = detect_heading(line, next_line) if preserve_formatting else False

                    if is_heading_line:
                        if in_list and list_buffer:
                            for list_item in list_buffer:
                                markdown_content.append(list_item + '\n')
                            markdown_content.append('\n')
                            list_buffer = []
                            in_list = False
                        if paragraph_buffer:
                            markdown_content.append(' '.join(paragraph_buffer) + '\n\n')
                            paragraph_buffer = []

                        formatted_line = format_line_as_markdown(line, is_heading=True)
                        markdown_content.append(formatted_line + '\n\n')
                        i += 1
                        continue

                    if is_list_item(line):
                        if paragraph_buffer:
                            markdown_content.append(' '.join(paragraph_buffer) + '\n\n')
                            paragraph_buffer = []

                        in_list = True
                        formatted_line = format_line_as_markdown(line)
                        list_buffer.append(formatted_line)
                    elif in_list:
                        if list_buffer and not is_heading_line:
                            list_buffer[-1] += ' ' + line
                        else:
                            for list_item in list_buffer:
                                markdown_content.append(list_item + '\n')
                            markdown_content.append('\n')
                            list_buffer = []
                            in_list = False
                            paragraph_buffer.append(line)
                    else:
                        paragraph_buffer.append(line)

                    i += 1

                if in_list and list_buffer:
                    for list_item in list_buffer:
                        markdown_content.append(list_item + '\n')
                    markdown_content.append('\n')
                if paragraph_buffer:
                    markdown_content.append(' '.join(paragraph_buffer) + '\n\n')

                if include_page_breaks and page_num < end_page - 1:
                    markdown_content.append('\n---\n\n')

    return ''.join(markdown_content)


def extract_text_to_markdown(
    pdf_path: str | Path,
    start_page: int = 1,
    end_page: int | None = None,
    use_marker: bool = False,
    use_pymupdf: bool = True,
    use_markitdown: bool = False,
    include_page_numbers: bool = True,
    include_page_breaks: bool = True,
    filter_headers_footers: bool = True,
    preserve_formatting: bool = True,
) -> dict:
    """
    Extract text from PDF and convert to markdown format.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page number (1-indexed)
        end_page: Ending page number (1-indexed), None for all pages
        use_marker: Try Marker first (ML-based, best quality but slow)
        use_pymupdf: Try PyMuPDF (good column detection)
        use_markitdown: Try MarkItDown
        include_page_numbers: Include page headers
        include_page_breaks: Include page separators
        filter_headers_footers: Filter repeated headers/footers
        preserve_formatting: Preserve text formatting

    Returns:
        Dictionary with extracted text and metadata
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"error": f"File not found: {pdf_path}"}

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

    if end_page is None:
        end_page = total_pages

    method_used = None
    markdown_text = None

    if use_marker and MARKER_AVAILABLE:
        try:
            markdown_text = extract_with_marker(pdf_path, start_page, end_page)
            method_used = "marker"
        except Exception as e:
            print(f"Marker extraction failed: {e}")

    if markdown_text is None and use_pymupdf and PYMUPDF_AVAILABLE:
        try:
            markdown_text = extract_with_pymupdf(pdf_path, start_page, end_page)
            method_used = "pymupdf"
        except Exception as e:
            print(f"PyMuPDF extraction failed: {e}")

    if markdown_text is None and use_markitdown and MARKITDOWN_AVAILABLE:
        try:
            markdown_text = extract_with_markitdown(pdf_path)
            method_used = "markitdown"
        except Exception as e:
            print(f"MarkItDown extraction failed: {e}")

    if markdown_text is None:
        try:
            markdown_text = extract_with_pdfplumber(
                pdf_path,
                start_page,
                end_page,
                include_page_numbers,
                include_page_breaks,
                filter_headers_footers,
                preserve_formatting,
            )
            method_used = "pdfplumber"
        except Exception as e:
            return {"error": f"All extraction methods failed: {e}"}

    return {
        "markdown": markdown_text,
        "total_pages": total_pages,
        "pages_extracted": f"{start_page}-{end_page}",
        "method": method_used,
        "char_count": len(markdown_text),
    }


def get_available_extractors() -> dict:
    """Return which extractors are available."""
    return {
        "marker": MARKER_AVAILABLE,
        "pymupdf": PYMUPDF_AVAILABLE,
        "markitdown": MARKITDOWN_AVAILABLE,
        "pdfplumber": True,
    }
