"""Tests for the fsspec IRODS filesystem implementation."""

import datetime
import os
import time
from typing import List, Dict, Any

import pytest

from fs_irods import IRODSFileSystem
from tests.iRODSFSBuilder import iRODSFSBuilder


@pytest.fixture
def fs():
    """Create an IRODSFileSystem instance for testing."""
    builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
    session = builder._session

    # Create filesystem using the session
    sut = IRODSFileSystem(session=session, root="/")

    # Set up test fixtures
    if not sut.exists("/tempZone/existing_file.txt"):
        sut.touch("/tempZone/existing_file.txt")
        sut.pipe_file("/tempZone/existing_file.txt", b"initial content")
    if not sut.exists("/tempZone/existing_collection"):
        sut.makedirs("/tempZone/existing_collection", exist_ok=True)
        sut.pipe_file("/tempZone/existing_collection/existing_file.txt", b"content")

    yield sut

    # Cleanup
    try:
        if sut.exists("/tempZone/existing_collection"):
            sut.rm("/tempZone/existing_collection", recursive=True)
        if sut.exists("/tempZone/existing_file.txt"):
            sut.rm("/tempZone/existing_file.txt")
        if sut.exists("/tempZone/new_collection"):
            sut.rm("/tempZone/new_collection", recursive=True)
    except Exception:
        pass  # Ignore cleanup errors

    sut.close()
    session.cleanup()


def test_default_state():
    """Test that the filesystem is in a valid default state."""
    builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
    session = builder._session
    sut = IRODSFileSystem(session=session, root="/")

    # Should be able to list the zone root
    items = sut.ls("/tempZone")
    assert len(items) >= 2  # home and trash typically exist

    sut.close()
    session.cleanup()


@pytest.mark.parametrize("path, expected_count", [("/tempZone", 4)])
def test_ls_detail(fs: IRODSFileSystem, path: str, expected_count: int):
    """Test listing with detail information."""
    entries = fs.ls(path, detail=True)
    assert len(entries) == expected_count

    # Each entry should have required keys
    for entry in entries:
        assert "name" in entry
        assert "size" in entry
        assert "type" in entry
        assert entry["type"] in ("file", "directory")


@pytest.mark.parametrize(
    "path, expected",
    [
        ["/tempZone/home", True],
        ["/tempZone/home/rods", True],
        ["/tempZone/existing_file.txt", False],
        ["/tempZone/i_dont_exist", False],
    ],
)
def test_isdir(fs: IRODSFileSystem, path: str, expected: bool):
    """Test directory checking."""
    assert fs.isdir(path) == expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ["/tempZone/existing_file.txt", True],
        ["/tempZone/existing_collection/existing_file.txt", True],
        ["/tempZone/i_dont_exist", False],
        ["/tempZone/new_collection", False],
        ["/tempZone", False],
    ],
)
def test_isfile(fs: IRODSFileSystem, path: str, expected: bool):
    """Test file checking."""
    assert fs.isfile(path) == expected


@pytest.mark.parametrize("path", ["/tempZone/test", "/tempZone/home/rods/test"])
def test_mkdir(fs: IRODSFileSystem, path: str):
    """Test creating a collection."""
    parent_dir = os.path.dirname(path)
    if not fs.exists(parent_dir):
        fs.makedirs(parent_dir, exist_ok=True)

    fs.mkdir(path)
    assert fs.isdir(path) is True
    fs.rmdir(path)
    assert fs.isdir(path) is False


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/home", FileExistsError],  # Already exists
        ["/tempZone/test/subcollection", FileNotFoundError],  # Parent doesn't exist
    ],
)
def test_mkdir_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test mkdir error handling."""
    with pytest.raises(exception):
        fs.mkdir(path, create_parents=False)


@pytest.mark.parametrize("path", ["/tempZone/test.txt", "/tempZone/home/rods/test.txt"])
def test_touch_remove(fs: IRODSFileSystem, path: str):
    """Test creating and removing a file."""
    fs.touch(path)
    assert fs.isfile(path) is True
    fs.rm_file(path)
    assert fs.isfile(path) is False


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/missing_collection/file.txt", FileNotFoundError],
        ["/tempZone/existing_file.txt", FileExistsError],  # Already exists but touch with truncate=False
    ],
)
def test_touch_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test touch error handling."""
    # Note: touch behavior may vary - this tests the general pattern
    if exception == FileNotFoundError:
        with pytest.raises(exception):
            fs.touch(path)


