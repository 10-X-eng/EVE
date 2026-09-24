"""Coordinate UI approval, main-thread export and detached supplier requests."""
import threading
import time
import json

from .rmfg import RMFGError
from .rmfg_jobs import RMFGJobs
from .tool_protocol import ToolError, tool_failure


class RMFGService:
    def __init__(self, home, auth, publish, bridge):
        self.jobs = RMFGJobs(home, auth)
        self.publish, self.bridge = publish, bridge
        self.closed = threading.Event()
        self.slot = threading.Lock()
        self.decision_lock = threading.Lock()
        self.pending = None

    def decide(self, job_id, approved):
        if type(approved) is not bool:
            raise ValueError('Choose Upload or Decline.')
        with self.decision_lock:
            if self.pending and self.pending['id'] == job_id and self.pending['approved'] is None:
                self.pending['approved'] = approved
                self.pending['event'].set()

    def submit(self, tool, arguments, complete, cancelled):
        if not self.slot.acquire(blocking=False):
            complete(tool_failure(ToolError('rmfg_unavailable', 'Another RMFG request is running. Finish it before starting another.')))
            return
        threading.Thread(target=self._run, args=(tool, dict(arguments), complete, cancelled),
                         name='STEVE-RMFG-job', daemon=True).start()

    def _run(self, tool, arguments, complete, caller_cancelled):
        job_id = arguments.get('job_id')
        def cancelled():
            return self.closed.is_set() or caller_cancelled()
        def check_cancelled():
            if cancelled():
                raise ToolError('cancelled', 'RMFG request cancelled. Any already submitted supplier work may continue on RMFG.')
        try:
            check_cancelled()
            self.jobs.auth.access_token()
            if tool == 'rmfg_materials':
                result = self.jobs.materials(arguments.get('cursor'))
            else:
                if not self.bridge:
                    raise ToolError('bridge_unavailable', 'Open this task inside Fusion.')
                action = arguments['action']
                if action != 'prepare':
                    arguments['_binding'] = self.jobs.read(job_id)['binding']
                received, values = threading.Event(), []
                def capture(value):
                    values.append(value)
                    received.set()
                self.bridge.submit('fusion_rmfg', arguments, capture, cancelled)
                while not received.wait(0.2):
                    check_cancelled()
                check_cancelled()
                snapshot = values[0]
                if not snapshot.get('ok'):
                    complete(snapshot)
                    return
                if action == 'prepare':
                    job = self.jobs.prepare(snapshot)
                    job_id = job['id']
                    pending = {'id': job_id, 'approved': None, 'event': threading.Event()}
                    with self.decision_lock:
                        self.pending = pending
                    self.publish({'rmfgUpload': {'id': job_id, 'body': job['body'], 'bytes': job['bytes']}})
                    deadline = time.monotonic()+600
                    try:
                        while not pending['event'].wait(0.2):
                            check_cancelled()
                            if time.monotonic() >= deadline:
                                raise ToolError('rmfg_unavailable', 'Upload approval expired. No geometry was uploaded.')
                        check_cancelled()
                    except Exception:
                        self.jobs.decide(job_id, False)
                        raise
                    finally:
                        with self.decision_lock:
                            self.pending = None
                        self.publish({'rmfgUpload': None})
                    self.jobs.decide(job_id, pending['approved'])
                    if not pending['approved']:
                        raise ToolError('cancelled', 'The user declined this upload. No geometry was uploaded.')
                    check_cancelled()
                    result = self.jobs.upload(job_id)
                elif action == 'status':
                    result = self.jobs.status(job_id, arguments.get('offset',0))
                else:
                    if not snapshot['snapshotMatches']:
                        raise ToolError('rmfg_unavailable', 'The body changed since this snapshot. Read the old report as historical evidence, or request a new snapshot and upload approval.')
                    check_cancelled()
                    result = (self.jobs.upload(job_id) if action == 'retry_upload'
                              else self.jobs.check(job_id, arguments['parts']))
                result['snapshotMatchesAtStart'] = snapshot.get('snapshotMatches', True)
                result['currency'] = 'Exported snapshot only. Geometry may have changed while RMFG processed it; recheck its revision before applying findings.'
            check_cancelled()
            if len(json.dumps(result, ensure_ascii=False, allow_nan=False)) > 24000:
                raise RMFGError('The supplier response exceeded the 24,000 character limit. Review this job in RMFG; do not repeat the upload.')
            complete(result)
        except Exception as error:
            if not isinstance(error, (ToolError, RMFGError)):
                error = RMFGError('RMFG could not complete this request. Check connection and job status before retrying.')
            if not isinstance(error, ToolError):
                error = ToolError('rmfg_unavailable', str(error))
            result = tool_failure(error)
            if job_id:
                result['jobId'] = job_id
            complete(result)
        finally:
            self.slot.release()

    def close(self):
        self.closed.set()
