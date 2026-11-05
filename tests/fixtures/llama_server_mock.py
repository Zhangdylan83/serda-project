#!/usr/bin/env python3
"""SYNTHETIC PROTOCOL FIXTURE ONLY. No weights loaded; no LLM inference."""
import argparse
import json
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from serda_pipeline.ga_schema_engine import extract
from serda_pipeline.ga_local_llm import domain_fields

parser=argparse.ArgumentParser();parser.add_argument('--version',action='store_true')
parser.add_argument('--host');parser.add_argument('--port',type=int);parser.add_argument('--api-key');args,_=parser.parse_known_args()
if args.version:
    print('SYNTHETIC MOCK ONLY build b12125; not a real llama.cpp binary');raise SystemExit(0)
if args.host!='127.0.0.1':raise SystemExit('Fixture refuses non-loopback')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,payload,code=200):
        data=json.dumps(payload).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def auth(self):return self.headers.get('Authorization')=='Bearer '+args.api_key
    def do_GET(self):
        self.send({'status':'ok'} if self.auth() and self.path=='/health' else {},200 if self.auth() else 401)
    def do_POST(self):
        if not self.auth():self.send({},401);return
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/apply-template':self.send({'prompt':json.dumps(data['messages'])});return
        if self.path=='/tokenize':self.send({'tokens':[1]*(len(data['content'])//4)});return
        if self.path!='/v1/chat/completions':self.send({},404);return
        assert 'tools' not in data
        assert data['chat_template_kwargs']['enable_thinking'] is False
        assert data['response_format']['type']=='json_schema'
        user=json.loads(data['messages'][-1]['content']);domain=user['domain'];text=user['source_text']
        _,audit=extract(text);fields=user['allowed_fields']
        findings=[dict(field_path=a['field_path'],value=a['predicted_value'],quote=a['accepted_evidence'][0]['evidence_text'],certainty='explicit')
                  for a in audit if a['field_path'] in fields and a['extraction_status']=='extracted']
        self.send({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'findings':findings})}}],
                   'usage':{'completion_tokens':25},'timings':{'predicted_n':25,'predicted_ms':1}})

HTTPServer((args.host,args.port),Handler).serve_forever()
