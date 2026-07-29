"""fsspec filesystem implementation for iRODS."""

import datetime
import io
import logging
import sys
from functools import cached_property
from multiprocessing import RLock
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from fsspec.spec import AbstractFileSystem
from fsspec.utils import tokenize
from irods.collection import iRODSCollection
from irods.data_object import iRODSDataObject
from irods.path import iRODSPath
from irods.session import iRODSSession

from fs_irods.utils import can_create

_logger = logging.getLogger(__name__)

# Global registry of open filesystem instances for cleanup
fs_instances = WeakKeyDictionary()

_utc = datetime.timezone(datetime.timedelta(0))


# Register the filesystem with fsspec
try:
    import fsspec
    fsspec.register_implementation("irods", "fs_irods.iRODSFSSpec.IRODSFileSystem")
except Exception:
    pass  # Ignore registration errors during import


def _get_default_port() -> int:
    """Get the default iRODS port."""
    return 1247


def finalize():
    """Close all open file handles on cleanup."""
    for fs in list(fs_instances):
        try:
            fs._finalize_files()
        except Exception:
            pass


# Register finalization before iRODS client cleanup
try:
    from irods.at_client_exit import register_for_execution_before_prc_cleanup
    register_for_execution_before_prc_cleanup(finalize)
except ImportError:
    # Fallback if at_client_exit is not available
    import atexit
    atexit.register(finalize)


class AbstractBufferedFile:
    """Base class for file-like objects.

    This is a placeholder base class that provides documentation
    for the expected interface. Actual implementations inherit from this.
    """


