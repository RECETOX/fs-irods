"""Tests for the fsspec IRODS filesystem implementation."""

import datetime
import os
import pytest

from fs_irods import IRODSFileSystem
from fs_irods.iRODSFSSpec import fs_instances
from tests.iRODSFSBuilder import iRODSFSBuilder


@pytest.fixture
def _fs():
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


# =============================================================================
# Basic State Tests
# =============================================================================

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


# =============================================================================
# ls() Tests
# =============================================================================

@pytest.mark.parametrize("path, expected_count", [("/tempZone", 4)])
def test_ls_detail(_fs: IRODSFileSystem, path: str, expected_count: int):
    """Test listing with detail information."""
    entries = _fs.ls(path, detail=True)
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
def test_ls_file(_fs: IRODSFileSystem, path: str, detail: bool):
    """Test basic listing without detail."""
    result = _fs.ls(path, detail)
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
def test_ls_exceptions(_fs: IRODSFileSystem, path: str, exception: type):
    """Test ls error handling."""
    with pytest.raises(exception):
        _fs.ls(path)


# =============================================================================
# isdir() and isfile() Tests
# =============================================================================

@pytest.mark.parametrize(
    "path, expected",
    [
        ["/tempZone/home", True],
        ["/tempZone/home/rods", True],
        ["/tempZone/existing_file.txt", False],
        ["/tempZone/i_dont_exist", False],
    ],
)
def test_isdir(_fs: IRODSFileSystem, path: str, expected: bool):
    """Test directory checking."""
    assert _fs.isdir(path) == expected


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
def test_isfile(_fs: IRODSFileSystem, path: str, expected: bool):
    """Test file checking."""
    assert _fs.isfile(path) == expected


# =============================================================================
# exists() Tests
# =============================================================================

@pytest.mark.parametrize(
    "path, expected_exists",
    [
        ["/tempZone/home", True],
        ["/tempZone/i_dont_exist", False],
        ["/tempZone/existing_file.txt", True],
        ["/tempZone/existing_collection/i_dont_exist.txt", False],
    ],
)
def test_exists(_fs: IRODSFileSystem, path: str, expected_exists: bool):
    """Test existence checking."""
    assert _fs.exists(path) == expected_exists


# =============================================================================
# mkdir() Tests
# =============================================================================

@pytest.mark.parametrize("path", ["/tempZone/test", "/tempZone/home/rods/test"])
def test_mkdir(_fs: IRODSFileSystem, path: str):
    """Test creating a collection."""
    parent_dir = os.path.dirname(path)
    if not _fs.exists(parent_dir):
        _fs.makedirs(parent_dir, exist_ok=True)

    _fs.mkdir(path)
    assert _fs.isdir(path) is True
    _fs.rmdir(path)
    assert _fs.isdir(path) is False


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/home", FileExistsError],
        ["/tempZone/test/subcollection", FileNotFoundError],
    ],
)
def test_mkdir_exceptions(_fs: IRODSFileSystem, path: str, exception: type):
    """Test mkdir error handling."""
    with pytest.raises(exception):
        _fs.mkdir(path, create_parents=False)


# =============================================================================
# makedirs() Tests
# =============================================================================

def test_makedirs(_fs: IRODSFileSystem):
    """Test recursively creating directories."""
    test_path = "/tempZone/makedirs_test/a/b/c"
    try:
        _fs.makedirs(test_path)
        assert _fs.isdir(test_path)
    finally:
        parent = "/tempZone/makedirs_test"
        if _fs.exists(parent):
            _fs.rm(parent, recursive=True)


def test_makedirs_exist_ok(_fs: IRODSFileSystem):
    """Test makedirs with exist_ok=True."""
    test_path = "/tempZone/existing_collection"
    _fs.makedirs(test_path, exist_ok=True)
    assert _fs.isdir(test_path)


@pytest.mark.parametrize(
    "path, exception, exist_ok",
    [
        ["/tempZone/existing_collection", FileExistsError, False],
        ["/tempZone/existing_file.txt", FileExistsError, True],
    ],
)
def test_makedirs_exceptions(_fs: IRODSFileSystem, path: str, exception: type, exist_ok: bool):
    """Test makedirs error handling."""
    with pytest.raises(exception):
        _fs.makedirs(path, exist_ok=exist_ok)


# =============================================================================
# touch() Tests
# =============================================================================

