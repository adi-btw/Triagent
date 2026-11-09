"""Split a document into one chunk per `## ` section.

Why sections and not fixed-size windows:
* Runbooks are already written in self-contained sections (Symptoms, Diagnosis,
  Mitigation). A section is the unit a human would cite, so it is the unit we cite.
* The chunk ID rule (`f"{doc_id}#s{n}"`, see app/schemas.py) is shared with the corpus
  and the eval set. Section IDs stay stable when you edit text *inside* a section,
  whereas window-based IDs shift every time a sentence is added upstream.

Trade-off: a very long section becomes one large chunk. bge-small truncates input at
512 tokens, so text past that point is invisible to vector search (BM25 still sees it).
We warn instead of sub-splitting because sub-chunks (`#s2a`, `#s2b`) would break the
citation-ID rule everyone else depends on. The fix is editorial: split the section.
"""

from __future__ import annotations

import hashlib
import logging

from app.schemas import Chunk, Document

logger = logging.getLogger(__name__)

HEADING_PREFIX = "## "
MAX_SECTION_TOKENS = 400  # under bge-small's 512-token limit, leaving headroom
TOKENS_PER_WORD = 1.3  # rough English average for WordPiece tokenizers


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (words x 1.3). Good enough for a warning threshold, and it
    keeps the chunker independent of any particular model's tokenizer."""
    return int(len(text.split()) * TOKENS_PER_WORD)


def content_hash(content: str) -> str:
    """sha256 of the exact text that gets embedded. Ingestion compares hashes to decide
    what to re-embed, so the title/heading prefix is deliberately part of the input:
    renaming a document changes every chunk's embedding input, so all must re-embed."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_document(doc: Document, body: str) -> list[Chunk]:
    """Pure function: (Document, Markdown body) -> one chunk per `## ` heading.

    * ordinal is the 1-based index of the heading; chunk_id = f"{doc_id}#s{ordinal}".
    * Text before the first `## ` (a preamble) is dropped, per the chunk ID rule.
    * `### ` sub-headings stay inside their parent section.
    * content = f"{doc_id} · {title} · {heading}\\n{section_body}". The prefix puts the
      document's context into every chunk's embedding: a bare "Mitigation" section says
      little; "PostgreSQL connection exhaustion · Mitigation" says a lot.
    """
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    sections: list[tuple[str, list[str]]] = []
    for line in lines:
        if line.startswith(HEADING_PREFIX):
            sections.append((line[len(HEADING_PREFIX) :].strip(), []))
        elif sections:  # lines before the first heading are the dropped preamble
            sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for ordinal, (heading, section_lines) in enumerate(sections, start=1):
        section_body = "\n".join(section_lines).strip()
        content = f"{doc.doc_id} · {doc.title} · {heading}\n{section_body}"
        chunk_id = f"{doc.doc_id}#s{ordinal}"
        tokens = estimate_tokens(content)
        if tokens > MAX_SECTION_TOKENS:
            logger.warning(
                "%s (%r) is ~%d tokens (> %d); consider splitting the section. "
                "Kept as one chunk to preserve the citation-ID rule.",
                chunk_id,
                heading,
                tokens,
                MAX_SECTION_TOKENS,
            )
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                ordinal=ordinal,
                heading=heading,
                content=content,
                content_hash=content_hash(content),
            )
        )
    return chunks