class IRODSFile(AbstractBufferedFile):
    """File-like object for iRODS data objects compatible with fsspec.

    This class wraps iRODS data object file handles and provides
    a file-like interface for reading and writing.
    """

    def __init__(
        self,
        fs: "IRODSFileSystem",
        path: str,
        mode: str = "rb",
        buffer_size: int = -1,
        **options,
    ):
        """Initialize the file.

        Args:
            fs: The parent filesystem instance.
            path: Path to the iRODS data object.
            mode: File mode ('r', 'w', 'a', etc.).
            buffer_size: Buffer size (-1 for default).
            **options: Additional options passed to iRODS session.
        """
        self.fs = fs
        self.path = path
        self.mode = mode
        self.buffer_size = buffer_size
        self.options = options
        self._file = None
        self._closed = False

        self._open_file()

        fs.files[self] = fs

    def _open_file(self):
        """Open the underlying iRODS data object."""
        create = can_create(self.mode)
        irods_mode = self.mode.replace("b", "")

        # Handle append mode - seek to end after opening
        if "a" in irods_mode:
            # Open for read/write to allow seeking
            self._file = self.fs._session.data_objects.open(
                self.path,
                irods_mode + "+",
                create,
                allow_redirect=False,
                auto_close=False,
                **self.options,
            )
            self._file.seek(0, io.SEEK_END)
        else:
            self._file = self.fs._session.data_objects.open(
                self.path,
                irods_mode,
                create,
                allow_redirect=False,
                auto_close=False,
                **self.options,
            )

    def read(self, length: int = -1) -> bytes:
        """Read data from the file.

        Args:
            length: Number of bytes to read (-1 for all).

        Returns:
            Bytes read from the file.
        """
        if self._closed:
            raise ValueError("I/O operation on closed file")
        if "r" not in self.mode and "a" not in self.mode:
            raise io.UnsupportedOperation("File not open for reading")

        if length == -1:
            return self._file.read()
        return self._file.read(length)

    def write(self, data: bytes) -> int:
        """Write data to the file.

        Args:
            data: Bytes to write.

        Returns:
            Number of bytes written.
        """
        if self._closed:
            raise ValueError("I/O operation on closed file")
        if "w" not in self.mode and "a" not in self.mode:
            raise io.UnsupportedOperation("File not open for writing")

        return self._file.write(data)

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Seek to a position in the file.

        Args:
            offset: Offset in bytes.
            whence: Where to seek from (SEEK_SET, SEEK_CUR, SEEK_END).

        Returns:
            New absolute position.
        """
        if self._closed:
            raise ValueError("I/O operation on closed file")
        return self._file.seek(offset, whence)

    def tell(self) -> int:
        """Return current file position.

        Returns:
            Current position in bytes.
        """
        if self._closed:
            raise ValueError("I/O operation on closed file")
        return self._file.tell()

    def close(self):
        """Close the file."""
        if self._closed:
            return

        try:
            if self._file is not None and not self._file.closed:
                self._file.close()
        finally:
            self._closed = True
            if self in self.fs.files:
                del self.fs.files[self]

    @property
    def closed(self) -> bool:
        """Check if the file is closed."""
        return self._closed

    def readable(self) -> bool:
        """Check if the file is readable."""
        return "r" in self.mode or "a" in self.mode

    def writable(self) -> bool:
        """Check if the file is writable."""
        return "w" in self.mode or "a" in self.mode

    def seekable(self) -> bool:
        """Check if the file supports seeking."""
        return True

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __del__(self):
        """Destructor to ensure file is closed."""
        if not self._closed:
            self.close()


class IRODSFileSystem(AbstractFileSystem):
    """iRODS filesystem implementation for fsspec.

    This class provides an fsspec-compatible interface to iRODS
    collections (directories) and data objects (files).

    Example usage:
        >>> from fs_irods import IRODSFileSystem
        >>> from irods.session import iRODSSession

        # Create a new session and filesystem
        >>> session = iRODSSession(host='localhost', user='rods', zone='tempZone')
        >>> fs = IRODSFileSystem(session=session)

        # Or use connection string
        >>> fs = IRODSFileSystem('irods://rods@tempZone/localhost:1247/')

        # List files
        >>> fs.ls('/tempZone/home/rods')

        # Read/write files
        >>> fs.pipe_file('/tempZone/test.txt', b'hello world')
        >>> fs.cat_file('/tempZone/test.txt')
        b'hello world'
    """

    protocol = "irods"
    root_marker = "/"

    def __init__(
        self,
        *args: Any,
        session: Optional[iRODSSession] = None,
        user: Optional[str] = None,
        zone: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Union[int, str] = None,
        root: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize the iRODS filesystem.

        Args:
            session: An existing iRODS session. If provided, other connection
                parameters are ignored.
            user: iRODS username. Required if session is not provided.
            zone: iRODS zone name. Required if session is not provided.
            password: iRODS password. Required if session is not provided.
            host: iRODS server hostname. Required if session is not provided.
            port: iRODS server port. Defaults to 1247.
            root: Root path within iRODS. Defaults to the user's home zone.
            *args: Additional positional arguments passed to parent.
            **kwargs: Additional keyword arguments passed to parent.
        """
        self._lock = RLock()
        self._finalizing = False

        self.files = WeakKeyDictionary()

        if port is None:
            port = _get_default_port()

        if session is None:
            if user is None or zone is None or password is None or host is None:
                raise ValueError(
                    "Must provide either a session or all connection parameters "
                    "(user, zone, password, host)"
                )
            self._session = iRODSSession(
                host=host,
                port=int(port),
                user=user,
                zone=zone,
                password=password,
            )
            self._owns_session = True
        else:
            self._session = session
            self._owns_session = False

        self._root = root if root is not None else f"/{self._session.zone}"

        super().__init__(*args, **kwargs)

    @property
    def _session(self) -> iRODSSession:
        """Get the iRODS session."""
        return self.__session

    @_session.setter
    def _session(self, value: iRODSSession):
        """Set the iRODS session."""
        self.__session = value

    def __del__(self):
        """Clean up resources on deletion."""
        if self._finalizing:
            return

        if sys.is_finalizing():
            # Interpreter is shutting down, skip cleanup
            return

        try:
            self._finalize_files()
            if self._owns_session:
                self._session.cleanup()
        except Exception:
            pass

    def _finalize_files(self):
        """Close all open file handles."""
        self._finalizing = True
        file_list = list(self.files)
        while file_list:
            f = file_list.pop()
            try:
                if not f.closed:
                    f.close()
            except Exception:
                pass

    @staticmethod
    def _get_kwargs_from_urls(path: str) -> Dict[str, Any]:
        """Extract connection parameters from a URL.

        Args:
            path: A URL like 'irods://user+zone@host:port/path'

        Returns:
            Dictionary with user, zone, password, host, port keys.
        """
        result = urlparse(path)

        if result.username is not None:
            try:
                user, zone = result.username.split("+")
            except ValueError:
                user = result.username
                zone = None
        else:
            user = None
            zone = None

        return {
            "user": user,
            "zone": zone,
            "password": result.password,
            "host": result.hostname,
            "port": result.port if result.port is not None else _get_default_port(),
        }

    @classmethod
    def _strip_protocol(cls, path: str) -> str:
        """Strip the protocol from a path.

        Args:
            path: A path possibly containing the irods:// protocol.

        Returns:
            Normalized path without protocol.
        """
        parsed = urlparse(path)
        path = parsed.path or cls.root_marker

        path = path.replace("\\", "/")

        if not path.startswith(cls.root_marker):
            path = cls.root_marker + path

        while "//" in path:
            path = path.replace("//", "/")

        return path

    def wrap(self, path: str) -> str:
        """Transform a path into a full iRODS path.

        Args:
            path: A path relative to the filesystem root.

        Returns:
            Full iRODS path.
        """
        path = self._strip_protocol(path)
        if path.startswith(self._root):
            return str(iRODSPath(path))
        return str(iRODSPath(self._root, path))

    def invalidate_cache(self, path: Optional[str] = None):
        """Invalidate the cache for a path.

        Args:
            path: Path to invalidate. If None, invalidates all cache.
        """
        # fsspec has its own cache mechanism via invalidate_cache
        # This is a no-op for now as we don't maintain additional caching

    def mkdir(
        self, path: str, create_parents: bool = True, **kwargs: Any
    ) -> None:
        """Create a collection (directory).

        Args:
            path: Path to the collection to create.
            create_parents: If True, create parent collections as needed.
                If False, raises when the path already exists or the
                parent collection does not exist.
            **kwargs: Additional keyword arguments.

        Raises:
            FileExistsError: If the collection already exists and
                ``create_parents`` is False.
            FileNotFoundError: If a parent collection does not exist and
                ``create_parents`` is False.
        """
        path = self.wrap(path)

        with self._lock:
            if self._session.collections.exists(path):
                if not create_parents:
                    raise FileExistsError(
                        f"Collection already exists: {path}"
                    )
                return

            if not create_parents:
                parent_path = self._parent(path)
                if parent_path and not self._session.collections.exists(
                    self.wrap(parent_path)
                ):
                    raise FileNotFoundError(
                        f"Parent collection does not exist: {parent_path}"
                    )

            self._session.collections.create(path, recurse=create_parents)

        self.invalidate_cache(self._parent(path))

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        """Recursively create directories.

        Args:
            path: Path to the directory to create.
            exist_ok: If False, raise error if path exists.
        """
        path = self.wrap(path)

        if self._session.data_objects.exists(path):
            raise FileExistsError(
                f"A data object exists at path {path}, cannot create a directory there"
            )

        coll_exists = self._session.collections.exists(path)
        if not coll_exists:
            self.mkdir(path, create_parents=True)
        elif not exist_ok:
            raise FileExistsError(f"An iRODS collection already exists at path {path}")

    def rmdir(self, path: str, recursive: bool = False) -> None:
        """Remove a collection.

        Args:
            path: Path to the collection to remove.
            recursive: If True, remove contents recursively.

        Raises:
            FileNotFoundError: If the path does not exist.
        """
        path = self.wrap(path)

        with self._lock:
            if not self._session.collections.exists(path):
                raise FileNotFoundError(f"No such collection: {path}")
            self._session.collections.remove(path, recurse=recursive)

        self.invalidate_cache(self._parent(path))

    def rm_file(self, path: str) -> None:
        """Remove a data object (file).

        Args:
            path: Path to the data object to remove.

        Raises:
            FileNotFoundError: If the path does not exist.
        """
        path = self.wrap(path)

        with self._lock:
            if not self._session.data_objects.exists(path):
                raise FileNotFoundError(f"No such file: {path}")
            self._session.data_objects.unlink(path)

        self.invalidate_cache(self._parent(path))

    def rm(
        self,
        path: str,
        recursive: bool = False,
        maxdepth: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """Remove a file or directory.

        Args:
            path: Path to remove.
            recursive: If True, remove directory contents recursively.
            maxdepth: Maximum depth to traverse when removing recursively.
            **kwargs: Additional keyword arguments.
        """
        path = self.wrap(path)

        with self._lock:
            if self._session.data_objects.exists(path):
                self._session.data_objects.unlink(path)
            elif self._session.collections.exists(path):
                self._session.collections.remove(path, recurse=recursive)
            else:
                raise FileNotFoundError(f"No such data object or collection: {path}")

        self.invalidate_cache(self._parent(path))

    def mv(
        self,
        path1: str,
        path2: str,
        recursive: bool = False,
        maxdepth: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """Move a file or directory.

        Args:
            path1: Source path.
            path2: Destination path.
            recursive: If True, move directory contents recursively (ignored).
            maxdepth: Maximum depth to traverse when moving recursively (ignored).
            **kwargs: Additional keyword arguments.
        """
        src_path = self.wrap(path1)
        dst_path = self.wrap(path2)

        with self._lock:
            if self._session.data_objects.exists(src_path):
                self._session.data_objects.move(src_path, dst_path)
            elif self._session.collections.exists(src_path):
                self._session.collections.move(src_path, dst_path)
            else:
                raise FileNotFoundError(f"No such data object or collection: {src_path}")

        self.invalidate_cache(self._parent(src_path))
        self.invalidate_cache(self._parent(dst_path))

    def cp_file(self, path1: str, path2: str, **kwargs: Any) -> None:
        """Copy a single file.

        Args:
            path1: Source path.
            path2: Destination path.
            **kwargs: Additional keyword arguments.
        """
        src_path = self.wrap(path1)
        dst_path = self.wrap(path2)

        with self._lock:
            if self._session.data_objects.exists(src_path):
                self._session.data_objects.copy(src_path, dst_path)
            elif self._session.collections.exists(src_path):
                # For collections, just create the destination
                self._session.collections.create(dst_path, recurse=True)
            else:
                raise FileNotFoundError(f"No such data object or collection: {src_path}")

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: Optional[int] = None,
        autocommit: bool = True,
        cache_options: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> IRODSFile:
        """Open a file for reading or writing.

        Args:
            path: Path to the file.
            mode: File mode ('rb', 'wb', 'ab', etc.).
            block_size: Block size for buffering (ignored).
            autocommit: Whether to commit immediately (must be True).
            cache_options: Cache options (ignored).
            **kwargs: Additional keyword arguments.

        Returns:
            An IRODSFile instance.
        """
        if not autocommit:
            raise NotImplementedError("Only autocommit=True operations are supported")

        fs_instances[self] = None

        path = self.wrap(path)
        return IRODSFile(self, path, mode=mode, **kwargs)

    def cat_file(
        self,
        path: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        **kwargs: Any,
    ) -> bytes:
        """Read entire contents of a file.

        Args:
            path: Path to the file.
            start: Start byte offset (optional).
            end: End byte offset (optional).
            **kwargs: Additional keyword arguments.

        Returns:
            File contents as bytes.
        """
        path = self.wrap(path)

        with self._lock:
            with self._session.data_objects.open(
                path, "r", allow_redirect=False, auto_close=False
            ) as f:
                if start is not None:
                    f.seek(start)
                if end is not None:
                    return f.read(end - f.tell())
                return f.read()

    def pipe_file(self, path: str, value: bytes, **kwargs: Any) -> None:
        """Write bytes to a file.

        Args:
            path: Path to the file.
            value: Bytes to write.
            **kwargs: Additional keyword arguments.
        """
        path = self.wrap(path)

        with self._lock:
            with self._session.data_objects.open(
                path, "w", allow_redirect=False, auto_close=False
            ) as f:
                f.write(value)

    def ls(
        self,
        path: str,
        detail: bool = True,
        **kwargs: Any,
    ) -> Union[List[str], List[Dict[str, Any]]]:
        """List contents of a directory.

        Args:
            path: Path to the directory.
            detail: If True, return detailed info dicts. If False, return paths only.
            **kwargs: Additional keyword arguments.

        Returns:
            List of entries (either strings or dicts depending on detail).
        """
        path = self.wrap(path)

        entries: List[Dict[str, Any]] = []

        with self._lock:
            if self._session.data_objects.exists(path):
                data_obj = self._session.data_objects.get(path)
                entries.append(self._data_object_info(data_obj))
            elif self._session.collections.exists(path):
                collection = self._session.collections.get(path)
                for subcoll in collection.subcollections:
                    entries.append(self._collection_info(subcoll))
                for data_obj in collection.data_objects:
                    entries.append(self._data_object_info(data_obj))
            else:
                raise FileNotFoundError(f"No such data object or collection: {path}")

        if detail:
            return entries
        return [entry["name"] for entry in entries]

    def _data_object_info(self, data_object: iRODSDataObject) -> Dict[str, Any]:
        """Build info dict for a data object.

        Args:
            data_object: The iRODS data object.

        Returns:
            Dictionary with file metadata.
        """
        return {
            "name": data_object.path,
            "size": data_object.size,
            "type": "file",
            "created": data_object.create_time,
            "mtime": data_object.modify_time,
            "checksum": data_object.checksum,
            "id": data_object.id,
            "owner": data_object.owner_name,
            "comments": data_object.comments,
            "expiry": data_object.expiry,
        }

    def _collection_info(self, collection: iRODSCollection) -> Dict[str, Any]:
        """Build info dict for a collection.

        Args:
            collection: The iRODS collection.

        Returns:
            Dictionary with directory metadata.
        """
        return {
            "name": collection.path,
            "size": 0,
            "type": "directory",
            "created": collection.create_time,
            "mtime": collection.modify_time,
            "id": collection.id,
            "owner": collection.owner_name,
        }

    def info(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Get information about a path.

        Args:
            path: Path to get info for.
            **kwargs: Additional keyword arguments.

        Returns:
            Dictionary with file/directory metadata.
        """
        path = self.wrap(path)

        with self._lock:
            if self._session.data_objects.exists(path):
                data_obj = self._session.data_objects.get(path)
                return self._data_object_info(data_obj)
            if self._session.collections.exists(path):
                collection = self._session.collections.get(path)
                return self._collection_info(collection)
            raise FileNotFoundError(f"No such data object or collection: {path}")

    def exists(self, path: str, **kwargs: Any) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check.
            **kwargs: Additional keyword arguments.

        Returns:
            True if the path exists.
        """
        path = self.wrap(path)

        with self._lock:
            return (
                self._session.data_objects.exists(path)
                or self._session.collections.exists(path)
            )

    def isdir(self, path: str) -> bool:
        """Check if a path is a directory.

        Args:
            path: Path to check.

        Returns:
            True if the path is a collection.
        """
        path = self.wrap(path)

        with self._lock:
            return self._session.collections.exists(path)

    def isfile(self, path: str) -> bool:
        """Check if a path is a file.

        Args:
            path: Path to check.

        Returns:
            True if the path is a data object.
        """
        path = self.wrap(path)

        with self._lock:
            return self._session.data_objects.exists(path)

    def checksum(self, path: str) -> Optional[str]:
        """Get the checksum of a file.

        Args:
            path: Path to the file.

        Returns:
            Checksum string (e.g., "sha256:abc123...") or None if not available.

        Raises:
            FileNotFoundError: If the path does not exist or is not a file.
        """
        path = self.wrap(path)

        with self._lock:
            if not self._session.data_objects.exists(path):
                raise FileNotFoundError(f"No such file: {path}")
            data_obj = self._session.data_objects.get(path)
            return data_obj.checksum

    def size(self, path: str) -> int:
        """Get the size of a file.

        Args:
            path: Path to the file.

        Returns:
            Size in bytes.

        Raises:
            FileNotFoundError: If the path does not exist or is not a file.
        """
        path = self.wrap(path)

        with self._lock:
            if not self.exists(path):
                raise FileNotFoundError(f"No such file: {path}")
            if not self._session.data_objects.exists(path):
                raise FileNotFoundError(f"Not a file: {path}")
            return self._session.data_objects.get(path).size

    def touch(self, path: str, truncate: bool = True, **kwargs: Any) -> None:
        """Create an empty file or update timestamp.

        Args:
            path: Path to the file.
            truncate: If True, set file size to 0.
            **kwargs: Additional keyword arguments.

        Raises:
            IsADirectoryError: If the path points to an existing collection.
            FileNotFoundError: If the parent collection does not exist.
            FileExistsError: If the file already exists and truncate is False.
        """
        path = self.wrap(path)

        with self._lock:
            if self._session.collections.exists(path):
                raise IsADirectoryError(f"Path is a collection, not a data object: {path}")

            if not self._session.data_objects.exists(path):
                parent_path = self._parent(path)
                if parent_path and not self._session.collections.exists(
                    self.wrap(parent_path)
                ):
                    raise FileNotFoundError(
                        f"Parent collection does not exist: {parent_path}"
                    )

                self._session.data_objects.create(path)
                self.invalidate_cache(self._parent(path))
                return

            if truncate:
                self._session.data_objects.truncate(path, size=0)
                self._session.data_objects.touch(path, **kwargs)
            else:
                raise FileExistsError(f"Data object already exists: {path}")


    def modified(self, path: str) -> datetime.datetime:
        """Return the modification timestamp of a file.

        Args:
            path: Path to the file.

        Returns:
            Modification time as datetime.
        """
        info = self.info(path)
        mtime = info.get("mtime")
        if mtime is None:
            raise FileNotFoundError(f"No such file: {path}")
        return mtime

    def created(self, path: str) -> datetime.datetime:
        """Return the creation timestamp of a file.

        Args:
            path: Path to the file.

        Returns:
            Creation time as datetime.
        """
        info = self.info(path)
        created = info.get("created")
        if created is None:
            raise FileNotFoundError(f"No such file: {path}")
        return created

    @cached_property
    def fsid(self) -> str:
        """Get a unique filesystem identifier.

        Returns:
            Unique ID based on host and port.
        """
        return "irods_" + tokenize(self._session.host, self._session.port)

    def du(
        self,
        path: str,
        total: bool = True,
        maxdepth: Optional[int] = None,
        withdirs: bool = False,
        **kwargs: Any,
    ) -> Union[int, Dict[str, int]]:
        """Sum up file sizes.

        Args:
            path: Path to calculate disk usage for.
            total: If True, return total sum. If False, return dict per path.
            maxdepth: Maximum depth to traverse.
            withdirs: Include directories in results.
            **kwargs: Additional keyword arguments.

        Returns:
            Total size or dict mapping paths to sizes.
        """
        return super().du(path, total=total, maxdepth=maxdepth, withdirs=withdirs, **kwargs)

    def find(
        self,
        path: str,
        maxdepth: Optional[int] = None,
        withdirs: bool = False,
        detail: bool = False,
        **kwargs: Any,
    ) -> Union[List[str], Dict[str, Dict[str, Any]]]:
        """List all files below a path.

        Args:
            path: Path to start search from.
            maxdepth: Maximum depth to traverse.
            withdirs: Include directories in results.
            detail: Return detailed info dicts instead of paths.
            **kwargs: Additional keyword arguments.

        Returns:
            List of paths or dict of info dicts.
        """
        path = self.wrap(path)
        return super().find(path, maxdepth=maxdepth, withdirs=withdirs, detail=detail, **kwargs)

    def walk(
        self,
        path: str,
        maxdepth: Optional[int] = None,
        topdown: bool = True,
        on_error: Any = "omit",
        **kwargs: Any,
    ):
        """Walk a directory tree.

        Args:
            path: Path to start walking from.
            maxdepth: Maximum depth to traverse.
            topdown: Directrion of traversal.
            on_error: Error handling strategy.
            **kwargs: Additional keyword arguments.

        Yields:
            Tuples of (path, dirs, files) for each directory.
        """
        path = self.wrap(path)
        yield from super().walk(
            path, maxdepth=maxdepth, topdown=topdown, on_error=on_error, **kwargs)

    @property
    def session(self) -> iRODSSession:
        """Get the underlying iRODS session."""
        return self._session

    @property
    def host(self) -> str:
        """Get the iRODS server hostname."""
        return self._session.host

    @property
    def port(self) -> int:
        """Get the iRODS server port."""
        return self._session.port

    @property
    def zone(self) -> str:
        """Get the iRODS zone name."""
        return self._session.zone

    @property
    def root(self) -> str:
        """Get the root path of this filesystem."""
        return self._root

    def close(self):
        """Close the filesystem and clean up resources."""
        self._finalize_files()
        if self._owns_session:
            self._session.cleanup()
        if self in fs_instances:
            del fs_instances[self]

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and close the filesystem."""
        self.close()
        return False

    def __str__(self) -> str:
        """String representation of the filesystem."""
        return f"IRODSFileSystem({self.host}:{self.port}/{self.zone})"

    def __repr__(self) -> str:
        """Repr representation of the filesystem."""
        return f"IRODSFileSystem(host={self.host!r}, port={self.port}, zone={self.zone!r})"