@pytest.mark.parametrize(
    "path", 
    ["/tempZone/test.txt", "/tempZone/home/rods/test.txt", "/tempZone/existing_file.txt"]
)
def test_touch_remove(_fs: IRODSFileSystem, path: str):
    """Test creating and removing a file."""
    _fs.touch(path)
    assert _fs.isfile(path) is True
    assert _fs.info(path)["size"] == 0
    _fs.rm_file(path)
    assert _fs.isfile(path) is False


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/i_dont_exist/file.txt", FileNotFoundError],
        ["/tempZone/existing_file.txt", FileExistsError],
        ["/tempZone/existing_collection", IsADirectoryError],
    ],
)
def test_touch_exceptions(_fs: IRODSFileSystem, path: str, exception: type):
    """Test touch error handling."""
    with pytest.raises(exception):
        _fs.touch(path, truncate=False)


# =============================================================================
# info() Tests
# =============================================================================

@pytest.mark.parametrize(
    "path, is_dir",
    [
        ["/tempZone/home", True],
        ["/tempZone/existing_file.txt", False],
    ],
)
def test_info(_fs: IRODSFileSystem, path: str, is_dir: bool):
    """Test getting file/directory info."""
    info = _fs.info(path)

    assert info["name"] == path
    assert info["type"] == ("directory" if is_dir else "file")
    assert "created" in info
    assert "mtime" in info

    if not is_dir:
        assert "size" in info
        assert "checksum" in info


@pytest.mark.parametrize(
    "path, exception",
    [["/tempZone/i_dont_exist", FileNotFoundError]]
)
def test_info_exceptions(_fs: IRODSFileSystem, path: str, exception: type):
    """Test info error handling."""
    with pytest.raises(exception):
        _fs.info(path)


# =============================================================================
# rmdir() Tests
# =============================================================================

@pytest.mark.parametrize("path", ["/tempZone/foo", "/tempZone/home/rods/test"])
def test_rmdir(_fs: IRODSFileSystem, path: str):
    """Test removing a directory."""
    parent_dir = os.path.dirname(path)
    if not _fs.exists(parent_dir):
        _fs.makedirs(parent_dir, exist_ok=True)

    _fs.mkdir(path)
    assert _fs.isdir(path) is True
    _fs.rmdir(path)
    assert _fs.isdir(path) is False


@pytest.mark.parametrize(
    "path, exception",
    [
        ["/tempZone/i_dont_exist", FileNotFoundError],
        ["/tempZone/existing_file.txt", FileNotFoundError],
    ],
)
def test_rmdir_exceptions(_fs: IRODSFileSystem, path: str, exception: type):
    """Test rmdir error handling."""
    with pytest.raises(exception):
        _fs.rmdir(path)


# =============================================================================
# rm() Tests
# =============================================================================

def test_rm_recursive(_fs: IRODSFileSystem):
    """Test recursive removal of directories."""
    base = "/tempZone/rm_recursive_test"
    _fs.makedirs(f"{base}/a/b")
    _fs.pipe_file(f"{base}/file1.txt", b"content1")
    _fs.pipe_file(f"{base}/a/file2.txt", b"content2")

    _fs.rm(base, recursive=True)

    assert not _fs.exists(base)


def test_rm_exceptions(_fs: IRODSFileSystem):
    """Test that rm raises FileNotFoundError for nonexistent path."""
    with pytest.raises(FileNotFoundError):
        _fs.rm("/tempZone/i_dont_exist", recursive=True)


# =============================================================================
# rm_file() Tests
# =============================================================================

def test_rm_file(_fs: IRODSFileSystem):
    """Test removing a single file."""
    test_path = "/tempZone/existing_file.txt"
    assert _fs.exists(test_path)
    _fs.rm_file(test_path)
    assert not _fs.exists(test_path)


