#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import datetime
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from langchain_docling.loader import ExportType
from source_langchain_docling_loader.source import EMBED_MODEL_ID, DoclingStream, SourceLangchainDoclingLoader

from airbyte_cdk.models import SyncMode


@contextmanager
def does_not_raise():
    yield


@pytest.fixture
def test_files():
    """Erstellt temporäre Testdateien verschiedener Typen."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # PDF-Datei
        pdf_path = Path(temp_dir) / "test_document.pdf"
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.5\nTest PDF content")

        # DOCX-Datei (Pseudoinhalt)
        docx_path = Path(temp_dir) / "test_doc.docx"
        with open(docx_path, "wb") as f:
            f.write(b"PKzip docx content")

        # CSV-Datei
        csv_path = Path(temp_dir) / "test_data.csv"
        with open(csv_path, "w") as f:
            f.write("id,name,value\n1,test,42\n")

        # Markdown-Datei
        md_path = Path(temp_dir) / "test_readme.md"
        with open(md_path, "w") as f:
            f.write("# Test Markdown\nThis is a test file.")

        # Ungültige Datei
        invalid_path = Path(temp_dir) / "invalid.xyz"
        with open(invalid_path, "w") as f:
            f.write("invalid content")

        # Struktur für Rückgabe erstellen
        yield {
            "dir_path": temp_dir,
            "pdf_path": str(pdf_path),
            "docx_path": str(docx_path),
            "csv_path": str(csv_path),
            "md_path": str(md_path),
            "invalid_path": str(invalid_path),
        }


@pytest.fixture
def mock_docling_loader(monkeypatch):
    """
    Mock für DoclingLoader zur Verwendung in Tests, die keine echte Verarbeitung erfordern.
    """

    class MockChunk:
        def __init__(self, content, metadata=None):
            self.page_content = content
            self.metadata = metadata or {}

    class MockDoclingLoader:
        def __init__(self, file_path, export_type, chunker):
            self.file_path = file_path
            self.export_type = export_type
            self.chunker = chunker

            # Simuliere verschiedene Chunks basierend auf dem Dateityp
            ext = os.path.splitext(file_path.lower())[1]
            if ext == ".pdf":
                self.chunks = [MockChunk("PDF content page 1", {"page": 1}), MockChunk("PDF content page 2", {"page": 2})]
            elif ext == ".csv":
                self.chunks = [MockChunk("CSV row 1", {"row": 1}), MockChunk("CSV row 2", {"row": 2}), MockChunk("CSV row 3", {"row": 3})]
            elif ext == ".docx":
                self.chunks = [MockChunk("DOCX content", {"paragraph": 1})]
            elif ext == ".md":
                self.chunks = [MockChunk("Markdown content", {"section": "main"})]
            else:
                self.chunks = [MockChunk(f"Content from {os.path.basename(file_path)}")]

        def lazy_load(self):
            return self.chunks

    # DoclingLoader durch unseren Mock ersetzen
    import source_langchain_docling_loader.source

    monkeypatch.setattr(source_langchain_docling_loader.source, "DoclingLoader", MockDoclingLoader)

    # HybridChunker mocken um echte Initialisierung zu verhindern
    monkeypatch.setattr(source_langchain_docling_loader.source, "HybridChunker", lambda tokenizer: None)

    return MockDoclingLoader


# Low-Level-Unit-Tests mit Mocks
def test_docling_stream_with_export_type():
    # Test mit DOC_CHUNKS
    stream1 = DoclingStream(paths=[], export_type="DOC_CHUNKS")
    assert stream1.export_type == ExportType.DOC_CHUNKS

    # Test mit MARKDOWN
    stream2 = DoclingStream(paths=[], export_type="MARKDOWN")
    assert stream2.export_type == ExportType.MARKDOWN

    # Test mit Default
    stream3 = DoclingStream(paths=[])
    assert stream3.export_type == ExportType.DOC_CHUNKS


def test_get_file_id(monkeypatch):
    stream = DoclingStream(paths=[])

    # Mock os.stat für deterministische Tests
    class MockStat:
        def __init__(self, mtime):
            self.st_mtime = mtime

    monkeypatch.setattr(os, "stat", lambda path: MockStat(1234567890))

    file_id_1 = stream._get_file_id("/path/to/file1.pdf")
    assert isinstance(file_id_1, str)
    assert len(file_id_1) > 0

    # Gleicher Pfad und mtime sollten gleiche ID erzeugen
    file_id_2 = stream._get_file_id("/path/to/file1.pdf")
    assert file_id_1 == file_id_2

    # Unterschiedlicher Pfad sollte unterschiedliche ID erzeugen
    file_id_3 = stream._get_file_id("/path/to/file2.pdf")
    assert file_id_1 != file_id_3

    # Gleicher Pfad aber andere mtime sollte unterschiedliche ID erzeugen
    monkeypatch.setattr(os, "stat", lambda path: MockStat(9876543210))
    file_id_4 = stream._get_file_id("/path/to/file1.pdf")
    assert file_id_1 != file_id_4


def test_get_file_modified_time(monkeypatch):
    stream = DoclingStream(paths=[])

    # Mock os.stat für deterministische Tests
    timestamp = 1609459200  # 2021-01-01 00:00:00
    monkeypatch.setattr(os, "stat", lambda path: type("MockStat", (), {"st_mtime": timestamp})())

    modified_time = stream._get_file_modified_time("/path/to/file.pdf")
    assert isinstance(modified_time, datetime.datetime)
    assert modified_time == datetime.datetime.fromtimestamp(timestamp)


def test_get_updated_state():
    stream = DoclingStream(paths=[])

    # Test mit leerem aktuellen State
    current_state = {}
    latest_record = {"file_modified_at": "2023-01-15T00:00:00"}

    updated_state = stream.get_updated_state(current_state, latest_record)
    assert updated_state["file_modified_at"] == "2023-01-15T00:00:00"

    # Test mit bestehendem State, neuerem Record
    current_state = {"file_modified_at": "2023-01-01T00:00:00"}
    latest_record = {"file_modified_at": "2023-01-15T00:00:00"}

    updated_state = stream.get_updated_state(current_state, latest_record)
    assert updated_state["file_modified_at"] == "2023-01-15T00:00:00"

    # Test mit bestehendem State, älterem Record
    current_state = {"file_modified_at": "2023-01-15T00:00:00"}
    latest_record = {"file_modified_at": "2023-01-01T00:00:00"}

    updated_state = stream.get_updated_state(current_state, latest_record)
    assert updated_state["file_modified_at"] == "2023-01-15T00:00:00"

    # Test mit fehlendem Cursor-Feld im Record
    current_state = {"file_modified_at": "2023-01-01T00:00:00"}
    latest_record = {"content": "test"}

    updated_state = stream.get_updated_state(current_state, latest_record)
    assert updated_state["file_modified_at"] == "2023-01-01T00:00:00"


def test_stream_slices():
    stream = DoclingStream(paths=[])

    # Test mit leerem State
    stream.state = {}
    slices = list(stream.stream_slices())
    assert len(slices) == 1
    assert slices[0]["state"] == {}

    # Test mit nicht-leerem State
    stream.state = {"file_modified_at": "2023-01-01T00:00:00"}
    slices = list(stream.stream_slices())
    assert len(slices) == 1
    assert slices[0]["state"] == {"file_modified_at": "2023-01-01T00:00:00"}

    # Test mit explizitem State-Parameter
    stream.state = {}
    state_param = {"file_modified_at": "2023-02-01T00:00:00"}
    slices = list(stream.stream_slices(stream_state=state_param))
    assert len(slices) == 1
    assert slices[0]["state"] == state_param
    assert stream.state == state_param


# Integration-Tests mit Fixtures
def test_is_supported_file_with_real_files(test_files):
    stream = DoclingStream(paths=[])

    # Unterstützte Dateiformate sollten erkannt werden
    assert stream._is_supported_file(test_files["pdf_path"]) is True
    assert stream._is_supported_file(test_files["docx_path"]) is True
    assert stream._is_supported_file(test_files["csv_path"]) is True
    assert stream._is_supported_file(test_files["md_path"]) is True

    # Nicht unterstützte Dateiformate sollten abgelehnt werden
    assert stream._is_supported_file(test_files["invalid_path"]) is False


def test_scan_directory_with_real_files(test_files):
    stream = DoclingStream(paths=[])

    # Scannen des temporären Verzeichnisses
    files = stream._scan_directory(test_files["dir_path"])

    # Sollte alle unterstützten Dateien finden
    assert len(files) == 4  # 4 unterstützte Dateien (PDF, DOCX, CSV, MD)

    # Überprüfen, ob jede unterstützte Datei gefunden wurde
    supported_files = [test_files["pdf_path"], test_files["docx_path"], test_files["csv_path"], test_files["md_path"]]

    for file_path in files:
        assert file_path in supported_files


def test_get_all_files_to_process_with_real_files(test_files):
    # Stream mit echten Dateipfaden initialisieren
    paths = [
        test_files["pdf_path"],  # Einzelne PDF-Datei
        test_files["csv_path"],  # Einzelne CSV-Datei
        test_files["dir_path"],  # Verzeichnis mit allen Testdateien
    ]

    stream = DoclingStream(paths=paths)

    # Methode aufrufen
    files = stream._get_all_files_to_process()

    # Sollte 6 Einträge haben: 2 für die einzelnen Dateien + 4 aus dem Verzeichnis
    # Beachte: Es werden 4 Duplikate sein, da die einzelnen Dateien auch im Verzeichnis sind
    assert len(files) == 6

    # Überprüfen der korrekten base_dir-Werte für einzelne Dateien
    pdf_entries = [f for f in files if f["file_path"] == test_files["pdf_path"]]
    assert len(pdf_entries) == 2  # Eine vom direkten Pfad, eine vom Verzeichnisscan
    # Mindestens ein Eintrag sollte das Elternverzeichnis des PDF als base_dir haben
    assert any(f["base_dir"] == str(Path(test_files["pdf_path"]).parent) for f in pdf_entries)

    # Überprüfen, dass alle unterstützten Dateitypen gefunden wurden
    file_paths = [f["file_path"] for f in files]
    assert test_files["pdf_path"] in file_paths
    assert test_files["docx_path"] in file_paths
    assert test_files["csv_path"] in file_paths
    assert test_files["md_path"] in file_paths
    # Ungültige Datei sollte nicht enthalten sein
    assert test_files["invalid_path"] not in file_paths


def test_get_document_records_with_mock_loader(test_files, mock_docling_loader):
    stream = DoclingStream(paths=[])

    # Mock für _get_file_id und _get_file_modified_time
    stream._get_file_id = lambda path: "test_file_id"
    stream._get_file_modified_time = lambda path: datetime.datetime(2023, 1, 1)

    # Test mit PDF-Datei
    file_info_pdf = {"file_path": test_files["pdf_path"], "base_dir": str(Path(test_files["pdf_path"]).parent)}
    records_pdf = stream._get_document_records(file_info_pdf)

    # Test mit CSV-Datei
    file_info_csv = {"file_path": test_files["csv_path"], "base_dir": str(Path(test_files["csv_path"]).parent)}
    records_csv = stream._get_document_records(file_info_csv)

    # Überprüfungen für PDF
    assert len(records_pdf) == 2
    assert records_pdf[0]["id"] == "test_file_id_0"
    assert "PDF content" in records_pdf[0]["content"]
    assert records_pdf[0]["metadata"]["source_file"] == test_files["pdf_path"]
    assert records_pdf[0]["metadata"]["relative_path"] == os.path.basename(test_files["pdf_path"])

    # Überprüfungen für CSV
    assert len(records_csv) == 3
    assert records_csv[0]["id"] == "test_file_id_0"
    assert "CSV row" in records_csv[0]["content"]
    assert records_csv[0]["metadata"]["source_file"] == test_files["csv_path"]
    assert records_csv[0]["metadata"]["relative_path"] == os.path.basename(test_files["csv_path"])


def test_get_document_records_with_cursor(test_files, mock_docling_loader):
    stream = DoclingStream(paths=[])

    # Mocks für Hilfsfunktionen
    stream._get_file_id = lambda path: "test_id"

    # Test 1: Datei nach Cursor-Wert geändert (sollte verarbeitet werden)
    stream._get_file_modified_time = lambda path: datetime.datetime(2023, 2, 1)

    # Aufruf mit Cursor-Wert früher als Datei-Änderungszeit
    file_info = {"file_path": test_files["csv_path"], "base_dir": str(Path(test_files["csv_path"]).parent)}
    records = stream._get_document_records(file_info, cursor_field="file_modified_at", cursor_value="2023-01-01T00:00:00")

    # Sollte die Datei verarbeiten
    assert len(records) == 3  # CSV hat 3 Chunks in unserem Mock

    # Test 2: Datei vor Cursor-Wert geändert (sollte übersprungen werden)
    stream._get_file_modified_time = lambda path: datetime.datetime(2023, 1, 1)

    # Aufruf mit Cursor-Wert später als Datei-Änderungszeit
    records = stream._get_document_records(file_info, cursor_field="file_modified_at", cursor_value="2023-02-01T00:00:00")

    # Sollte die Datei überspringen
    assert len(records) == 0


def test_incremental_filtering(test_files, mock_docling_loader, monkeypatch):
    """
    Detaillierter Test der inkrementellen Filterung in DoclingStream.
    Überwacht, welche Methoden mit welchen Parametern aufgerufen werden.
    """
    # Stream mit echtem Verzeichnispfad initialisieren
    stream = DoclingStream(paths=[test_files["dir_path"]])

    # Feste Timestamps für die Tests
    modified_time = datetime.datetime(2023, 1, 1)
    monkeypatch.setattr(stream, "_get_file_modified_time", lambda path: modified_time)
    monkeypatch.setattr(stream, "_get_file_id", lambda path: hashlib.md5(path.encode()).hexdigest())

    # Überwachen der _get_document_records-Aufrufe
    original_get_document_records = stream._get_document_records
    call_args = []

    def mock_get_document_records(file_info, cursor_field=None, cursor_value=None):
        call_args.append({"file_path": file_info["file_path"], "cursor_field": cursor_field, "cursor_value": cursor_value})
        return original_get_document_records(file_info, cursor_field, cursor_value)

    monkeypatch.setattr(stream, "_get_document_records", mock_get_document_records)

    # Inkrementelle Synchronisierung mit zukünftigem Datum testen
    future_state = {"file_modified_at": "2023-02-01T00:00:00"}

    # Explicit stream_state Parameter beim Aufruf von read_records
    future_records = list(stream.read_records(SyncMode.incremental, stream_state=future_state))

    # Überprüfen, dass jeder Aufruf von _get_document_records den richtigen cursor_value hat
    assert len(call_args) > 0
    for call in call_args:
        assert call["cursor_field"] == "file_modified_at"
        assert call["cursor_value"] == "2023-02-01T00:00:00"

    # Ergebnisse sollten leer sein, da alle Dateien vor dem State-Datum modifiziert wurden
    assert len(future_records) == 0


def test_process_files_incremental(test_files, mock_docling_loader, monkeypatch):
    """Test für die _process_files_incremental-Methode mit direkter Übergabe des cursor_field und cursor_value."""
    stream = DoclingStream(paths=[])

    # Setze den State
    stream.state = {"file_modified_at": "2023-02-01T00:00:00"}

    # Erstelle Testdaten
    file_info1 = {"file_path": test_files["pdf_path"], "base_dir": str(Path(test_files["pdf_path"]).parent)}
    file_info2 = {"file_path": test_files["csv_path"], "base_dir": str(Path(test_files["csv_path"]).parent)}

    # Mock _get_file_modified_time um ein festes Datum zurückzugeben
    monkeypatch.setattr(stream, "_get_file_modified_time", lambda path: datetime.datetime(2023, 1, 1))

    # Mock _get_document_records, um die Übergabe von cursor_field und cursor_value zu prüfen
    original_get_document_records = stream._get_document_records
    calls = []

    def mock_get_document_records(file_info, cursor_field=None, cursor_value=None):
        calls.append((file_info, cursor_field, cursor_value))
        # Bei diesem Test sollten keine Records zurückgegeben werden
        # da das Änderungsdatum vor dem State-Datum liegt
        return []

    monkeypatch.setattr(stream, "_get_document_records", mock_get_document_records)

    # Methode aufrufen
    list(stream._process_files_incremental([file_info1, file_info2]))

    # Überprüfen, dass _get_document_records mit den richtigen Parametern aufgerufen wurde
    assert len(calls) == 2
    for call in calls:
        assert call[1] == "file_modified_at"  # cursor_field
        assert call[2] == "2023-02-01T00:00:00"  # cursor_value


def test_read_records_stream_state_parameter(test_files, mock_docling_loader, monkeypatch):
    """
    Test für die korrekte Übergabe des stream_state-Parameters an die read_records-Methode.
    """
    # Stream mit echtem Verzeichnispfad initialisieren
    stream = DoclingStream(paths=[test_files["dir_path"]])

    # Mock _get_all_files_to_process um eine feste Liste zurückzugeben
    fake_files = [
        {"file_path": test_files["pdf_path"], "base_dir": str(Path(test_files["pdf_path"]).parent)},
        {"file_path": test_files["csv_path"], "base_dir": str(Path(test_files["csv_path"]).parent)},
    ]
    monkeypatch.setattr(stream, "_get_all_files_to_process", lambda: fake_files)

    # Überwachen von _process_files_incremental
    original_process_incremental = stream._process_files_incremental
    incremental_state_arg = None

    def mock_process_incremental(files_to_process):
        nonlocal incremental_state_arg
        incremental_state_arg = stream.state.copy()
        return []

    monkeypatch.setattr(stream, "_process_files_incremental", mock_process_incremental)

    # Methode mit explizitem stream_state aufrufen
    test_state = {"file_modified_at": "2023-02-01T00:00:00"}
    list(stream.read_records(SyncMode.incremental, stream_state=test_state))

    # Überprüfen, dass der State korrekt gesetzt wurde
    assert incremental_state_arg == test_state
    assert stream.state == test_state


# Tests für die Source-Klasse
def test_check_connection_with_real_files(test_files):
    source = SourceLangchainDoclingLoader()

    # Logger-Mock
    logger_mock = type(
        "MockLogger",
        (),
        {"info": lambda *args, **kwargs: None, "warning": lambda *args, **kwargs: None, "error": lambda *args, **kwargs: None},
    )()

    # Test mit gültigen Pfaden
    config = {"paths": [test_files["pdf_path"], test_files["dir_path"]]}

    result, message = source.check_connection(logger_mock, config)
    assert result is True
    assert message is None

    # Test mit ungültigem Export-Typ
    config_invalid_export = {"paths": [test_files["pdf_path"]], "export_type": "INVALID_TYPE"}

    result, message = source.check_connection(logger_mock, config_invalid_export)
    assert result is False
    assert "Unsupported export_type" in message

    # Test mit leeren Pfaden
    config_empty = {"paths": []}
    result, message = source.check_connection(logger_mock, config_empty)
    assert result is False
    assert "non-empty list" in message

    # Test mit ungültigen Pfaden
    config_invalid = {"paths": ["/path/does/not/exist"]}
    result, message = source.check_connection(logger_mock, config_invalid)
    assert result is False
    assert "No valid paths found" in message


def test_streams(test_files, monkeypatch):
    # HybridChunker mocken um echte Initialisierung zu verhindern
    import source_langchain_docling_loader.source

    monkeypatch.setattr(source_langchain_docling_loader.source, "HybridChunker", lambda tokenizer: None)

    source = SourceLangchainDoclingLoader()
    config = {"paths": [test_files["pdf_path"], test_files["dir_path"]], "export_type": "MARKDOWN", "chunker_tokenizer": EMBED_MODEL_ID}

    streams = source.streams(config)

    assert len(streams) == 1
    assert isinstance(streams[0], DoclingStream)
    assert streams[0].paths == config["paths"]
    assert streams[0].export_type == ExportType.MARKDOWN


# Integration Test für die gesamte Verarbeitungspipeline
def test_end_to_end_full_refresh(test_files, mock_docling_loader, monkeypatch):
    """
    Teste die gesamte Pipeline mit vollständiger Aktualisierung.
    """
    # Mock für get_json_schema, um ohne die tatsächliche Schemadatei zu funktionieren
    monkeypatch.setattr(
        DoclingStream,
        "get_json_schema",
        lambda self: {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "content": {"type": "string"},
                "metadata": {"type": "object"},
                "extracted_at": {"type": "string"},
                "file_modified_at": {"type": "string"},
            },
        },
    )

    # Source und Config erstellen
    source = SourceLangchainDoclingLoader()
    config = {"paths": [test_files["dir_path"]], "export_type": "DOC_CHUNKS"}

    # Stream-Instanz erzeugen
    streams = source.streams(config)
    assert len(streams) == 1

    stream = streams[0]

    # Records mit Full Refresh lesen
    records = list(stream.read_records(SyncMode.full_refresh))

    # Überprüfen, dass Records für alle Dateitypen vorhanden sind
    assert any(test_files["pdf_path"] in r["metadata"]["source_file"] for r in records)
    assert any(test_files["docx_path"] in r["metadata"]["source_file"] for r in records)
    assert any(test_files["csv_path"] in r["metadata"]["source_file"] for r in records)
    assert any(test_files["md_path"] in r["metadata"]["source_file"] for r in records)


def test_end_to_end_incremental(test_files, mock_docling_loader, monkeypatch):
    """
    Teste die gesamte Pipeline mit inkrementeller Synchronisierung.
    """
    # Mock für get_json_schema
    monkeypatch.setattr(
        DoclingStream,
        "get_json_schema",
        lambda self: {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "content": {"type": "string"},
                "metadata": {"type": "object"},
                "extracted_at": {"type": "string"},
                "file_modified_at": {"type": "string"},
            },
        },
    )

    # Zeitstempel für die Tests
    modification_times = {
        test_files["pdf_path"]: datetime.datetime(2023, 1, 15),  # Neuere Datei
        test_files["docx_path"]: datetime.datetime(2023, 1, 10),  # Ältere Datei
        test_files["csv_path"]: datetime.datetime(2023, 2, 1),  # Neueste Datei
        test_files["md_path"]: datetime.datetime(2023, 1, 5),  # Älteste Datei
    }

    # Mock für _get_file_modified_time
    def mock_modified_time(path):
        # Standardwert für unbekannte Pfade
        return modification_times.get(path, datetime.datetime(2023, 1, 1))

    # Source und Config erstellen
    source = SourceLangchainDoclingLoader()
    config = {"paths": [test_files["dir_path"]], "export_type": "DOC_CHUNKS"}

    # Stream-Instanz erzeugen
    streams = source.streams(config)
    stream = streams[0]

    # Mock _get_file_modified_time
    monkeypatch.setattr(stream, "_get_file_modified_time", mock_modified_time)

    # 1. Test: Synchronisierung mit State von Anfang Januar
    # Sollte alle Dateien zurückgeben
    state_jan1 = {"file_modified_at": "2023-01-01T00:00:00"}
    records_jan1 = list(stream.read_records(SyncMode.incremental, stream_state=state_jan1))

    # Überprüfen, dass wir Records für alle Dateien erhalten
    assert len(records_jan1) > 0
    assert any(test_files["pdf_path"] in r["metadata"]["source_file"] for r in records_jan1)
    assert any(test_files["docx_path"] in r["metadata"]["source_file"] for r in records_jan1)
    assert any(test_files["csv_path"] in r["metadata"]["source_file"] for r in records_jan1)
    assert any(test_files["md_path"] in r["metadata"]["source_file"] for r in records_jan1)

    # 2. Test: Synchronisierung mit State von Mitte Januar
    # Sollte nur PDF und CSV zurückgeben
    state_jan15 = {"file_modified_at": "2023-01-15T00:00:00"}
    records_jan15 = list(stream.read_records(SyncMode.incremental, stream_state=state_jan15))

    # Überprüfen, dass wir nur Records für neuere Dateien erhalten
    assert len(records_jan15) > 0
    assert any(test_files["csv_path"] in r["metadata"]["source_file"] for r in records_jan15)
    # Keine Records für ältere Dateien
    assert not any(test_files["docx_path"] in r["metadata"]["source_file"] for r in records_jan15)
    assert not any(test_files["md_path"] in r["metadata"]["source_file"] for r in records_jan15)

    # 3. Test: Synchronisierung mit State nach dem neuesten Datum
    # Sollte keine Records zurückgeben
    state_future = {"file_modified_at": "2023-02-15T00:00:00"}
    records_future = list(stream.read_records(SyncMode.incremental, stream_state=state_future))

    # Überprüfen, dass wir keine Records erhalten
    assert len(records_future) == 0
