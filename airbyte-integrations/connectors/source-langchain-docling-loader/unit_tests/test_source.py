#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import os
import pytest
from unittest.mock import MagicMock, patch, mock_open, call

from source_langchain_docling_loader.source import SourceLangchainDoclingLoader, DoclingStream, EXPORT_TYPES


def test_check_connection_valid_paths():
    source = SourceLangchainDoclingLoader()
    logger_mock = MagicMock()
    
    with patch("os.path.exists", return_value=True), \
         patch("os.path.isdir", return_value=True), \
         patch("os.scandir", return_value=iter([MagicMock()])):
        
        config = {"paths": ["/path/to/valid/directory", "/path/to/valid/file.pdf"]}
        result, message = source.check_connection(logger_mock, config)
        
        assert result is True
        assert message is None


def test_check_connection_invalid_export_type():
    source = SourceLangchainDoclingLoader()
    logger_mock = MagicMock()
    
    config = {
        "paths": ["/path/to/valid/directory"],
        "export_type": "INVALID_TYPE"
    }
    
    result, message = source.check_connection(logger_mock, config)
    
    assert result is False
    assert "Unsupported export_type" in message
    assert all(export_type in message for export_type in EXPORT_TYPES)


def test_check_connection_empty_paths():
    source = SourceLangchainDoclingLoader()
    logger_mock = MagicMock()
    
    config = {"paths": []}
    result, message = source.check_connection(logger_mock, config)
    
    assert result is False
    assert "non-empty list" in message


def test_check_connection_no_valid_paths():
    source = SourceLangchainDoclingLoader()
    logger_mock = MagicMock()
    
    with patch("os.path.exists", return_value=False):
        config = {"paths": ["/path/to/nonexistent/directory", "/path/to/nonexistent/file.pdf"]}
        result, message = source.check_connection(logger_mock, config)
        
        assert result is False
        assert "No valid paths found" in message


def test_check_connection_mixed_paths():
    source = SourceLangchainDoclingLoader()
    logger_mock = MagicMock()
    
    # First path exists, second doesn't
    # Setup a mock that returns True for the first path and False for the second
    path_exists_mock = MagicMock()
    path_exists_mock.side_effect = [True, False]
    
    with patch("os.path.exists", path_exists_mock), \
         patch("os.path.isdir", return_value=True), \
         patch("os.scandir", return_value=iter([MagicMock()])):
        
        config = {"paths": ["/path/to/valid/directory", "/path/to/nonexistent/file.pdf"]}
        result, message = source.check_connection(logger_mock, config)
        
        assert result is True
        assert message is None


def test_docling_stream_with_export_type():
    # Test with DOC_CHUNKS
    stream1 = DoclingStream(paths=[], export_type="DOC_CHUNKS")
    from langchain_docling import ExportType
    assert stream1.export_type == ExportType.DOC_CHUNKS
    
    # Test with MARKDOWN
    stream2 = DoclingStream(paths=[], export_type="MARKDOWN")
    assert stream2.export_type == ExportType.MARKDOWN
    
    # Test with default
    stream3 = DoclingStream(paths=[])
    assert stream3.export_type == ExportType.DOC_CHUNKS


def test_streams():
    source = SourceLangchainDoclingLoader()
    config = {
        "paths": ["/path/to/documents", "/path/to/file.pdf"],
        "export_type": "MARKDOWN"
    }
    
    streams = source.streams(config)
    
    assert len(streams) == 1
    assert isinstance(streams[0], DoclingStream)
    assert streams[0].paths == config["paths"]
    from langchain_docling import ExportType
    assert streams[0].export_type == ExportType.MARKDOWN


def test_is_supported_file():
    stream = DoclingStream(paths=[])
    
    # Test with supported file formats
    assert stream._is_supported_file("test.pdf") is True
    assert stream._is_supported_file("test.PDF") is True
    assert stream._is_supported_file("test.docx") is True
    assert stream._is_supported_file("test.pptx") is True
    assert stream._is_supported_file("test.html") is True
    assert stream._is_supported_file("test.htm") is True
    assert stream._is_supported_file("test.txt") is True
    assert stream._is_supported_file("test.md") is True
    assert stream._is_supported_file("test.rtf") is True
    
    # Test with unsupported file formats
    assert stream._is_supported_file("test.csv") is False
    assert stream._is_supported_file("test.json") is False
    assert stream._is_supported_file("test.xyz") is False
    assert stream._is_supported_file("test") is False


@patch('os.walk')
def test_scan_directory(mock_walk):
    # Setup mock for os.walk to return some files
    mock_walk.return_value = [
        ('/path/to/docs', [], ['file1.pdf', 'file2.docx', 'file3.txt', 'unsupported.xyz']),
        ('/path/to/docs/subdir', [], ['file4.pptx', 'unsupported.abc'])
    ]
    
    # Create the stream
    stream = DoclingStream(paths=[])
    
    # Call _scan_directory
    files = stream._scan_directory('/path/to/docs')
    
    # Assertions
    assert len(files) == 4  # Should find 4 supported files
    assert '/path/to/docs/file1.pdf' in files
    assert '/path/to/docs/file2.docx' in files
    assert '/path/to/docs/file3.txt' in files
    assert '/path/to/docs/subdir/file4.pptx' in files


@patch('os.path.exists')
@patch('os.path.isfile')
@patch('os.path.isdir')
def test_get_all_files_to_process(mock_isdir, mock_isfile, mock_exists):
    # Setup stream with mock methods
    stream = DoclingStream(paths=['/path/to/file.pdf', '/path/to/dir'])
    stream._is_supported_file = MagicMock(return_value=True)
    stream._scan_directory = MagicMock(return_value=['/path/to/dir/file1.pdf', '/path/to/dir/file2.docx'])
    
    # Mock behavior
    mock_exists.return_value = True
    mock_isfile.side_effect = [True, False]  # First path is file, second is not
    mock_isdir.side_effect = [False, True]   # First path is not dir, second is
    
    # Call method
    files = stream._get_all_files_to_process()
    
    # Assertions
    assert len(files) == 3
    assert files[0]["file_path"] == '/path/to/file.pdf'
    assert files[0]["base_dir"] == '/path/to'
    assert files[1]["file_path"] == '/path/to/dir/file1.pdf'
    assert files[1]["base_dir"] == '/path/to/dir'
    assert files[2]["file_path"] == '/path/to/dir/file2.docx'
    assert files[2]["base_dir"] == '/path/to/dir'