def test_rm_file_exceptions(_fs: IRODSFileSystem):
    """Test that rm_file raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        _fs.rm_file("/tempZone/i_dont_exist.txt")


# =============================================================================
# cp_file() Tests
# =============================================================================

@pytest.mark.parametrize(
    "src_path, dst_path",
    [
        ["/tempZone/existing_collection", "/tempZone/new_copy"],
        ["/tempZone/existing_file.txt", "/tempZone/home/new_file.txt"],
    ],
)
def test_cp_file(_fs: IRODSFileSystem, src_path: str, dst_path: str):
    """Test copying a file."""
    try:
        _fs.cp_file(src_path, dst_path)
        assert _fs.exists(dst_path)

        if _fs.isfile(src_path):
            src_content = _fs.cat_file(src_path)
            dst_content = _fs.cat_file(dst_path)
            assert src_content == dst_content
    finally:
        if _fs.exists(dst_path):
            _fs.rm(dst_path, recursive=True)


@pytest.mark.parametrize(
    "src_path",
    [
        "/tempZone/i_dont_exist.txt",
    ],
)
def test_cp_file_exceptions(_fs: IRODSFileSystem, src_path: str):
    """Test that cp_file raises FileNotFoundError for non-existent source."""
    with pytest.raises(FileNotFoundError):
        _fs.cp_file(src_path, "/tempZone/destination.txt")


# =============================================================================
# mv() Tests
# =============================================================================

@pytest.mark.parametrize(
    "src, dst",
    [
        ["/tempZone/existing_file.txt", "/tempZone/home/mv_existing_file.txt"],
        ["/tempZone/existing_collection", "/tempZone/home/existing_collection"],
    ],
)
def test_mv_file(_fs: IRODSFileSystem, src: str, dst: str):
    """Test moving a file."""
    try:
        _fs.mv(src, dst)

        assert not _fs.exists(src)
        assert _fs.exists(dst)
        if _fs.isfile(dst):
            assert _fs.cat_file(dst) == b"initial content"
        else:
            assert _fs.exists(f"{dst}/existing_file.txt")
            assert _fs.cat_file(f"{dst}/existing_file.txt") == b"content"
    finally:
        if _fs.exists(dst):
            _fs.rm(dst, recursive=True)


@pytest.mark.parametrize(
    "src, dst",
    [
        ["/tempZone/i_dont_exist.txt", "/tempZone/destination.txt"],
        ["/tempZone/i_dont_exist", "/tempZone/home/destination"],
    ],
)
def test_mv_file_exceptions(_fs: IRODSFileSystem, src: str, dst: str):
    """Test that mv raises FileNotFoundError for non-existent source."""
    with pytest.raises(FileNotFoundError):
        _fs.mv(src, dst)


# =============================================================================
# cat_file() and pipe_file() Tests
# =============================================================================

def test_cat_file(_fs: IRODSFileSystem):
    """Test reading entire file contents."""
    content = _fs.cat_file("/tempZone/existing_collection/existing_file.txt")
    assert content == b"content"
    content = _fs.cat_file("/tempZone/existing_collection/existing_file.txt", start=0, end=5)
    assert content == b"conte"


def test_pipe_file(_fs: IRODSFileSystem):
    """Test writing bytes to a file."""
    test_path = "/tempZone/piped_file.txt"
    try:
        test_content = b"test content for piping"
        _fs.pipe_file(test_path, test_content)

        read_content = _fs.cat_file(test_path)
        assert read_content == test_content
    finally:
        if _fs.exists(test_path):
            _fs.rm_file(test_path)


# =============================================================================
# open() Tests
# =============================================================================

@pytest.mark.parametrize(
    "path, expected",
    [
        ["/tempZone/existing_file.txt", b"initial content"],
        ["/tempZone/existing_collection/existing_file.txt", b"content"],
    ],
)
def test_open_read(_fs: IRODSFileSystem, path: str, expected: bytes):
    """Test opening a file for reading."""
    with _fs.open(path, "rb") as f:
        assert f.read() == expected


def test_open_write(_fs: IRODSFileSystem):
    """Test opening a file for writing."""
    test_path = "/tempZone/open_write_test.txt"
    try:
        with _fs.open(test_path, "wb") as f:
            f.write(b"written content")
        assert _fs.cat_file(test_path) == b"written content"
    finally:
        if _fs.exists(test_path):
            _fs.rm_file(test_path)


def test_open_append(_fs: IRODSFileSystem):
    """Test opening a file for appending."""
    test_path = "/tempZone/open_append_test.txt"
    try:
        _fs.pipe_file(test_path, b"first ")
        with _fs.open(test_path, "ab") as f:
            f.write(b"appended")
        assert _fs.cat_file(test_path) == b"first appended"
    finally:
        if _fs.exists(test_path):
            _fs.rm_file(test_path)


def test_open_autocommit_not_implemented(_fs: IRODSFileSystem):
    """Test that open raises NotImplementedError when autocommit=False."""
    with pytest.raises(NotImplementedError):
        _fs.open("/tempZone/existing_file.txt", autocommit=False)


# =============================================================================
# size() Tests
# =============================================================================

def test_size(_fs: IRODSFileSystem):
    """Test getting file size."""
    test_path = "/tempZone/existing_file.txt"
    size = _fs.size(test_path)
    assert size == 15


@pytest.mark.parametrize(
    "path",
    [
        "/tempZone/i_dont_exist.txt",
        "/tempZone/existing_collection",
    ],
)
def test_size_exceptions(_fs: IRODSFileSystem, path: str):
    """Test that size raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        _fs.size(path)