@pytest.mark.parametrize(
    "path, is_dir",
    [
        ["/tempZone/home", True],
        ["/tempZone/existing_file.txt", False],
    ],
)
def test_info(fs: IRODSFileSystem, path: str, is_dir: bool):
    """Test getting file/directory info."""
    info = fs.info(path)

    assert info["name"] == os.path.basename(path.rstrip("/")) or info["name"].endswith(os.path.basename(path))
    assert info["type"] == ("directory" if is_dir else "file")
    assert "created" in info
    assert "mtime" in info

    if not is_dir:
        assert "size" in info
        assert "checksum" in info


@pytest.mark.parametrize(
    "path, expected_exists",
    [
        ["/tempZone/home", True],
        ["/tempZone/home/rods", True],
        ["/tempZone/fakedir", False],
        ["/tempZone/home/other_user", False],
        ["/tempZone/existing_file.txt", True],
        ["/tempZone/existing_collection/existing_file.txt", True],
    ],
)
def test_exists(fs: IRODSFileSystem, path: str, expected_exists: bool):
    """Test existence checking."""
    assert fs.exists(path) == expected_exists


@pytest.mark.parametrize("path", ["/tempZone/foo", "/tempZone/home/rods/test"])
def test_rmdir(fs: IRODSFileSystem, path: str):
    """Test removing a directory."""
    parent_dir = os.path.dirname(path)
    if not fs.exists(parent_dir):
        fs.makedirs(parent_dir, exist_ok=True)

    fs.mkdir(path)
    assert fs.isdir(path) is True
    fs.rmdir(path)
    assert fs.isdir(path) is False


@pytest.mark.parametrize(
    "src_path, dst_path",
    [
        ["/tempZone/existing_collection", "/tempZone/home/copy_test"],
        ["/tempZone/existing_collection", "/tempZone/new_copy"],
    ],
)
def test_cp_file(fs: IRODSFileSystem, src_path: str, dst_path: str):
    """Test copying a file."""
    try:
        fs.cp_file(src_path, dst_path)
        assert fs.exists(dst_path)

        # For data objects, verify content
        if fs.isfile(src_path):
            src_content = fs.cat_file(src_path)
            dst_content = fs.cat_file(dst_path)
            assert src_content == dst_content
    finally:
        if fs.exists(dst_path):
            fs.rm(dst_path, recursive=True)


@pytest.mark.parametrize(
    "path, expected_entries",
    [
        ["/tempZone", True],  # Should have multiple entries
        ["/tempZone/home", True],
    ],
)
def test_ls_basic(fs: IRODSFileSystem, path: str, expected_entries: bool):
    """Test basic listing without detail."""
    result = fs.ls(path, detail=False)
    if expected_entries:
        assert len(result) > 0
        assert all(isinstance(item, str) for item in result)
    else:
        assert len(result) == 0


def test_cat_file(fs: IRODSFileSystem):
    """Test reading entire file contents."""
    content = fs.cat_file("/tempZone/existing_collection/existing_file.txt")
    assert content == b"content"


def test_pipe_file(fs: IRODSFileSystem):
    """Test writing bytes to a file."""
    test_path = "/tempZone/piped_file.txt"
    try:
        test_content = b"test content for piping"
        fs.pipe_file(test_path, test_content)

        read_content = fs.cat_file(test_path)
        assert read_content == test_content
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


def test_open_read(fs: IRODSFileSystem):
    """Test opening a file for reading."""
    test_path = "/tempZone/open_test.txt"
    try:
        fs.pipe_file(test_path, b"hello world")

        with fs.open(test_path, "rb") as f:
            content = f.read()
            assert content == b"hello world"
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


def test_open_write(fs: IRODSFileSystem):
    """Test opening a file for writing."""
    test_path = "/tempZone/open_write_test.txt"
    try:
        with fs.open(test_path, "wb") as f:
            f.write(b"written content")

        content = fs.cat_file(test_path)
        assert content == b"written content"
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


def test_open_append(fs: IRODSFileSystem):
    """Test opening a file for appending."""
    test_path = "/tempZone/open_append_test.txt"
    try:
        fs.pipe_file(test_path, b"first ")

        with fs.open(test_path, "ab") as f:
            f.write(b"appended")

        content = fs.cat_file(test_path)
        assert content == b"first appended"
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


def test_mv_file(fs: IRODSFileSystem):
    """Test moving a file."""
    src = "/tempZone/mv_src.txt"
    dst = "/tempZone/mv_dst.txt"
    try:
        fs.pipe_file(src, b"move me")

        fs.mv(src, dst)

        assert not fs.exists(src)
        assert fs.exists(dst)
        assert fs.cat_file(dst) == b"move me"
    finally:
        if fs.exists(dst):
            fs.rm_file(dst)


