"""Offline, escaped, reference-first SERDA review. No remote resources/scripts."""
from html import escape
import json


def highlighted(text, spans):
    points=sorted({0,len(text),*(max(0,min(len(text),int(x))) for span in spans for x in span)})
    chunks=[]
    for start,end in zip(points,points[1:]):
        piece=escape(text[start:end])
        chunks.append('<mark>'+piece+'</mark>' if any(a<end and b>start for a,b in spans) else piece)
    return ''.join(chunks)


def render(path,manifest,notes,predictions):
    html=['<!doctype html><html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>SERDA GA review</title>',
          '<style>body{max-width:1100px;margin:2em auto;font:16px sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{border:1px solid #999;padding:.5em}table{border-collapse:collapse}mark{background:#ffe89b}</style>',
          '<h1>SENSITIVE — SERDA only</h1><p>Development/error-analysis sample. Read the full original text and fill reference_annotations.csv before expanding CPU predictions. Approvals are sample-specific in sample_manifest.csv. Candidate reconstruction is not proof of document completeness.</p>']
    for m,note in zip(manifest,notes):
        hits=[p for p in predictions if p['sample_id']==m['sample_id']]
        html.append('<section><h2>'+escape(m['sample_id'])+'</h2><p>'+escape(str(m['template_group'])+' | '+str(m['selection_reason'])+' | '+str(m['reconstruction_status']))+'</p>')
        html.append('<p>Reconstruction warnings: '+escape('; '.join(note['reconstruction_warnings']))+'</p>')
        html.append('<h3>Full proposed note — reference first</h3><pre>'+escape(note['text'])+'</pre>')
        html.append('<details><summary>All original rows and reconstruction mapping</summary><pre>'+escape(json.dumps(dict(metadata_evidence=note.get('metadata_evidence',{}),hard_blocks=note['hard_blocks'],raw_rows=note['raw_rows'],source_mapping=note['source_rows']),ensure_ascii=False,indent=2))+'</pre></details>')
        html.append('<details><summary>Reveal CPU predictions and matched evidence</summary>')
        spans=[tuple(s) for p in hits for s in json.loads(p['evidence_start_end'])]
        html.append('<pre>'+highlighted(note['text'],spans)+'</pre><table><tr><th>Field</th><th>Value / denominator</th><th>Status</th><th>Evidence / review reason</th></tr>')
        for p in hits:
            html.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [p['field_path'],str(p['predicted_value'])+' / '+str(p['predicted_denominator']),p['extraction_status'],p['evidence_text']+' '+p['review_reason']])+'</tr>')
        html.append('</table></details></section>')
    html.append('</html>');path.write_text('\n'.join(html),encoding='utf-8')
