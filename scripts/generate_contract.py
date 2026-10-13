"""Regenere les constantes depuis le contrat SDK versionne, sans reseau."""
import argparse
import json
from pathlib import Path
from pprint import pformat

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
contract = json.loads((root / 'contract/sdk.json').read_text(encoding='utf-8'))
lines = ['"""Genere par scripts/generate_contract.py ; ne pas modifier directement."""',
         '', 'from __future__ import annotations', '']
for name in ['API_VERSION', 'CONTRAT_SOURCE', 'OPERATIONS', 'FAMILLE_PAR_CODE', 'KEY_PREFIXES']:
    lines += [name + ' = ' + pformat(contract[name], sort_dicts=False, width=100), '']
lines += ['HORS_PERIMETRE = frozenset(' + repr(contract['HORS_PERIMETRE']) + ')', '']
expected = '\n'.join(lines)
path = root / 'src/spavik/_contract.py'
if args.check:
    if path.read_text(encoding='utf-8') != expected:
        raise SystemExit('Generated contract is stale. Run python scripts/generate_contract.py.')
    print('Generated contract is current.')
else:
    path.write_text(expected, encoding='utf-8')
