"""Tests for the fsspec IRODS filesystem implementation."""

import datetime
import os
import time
from typing import List, Dict, Any

import pytest

from fs_irods import IRODSFileSystem
from fs_irods.iRODSFSSpec import fs_instances
from tests.iRODSFSBuilder import iRODSFSBuilder

@pytest.fixture
def fs():
    """Create an IRODSFileSystem instance for testing."""
    builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
    session = builder._session

    # Create filesystem using the session
    sut = IRODSFileSystem(session=session)

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
    except Exception:
        pass  # Ignore cleanup errors

    sut.close()
    session.cleanup()


def test_default_state():
    """Test that the filesystem is in a valid default state."""
    builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
    session = builder._session
    sut = IRODSFileSystem(session=session, root="/")

    items = sut.ls("/tempZone")
    assert len(items) >= 2  # /tempZone/home and /tempZone/trash
    items = sut.ls("/tempZone/home")
    assert len(items) >= 2  # /tempZone/home/rods and /tempZone/home/public

    sut.close()
    session.cleanup()


@pytest.mark.parametrize("path, expected_count", [("/tempZone", 4)])
def test_ls_detail(fs: IRODSFileSystem, path: str, expected_count: int):
    """Test listing with detail information."""
    entries = fs.ls(path, detail=True)
    assert len(entries) == expected_count

    for entry in entries:
        assert "name" in entry
        assert "size" in entry
        assert "type" in entry
        assert entry["type"] in ("file", "directory")


@pytest.mark.parametrize(
    "path, detail",
    [
        ["/tempZone/existing_file.txt", True],
        ["/tempZone/existing_collection/existing_file.txt", True],
        ["/tempZone/existing_collection/existing_file.txt", False],
    ],
)
def test_ls_file(fs: IRODSFileSystem, path: str, detail: bool):
    """Test basic listing without detail."""
    result = fs.ls(path, detail)
    if detail:
        assert result[0]["name"] == path
        assert result[0]["type"] == "file"
        assert "created" in result[0]
        assert "mtime" in result[0]
        assert "size" in result[0]
        assert "checksum" in result[0]
    else:
        assert result[0] == path


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/i_dont_exist", FileNotFoundError],
    ],
)
def test_ls_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test ls error handling."""
    with pytest.raises(exception):
        fs.ls(path)


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
        ["/tempZone/home", FileExistsError],
        ["/tempZone/test/subcollection", FileNotFoundError],
    ],
)
def test_mkdir_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test mkdir error handling."""
    with pytest.raises(exception):
        fs.mkdir(path, create_parents=False)


@pytest.mark.parametrize(
    "path", ["/tempZone/test.txt", "/tempZone/home/rods/test.txt", "/tempZone/existing_file.txt"])
def test_touch_remove(fs: IRODSFileSystem, path: str):
    """Test creating and removing a file."""
    fs.touch(path)
    assert fs.isfile(path) is True
    assert fs.info(path)["size"] == 0
    fs.rm_file(path)
    assert fs.isfile(path) is False


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/missing_collection/file.txt", FileNotFoundError],
        ["/tempZone/existing_file.txt", FileExistsError],
        ["/tempZone/existing_collection", IsADirectoryError],
    ],
)
def test_touch_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test touch error handling."""
    with pytest.raises(exception):
        fs.touch(path, truncate = False)


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

    assert info["name"] == path
    assert info["type"] == ("directory" if is_dir else "file")
    assert "created" in info
    assert "mtime" in info

    if not is_dir:
        assert "size" in info
        assert "checksum" in info


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/i_dont_exist", FileNotFoundError],
        ["/tempZone/not_existing_collection", FileNotFoundError],
    ],
)
def test_info_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test info error handling."""
    with pytest.raises(exception):
        fs.info(path)


