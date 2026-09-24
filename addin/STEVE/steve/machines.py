"""Sourced machine capabilities: one bounded JSON definition per machine.

Definitions are data, never executable plugins. Plans select an exact content
hash; editing a definition requires explicit plan refresh before rechecking.
"""
import copy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

DIRECTORY = Path(__file__).with_name('machine_definitions')
PROCESSES = {'milling', 'turning', 'sheet_metal', 'fdm', 'resin', 'powder'}


class MachineDefinitionError(RuntimeError):
    code = 'machine_definition_unavailable'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value):
        raise ValueError('Use a machine ID returned by fusion_api_help steve.machines, not a path.')
    return value


def text(value, limit=400):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Machine metadata must be nonempty bounded text.')


def validate(value, machine_id):
    if not isinstance(value, dict) or set(value) != {'id', 'name', 'manufacturer', 'revision', 'processes', 'verified_on', 'sources', 'capabilities', 'unverified'}:
        raise ValueError('Machine definition fields do not match the documented schema.')
    if identifier(value['id']) != machine_id:
        raise ValueError('Machine ID must match its filename.')
    for field in ('name', 'manufacturer', 'revision'):
        text(value[field], 100)
    if not isinstance(value['verified_on'], str) or date.fromisoformat(value['verified_on']).isoformat() != value['verified_on']:
        raise ValueError('verified_on must be an ISO date.')
    processes = value['processes']
    if not isinstance(processes, list) or not processes or any(p not in PROCESSES for p in processes) or len(set(processes)) != len(processes):
        raise ValueError('List distinct supported manufacturing processes.')
    sources = value['sources']
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 8:
        raise ValueError('Supply 1 to 8 source references.')
    for key, url in sources.items():
        identifier(key)
        text(url, 250)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Machine sources must be public HTTPS references.')
    capabilities = value['capabilities']
    if not isinstance(capabilities, dict) or not 1 <= len(capabilities) <= 24:
        raise ValueError('Supply 1 to 24 measured capability limits.')
    for key, entry in capabilities.items():
        identifier(key)
        if not isinstance(entry, dict) or set(entry) != {'value', 'units', 'relation', 'source', 'scope'}:
            raise ValueError('Each capability requires value, units, relation, source and scope.')
        if type(entry['value']) not in (int, float) or not math.isfinite(entry['value']):
            raise ValueError('Capability values must be finite numbers.')
        text(entry['units'], 30)
        text(entry['scope'])
        if entry['relation'] not in ('<=', '>=', '==') or entry['source'] not in sources:
            raise ValueError('Capability relation or source is invalid.')
    if not isinstance(value['unverified'], list) or not 1 <= len(value['unverified']) <= 12:
        raise ValueError('Document 1 to 12 unverified capability areas.')
    for limitation in value['unverified']:
        text(limitation)
    return copy.deepcopy(value)


def load(machine_id):
    machine_id = identifier(machine_id)
    try:
        path = DIRECTORY / (machine_id + '.json')
        with path.open('rb') as stream:
            raw = stream.read(16001)
        if len(raw) > 16000:
            raise ValueError('Machine definition exceeds 16,000 bytes.')
        value = validate(json.loads(raw), machine_id)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        return {**value, 'definition_hash': digest}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MachineDefinitionError(f'Machine {machine_id} is missing or invalid. Read steve.machines and repair its definition; do not substitute another machine.') from exc


def validate_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {'id', 'definition_hash'}:
        raise ValueError('machine requires id and definition_hash from fusion_api_help steve.machines.<id>.')
    identifier(reference['id'])
    if not isinstance(reference['definition_hash'], str) or not re.fullmatch('[0-9a-f]{64}', reference['definition_hash']):
        raise ValueError('Use the exact machine definition_hash returned by API help.')


def resolve(reference, process):
    validate_reference(reference)
    definition = load(reference['id'])
    if definition['definition_hash'] != reference['definition_hash']:
        raise MachineDefinitionError('Machine definition changed. Read steve.machines.' + reference['id'] +
                                     ', review the changed capabilities, then explicitly update the plan with its new hash before checking.')
    if process not in definition['processes']:
        raise MachineDefinitionError('Selected machine does not declare this process. Confirm the intended machine/process; do not reuse another process profile.')
    return definition


def status(reference):
    try:
        current = load(reference['id'])
    except MachineDefinitionError:
        return 'unknown'
    return 'current' if current['definition_hash'] == reference['definition_hash'] else 'stale'


def help(machine_id=None):
    if machine_id is not None:
        definition = load(machine_id)
        return {**definition, 'selection': {key: definition[key] for key in ('id', 'definition_hash')},
                'usage': 'Copy selection into the confirmed plan stage machine field. Compare machine.<capability> using the declared relation/units; read scope first. Missing capabilities remain unknown. No machine is selected automatically.'}
    paths = sorted(DIRECTORY.glob('*.json'))
    if len(paths) > 100:
        raise MachineDefinitionError('Machine catalog exceeds 100 definitions; narrow the installed catalog.')
    items, unavailable = [], []
    for path in paths:
        try:
            definition = load(path.stem)
            items.append({key: definition[key] for key in ('id', 'name', 'revision', 'processes')})
        except (ValueError, MachineDefinitionError):
            unavailable.append(path.stem)
    return {'machines': items, 'unavailable': unavailable,
            'usage': 'Read steve.machines.<id> for capabilities and selection. Confirm the machine with the user; machine specifications do not establish installed tooling, material settings or manufacturing success.'}