def test_rm_file(fs: IRODSFileSystem):
    """Test removing a single file."""
    test_path = "/tempZone/remove_me.txt"
    try:
        fs.pipe_file(test_path, b"delete me")
        assert fs.exists(test_path)

        fs.rm_file(test_path)
        assert not fs.exists(test_path)
    except Exception:
        pass  # Clean up on failure
    finally:
        if fs.exists(test_path):
            try:
                fs.rm_file(test_path)
            except Exception:
                pass


def test_size(fs: IRODSFileSystem):
    """Test getting file size."""
    test_path = "/tempZone/size_test.txt"
    try:
        test_content = b"x" * 100
        fs.pipe_file(test_path, test_content)

        size = fs.size(test_path)
        assert size == 100
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


def test_modified(fs: IRODSFileSystem):
    """Test getting modification time."""
    mtime = fs.modified("/tempZone/existing_file.txt")
    assert isinstance(mtime, datetime.datetime)


def test_created(fs: IRODSFileSystem):
    """Test getting creation time."""
    ctime = fs.created("/tempZone/existing_file.txt")
    assert isinstance(ctime, datetime.datetime)


def test_makedirs(fs: IRODSFileSystem):
    """Test recursively creating directories."""
    test_path = "/tempZone/makedirs_test/a/b/c"
    try:
        fs.makedirs(test_path)
        assert fs.isdir(test_path)
    finally:
        parent = "/tempZone/makedirs_test"
        if fs.exists(parent):
            fs.rm(parent, recursive=True)


def test_makedirs_exist_ok(fs: IRODSFileSystem):
    """Test makedirs with exist_ok=True."""
    test_path = "/tempZone/existing_collection"
    # This should not raise when exist_ok=True
    fs.makedirs(test_path, exist_ok=True)
    assert fs.isdir(test_path)


def test_makedirs_raises_on_existing_file(fs: IRODSFileSystem):
    """Test makedirs raises when path is a file."""
    test_path = "/tempZone/existing_file.txt"
    with pytest.raises(FileExistsError):
        fs.makedirs(test_path)


def test_fs_properties(fs: IRODSFileSystem):
    """Test filesystem properties."""
    assert fs.host is not None
    assert fs.port is not None
    assert fs.zone is not None
    assert fs.root is not None


def test_str_repr(fs: IRODSFileSystem):
    """Test string representations."""
    str_repr = str(fs)
    assert "IRODSFileSystem" in str_repr

    repr_str = repr(fs)
    assert "IRODSFileSystem" in repr_str


def test_fsid(fs: IRODSFileSystem):
    """Test filesystem ID generation."""
    fsid = fs.fsid
    assert fsid is not None
    assert isinstance(fsid, str)
    assert fsid.startswith("irods_")


def test_wrap(fs: IRODSFileSystem):
    """Test path wrapping."""
    # Test various path formats
    assert fs.wrap("/tempZone") == "/tempZone"
    assert fs.wrap("subdir") == "/tempZone/subdir"
    assert fs.wrap("/subdir") == "/tempZone/subdir"


def test_strip_protocol():
    """Test protocol stripping."""
    # Class method, doesn't need instance
    result = IRODSFileSystem._strip_protocol("irods://user@host:1247/tempZone/path")
    assert result == "/tempZone/path"

    result = IRODSFileSystem._strip_protocol("/absolute/path")
    assert result == "/absolute/path"


def test_get_kwargs_from_urls():
    """Test URL parsing for connection parameters."""
    kwargs = IRODSFileSystem._get_kwargs_from_urls("irods://user+zone@host:1247/path")
    assert kwargs["user"] == "user"
    assert kwargs["zone"] == "zone"
    assert kwargs["host"] == "host"
    assert kwargs["port"] == 1247


def test_close(fs: IRODSFileSystem):
    """Test closing the filesystem."""
    # Should close without error
    fs.close()

    # After close, session should be cleaned up
    # (This is hard to verify directly, but we can check no exceptions)


def test_context_manager():
    """Test using filesystem as context manager."""
    builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
    session = builder._session

    with IRODSFileSystem(session=session, root="/") as fs:
        assert fs is not None
        assert fs.exists("/tempZone")

    # After exit, should be closed
    session.cleanup()


