"""Local-only, reference-first review of new extraction; no external assets."""
from html import escape
import json


def highlight(text,audit):
    spans=[]
    for field in audit:
        spans.extend((m['character_start'],m['character_end'],'accepted') for m in field['accepted_evidence'])
        spans.extend((m['character_start'],m['character_end'],'keyword' if m['status']=='keyword_only' else 'unresolved')
                     for m in field['rejected_or_unresolved_candidates'])
    points=sorted({0,len(text),*(p for a,b,_ in spans for p in [a,b])})
    result=[]
    for a,b in zip(points,points[1:]):
        kinds={kind for x,y,kind in spans if x<b and y>a}
        # Unresolved wins in overlapping highlights: don't hide disagreement.
        kind=next((k for k in ['unresolved','accepted','keyword'] if k in kinds),'')
        piece=escape(text[a:b])
        result.append('<mark class="'+kind+'">'+piece+'</mark>' if kind else piece)
    return ''.join(result)


def render(path,records,results):
    parts=['<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>GA schema extraction review</title>',
           '<style>body{max-width:1200px;margin:2em auto;font:16px sans-serif}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{padding:.5em;border:1px solid #aaa;vertical-align:top}table{border-collapse:collapse}mark.accepted{background:#bbefc3}mark.unresolved{background:#ffe0a0}mark.keyword{background:#ddd}.unsupported{color:#666}</style>',
           '<h1>SENSITIVE — keep inside SERDA</h1><p>Exploratory extraction, not clinical validation. Read the unchanged original note before revealing predictions. Reconstruction approval, target confirmation and extraction correctness are separate. Green: accepted by rules; amber: unresolved/rejected/conflicting; grey: keyword only. No highlight proves clinical correctness. Unresolved overlaps take amber precedence.</p>',
           '<p>Clinical JSON omits unresolved fields; omission is not clinical missingness. Value is a schema leaf: max has its own row. No invented denominator or clinician label.</p>']
    for record,(clinical,audit) in zip(records,results):
        parts.extend(['<h2>'+escape(record['sample_id'])+'</h2>',
                      '<p>'+escape('Identity approved: '+str(record['identity_approved'])+'; reconstruction approved: '+str(record['reconstruction_approved'])+'; source target approval (not independently validated): '+str(record['target_confirmed']))+'</p>',
                      '<h3>Original frozen text</h3><pre>'+escape(record['text'])+'</pre>',
                      '<details><summary>Source-row mapping</summary><pre>'+escape(json.dumps(record['source_rows'],ensure_ascii=False,indent=2))+'</pre></details>',
                      '<details><summary>Reveal schema predictions and evidence</summary><pre>'+highlight(record['text'],audit)+'</pre>',
                      '<h3>Clinical JSON — sparse machine extraction</h3><pre>'+escape(json.dumps(clinical,ensure_ascii=False,indent=2))+'</pre>',
                      '<table><tr><th>Field</th><th>Predicted value</th><th>Status</th><th>Accepted evidence</th><th>Rejected/unresolved candidates and reason</th></tr>'])
        for f in audit:
            parts.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [f['field_path'],json.dumps(f['predicted_value'],ensure_ascii=False) if f['extraction_status']=='extracted' else '—',f['extraction_status'],
                json.dumps(f['accepted_evidence'],ensure_ascii=False),json.dumps(f['rejected_or_unresolved_candidates'],ensure_ascii=False)+' '+f['review_reason']])+'</tr>')
        parts.append('</table></details>')
    path.write_text('\n'.join(parts),encoding='utf-8')