# =============================================================================
# modified() Tests
# =============================================================================

def test_modified(_fs: IRODSFileSystem):
    """Test getting modification time."""
    mtime = _fs.modified("/tempZone/existing_file.txt")
    assert isinstance(mtime, datetime.datetime)


def test_modified_exceptions(_fs: IRODSFileSystem):
    """Test that modified raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        _fs.modified("/tempZone/i_dont_exist.txt")


# =============================================================================
# created() Tests
# =============================================================================

def test_created(_fs: IRODSFileSystem):
    """Test getting creation time."""
    ctime = _fs.created("/tempZone/existing_file.txt")
    assert isinstance(ctime, datetime.datetime)


def test_created_exceptions(_fs: IRODSFileSystem):
    """Test that created raises FileNotFoundError for non-existent files."""
    with pytest.raises(FileNotFoundError):
        _fs.created("/tempZone/i_dont_exist.txt")


# =============================================================================
# checksum() Tests
# =============================================================================

def test_checksum(_fs: IRODSFileSystem):
    """Test getting file checksum."""
    test_path = "/tempZone/existing_file.txt"
    checksum = _fs.checksum(test_path)

    if checksum is not None:
        assert isinstance(checksum, str)
        assert ":" in checksum or len(checksum) > 0


def test_checksum_exceptions(_fs: IRODSFileSystem):
    """Test checksum raises for nonexistent file."""
    with pytest.raises(FileNotFoundError):
        _fs.checksum("/tempZone/i_dont_exist.txt")


# =============================================================================
# find() Tests
# =============================================================================

def test_find(_fs: IRODSFileSystem):
    """Test finding all files recursively."""
    base = "/tempZone/find_test"
    try:
        # Create a nested structure
        _fs.makedirs(f"{base}/a/b/c")
        _fs.pipe_file(f"{base}/file1.txt", b"content1")
        _fs.pipe_file(f"{base}/a/file2.txt", b"content2")
        _fs.pipe_file(f"{base}/a/b/file3.txt", b"content3")

        # Find all files
        result = _fs.find(base)
        assert isinstance(result, list)
        assert len(result) == 3
        assert f"{base}/file1.txt" in result
        assert f"{base}/a/file2.txt" in result
        assert f"{base}/a/b/file3.txt" in result

        # Find with directories included
        result_with_dirs = _fs.find(base, withdirs=True)
        assert isinstance(result_with_dirs, list)
        assert len(result_with_dirs) >= 3  # Files plus possibly directories

        # Find with maxdepth
        result_depth1 = _fs.find(base, maxdepth=1)
        assert isinstance(result_depth1, list)
        # Should only find file1.txt at depth 1, not files in subdirectories
        assert f"{base}/file1.txt" in result_depth1

        # Find with detail - fsspec may return list of dicts or dict of dicts
        result_detail = _fs.find(base, detail=True)
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
        if _fs.exists(base):
            _fs.rm(base, recursive=True)


def test_find_empty(_fs: IRODSFileSystem):
    """Test find on empty directory."""
    base = "/tempZone/i_dont_exist"
    try:
        _fs.makedirs(base)

        result = _fs.find(base)
        assert result == []
    finally:
        if _fs.exists(base):
            _fs.rm(base, recursive=True)


# =============================================================================
# walk() Tests
# =============================================================================

def test_walk(_fs: IRODSFileSystem):
    """Test walking directory tree."""
    base = "/tempZone/walk_test"
    try:
        # Create a nested structure
        _fs.makedirs(f"{base}/a/b")
        _fs.pipe_file(f"{base}/file1.txt", b"content1")
        _fs.pipe_file(f"{base}/a/file2.txt", b"content2")
        _fs.pipe_file(f"{base}/a/b/file3.txt", b"content3")

        # Walk the directory tree
        results = list(_fs.walk(base))

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
        if _fs.exists(base):
            _fs.rm(base, recursive=True)


def test_walk_maxdepth(_fs: IRODSFileSystem):
    """Test walk with maxdepth limit."""
    base = "/tempZone/walk_depth_test"
    try:
        # Create a nested structure
        _fs.makedirs(f"{base}/a/b/c")
        _fs.pipe_file(f"{base}/file1.txt", b"content1")
        _fs.pipe_file(f"{base}/a/file2.txt", b"content2")
        _fs.pipe_file(f"{base}/a/b/file3.txt", b"content3")
        _fs.pipe_file(f"{base}/a/b/c/file4.txt", b"content4")

        # Walk with maxdepth=1
        results = list(_fs.walk(base, maxdepth=1))

        # Should only visit root level
        assert len(results) >= 1
        for entry in results:
            path = entry[0]
            # No path should be deeper than one level
            depth = path.count("/") - base.count("/")
            assert depth <= 1
    finally:
        if _fs.exists(base):
            _fs.rm(base, recursive=True)


# =============================================================================
# du() Tests
# =============================================================================

def test_du(_fs: IRODSFileSystem):
    """Test disk usage calculation."""
    base = "/tempZone/du_test"
    try:
        # Create files with known sizes
        _fs.makedirs(base)
        _fs.pipe_file(f"{base}/file1.txt", b"x" * 100)
        _fs.pipe_file(f"{base}/file2.txt", b"x" * 200)

        # Get total size
        total = _fs.du(base)
        assert isinstance(total, int)
        assert total == 300

        # Get per-file sizes
        sizes = _fs.du(base, total=False)
        assert isinstance(sizes, dict)
        assert f"{base}/file1.txt" in sizes
        assert f"{base}/file2.txt" in sizes
        assert sizes[f"{base}/file1.txt"] == 100
        assert sizes[f"{base}/file2.txt"] == 200

        # With maxdepth
        _fs.makedirs(f"{base}/subdir")
        _fs.pipe_file(f"{base}/subdir/file3.txt", b"x" * 50)

        # Limited depth should not include subdir contents
        shallow = _fs.du(base, maxdepth=1, total=False)
        assert isinstance(shallow, dict)
        # file1.txt and file2.txt should be included
        assert f"{base}/file1.txt" in shallow
        assert f"{base}/file2.txt" in shallow
    finally:
        if _fs.exists(base):
            _fs.rm(base, recursive=True)


def test_du_empty(_fs: IRODSFileSystem):
    """Test du on empty directory."""
    base = "/tempZone/i_dont_exist"
    try:
        _fs.makedirs(base)

        total = _fs.du(base)
        assert total == 0
    finally:
        if _fs.exists(base):
            _fs.rm(base, recursive=True)


# =============================================================================
# File Handle Management Tests
# =============================================================================

def test_finalize_files(_fs: IRODSFileSystem):
    """Test file handle finalization."""
    # Open a file but don't close it explicitly
    test_path = "/tempZone/finalize_test.txt"
    try:
        _fs.pipe_file(test_path, b"test content")

        _ = _fs.open(test_path, "rb")
        # Don't close - rely on finalization

        # Call finalization
        _fs._finalize_files()

        # Should not raise
    finally:
        if _fs.exists(test_path):
            _fs.rm_file(test_path)


def test_close_removes_from_instances(_fs: IRODSFileSystem):
    """Test that close removes filesystem from global instances registry."""
    with _fs.open("/tempZone/existing_file.txt", "rb") as f:
        f.read(3)

    assert _fs in fs_instances
    _fs.close()
    assert _fs not in fs_instances


# =============================================================================
# Filesystem Properties and Metadata Tests
# =============================================================================

def test_fs_properties(_fs: IRODSFileSystem):
    """Test filesystem properties."""
    assert _fs.host is not None
    assert _fs.port is not None
    assert _fs.zone is not None
    assert _fs.root is not None


def test_str_repr(_fs: IRODSFileSystem):
    """Test string representations."""
    str_repr = str(_fs)
    assert "IRODSFileSystem" in str_repr

    repr_str = repr(_fs)
    assert "IRODSFileSystem" in repr_str


def test_fsid(_fs: IRODSFileSystem):
    """Test filesystem ID generation."""
    fsid = _fs.fsid
    assert fsid is not None
    assert isinstance(fsid, str)
    assert fsid.startswith("irods_")


def test_wrap(_fs: IRODSFileSystem):
    """Test path wrapping delegates correctly to iRODSPath."""
    assert _fs.wrap("/tempZone") == "/tempZone"
    assert _fs.wrap("subdir") == "/tempZone/subdir"
    assert _fs.wrap("/subdir") == "/tempZone/subdir"
    assert _fs.wrap("irods://host:1247/tempZone/path") == "/tempZone/path"


def test_get_kwargs_from_urls(_fs: IRODSFileSystem):
    """Test URL parsing for connection parameters."""
    kwargs = IRODSFileSystem._get_kwargs_from_urls("irods://user+zone@host:1247/path")
    assert kwargs["user"] == "user"
    assert kwargs["zone"] == "zone"
    assert kwargs["host"] == "host"
    assert kwargs["port"] == 1247


# =============================================================================
# IRODSFile Class Tests
# =============================================================================

class TestIRODSFile:
    """Tests for the IRODSFile class."""

    @pytest.fixture
    def _fs(self):
        """Create a filesystem for file tests."""
        builder: iRODSFSBuilder = iRODSFSBuilder().with_root("/")
        session = builder._session
        sut = IRODSFileSystem(session=session, root="/")
        yield sut
        sut.close()
        session.cleanup()

    def test_file_read(self, _fs: IRODSFileSystem):
        """Test reading from an IRODSFile."""
        test_path = "/tempZone/file_read_test.txt"
        try:
            _fs.pipe_file(test_path, b"test data")

            with _fs.open(test_path, "rb") as f:
                assert f.readable()
                data = f.read()
                assert data == b"test data"
        finally:
            if _fs.exists(test_path):
                _fs.rm_file(test_path)

    def test_file_write(self, _fs: IRODSFileSystem):
        """Test writing to an IRODSFile."""
        test_path = "/tempZone/file_write_test.txt"
        try:
            with _fs.open(test_path, "wb") as f:
                assert f.writable()
                written = f.write(b"new data")
                assert written > 0

            content = _fs.cat_file(test_path)
            assert content == b"new data"
        finally:
            if _fs.exists(test_path):
                _fs.rm_file(test_path)

    def test_file_seek_tell(self, _fs: IRODSFileSystem):
        """Test seeking and telling in a file."""
        test_path = "/tempZone/file_seek_test.txt"
        try:
            _fs.pipe_file(test_path, b"0123456789")

            with _fs.open(test_path, "rb") as f:
                pos = f.tell()
                assert pos == 0

                f.seek(5)
                pos = f.tell()
                assert pos == 5

                f.seek(-3, 2)  # Seek to 3 bytes before end
                pos = f.tell()
                assert pos == 7
        finally:
            if _fs.exists(test_path):
                _fs.rm_file(test_path)

    def test_file_context_manager(self, _fs: IRODSFileSystem):
        """Test file as context manager."""
        test_path = "/tempZone/file_context_test.txt"
        try:
            _fs.pipe_file(test_path, b"context test")

            with _fs.open(test_path, "rb") as f:
                assert not f.closed
                data = f.read()

            assert f.closed
            assert data == b"context test"
        finally:
            if _fs.exists(test_path):
                _fs.rm_file(test_path)

    def test_file_closed_property(self, _fs: IRODSFileSystem):
        """Test file closed property."""
        test_path = "/tempZone/file_closed_test.txt"
        try:
            _fs.pipe_file(test_path, b"test")

            f = _fs.open(test_path, "rb")
            assert not f.closed

            f.close()
            assert f.closed
        finally:
            if _fs.exists(test_path):
                _fs.rm_file(test_path)

    def test_file_readable_writable_seekable(self, _fs: IRODSFileSystem):
        """Test file capability methods."""
        test_path = "/tempZone/file_caps_test.txt"
        try:
            _fs.pipe_file(test_path, b"test data")

            with _fs.open(test_path, "rb") as f:
                assert f.readable() is True
                # Note: writable() and seekable() depend on mode
                assert f.seekable() is True

            with _fs.open(test_path, "wb") as f:
                assert f.writable() is True
                assert f.readable() is False
                assert f.seekable() is True
        finally:
            if _fs.exists(test_path):
                _fs.rm_file(test_path)
