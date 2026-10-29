"""Draft-schema coverage registry; no clinical interpretation or missingness inference."""
import json
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / 'schemas' / 'ga_note_extraction_schema.json'


def registry():
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    mappings = {'cognition.moca': 'moca', 'physical_performance.sppb_total': 'sppb',
                'physical_function.ves13': 'ves_13', 'psychological.gds15': 'gds'}
    result = []
    def visit(node, path):
        if '$ref' in node: node = schema['$defs'][node['$ref'].split('/')[-1]]
        if 'properties' in node:
            for name, child in node['properties'].items(): visit(child, path+'.'+name if path else name)
            return
        parent, _, leaf = path.rpartition('.')
        domain = mappings.get(parent, '') if leaf in {'value','max'} else ''
        # Total SPPB and GDS version require adjudication; existing rule alone is insufficient.
        supported = domain in {'moca','ves_13'}
        result.append(dict(field_path=path, domain=domain or 'unsupported',
            support_status='partial_score_extraction' if supported else 'not_supported',
            limitation=('Baseline explicit score patterns only; no clinical missingness inference.' if supported else
                        'Requires total/version adjudication before mapping.' if domain else 'No schema-aligned rule implemented.'),
            component=leaf))
    visit(schema, '')
    return result


def adapt(prediction, field):
    """Per-leaf grid; denominator is a separate field, never silently filled."""
    if field.get('component') == 'max' and prediction['extraction_status'] == 'extracted':
        prediction['predicted_value'] = prediction['predicted_denominator']
        if prediction['predicted_value'] in ('', None): prediction['extraction_status'] = 'not_found'
    prediction['predicted_denominator'] = ''
    return prediction
