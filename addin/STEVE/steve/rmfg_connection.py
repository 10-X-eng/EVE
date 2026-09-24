"""Optional supplier connection. Network and credential access stay off the UI thread."""
import threading
import time

from .rmfg import RMFGAuth, RMFGError
from .secure_store import SecureStore


class RMFGConnection:
    def __init__(self, home, publish, open_browser, auth=None):
        self.auth = auth or RMFGAuth(SecureStore(home, 'rmfg'))
        self.publish, self.open_browser = publish, open_browser
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._cancel = threading.Event()
        self._running = False
        self._attempt = None

    def action(self, action):
        if action == 'rmfgCancel':
            self._cancel.set()
            return
        if action not in ('rmfgConnect', 'rmfgRefresh', 'rmfgDisconnect'):
            raise ValueError('Unknown RMFG connection action.')
        with self._lock:
            if self._closed.is_set() or self._running:
                return
            self._running = True
            self._cancel.clear()
        self.publish({'rmfgBusy': True, 'rmfgError': ''})
        threading.Thread(target=self._work, args=(action,), name='STEVE-RMFG-connection', daemon=True).start()

    def _state(self, **changes):
        if not self._closed.is_set():
            self.publish(changes)

    def _work(self, action):
        try:
            if action == 'rmfgDisconnect':
                self.auth.disconnect()
            elif action == 'rmfgConnect':
                attempt = self.auth.begin()
                self._attempt = attempt
                self._state(rmfgState='authorizing', rmfgCode=attempt.user_code)
                # Only the validated provider URL is opened. It never enters logs/model context.
                if not self.open_browser(attempt.url):
                    self._state(rmfgError='The browser did not open. Cancel and connect again after checking your default browser.')
                while not self._closed.is_set() and not self._cancel.is_set():
                    if self._closed.wait(min(1, max(0.05, attempt.next_poll-time.time()))):
                        break
                    if self.auth.poll(attempt) == 'connected':
                        break
                if self._closed.is_set() or self._cancel.is_set():
                    self.auth.cancel(attempt)
                self._attempt = None
            elif action == 'rmfgRefresh':
                if self.auth.status()['state'] == 'connected':
                    self.auth.access_token()
            state = self.auth.status()['state']
            self._state(rmfgState='reconnect' if state == 'authorizing' else state)
        except Exception as error:
            # Only our bounded errors can be displayed; OS/network exceptions can include secrets.
            message = str(error) if isinstance(error, RMFGError) else 'RMFG connection unavailable. Unlock the system credential store or reconnect.'
            self._state(rmfgError=message, rmfgState='reconnect')
        finally:
            with self._lock:
                self._running = False
            self._state(rmfgBusy=False, rmfgCode='')

    def close(self):
        self._closed.set()
        self._cancel.set()