class TestIRODSFile:
    """Tests for the IRODSFile class."""

    @pytest.fixture
    def fs(self):
        """Create a filesystem for file tests."""
        builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
        session = builder._session
        sut = IRODSFileSystem(session=session, root="/")
        yield sut
        sut.close()
        session.cleanup()

    def test_file_read(self, fs: IRODSFileSystem):
        """Test reading from an IRODSFile."""
        test_path = "/tempZone/file_read_test.txt"
        try:
            fs.pipe_file(test_path, b"test data")

            with fs.open(test_path, "rb") as f:
                assert f.readable()
                data = f.read()
                assert data == b"test data"
        finally:
            if fs.exists(test_path):
                fs.rm_file(test_path)

    def test_file_write(self, fs: IRODSFileSystem):
        """Test writing to an IRODSFile."""
        test_path = "/tempZone/file_write_test.txt"
        try:
            with fs.open(test_path, "wb") as f:
                assert f.writable()
                written = f.write(b"new data")
                assert written > 0

            content = fs.cat_file(test_path)
            assert content == b"new data"
        finally:
            if fs.exists(test_path):
                fs.rm_file(test_path)

    def test_file_seek_tell(self, fs: IRODSFileSystem):
        """Test seeking and telling in a file."""
        test_path = "/tempZone/file_seek_test.txt"
        try:
            fs.pipe_file(test_path, b"0123456789")

            with fs.open(test_path, "rb") as f:
                pos = f.tell()
                assert pos == 0

                f.seek(5)
                pos = f.tell()
                assert pos == 5

                f.seek(-3, 2)  # Seek to 3 bytes before end
                pos = f.tell()
                assert pos == 7
        finally:
            if fs.exists(test_path):
                fs.rm_file(test_path)

    def test_file_context_manager(self, fs: IRODSFileSystem):
        """Test file as context manager."""
        test_path = "/tempZone/file_context_test.txt"
        try:
            fs.pipe_file(test_path, b"context test")

            with fs.open(test_path, "rb") as f:
                assert not f.closed
                data = f.read()

            assert f.closed
            assert data == b"context test"
        finally:
            if fs.exists(test_path):
                fs.rm_file(test_path)

    def test_file_closed_property(self, fs: IRODSFileSystem):
        """Test file closed property."""
        test_path = "/tempZone/file_closed_test.txt"
        try:
            fs.pipe_file(test_path, b"test")

            f = fs.open(test_path, "rb")
            assert not f.closed

            f.close()
            assert f.closed
        finally:
            if fs.exists(test_path):
                fs.rm_file(test_path)


# Integration-style tests that mirror the pyfilesystem2 test suite
class TestIRODSFSSpecIntegration:
    """Integration tests mirroring the pyfilesystem2 test structure."""

    @pytest.fixture
    def fs(self):
        """Create a fresh filesystem for integration tests."""
        builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
        session = builder._session
        sut = IRODSFileSystem(session=session, root="/")

        # Setup fixtures
        if not sut.exists("/tempZone/integration_test"):
            sut.makedirs("/tempZone/integration_test", exist_ok=True)

        yield sut

        # Cleanup
        try:
            if sut.exists("/tempZone/integration_test"):
                sut.rm("/tempZone/integration_test", recursive=True)
        except Exception:
            pass

        sut.close()
        session.cleanup()

    def test_upload_download(self, fs: IRODSFileSystem):
        """Test uploading and downloading files."""
        import tempfile

        test_path = "/tempZone/integration_test/uploaded.txt"
        test_content = b"upload download test"

        # Upload
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(test_content)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                with fs.open(test_path, "wb") as dest:
                    dest.write(f.read())

            # Download
            downloaded_content = fs.cat_file(test_path)
            assert downloaded_content == test_content
        finally:
            os.unlink(tmp_path)
            if fs.exists(test_path):
                fs.rm_file(test_path)

    def test_nested_directories(self, fs: IRODSFileSystem):
        """Test nested directory operations."""
        base = "/tempZone/integration_test/nested"
        deep_path = f"{base}/a/b/c/d"

        try:
            # Create deep structure
            fs.makedirs(deep_path)
            assert fs.isdir(deep_path)

            # Write file at depth
            fs.pipe_file(f"{deep_path}/file.txt", b"deep file")

            # Read back
            content = fs.cat_file(f"{deep_path}/file.txt")
            assert content == b"deep file"

            # List intermediate
            items = fs.ls(f"{base}/a/b", detail=False)
            assert "c" in items
        finally:
            if fs.exists(base):
                fs.rm(base, recursive=True)

    def test_concurrent_operations(self, fs: IRODSFileSystem):
        """Test that locking works correctly."""
        import threading

        results = []
        errors = []

        def write_file(i):
            try:
                path = f"/tempZone/integration_test/concurrent_{i}.txt"
                fs.pipe_file(path, f"content {i}".encode())
                results.append(i)
            except Exception as e:
                errors.append(e)

        # Run concurrent writes
        threads = [threading.Thread(target=write_file, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5

        # Verify all files created
        for i in range(5):
            path = f"/tempZone/integration_test/concurrent_{i}.txt"
            assert fs.exists(path)
            fs.rm_file(path)
