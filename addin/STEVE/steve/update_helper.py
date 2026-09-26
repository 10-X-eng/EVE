"""Copied outside STEVE before launch so Fusion can unload and replace the add-in."""
import json
from pathlib import Path
import threading
import time

import adsk.core
from .transaction import Transaction, write_json

_app = None
_transaction = None
_handler = None
_event = None
_done = threading.Event()
_phase = 'idle'
_deadline = 0
_error = ''
_event_id = ''
_pending = threading.Event()


def _target():
    return _app.scripts.itemByPath(str(_transaction.target))


def _finish(message):
    _transaction.result(message)
    own = _app.scripts.itemByPath(str(Path(__file__).parent))
    stop({})
    if own:
        own.isRunOnStartup = False
        own.unlink()


def _worker(operation, next_phase):
    global _phase, _error
    try:
        operation()
        _phase = next_phase
    except Exception as error:
        _error = str(error)
        _phase = 'fatal' if next_phase == 'restart_old' else 'recover'


def _start_worker(operation, next_phase):
    global _phase
    _phase = 'working'
    threading.Thread(target=_worker, args=(operation, next_phase), daemon=True,
                     name='STEVE-Update-Files').start()


class Tick(adsk.core.CustomEventHandler):
    def notify(self, args):
        global _phase, _deadline, _error
        _pending.clear()
        if _done.is_set() or _phase == 'working':
            return
        try:
            target = _target()
            if _phase == 'stop':
                ui = _app.userInterface
                command = ui.activeCommand
                schematic_idle = (command == 'Electron::Group' and ui.activeWorkspace
                                  and ui.activeWorkspace.id == 'SchEditorEnvironement')
                if command != 'SelectCommand' and not schematic_idle:
                    return
                if target and target.isRunning and not target.stop():
                    raise RuntimeError('Fusion could not stop STEVE. Installation was not changed.')
                if target and target.isRunning:
                    return
                _start_worker(_transaction.activate, 'start')
            elif _phase == 'start':
                handoff = {**_transaction.data.get('resume', {}),
                           'nonce': _transaction.data['nonce'], 'target': str(_transaction.target),
                           'version': _transaction.data['version']}
                write_json(Path(_transaction.data['home']) / 'update-handoff.json', handoff)
                if not target or not target.run(False):
                    raise RuntimeError('Fusion could not start the updated STEVE.')
                _deadline = time.monotonic() + 30
                _phase = 'verify'
            elif _phase == 'verify':
                receipt = Path(_transaction.data['home']) / 'update-loaded.json'
                value = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
                if (value.get('nonce') == _transaction.data['nonce']
                        and value.get('version') == _transaction.data['version']
                        and target and target.isRunning):
                    _transaction.state('complete')
                    _finish('Installed STEVE ' + _transaction.data['version'] + '. Fusion stayed open.')
                elif time.monotonic() >= _deadline:
                    raise RuntimeError('The updated add-in did not confirm startup; restoring the previous version.')
            elif _phase == 'recover':
                if _transaction.data['phase'] == 'prepared' and not _transaction.backup.exists():
                    _transaction.result('Installation failed: ' + _error + ' Installed files were not changed.')
                    if target and not target.isRunning:
                        target.run(False)
                    _finish('Installation failed: ' + _error + ' Installed files were not changed.')
                    return
                if target and target.isRunning and not target.stop():
                    _transaction.result('Installation failed: could not stop STEVE for recovery. Restart Fusion to recover.')
                    stop({})
                    return
                if target and target.isRunning:
                    return
                _start_worker(_transaction.rollback, 'restart_old')
            elif _phase == 'restart_old':
                # Remove new-version handoff before starting the previous code.
                (Path(_transaction.data['home']) / 'update-handoff.json').unlink(missing_ok=True)
                _transaction.result('Installation failed: ' + _error + ' Previous STEVE files restored.')
                if target and target.run(False):
                    _finish('Installation failed: ' + _error + ' Previous STEVE files restored.')
                else:
                    _finish('Installation failed: previous files restored. Start STEVE from Scripts and Add-Ins.')
            elif _phase == 'fatal':
                _transaction.result('Installation failed: ' + _error + ' Recovery will retry when Fusion starts.')
                stop({})
        except Exception as error:
            _error = str(error)
            if _phase in ('recover', 'restart_old'):
                # Keep this recovery helper registered for the next Fusion startup.
                _transaction.result('Installation failed: ' + _error + ' Recovery will retry when Fusion starts.')
                stop({})
            else:
                _phase = 'recover'


def run(context):
    global _app, _transaction, _handler, _event, _event_id, _phase, _error
    _app = adsk.core.Application.get()
    _transaction = Transaction(Path(__file__).parent / 'request.json')
    _event_id = 'STEVE_Update_' + _transaction.data['nonce']
    _done.clear()
    phase = _transaction.data['phase']
    if phase in ('complete', 'rolled_back'):
        _finish('STEVE update is already complete.' if phase == 'complete' else 'Installation failed: previous files restored.')
        return
    _phase = 'stop' if phase == 'prepared' else 'recover'
    _error = 'The update was interrupted.' if _phase == 'recover' else ''
    _event = _app.registerCustomEvent(_event_id)
    _handler = Tick()
    _event.add(_handler)
    def wake():
        while not _done.wait(0.25):
            if _pending.is_set():
                continue
            try:
                _pending.set()
                _app.fireCustomEvent(_event_id)
            except RuntimeError:
                return
    threading.Thread(target=wake, daemon=True, name='STEVE-Update-Wake').start()


def stop(context):
    global _event, _handler
    _done.set()
    if _event and _handler:
        try:
            _event.remove(_handler)
            _app.unregisterCustomEvent(_event_id)
        except RuntimeError:
            pass
    _event = _handler = None
