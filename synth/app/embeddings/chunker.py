import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.embeddings.models import Chunk


class BaseChunker(ABC):
    @abstractmethod
    def chunk_file(self, file_path: Path, content: str) -> list[Chunk]:
        pass

    @abstractmethod
    def chunk_directory(self, directory: Path, extensions: list[str] = None) -> list[Chunk]:
        pass


class FixedChunker(BaseChunker):
    def __init__(self, chunk_size: int = 512, overlap: int = 50):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_file(self, file_path: Path, content: str) -> list[Chunk]:
        chunks = []
        source = str(file_path)
        title = file_path.stem

        tokens = self._split_into_tokens(content)
        total_tokens = len(tokens)

        for i in range(0, total_tokens, self.chunk_size - self.overlap):
            chunk_tokens = tokens[i:i + self.chunk_size]
            chunk_content = self._tokens_to_text(chunk_tokens)

            if not chunk_content.strip():
                continue

            chunk_index = i // (self.chunk_size - self.overlap)
            total_chunks = (total_tokens + self.chunk_size - self.overlap - 1) // (self.chunk_size - self.overlap)

            chunk = Chunk(
                id=str(uuid.uuid4()),
                content=chunk_content,
                metadata={
                    "source": source,
                    "title": title,
                    "section": "",
                    "chunk_index": chunk_index,
                    "total_chunks": total_chunks,
                },
            )
            chunks.append(chunk)

        return chunks

    def chunk_directory(self, directory: Path, extensions: list[str] = None) -> list[Chunk]:
        if extensions is None:
            extensions = [".md"]

        chunks = []
        for ext in extensions:
            for file_path in directory.rglob(f"*{ext}"):
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        file_chunks = self.chunk_file(file_path, content)
                        chunks.extend(file_chunks)
                    except Exception as e:
                        print(f"Error chunking file {file_path}: {e}")

        return chunks

    def _split_into_tokens(self, text: str) -> list[str]:
        words = text.split()
        return words

    def _tokens_to_text(self, tokens: list[str]) -> str:
        return " ".join(tokens)


class StructureChunker(BaseChunker):
    HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def __init__(self, min_chunk_size: int = 100, max_chunk_size: int = 1000, preserve_headers: bool = True):
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.preserve_headers = preserve_headers

    def chunk_file(self, file_path: Path, content: str) -> list[Chunk]:
        chunks = []
        source = str(file_path)
        title = file_path.stem

        sections = self._split_by_headers(content)

        current_section_title = ""
        current_words = []

        for section in sections:
            header, section_content = section

            words = section_content.split()

            if len(current_words) + len(words) > self.max_chunk_size and current_words:
                chunk_content = " ".join(current_words)

                if self.preserve_headers and current_section_title:
                    chunk_content = f"{current_section_title}\n\n{chunk_content}"

                chunks.append(Chunk(
                    id=str(uuid.uuid4()),
                    content=chunk_content,
                    metadata={
                        "source": source,
                        "title": title,
                        "section": current_section_title,
                        "chunk_index": len(chunks),
                        "total_chunks": 0,
                    },
                ))

                if len(words) > self.max_chunk_size:
                    subchunks = self._split_large_section(file_path, words, current_section_title, source, title)
                    chunks.extend(subchunks[:-1])
                    current_words = subchunks[-1] if subchunks else []
                    current_section_title = header if header else current_section_title
                else:
                    current_words = words
                    current_section_title = header if header else current_section_title
            else:
                current_words.extend(words)
                if header:
                    current_section_title = header

        if current_words:
            chunk_content = " ".join(current_words)
            if self.preserve_headers and current_section_title:
                chunk_content = f"{current_section_title}\n\n{chunk_content}"

            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                content=chunk_content,
                metadata={
                    "source": source,
                    "title": title,
                    "section": current_section_title,
                    "chunk_index": len(chunks),
                    "total_chunks": len(chunks),
                },
            ))

        for i, chunk in enumerate(chunks):
            chunk.metadata["total_chunks"] = len(chunks)
            chunk.metadata["chunk_index"] = i

        return chunks

    def chunk_directory(self, directory: Path, extensions: list[str] = None) -> list[Chunk]:
        if extensions is None:
            extensions = [".md"]

        chunks = []
        for ext in extensions:
            for file_path in directory.rglob(f"*{ext}"):
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        file_chunks = self.chunk_file(file_path, content)
                        chunks.extend(file_chunks)
                    except Exception as e:
                        print(f"Error chunking file {file_path}: {e}")

        return chunks

    def _split_by_headers(self, content: str) -> list[tuple[str, str]]:
        sections = []
        matches = list(self.HEADER_PATTERN.finditer(content))

        if not matches:
            return [("", content)]

        for i, match in enumerate(matches):
            header = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()

            sections.append((header, section_content))

        return sections

    def _split_large_section(
        self,
        file_path: Path,
        words: list[str],
        section_title: str,
        source: str,
        title: str,
    ) -> list[list[str]]:
        subchunks = []
        current_words = []

        for word in words:
            current_words.append(word)

            if len(current_words) >= self.max_chunk_size:
                subchunks.append(current_words)
                current_words = current_words[-self.min_chunk_size:]

        if current_words:
            subchunks.append(current_words)

        return subchunks


def create_chunker(strategy: str, params: dict[str, Any] = None) -> BaseChunker:
    if params is None:
        params = {}

    if strategy == "fixed":
        return FixedChunker(
            chunk_size=params.get("chunk_size", 512),
            overlap=params.get("overlap", 50),
        )
    elif strategy == "structure":
        return StructureChunker(
            min_chunk_size=params.get("min_chunk_size", 100),
            max_chunk_size=params.get("max_chunk_size", 1000),
            preserve_headers=params.get("preserve_headers", True),
        )
    else:
        raise ValueError(f"Unknown chunking strategy: {strategy}")
