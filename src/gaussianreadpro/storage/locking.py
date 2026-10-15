"""Process lifetime writer locks. Sidecars stay in place to avoid inode races."""
import os

from .codec import StorageError


class WriterLock:
    def __init__(self, path):
        self.path = str(path) + ".lock"
        self.file = None

    def acquire(self):
        try:
            handle = open(self.path, "a+b")
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.file = handle
        except OSError as exc:
            if 'handle' in locals():
                handle.close()
            raise StorageError("project_locked", str(exc)) from exc

    def close(self):
        if self.file is not None:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None