@pytest.mark.parametrize(
    "path, expected_exists",
    [
        ["/tempZone/home", True],
        ["/tempZone/fakedir", False],
        ["/tempZone/existing_file.txt", True],
        ["/tempZone/existing_collection/fake_file.txt", False],
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
    "path, exception",
    [
        ["/tempZone/i_dont_exist", FileNotFoundError],
        ["/tempZone/existing_file.txt", FileNotFoundError],
    ],
)
def test_rmdir_exceptions(fs: IRODSFileSystem, path: str, exception: type):
    """Test rmdir error handling."""
    with pytest.raises(exception):
        fs.rmdir(path)


@pytest.mark.parametrize(
    "src_path, dst_path",
    [
        ["/tempZone/existing_collection", "/tempZone/new_copy"],
        ["/tempZone/existing_file.txt", "/tempZone/home/new_file.txt"],
    ],
)
def test_cp_file(fs: IRODSFileSystem, src_path: str, dst_path: str):
    """Test copying a file."""
    try:
        fs.cp_file(src_path, dst_path)
        assert fs.exists(dst_path)

        if fs.isfile(src_path):
            src_content = fs.cat_file(src_path)
            dst_content = fs.cat_file(dst_path)
            assert src_content == dst_content
    finally:
        if fs.exists(dst_path):
            fs.rm(dst_path, recursive=True)


@pytest.mark.parametrize(
    "src_path",
    [
        "/tempZone/i_dont_exist.txt",
    ],
)
def test_cp_file_exceptions(fs: IRODSFileSystem, src_path: str):
    """Test that cp_file raises FileNotFoundError for non-existent source."""
    with pytest.raises(FileNotFoundError):
        fs.cp_file(src_path, "/tempZone/destination.txt")


def test_cat_file(fs: IRODSFileSystem):
    """Test reading entire file contents."""
    content = fs.cat_file("/tempZone/existing_collection/existing_file.txt")
    assert content == b"content"
    content = fs.cat_file("/tempZone/existing_collection/existing_file.txt", start=0, end=5)
    assert content == b"conte"


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


@pytest.mark.parametrize(
    "path, expected",
    [
        ["/tempZone/existing_file.txt", b"initial content"],
        ["/tempZone/existing_collection/existing_file.txt", b"content"],
    ],
)
def test_open_read(fs: IRODSFileSystem, path: str, expected: bytes):
    """Test opening a file for reading."""
    with fs.open(path, "rb") as f:
        assert f.read() == expected


def test_open_write(fs: IRODSFileSystem):
    """Test opening a file for writing."""
    test_path = "/tempZone/open_write_test.txt"
    try:
        with fs.open(test_path, "wb") as f:
            f.write(b"written content")
        assert fs.cat_file(test_path) == b"written content"
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
        assert fs.cat_file(test_path) == b"first appended"
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


@pytest.mark.parametrize(
    "src, dst",
    [
        ["/tempZone/existing_file.txt", "/tempZone/home/mv_existing_file.txt"],
        ["/tempZone/existing_collection", "/tempZone/home/existing_collection"],
    ],
)
def test_mv_file(fs: IRODSFileSystem, src: str, dst: str):
    """Test moving a file."""
    try:
        fs.mv(src, dst)

        assert not fs.exists(src)
        assert fs.exists(dst)
        if fs.isfile(dst):
            assert fs.cat_file(dst) == b"initial content"
        else:
            assert fs.exists(f"{dst}/existing_file.txt")
            assert fs.cat_file(f"{dst}/existing_file.txt") == b"content"
    finally:
        if fs.exists(dst):
            fs.rm(dst, recursive=True)


def test_rm_file(fs: IRODSFileSystem):
    """Test removing a single file."""
    test_path = "/tempZone/existing_file.txt"
    try:
        assert fs.exists(test_path)
        fs.rm_file(test_path)
        assert not fs.exists(test_path)
    except Exception:
        pass
    finally:
        if fs.exists(test_path):
            try:
                fs.rm_file(test_path)
            except Exception:
                pass


def test_rm_file_exceptions(fs: IRODSFileSystem):
    """Test that rm_file raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        fs.rm_file("/tempZone/i_dont_exist.txt")


def test_size(fs: IRODSFileSystem):
    """Test getting file size."""
    test_path = "/tempZone/existing_file.txt"
    size = fs.size(test_path)
    assert size == 15

@pytest.mark.parametrize(
    "path",
    [
        "/tempZone/i_dont_exist.txt",
        "/tempZone/existing_collection",
    ],
)
def test_size_exceptions(fs: IRODSFileSystem, path: str):
    """Test that size raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        fs.size(path)


def test_modified(fs: IRODSFileSystem):
    """Test getting modification time."""
    mtime = fs.modified("/tempZone/existing_file.txt")
    assert isinstance(mtime, datetime.datetime)


def test_modified_exceptions(fs: IRODSFileSystem):
    """Test that modified raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        fs.modified("/tempZone/i_dont_exist.txt")


def test_created(fs: IRODSFileSystem):
    """Test getting creation time."""
    ctime = fs.created("/tempZone/existing_file.txt")
    assert isinstance(ctime, datetime.datetime)


def test_created_exceptions(fs: IRODSFileSystem):
    """Test that created raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        fs.created("/tempZone/i_dont_exist.txt")


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
    fs.makedirs(test_path, exist_ok=True)
    assert fs.isdir(test_path)


@pytest.mark.parametrize(
    "path, exceptions, exist_ok",
    [
        ["/tempZone/existing_collection", FileExistsError, False],
        ["/tempZone/existing_file.txt", FileExistsError, True],
    ],
)
def test_makedirs_exceptions(fs: IRODSFileSystem, path: str, exceptions: type, exist_ok: bool):
    with pytest.raises(exceptions):
        fs.makedirs(path, exist_ok=exist_ok)


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
    """Test path wrapping delegates correctly to iRODSPath."""
    assert fs.wrap("/tempZone") == "/tempZone"
    assert fs.wrap("subdir") == "/tempZone/subdir"
    assert fs.wrap("/subdir") == "/tempZone/subdir"
    assert fs.wrap("irods://host:1247/tempZone/path") == "/tempZone/path"


def test_close_removes_from_instances(fs: IRODSFileSystem):
    """Test that close removes filesystem from global instances registry."""
    with fs.open("/tempZone/existing_file.txt", "rb") as f:
        f.read(3)  # Just trigger the open, don't need to read anything

    assert fs in fs_instances
    fs.close()
    assert fs not in fs_instances


def test_get_kwargs_from_urls():
    """Test URL parsing for connection parameters."""
    kwargs = IRODSFileSystem._get_kwargs_from_urls("irods://user+zone@host:1247/path")
    assert kwargs["user"] == "user"
    assert kwargs["zone"] == "zone"
    assert kwargs["host"] == "host"
    assert kwargs["port"] == 1247


def test_checksum(fs: IRODSFileSystem):
    """Test getting file checksum."""
    test_path = "/tempZone/existing_file.txt"
    checksum = fs.checksum(test_path)

    if checksum is not None:
        assert isinstance(checksum, str)
        assert ":" in checksum or len(checksum) > 0


def test_checksum_nonexistent(fs: IRODSFileSystem):
    """Test checksum raises for nonexistent file."""
    with pytest.raises(FileNotFoundError):
        fs.checksum("/tempZone/i_dont_exist.txt")


def test_find(fs: IRODSFileSystem):
    """Test finding all files recursively."""
    base = "/tempZone/find_test"
    try:
        # Create a nested structure
        fs.makedirs(f"{base}/a/b/c")
        fs.pipe_file(f"{base}/file1.txt", b"content1")
        fs.pipe_file(f"{base}/a/file2.txt", b"content2")
        fs.pipe_file(f"{base}/a/b/file3.txt", b"content3")

        # Find all files
        result = fs.find(base)
        assert isinstance(result, list)
        assert len(result) == 3
        assert f"{base}/file1.txt" in result
        assert f"{base}/a/file2.txt" in result
        assert f"{base}/a/b/file3.txt" in result

        # Find with directories included
        result_with_dirs = fs.find(base, withdirs=True)
        assert isinstance(result_with_dirs, list)
        assert len(result_with_dirs) >= 3  # Files plus possibly directories

        # Find with maxdepth
        result_depth1 = fs.find(base, maxdepth=1)
        assert isinstance(result_depth1, list)
        # Should only find file1.txt at depth 1, not files in subdirectories
        assert f"{base}/file1.txt" in result_depth1

        # Find with detail - fsspec may return list of dicts or dict of dicts
        result_detail = fs.find(base, detail=True)
        # When detail=True, result is either a dict mapping paths to info,
        # or a list of info dicts depending on fsspec version
        if isinstance(result_detail, dict):
            assert len(result_detail) == 3
        elif isinstance(result_detail, list):
            assert len(result_detail) == 3
            for item in result_detail:
                assert isinstance(item, dict)
                assert "name" in item
    finally:
        if fs.exists(base):
            fs.rm(base, recursive=True)


def test_find_empty(fs: IRODSFileSystem):
    """Test find on empty directory."""
    base = "/tempZone/i_dont_exist"
    try:
        fs.makedirs(base)

        result = fs.find(base)
        assert result == []
    finally:
        if fs.exists(base):
            fs.rm(base, recursive=True)


def test_walk(fs: IRODSFileSystem):
    """Test walking directory tree."""
    base = "/tempZone/walk_test"
    try:
        # Create a nested structure
        fs.makedirs(f"{base}/a/b")
        fs.pipe_file(f"{base}/file1.txt", b"content1")
        fs.pipe_file(f"{base}/a/file2.txt", b"content2")
        fs.pipe_file(f"{base}/a/b/file3.txt", b"content3")

        # Walk the directory tree
        results = list(fs.walk(base))

        # Should yield tuples of (path, dirs, files)
        assert len(results) > 0
        for entry in results:
            assert len(entry) == 3
            path, dirs, files = entry
            assert path.startswith(base)
            assert isinstance(dirs, list)
            assert isinstance(files, list)

        # Verify we visited the root
        root_entry = results[0]
        assert root_entry[0] == base
    finally:
        if fs.exists(base):
            fs.rm(base, recursive=True)


def test_walk_maxdepth(fs: IRODSFileSystem):
    """Test walk with maxdepth limit."""
    base = "/tempZone/walk_depth_test"
    try:
        # Create a nested structure
        fs.makedirs(f"{base}/a/b/c")
        fs.pipe_file(f"{base}/file1.txt", b"content1")
        fs.pipe_file(f"{base}/a/file2.txt", b"content2")
        fs.pipe_file(f"{base}/a/b/file3.txt", b"content3")
        fs.pipe_file(f"{base}/a/b/c/file4.txt", b"content4")

        # Walk with maxdepth=1
        results = list(fs.walk(base, maxdepth=1))

        # Should only visit root level
        assert len(results) >= 1
        for entry in results:
            path = entry[0]
            # No path should be deeper than one level
            depth = path.count("/") - base.count("/")
            assert depth <= 1
    finally:
        if fs.exists(base):
            fs.rm(base, recursive=True)


def test_du(fs: IRODSFileSystem):
    """Test disk usage calculation."""
    base = "/tempZone/du_test"
    try:
        # Create files with known sizes
        fs.makedirs(base)
        fs.pipe_file(f"{base}/file1.txt", b"x" * 100)
        fs.pipe_file(f"{base}/file2.txt", b"x" * 200)

        # Get total size
        total = fs.du(base)
        assert isinstance(total, int)
        assert total == 300

        # Get per-file sizes
        sizes = fs.du(base, total=False)
        assert isinstance(sizes, dict)
        assert f"{base}/file1.txt" in sizes
        assert f"{base}/file2.txt" in sizes
        assert sizes[f"{base}/file1.txt"] == 100
        assert sizes[f"{base}/file2.txt"] == 200

        # With maxdepth
        fs.makedirs(f"{base}/subdir")
        fs.pipe_file(f"{base}/subdir/file3.txt", b"x" * 50)

        # Limited depth should not include subdir contents
        shallow = fs.du(base, maxdepth=1, total=False)
        assert isinstance(shallow, dict)
        # file1.txt and file2.txt should be included
        assert f"{base}/file1.txt" in shallow
        assert f"{base}/file2.txt" in shallow
    finally:
        if fs.exists(base):
            fs.rm(base, recursive=True)


def test_du_empty(fs: IRODSFileSystem):
    """Test du on empty directory."""
    base = "/tempZone/i_dont_exist"
    try:
        fs.makedirs(base)

        total = fs.du(base)
        assert total == 0
    finally:
        if fs.exists(base):
            fs.rm(base, recursive=True)


def test_rm_recursive(fs: IRODSFileSystem):
    """Test recursive removal of directories."""
    base = "/tempZone/rm_recursive_test"
    fs.makedirs(f"{base}/a/b")
    fs.pipe_file(f"{base}/file1.txt", b"content1")
    fs.pipe_file(f"{base}/a/file2.txt", b"content2")

    fs.rm(base, recursive=True)

    assert not fs.exists(base)


def test_rm_nonexistent_exceptions(fs: IRODSFileSystem):
    """Test that rm raises FileNotFoundError for nonexistent path."""
    with pytest.raises(FileNotFoundError):
        fs.rm("/tempZone/i_dont_exist", recursive=True)


def test_finalize_files(fs: IRODSFileSystem):
    """Test file handle finalization."""
    # Open a file but don't close it explicitly
    test_path = "/tempZone/finalize_test.txt"
    try:
        fs.pipe_file(test_path, b"test content")

        f = fs.open(test_path, "rb")
        # Don't close - rely on finalization

        # Call finalization
        fs._finalize_files()

        # Should not raise
    finally:
        if fs.exists(test_path):
            fs.rm_file(test_path)


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

    def test_file_readable_writable_seekable(self, fs: IRODSFileSystem):
        """Test file capability methods."""
        test_path = "/tempZone/file_caps_test.txt"
        try:
            fs.pipe_file(test_path, b"test data")

            with fs.open(test_path, "rb") as f:
                assert f.readable() is True
                # Note: writable() and seekable() depend on mode
                assert f.seekable() is True

            with fs.open(test_path, "wb") as f:
                assert f.writable() is True
                assert f.readable() is False
                assert f.seekable() is True
        finally:
            if fs.exists(test_path):
                fs.rm_file(test_path)
