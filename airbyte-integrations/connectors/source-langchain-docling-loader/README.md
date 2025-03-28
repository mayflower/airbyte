# LangChain DoclingLoader Source

This is the repository for the LangChain DoclingLoader source connector, written in Python.
For information about how to use this connector within Airbyte, see [the documentation](https://docs.airbyte.io/integrations/sources/langchain-docling-loader).

## Overview

This connector processes a list of file and directory paths, using DoclingLoader from LangChain to extract content and metadata. It handles:

1. Individual files - Directly processes supported file formats
2. Directories - Recursively scans for supported document types

## Quick Start

```bash
# Basic configuration example
{
  "paths": ["/path/to/documents"],
  "export_type": "DOC_CHUNKS",
  "sync_mode": "full_refresh"
}

# Run the connector
docker run --rm -v $(pwd)/config.json:/config.json airbyte/source-langchain-docling-loader:dev read --config /config.json
```

## Supported Document Formats

The connector supports the following document formats:

- **PDF**: `.pdf` files
- **Office Formats**:
  - Microsoft Word (`.docx`)
  - Microsoft Excel (`.xlsx`)
  - Microsoft PowerPoint (`.pptx`)
- **Text Formats**:
  - Markdown (`.md`, `.markdown`)
  - Rich Text Format (`.rtf`)
  - AsciiDoc (`.adoc`, `.asciidoc`)
  - HTML/XHTML (`.html`, `.htm`, `.xhtml`)
  - CSV (`.csv`)
  - Any other text-based format (all `text/*` MIME types)
- **Image Formats**:
  - PNG (`.png`)
  - JPEG (`.jpg`, `.jpeg`)
  - TIFF (`.tiff`, `.tif`)
  - BMP (`.bmp`)

## Configuration

### Required Parameters

- `paths`: An array of file and directory paths to process. Each path can be:
  - A path to a specific document (in a supported format)
  - A path to a directory (will be recursively scanned for supported files)
  - Paths can use tilde (~) expansion for user's home directory

### Optional Parameters

- `export_type`: The export type for the documents. Only these two values are supported:
  - `DOC_CHUNKS` (default): Chunks each document into separate pieces that are more suitable for language model processing
  - `MARKDOWN`: Captures each input document as a single LangChain Document, preserving the full content without chunking
- `chunker_tokenizer`: Optional tokenizer model ID to use with HybridChunker. This parameter determines how documents are split into chunks. Leave empty to not use chunking.

### Export Type Comparison

| Export Type  | Description                                                       | Best For                                                                            | Typical Output                                                    |
| ------------ | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `DOC_CHUNKS` | Splits documents into smaller, semantically meaningful pieces     | RAG applications, content analysis, Q&A systems                                     | Many smaller documents with metadata pointing to source locations |
| `MARKDOWN`   | Preserves the entire document as a single unit in markdown format | Document archiving, full-text indexing, documents where structure must be preserved | One document per input file with complete content                 |

### Chunker Tokenizer Options

The `chunker_tokenizer` parameter accepts various pre-trained tokenizer models. Here are some of the commonly used options:

| Tokenizer Model                | Description                | Language Focus | Notes                                           |
| ------------------------------ | -------------------------- | -------------- | ----------------------------------------------- |
| `gpt2`                         | OpenAI's GPT-2 tokenizer   | English        | Good general-purpose option for English content |
| `bert-base-uncased`            | BERT base model tokenizer  | English        | Uncased version (ignores capitalization)        |
| `bert-base-cased`              | BERT base model tokenizer  | English        | Cased version (preserves capitalization)        |
| `bert-base-multilingual-cased` | Multilingual BERT          | 104 languages  | Good for multilingual content                   |
| `xlm-roberta-base`             | XLM-RoBERTa model          | 100 languages  | Strong multilingual performance                 |
| `distilbert-base-uncased`      | DistilBERT model tokenizer | English        | Lighter and faster than BERT                    |
| `gpt-neox-20b`                 | GPT-NeoX tokenizer         | English        | For larger context handling                     |
| `microsoft/deberta-v3-base`    | DeBERTa model tokenizer    | English        | Improved BERT variant                           |
| `t5-base`                      | T5 model tokenizer         | English        | Text-to-Text Transfer Transformer               |
| `EleutherAI/gpt-neo-1.3B`      | GPT-Neo tokenizer          | English        | Open-source GPT alternative                     |

For language-specific content, these specialized models may provide better chunking:

| Tokenizer Model                                    | Language        | Description                                    | Notes                                                                                 |
| -------------------------------------------------- | --------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| `dbmdz/bert-base-german-cased`                     | German          | BERT model trained on German corpus            | Optimal for German text, preserves capitalization which is important for German nouns |
| `camembert-base`                                   | French          | RoBERTa model trained on French corpus         | Specifically tuned for French linguistic features and accents                         |
| `dccuchile/bert-base-spanish-wwm-cased`            | Spanish         | BERT model with whole word masking for Spanish | Better handles Spanish conjugations and morphology                                    |
| `cl-tohoku/bert-base-japanese`                     | Japanese        | BERT model with Japanese-specific tokenization | Uses character-level tokenization appropriate for kanji and kana                      |
| `allegro/herbert-base-cased`                       | Polish          | BERT model trained on Polish language          | Handles Polish diacritics and complex grammar                                         |
| `DeepPavlov/rubert-base-cased`                     | Russian         | BERT model for Russian language                | Optimized for Cyrillic alphabet and Russian morphology                                |
| `bert-base-chinese`                                | Chinese         | BERT model trained on Chinese corpus           | Character-based tokenization suitable for Chinese text without spaces                 |
| `indolem/indobert-base-uncased`                    | Indonesian      | BERT model for Indonesian language             | Trained on formal and informal Indonesian text varieties                              |
| `nlptown/bert-base-multilingual-uncased-sentiment` | Multilingual    | BERT model fine-tuned for sentiment analysis   | Works across multiple languages, useful if documents contain emotional content        |
| `ai4bharat/indic-bert`                             | Indic languages | BERT model for 12 Indian languages             | Covers Hindi, Bengali, Marathi, Tamil, etc. - useful for South Asian content          |
| `aubmindlab/bert-base-arabertv02`                  | Arabic          | AraBERT model for Arabic language              | Handles right-to-left text and Arabic-specific morphology                             |
| `Finnish-NLP/bert-base-finnish-cased-v1`           | Finnish         | BERT model trained on Finnish corpus           | Handles Finnish compound words and cases effectively                                  |
| `ltg/bert-base-swedish-cased`                      | Swedish         | BERT model trained on Swedish text             | Optimized for Scandinavian characters and Swedish grammar                             |
| `flax-community/hf-norwegian-roberta-base`         | Norwegian       | RoBERTa model for Norwegian                    | Good performance on Norwegian Bokmål and Nynorsk                                      |
| `wietsedv/bert-base-dutch-cased`                   | Dutch           | BERT model trained on Dutch corpus             | Handles compound words common in Dutch language                                       |
| `KoichiYasuoka/bert-base-korean-morph`             | Korean          | BERT model with Korean morphological analysis  | Better handles Korean agglutinative grammar with morpheme-aware tokenization          |
| `neuralmind/bert-base-portuguese-cased`            | Portuguese      | BERT model trained on Brazilian Portuguese     | Optimized for Portuguese grammar and accents                                          |
| `SZTAKI-HLT/hubert-base-cc`                        | Hungarian       | BERT model for Hungarian language              | Specifically designed for Hungarian's complex agglutinative structure                 |
| `mtheos/athenian-bert`                             | Greek           | BERT model trained on modern Greek             | Handles Greek alphabet and linguistic structures                                      |
| `akuthi/indic-legal-bert`                          | Legal/Indic     | BERT model for Indian legal documents          | Specialized for legal terminology in Indian languages                                 |

**Note:** The tokenizer used affects how documents are split into chunks, which can impact retrieval quality. Choose a tokenizer that best matches your content's language and domain. For documents containing specialized terminology (medical, legal, technical), consider using domain-specific tokenizers when available.

### Examples

#### Basic configuration

```json
{
  "paths": ["/data/documents/"]
}
```

This configuration will process all files in the specified directory and its subdirectories on every sync.

#### Language-specific configuration

```json
{
  "paths": ["/data/german_documents/"],
  "export_type": "MARKDOWN",
  "chunker_tokenizer": "dbmdz/bert-base-german-cased"
}
```

This configuration is optimized for processing German documents, using a German-specific tokenizer.

## Output Schema

Each record in the output will contain:

- `id`: A unique identifier for the document chunk
- `content`: The text content of the document chunk
- `metadata`: Metadata associated with the document, including:
  - `source_file`: The absolute path to the source file
  - `relative_path`: The path relative to the input directory/base path
  - Other document-specific metadata (page numbers, sections, etc.)
- `extracted_at`: Timestamp when the document was extracted
- `file_modified_at`: Last modification timestamp of the source file

## State Management

For incremental syncs, the connector tracks the last modified time of processed files in the state. Only files modified since this time will be processed in subsequent syncs.

For resumable full refresh syncs, the connector maintains a checkpoint of the last processed file, allowing it to resume from that point if interrupted.

## Performance Considerations

- Processing large document collections may require significant time and memory
- The connector processes files sequentially, not in parallel
- For incremental syncs, only modified files are processed, which can significantly reduce sync time for large document collections
- Memory usage depends on the size of the documents and the chunking strategy used

Security and Permissions
The connector requires read access to all files and directories specified in the paths configuration. Ensure that the user running Airbyte has appropriate permissions.

## Troubleshooting

Common issues:

- **Permission Denied**: Ensure the user running Airbyte has read permissions for all specified paths
- **Unsupported File Format**: Check if the file type is in the supported formats list
- **Memory Issues**: For very large documents, consider using a chunking strategy or processing fewer documents at once

## Local development

### Prerequisites

**To iterate on this connector, make sure to complete this prerequisites section.**

#### Poetry

This connector uses [Poetry](https://python-poetry.org/) for Python dependency management. Please install Poetry if you don't have it already.

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

#### Python version required `= ^3.9`

### Development Environment Setup

1. Install dependencies with Poetry:

```bash
cd airbyte-integrations/connectors/source-langchain-docling-loader-2
poetry install
```

2. Create mock documents for testing:

```bash
mkdir -p test_files
echo "Test document content" > test_files/test.txt
```

### Running the connector

```bash
# Using Poetry to run the connector with specific commands
poetry run python main.py spec
poetry run python main.py check --config sample_files/config.json
poetry run python main.py discover --config sample_files/config.json
poetry run python main.py read --config sample_files/config.json --catalog sample_files/configured_catalog.json
```

### Unit Tests

Run unit tests with Poetry:

```bash
poetry run pytest -xvs unit_tests/
```

### Integration Tests

Run integration tests with Poetry:

```bash
poetry run pytest -xvs integration_tests/
```

### Building the Docker image

```bash
docker build -f Dockerfile -t registry.data.mayflower.zone/airbyte-base-image:dev --platform=linux/amd64,linux/arm64 .
docker push registry.data.mayflower.zone/airbyte-base-image:dev
```

### Running the connector in Docker

```bash
docker run --rm -v $(pwd)/sample_files:/sample_files airbyte/source-langchain-docling-loader:dev spec
docker run --rm -v $(pwd)/sample_files:/sample_files airbyte/source-langchain-docling-loader:dev check --config /sample_files/config.json
docker run --rm -v $(pwd)/sample_files:/sample_files airbyte/source-langchain-docling-loader:dev discover --config /sample_files/config.json
docker run --rm -v $(pwd)/sample_files:/sample_files -v $(pwd)/local_sample_files:/local_sample_files airbyte/source-langchain-docling-loader:dev read --config /sample_files/config.json --catalog /sample_files/configured_catalog.json
```

## Summary

The LangChain DoclingLoader source connector provides a flexible way to extract content from various document formats for use in Airbyte data pipelines. Key features include:

- **Versatile document processing**: Support for multiple document formats including PDFs, Word documents, PowerPoint presentations, and more
- **Flexible path handling**: Process individual files or recursively scan directories
- **Multiple sync modes**: Choose between full refresh, incremental, or resumable sync modes
- **Configurable export types**: Select between chunked documents (DOC_CHUNKS) or full documents (MARKDOWN)
- **Language-aware tokenization**: Optional language-specific tokenization for improved chunking quality
- **Rich metadata extraction**: Maintain document context with detailed metadata in each record

This connector is particularly valuable for language model applications, content analysis, document management systems, and any workflow requiring structured extraction of document content.
