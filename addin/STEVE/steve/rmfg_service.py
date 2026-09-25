"""Coordinate main-thread export and automatic, detached supplier requests."""
import threading
import json

from .rmfg import RMFGClient, RMFGError
from .rmfg_jobs import RMFGJobs
from .rmfg_checkout import RMFGCheckout
from .tool_protocol import ToolError, tool_failure


class RMFGService:
    def __init__(self, home, auth, publish, bridge):
        self.jobs = RMFGJobs(home, auth)
        self.checkout = RMFGCheckout(self.jobs, RMFGClient(lambda: auth.access_token({'designs', 'dfm', 'quotes', 'carts'})))
        self.publish, self.bridge = publish, bridge
        self.closed = threading.Event()
        self.slot = threading.Lock()

    def submit(self, tool, arguments, complete, cancelled):
        if not self.slot.acquire(blocking=False):
            complete(tool_failure(ToolError('rmfg_unavailable', 'Another RMFG request is running. Finish it before starting another.')))
            return
        threading.Thread(target=self._run, args=(tool, dict(arguments), complete, cancelled),
                         name='STEVE-RMFG-job', daemon=True).start()

    def _run(self, tool, arguments, complete, caller_cancelled):
        job_id = arguments.get('job_id')
        checkout_id = arguments.get('checkout_id')
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
            elif tool == 'rmfg_checkout':
                if not self.bridge:
                    raise ToolError('bridge_unavailable', 'Open this task inside Fusion.')
                action = arguments['action']
                if 'items' in arguments:
                    checkout_id = self.checkout.prepare(arguments['items'])['id']
                record = self.checkout.read(checkout_id)
                matches = True
                for reference in record['references']:
                    check_cancelled()
                    binding = reference['binding']
                    received, values = threading.Event(), []
                    self.bridge.submit('fusion_rmfg', {'action': 'status', 'document_id': arguments['document_id'],
                        'part_token': binding['partToken'], '_binding': binding},
                        lambda value: (values.append(value), received.set()), cancelled)
                    while not received.wait(0.2):
                        check_cancelled()
                    check_cancelled()
                    if not values[0].get('ok'):
                        raise ToolError('rmfg_unavailable', 'A checkout part is unavailable in the pinned document. Resolve the original parts before continuing.')
                    matches = matches and values[0]['snapshotMatches']
                if not matches and action != 'status':
                    raise ToolError('rmfg_unavailable', 'A checkout part changed. Prepare and check its current snapshot, then request a new quote with the current jobs.')
                check_cancelled()
                result = (self.checkout.quote(checkout_id) if action == 'quote' else
                          self.checkout.create(checkout_id) if action == 'create' else
                          self.checkout.status(checkout_id, arguments.get('offset', 0)))
                result['snapshotMatchesAtStart'] = matches
                if not matches:
                    result['checkoutAvailable'] = False
                    result['canCheckout'] = False
                result['snapshotScope'] = 'Quoted snapshots only. Changed parts need new snapshots and a new quote.'
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
                    check_cancelled()
                    self.publish({'status': 'Uploading part to RMFG'})
                    check_cancelled()
                    result = self.jobs.upload(job_id)
                elif action == 'status':
                    result = self.jobs.status(job_id, arguments.get('offset',0))
                else:
                    if not snapshot['snapshotMatches']:
                        raise ToolError('rmfg_unavailable', 'The body changed since this snapshot. Read the old report as historical evidence, or prepare a new snapshot for upload.')
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
            if checkout_id:
                result['checkoutId'] = checkout_id
            complete(result)
        finally:
            self.slot.release()

    def close(self):
        self.closed.set()
