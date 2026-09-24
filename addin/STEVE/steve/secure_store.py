"""User-bound encrypted Windows storage and macOS Keychain, with process locks."""
from contextlib import contextmanager
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading


class SecureStore:
    def __init__(self, directory, name):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', name):
            raise ValueError('Invalid secure-store name.')
        self.directory = Path(directory)
        self.name = name
        self.account = hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest()
        self._lock = threading.RLock()
        self._depth = 0

    @contextmanager
    def locked(self, busy_message='Another STEVE instance is using this connection. Retry when it finishes.'):
        with self._lock:
            if self._depth:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (self.directory / (self.name + '.lock')).open('a+b') as stream:
                if stream.tell() == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise RuntimeError(busy_message) from None
                try:
                    self._depth = 1
                    yield
                finally:
                    self._depth = 0
                    stream.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def read(self):
        try:
            if sys.platform == 'darwin':
                raw = self._keychain()
                if raw is None:
                    return None
            elif os.name == 'nt':
                path = self.directory / (self.name + '.dpapi')
                if not path.exists():
                    return None
                if path.stat().st_size > 100000:
                    raise ValueError('Invalid credential record size')
                from .grok_auth import protect
                raw = protect(path.read_bytes(), decrypt=True)
            else:
                raise RuntimeError('Secure connections currently require Windows or macOS.')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('Invalid credential record')
            return value
        except Exception:
            raise RuntimeError('The protected connection could not be read. Unlock the system credential store or reconnect.') from None

    def write(self, value):
        data = json.dumps(value, allow_nan=False).encode('utf-8')
        if len(data) > 64000:
            raise ValueError('The protected connection record is too large.')
        if sys.platform == 'darwin':
            self._keychain(data)
            return
        if os.name != 'nt':
            raise RuntimeError('Secure connections currently require Windows or macOS.')
        from .grok_auth import protect
        encrypted = protect(data)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.directory / (self.name + '.dpapi'))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _keychain(self, data=None):
        """Native Security.framework calls; secrets never enter process arguments."""
        cf = ctypes.CDLL(ctypes.util.find_library('CoreFoundation'))
        security = ctypes.CDLL(ctypes.util.find_library('Security'))
        pointer = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = pointer
        cf.CFDataCreate.argtypes = [pointer, pointer, ctypes.c_long]
        cf.CFDataCreate.restype = pointer
        cf.CFDictionaryCreate.argtypes = [pointer, pointer, pointer, ctypes.c_long, pointer, pointer]
        cf.CFDictionaryCreate.restype = pointer
        cf.CFRelease.argtypes = [pointer]
        cf.CFDataGetLength.argtypes = [pointer]
        cf.CFDataGetLength.restype = ctypes.c_long
        cf.CFDataGetBytePtr.argtypes = [pointer]
        cf.CFDataGetBytePtr.restype = pointer
        for name in ('SecItemCopyMatching', 'SecItemAdd', 'SecItemUpdate'):
            method = getattr(security, name)
            method.argtypes = [pointer, pointer]
            method.restype = ctypes.c_int32
        owned = []
        def constant(name):
            return pointer.in_dll(security, name).value
        def string(value):
            result = cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
            owned.append(result)
            return result
        def dictionary(pairs):
            keys = (pointer*len(pairs))(*(k for k,v in pairs))
            values = (pointer*len(pairs))(*(v for k,v in pairs))
            result = cf.CFDictionaryCreate(None, keys, values, len(pairs), None, None)
            owned.append(result)
            return result
        try:
            identity = [(constant('kSecClass'), constant('kSecClassGenericPassword')),
                        (constant('kSecAttrService'), string('STEVE.' + self.name)),
                        (constant('kSecAttrAccount'), string(self.account))]
            if data is None:
                query = dictionary(identity + [(constant('kSecReturnData'), pointer.in_dll(cf, 'kCFBooleanTrue').value)])
                output = pointer()
                status = security.SecItemCopyMatching(query, ctypes.byref(output))
                if status == -25300:
                    return None
                if status != 0:
                    raise RuntimeError('Keychain access failed.')
                owned.append(output.value)
                length = cf.CFDataGetLength(output)
                if not 0 <= length <= 64000:
                    raise RuntimeError('Invalid Keychain record size.')
                return ctypes.string_at(cf.CFDataGetBytePtr(output), length)
            buffer = ctypes.create_string_buffer(data)
            blob = cf.CFDataCreate(None, buffer, len(data))
            owned.append(blob)
            attributes = [(constant('kSecValueData'), blob)]
            status = security.SecItemUpdate(dictionary(identity), dictionary(attributes))
            if status == -25300:
                status = security.SecItemAdd(dictionary(identity + attributes), None)
            if status != 0:
                raise RuntimeError('Keychain connection could not be saved.')
        finally:
            for value in reversed(owned):
                if value:
                    cf.CFRelease(value)
