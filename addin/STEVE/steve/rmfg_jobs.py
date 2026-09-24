"""Durable, revision-bound supplier jobs; no Autodesk access or arbitrary file uploads."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .rmfg import RMFGClient, RMFGError, identifier
from .secure_store import SecureStore


def fields(value, names):
    return {key: value[key] for key in names.split() if key in value}


class RMFGJobs:
    def __init__(self, home, auth, client=None):
        self.folder = Path(home) / 'rmfg-jobs'
        self.auth = auth
        self.client = client or RMFGClient(auth.access_token)
        self.guard = SecureStore(home, 'rmfg-job-write')

    def _write(self, job):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / (identifier(job['id']) + '.json')
        data = json.dumps(job, allow_nan=False).encode('utf-8')
        if len(data) > 2*1024*1024:
            raise RMFGError('RMFG job metadata is too large. Inspect this report on RMFG.')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.folder, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def read(self, job_id):
        path = self.folder / (identifier(job_id)+'.json')
        if not path.exists() or path.stat().st_size > 2*1024*1024:
            raise RMFGError('RMFG job is unavailable. Use a job ID previously returned by STEVE on this computer.')
        job = json.loads(path.read_text(encoding='utf-8'))
        if job.get('connection') != self.auth.connection_id():
            raise RMFGError('This job belongs to an earlier RMFG connection. Request a new check under the current connection.')
        return job

    def prepare(self, snapshot):
        """Store exact exported bytes before approval; never accepts an input path."""
        with self.guard.locked():
            self.folder.mkdir(parents=True, exist_ok=True)
            files = list(self.folder.glob('*.step'))
            if len(files) >= 100 or sum(p.stat().st_size for p in files)+len(snapshot['step']) > 200*1024*1024:
                raise RMFGError('Local RMFG snapshots reached the storage limit. Remove old rmfg-jobs files when STEVE is stopped.')
            job = {'id': uuid4().hex, 'connection': self.auth.connection_id(),
                   'binding': fields(snapshot, 'documentKey partToken revision'),
                   'body': snapshot['body'], 'sha256': hashlib.sha256(snapshot['step']).hexdigest(),
                   'bytes': len(snapshot['step']), 'state': 'awaiting_approval', 'uploadKey': uuid4().hex}
            (self.folder / (job['id']+'.step')).write_bytes(snapshot['step'])
            self._write(job)
            return job

    def decide(self, job_id, approved):
        with self.guard.locked():
            job = self.read(job_id)
            if job['state'] != 'awaiting_approval':
                raise RMFGError('That upload request is no longer awaiting approval.')
            job['state'] = 'approved' if approved else 'declined'
            self._write(job)
            if not approved:
                (self.folder / (job['id']+'.step')).unlink(missing_ok=True)

    def upload(self, job_id):
        with self.guard.locked():
            job = self.read(job_id)
            if job.get('designId'):
                raise RMFGError('This snapshot was already uploaded. Use status for this same job; do not submit another upload.')
            if job['state'] not in ('approved', 'uploading'):
                raise RMFGError('Approve this exact snapshot in STEVE before uploading.')
            data = (self.folder / (job['id']+'.step')).read_bytes()
            if hashlib.sha256(data).hexdigest() != job['sha256']:
                raise RMFGError('The approved snapshot changed. Request a new upload; do not reuse this job.')
            job['state'] = 'uploading'
            self._write(job)  # Persist the write key before a possibly ambiguous network result.
            result = self.client.analyze(data, job['uploadKey'])
            job['designId'] = identifier(result['id'])
            job['state'] = 'analyzing'
            self._write(job)
            return self.status(job['id'])

    def materials(self, cursor=None):
        result = self.client.materials(cursor)
        rows = result.get('data', [])
        if not isinstance(rows, list) or len(rows)>20:
            raise RMFGError('RMFG returned an unexpected catalog page.')
        return {'ok': True, 'materials': [fields(row, 'id material type thickness_mm display_thickness description bendable') for row in rows],
                **fields(result, 'has_more next_cursor')}

    def status(self, job_id, offset=0):
        with self.guard.locked():
            job = self.read(job_id)
            if job.get('reportId'):
                report = self.client.dfm(job['reportId'])
                return self.report(job, report, offset)
            result = {'ok': True, 'jobId': job['id'], 'snapshot': fields(job, 'body sha256 bytes binding'), 'state': job['state']}
            if job.get('designId'):
                design = self.client.design(job['designId'])
                parts = design.get('parts', [])
                job['parts'] = [fields(part, 'id name suggested_process analysis_status detected_thickness_mm bend_count') for part in parts]
                job['designState'] = design.get('status')
                self._write(job)
                result.update(designState=job['designState'], parts=job['parts'][offset:offset+20],
                              nextOffset=offset+20 if offset+20<len(parts) else None)
            if job['state'] == 'uploading':
                result['recovery'] = 'The upload outcome is uncertain. Retry this same job ID to reuse the exact bytes and write key; do not upload a new snapshot.'
            return result

    def check(self, job_id, parts):
        with self.guard.locked():
            job = self.read(job_id)
            if job.get('designState') != 'ready':
                raise RMFGError('Read this job status until analysis is ready, then configure its returned parts.')
            observed = {part['id']: part for part in job.get('parts', [])}
            requested = {p.get('part_id') for p in parts}
            if (not observed or requested != set(observed) or len(requested)!=len(parts)
                    or any(part.get('suggested_process')!='sheet_metal' or part.get('analysis_status')=='failed' for part in observed.values())):
                raise RMFGError('Configure every analyzed sheet-metal part exactly once. Unsupported or failed parts need review in RMFG.')
            canonical = json.dumps(parts, sort_keys=True, separators=(',', ':'))
            # An ambiguous request can only be retried identically. Start a new snapshot
            # after a deliberate material/configuration change, preserving old evidence.
            if job.get('configuration') not in (None, canonical):
                raise RMFGError('This job already has a different material configuration. Use a new job for the changed configuration.')
            job.update(configuration=canonical, dfmKey=job.get('dfmKey') or uuid4().hex, state='checking')
            self._write(job)
            report = self.client.create_dfm(job['designId'], parts, job['dfmKey'])
            if report.get('design_id') != job['designId']:
                raise RMFGError('RMFG returned a report for an unexpected design. Keep this job for investigation; do not apply the report.')
            job.update(reportId=identifier(report['id']), state='reported')
            self._write(job)
            return self.report(job, report, 0)

    @staticmethod
    def report(job, report, offset):
        if report.get('design_id') != job['designId']:
            raise RMFGError('The RMFG report no longer matches this snapshot. Do not apply its findings.')
        # Never expose signed model links, credentials, files or supplier-internal issues.
        issues = []
        for part in report.get('parts', []):
            for issue in part.get('issues', []):
                if issue.get('customer_visible', True):
                    issues.append({'part_id': part.get('part_id'), **fields(issue, 'code message severity accepted source hole_id bend_id')})
        for issue in report.get('assembly_issues', []):
            if issue.get('customer_visible', True):
                issues.append(fields(issue, 'code message severity accepted source part_id'))
        return {'ok': True, 'jobId': job['id'], 'snapshot': fields(job, 'body sha256 bytes binding'),
                'state': 'reported', **fields(report, 'id status configuration_hash dfm_ruleset_version'),
                'issues': issues[offset:offset+20], 'nextOffset': offset+20 if offset+20<len(issues) else None,
                'coverage': 'RMFG supplier report for the exported snapshot and chosen materials; not universal manufacturing approval. Read all issue pages and review unresolved requirements in RMFG.',
                'requirementsPresent': bool(report.get('requirements')), 'productionFilesRequested': False}
