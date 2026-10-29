"""CPU draft-schema extraction. Rules return source spans, never inferred labels.

Sparse clinical objects intentionally OMIT unresolved fields: schema null means
clinically undocumented, something a failed parser cannot establish.
"""
import json
import re
from collections import defaultdict
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'schemas/ga_note_extraction_schema.json'
NUMBER = r'(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten)'
WORDS = dict(zip('zero one two three four five six seven eight nine ten'.split(), range(11)))
SCORES = {
    'physical_function.ves13': (r'Vulnerable\s+Elders\s+Survey[- ]?13|VES[- ]?13',10),
    'physical_function.iadl.total': (r'OARS\s+IADL(?:\s+total)?',14),
    'physical_function.mos_physical_function.score': (r'(?:MOS\s+|SF[- ]?36\s+)?PF[- ]?10(?:\s+score)?',None),
    'physical_performance.sppb_total': (r'SPPB(?:\s+total)?|Short\s+Physical\s+Performance\s+Battery(?:\s+total)?',12),
    'physical_performance.sppb_balance': (r'SPPB\s+balance',4),
    'physical_performance.sppb_gait': (r'SPPB\s+gait',4),
    'physical_performance.sppb_chair_stands': (r'SPPB\s+chair\s+(?:stands?|rise)',4),
    'cognition.moca': (r'MoCA|Montreal\s+Cognitive\s+Assessment',30),
    'cognition.bomc': (r'BOMC|Blessed\s+Orientation[- ]Memory[- ]Concentration(?:\s+Test)?',28),
    'cognition.mini_cog': (r'Mini[- ]?Cog',5),
    'cognition.mmse': (r'MMSE|Mini[- ]Mental\s+State\s+Examination',30),
    'cognition.slums': (r'SLUMS|Saint\s+Louis\s+University\s+Mental\s+Status(?:\s+Examination)?',30),
    'psychological.gds15': (r'GDS(?:[- ]?15)?|Geriatric\s+Depression\s+Scale(?:[- ]?15)?',15),
    'psychological.gad7': (r'GAD[- ]?7|Generalized\s+Anxiety\s+Disorder[- ]?7',21),
    'nutrition.mna_sf': (r'MNA[- ]?SF|Mini\s+Nutritional\s+Assessment[- ]Short\s+Form',14),
    'social_support.mos_social_support_tangible': (r'MOS\s+(?:social\s+support\s+)?tangible(?:\s+support)?',100),
    'social_support.mos_social_support_emotional': (r'MOS\s+(?:social\s+support\s+)?emotional(?:\s+support)?',100),
}
ADL = {'bathing':r'bathing|baths?', 'dressing':r'dressing', 'eating':r'eating|feeding',
       'transferring':r'transferring|transfers?', 'walking':r'walking', 'toileting':r'toileting'}
IADL = {'telephone':r'(?:using\s+)?(?:the\s+)?telephone|phone', 'transportation':r'transportation',
        'shopping':r'shopping', 'meal_preparation':r'meal\s+preparation|preparing\s+meals|cooking',
        'housework':r'housework', 'medications':r'medications?|medication\s+management',
        'finances':r'finances|financial\s+management'}
MOS = {'vigorous_activities':r'vigorous activities', 'moderate_activities':r'moderate activities',
       'lifting_groceries':r'lifting groceries', 'climbing_several_flights':r'climbing several flights',
       'climbing_one_flight':r'climbing one flight', 'bending_kneeling_stooping':r'bending[,]? kneeling(?:[,]? (?:and )?stooping)?',
       'walking_more_than_mile':r'walking more than (?:a|one) mile', 'walking_several_blocks':r'walking several blocks',
       'walking_one_block':r'walking one block', 'bathing_dressing':r'bathing(?:\s*/\s*| and )dressing'}


def schema_leaves():
    schema=json.loads(SCHEMA_PATH.read_text(encoding='utf-8')); leaves={}
    def walk(node,path):
        if '$ref' in node: node=schema['$defs'][node['$ref'].split('/')[-1]]
        if 'properties' in node:
            for k,v in node['properties'].items(): walk(v,path+'.'+k if path else k)
        else: leaves[path]=node
    walk(schema,'');return schema,leaves


def number(raw):
    return WORDS[raw.lower()] if raw.lower() in WORDS else float(raw) if '.' in raw else int(raw)


def context_status(text,start,end,score=False,judgment=False):
    # Sentence/clause scope is deliberately bounded; no full temporal NLP claimed.
    left=re.split(r'[\n;!?]|\.(?!\d)|\b(?:but|whereas|today|now)\b',text[max(0,start-160):start],flags=re.I)[-1]
    right=re.split(r'[\n;!?]|\.(?!\d)|\b(?:but|whereas|and\s+(?:today|now))\b',text[end:end+65],flags=re.I)[0]
    span=text[start:end]; context=left+' '+span+' '+right
    if re.search(r'\b(?:mother|father|sister|brother|spouse)\s+(?:has|had|scored|uses|is)\b',left,re.I): return 'other_person'
    if re.search(r'\b(?:not performed|not done|unable to (?:complete|perform)|declined (?:test|assessment)|could not complete|not administered)\b',context,re.I): return 'not_performed'
    if re.search(r'\b(?:may|might|possibly|uncertain|unclear|suspected|if|would|will|planned)\b',context,re.I): return 'uncertain_context'
    if re.search(r'\b(?:previous(?:ly)?|historical|last visit|last year|prior (?:score|assessment)|in 20\d\d)\b',context,re.I): return 'historical_context'
    if re.search(r'\b(?:no|not|denies|denied|without)\s*$',left,re.I): return 'negated_context'
    if score and (re.search(r'\b(?:no|not|denies)\s*$',left,re.I) or re.search(r'\b(?:not valid|invalid|unreliable)\b',right,re.I)): return 'negated_or_invalid'
    if judgment and re.search(r'\b(?:patient|family|wife|husband|daughter|son)\s+(?:reports?|states?|denies|says)\b',context,re.I): return 'not_clinician_judgment'
    return 'candidate'


def put(obj,path,value):
    parts=path.split('.')
    for part in parts[:-1]: obj=obj.setdefault(part,{})
    obj[parts[-1]]=value


class Extractor:
    def __init__(self,text,source_rows=()):
        self.text=text;self.source_rows=source_rows;self.matches=defaultdict(list);self.support={}

    def register(self,path,rule): self.support.setdefault(path,set()).add(rule)

    def add(self,path,value,start,end,rule,status=None,score=False,judgment=False):
        self.register(path,rule)
        status=status or context_status(self.text,start,end,score,judgment)
        self.matches[path].append(dict(predicted_value=value,character_start=start,character_end=end,
            evidence_text=self.text[start:end],rule_id=rule,review_reason=status,
            source_excel_rows=sorted({r['source_excel_row'] for r in self.source_rows
                if r['text_start']<end and r['text_end']>start}),status=status))

    def rule(self,path,pattern,value,rule,score=False,judgment=False):
        self.register(path,rule)
        for m in re.finditer(pattern,self.text,re.I):
            self.add(path,value(m) if callable(value) else value,m.start(),m.end(),rule,score=score,judgment=judgment)

    def scores(self):
        for path,(alias,limit) in SCORES.items():
            name=r'\b(?:'+alias+r')\b'
            # Full name followed by its acronym is one reference, not a second score.
            suffix=r'(?:\s*\((?:VES[- ]?13|MoCA|BOMC|SPPB|GDS[- ]?15|MNA[- ]?SF)\))?'
            num=r'(?P<value>\d{1,3}(?:\.\d+)?)(?:\s*/\s*(?P<max>\d{1,3}(?:\.\d+)?))?(?![\d/]|\.\d)'
            patterns=[r'(?P<name>'+name+suffix+r')\s*(?:score(?:d)?\s*)?(?::|=|of|is|was)?\s*'+num,
                      r'(?<![\w./+\-])'+num+r'\s+(?:on|on\s+the|in)\s+(?P<name>'+name+suffix+r')']
            for leaf in ['value','max','interpretation']:self.register(path+'.'+leaf,'explicit_score')
            found_spans=[]
            for pattern in patterns:
                for m in re.finditer(pattern,self.text,re.I):
                    val=number(m['value']);den=number(m['max']) if m['max'] else None
                    status=context_status(self.text,m.start(),m.end(),score=True)
                    if (limit is not None and val>limit) or (den is not None and (den<=0 or val>den or limit is not None and den!=limit)): status='invalid_score_range_or_version'
                    if path=='psychological.gds15' and den!=15 and not re.search(r'(?:GDS|Scale)[- ]?15',m['name'],re.I):status='unresolved_instrument_version'
                    # Bare SPPB with explicit number is total; named subscores cannot match this grammar.
                    self.add(path+'.value',val,m.start(),m.end(),'explicit_score',status)
                    if den is not None:self.add(path+'.max',den,m.start(),m.end(),'explicit_score',status)
                    found_spans.append((m.start(),m.end()))
                    tail=self.text[m.end():m.end()+60]
                    interpretation=re.match(r'\s*[,;:]?\s*(?:\(|interpreted as\s+|interpretation:\s*)(normal|borderline|impaired)\b',tail,re.I)
                    if interpretation:
                        self.add(path+'.interpretation',interpretation[1].lower(),m.start(),m.end()+interpretation.end(),'documented_score_interpretation',status)
            for m in re.finditer(name,self.text,re.I):
                if not any(a<=m.start()<b for a,b in found_spans):
                    reason=context_status(self.text,m.start(),m.end(),score=True)
                    self.add(path+'.value',None,m.start(),m.end(),'instrument_mention',reason if reason!='candidate' else 'keyword_only')

    def function(self):
        levels={'independent':r'independent', 'needs_assistance':r'needs?\s+(?:assistance|assist|help)|requires?\s+(?:assistance|help)', 'dependent':r'dependent'}
        for kind,items in [('adl',ADL),('iadl',IADL)]:
            base='physical_function.'+kind
            self.register(base+'.source','function_source')
            for item in items:self.register(base+'.'+item,'explicit_function_item_or_global')
            for level,pat in levels.items():
                global_pat=r'\b(?:'+pat+r')\s+(?:with|in|for)\s+(?:all\s+)?'+kind+r's\b'
                for m in re.finditer(global_pat,self.text,re.I):
                    # A global statement with exceptions cannot safely populate every item.
                    tail=self.text[m.end():m.end()+60]
                    exception=bool(re.match(r'\s*[,;]?\s*(?:except|but)\b',tail,re.I))
                    status='global_exception_needs_review' if exception else context_status(self.text,m.start(),m.end())
                    for item in items:self.add(base+'.'+item,level,m.start(),m.end(),'global_function',status)
                    self.add(base+'.source','global_statement',m.start(),m.end(),'function_source',status)
                # Explicit items following a status can be a short list, without crossing clauses.
                for m in re.finditer(r'\b(?:'+pat+r')\s+(?:with|in|for)\s+(?P<items>[^.;\n]{1,130})',self.text,re.I):
                    if re.search(r'\b(?:I?ADLs?|except|otherwise|but|not|no|independent|dependent|needs?|requires?)\b',m['items'],re.I): continue
                    for item,alias in items.items():
                        hit=re.search(r'\b(?:'+alias+r')\b',m['items'],re.I)
                        if hit:
                            end=m.start('items')+hit.end()
                            self.add(base+'.'+item,level,m.start(),end,'itemized_function')
                            self.add(base+'.source','itemized',m.start(),end,'function_source')
                for item,alias in items.items():
                    pattern=r'\b(?:'+alias+r')\s*:\s*(?:'+pat+r')\b'
                    for m in re.finditer(pattern,self.text,re.I):
                        self.add(base+'.'+item,level,m.start(),m.end(),'itemized_function')
                        self.add(base+'.source','itemized',m.start(),m.end(),'function_source')
        # Erika's explicit 'needs help with X, otherwise independent' rule.
        # Require named items confined to exactly one ADL/IADL inventory.
        for m in re.finditer(r'\bneeds?\s+(?:assistance|assist|help)\s+with\s+(?P<items>[^.;\n]{1,100}?),?\s+otherwise independent\b',self.text,re.I):
            named={kind:[item for item,alias in items.items() if re.search(r'\b(?:'+alias+r')\b',m['items'],re.I)] for kind,items in [('adl',ADL),('iadl',IADL)]}
            kinds=[kind for kind in named if named[kind]]
            if len(kinds)!=1:continue
            kind=kinds[0];items=ADL if kind=='adl' else IADL;base='physical_function.'+kind
            for item in items:self.add(base+'.'+item,'needs_assistance' if item in named[kind] else 'independent',m.start(),m.end(),'explicit_otherwise_global')
            self.add(base+'.source','global_statement',m.start(),m.end(),'function_source')
        for item,alias in MOS.items():
            for phrase,value in [('limited a lot','limited_a_lot'),('limited a little','limited_a_little'),('not limited at all','not_limited_at_all')]:
                self.rule('physical_function.mos_physical_function.'+item,
                          r'\b(?:'+alias+r')\s*[:=-]\s*'+phrase+r'\b',value,'explicit_mos_function_item')
        for device in ['cane','walker','wheelchair']:
            self.rule('physical_function.assistive_device',r'\b(?:uses?|ambulates? with|walks? with)\s+(?:a\s+)?'+device+r'\b',device,'explicit_device')
        self.rule('physical_function.assistive_device',r'\b(?:no assistive device|does not use (?:an? )?assistive device)\b','none','explicit_no_device')

    def counts(self,base,label):
        # Register and parse both orderings; inequalities retain qualifiers.
        for leaf in ['value','qualifier']:self.register(base+'.'+leaf,'explicit_count')
        token=r'(?P<qual>approximately\s+|about\s+|roughly\s+|around\s+|~\s*|>\s*|more than\s+)?(?P<num>'+NUMBER+r')'
        for pattern in [token+r'\s+(?:'+label+r')\b',r'\b(?:'+label+r')\s*:\s*'+token]:
            for m in re.finditer(pattern,self.text,re.I):
                q=(m['qual'] or '').strip().lower()
                qualifier='greater_than' if q.startswith('>') or q=='more than' else 'approximate' if q else 'exact'
                status=context_status(self.text,m.start(),m.end())
                prefix=self.text[max(0,m.start()-20):m.start()]
                if re.search(r'(?:<|[-+]|at least|at most|up to|no|denies|(?:\d+|one|two|three|four|five)\s*(?:-|to))\s*$',prefix,re.I):status='unsupported_count_context'
                self.add(base+'.value',number(m['num']),m.start(),m.end(),'explicit_count',status)
                self.add(base+'.qualifier',qualifier,m.start(),m.end(),'explicit_count',status)

    def narrative(self):
        self.rule('performance_status.ecog',r'\bECOG(?:\s+performance\s+status)?\s*[:=]?\s*([0-4])(?![\d/-]|\.\d)',lambda m:int(m[1]),'ecog',score=True)
        self.rule('performance_status.kps',r'\b(?:KPS|Karnofsky(?:\s+performance\s+status)?)\s*[:=]?\s*(100|\d{1,2})(?![\d/-]|\.\d)\s*%?',lambda m:int(m[1]),'kps',score=True)
        self.rule('physical_performance.gait_speed_m_per_s',r'\bgait\s+speed\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:m/s|m/sec|meters per second)\b',lambda m:float(m[1]),'gait_speed',score=True)
        self.rule('physical_performance.timed_up_and_go_s',r'\b(?:TUG|Timed\s+Up\s+and\s+Go)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)\b',lambda m:float(m[1]),'tug',score=True)
        self.counts('falls.number_of_falls',r'falls?')
        self.rule('falls.any_fall',r'\b(?:no\s+(?:prior\s+)?falls?|denies\s+(?:any\s+)?falls?)\b','no','explicit_no_falls')
        self.rule('falls.any_fall',r'\b(?:[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten)\s+falls?\b','yes','explicit_falls')
        self.rule('falls.any_fall',r'\b(?:has had|reports|history of)\s+(?:a\s+)?falls?\b','yes','explicit_falls')
        self.rule('falls.any_fall',r'\bzero falls\b|\b0 falls\b','no','explicit_zero_falls')
        self.register('falls.lookback_months','explicit_fall_period')
        for m in re.finditer(r'\b(?:(?:no|denies)\s+(?:any\s+)?)?falls?\s+(?:in|during|over)\s+(?:the\s+)?(?:past|last)\s+(?:(?P<n>6|12|six|twelve)\s+months|(?P<year>year))\b',self.text,re.I):
            n=12 if m['year'] or m['n'] in {'12','twelve'} else 6
            self.add('falls.lookback_months',n,m.start(),m.end(),'explicit_fall_period')
        self.counts('polypharmacy.medication_count',r'medications?|meds')
        self.counts('comorbidity.condition_count',r'comorbidities|chronic conditions')
        for name in ['vision','hearing']:
            for value in ['excellent','good','fair','poor']:
                self.rule('comorbidity.'+name,r'\b'+name+r'\s*(?::|is)\s*'+value+r'\b',value,'explicit_sensory_rating')
            self.rule('comorbidity.'+name,r'\b'+name+r'\s*(?::|is)\s*impaired\b','impaired_unspecified','explicit_sensory_rating')
        self.rule('polypharmacy.pims_present',r'\b(?:PIMs?|potentially inappropriate medications?)\s*:\s*(?:yes|present)\b','yes','explicit_pims')
        self.rule('polypharmacy.pims_present',r'\b(?:PIMs?|potentially inappropriate medications?)\s*:\s*(?:no|none|absent)\b','no','explicit_pims')
        self.rule('social_support.lives_alone',r'\blives alone\b','yes','explicit_living')
        self.rule('social_support.lives_alone',r'\b(?:does not live alone|lives with (?:his |her |a |their )?(?:wife|husband|spouse|partner|family|daughter|son))\b','no','explicit_living')
        self.rule('social_support.has_caregiver',r'\b(?:has (?:a )?caregiver|caregiver\s*:\s*(?:yes|present))\b','yes','explicit_caregiver')
        self.rule('social_support.has_caregiver',r'\b(?:no caregiver|caregiver\s*:\s*(?:no|none))\b','no','explicit_caregiver')
        self.rule('nutrition.weight_loss',r'\b(?:no (?:unintentional )?weight loss|denies (?:unintentional )?weight loss)\b','no','explicit_no_weight_loss')
        self.rule('nutrition.weight_loss',r'\b(?:reports|has had)\s+(?:unintentional\s+)?weight loss\b','yes','explicit_weight_loss')
        for leaf in ['value','unit']:self.register('nutrition.weight_loss_amount.'+leaf,'explicit_weight_loss')
        self.register('nutrition.weight_loss_lookback_months','explicit_weight_loss_period')
        for m in re.finditer(r'\b(?:lost|weight loss\s*(?:of|:)?)\s*(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>lb|lbs|pounds?|kg|kilograms?)\b(?:\s+(?:over|during|in)\s+(?:the\s+)?(?:past|last)\s+(?P<months>\d+|six|twelve)\s+months)?',self.text,re.I):
            unit='lb' if m['unit'].lower().startswith(('lb','pound')) else 'kg'
            self.add('nutrition.weight_loss','yes',m.start(),m.end(),'explicit_weight_loss')
            self.add('nutrition.weight_loss_amount.value',float(m['n']),m.start(),m.end(),'explicit_weight_loss')
            self.add('nutrition.weight_loss_amount.unit',unit,m.start(),m.end(),'explicit_weight_loss')
            if m['months']:
                n={'six':6,'twelve':12}.get(m['months'].lower()) or int(m['months'])
                self.add('nutrition.weight_loss_lookback_months',n,m.start(),m.end(),'explicit_weight_loss_period')
        for leaf in ['value','unit']:self.register('nutrition.current_weight.'+leaf,'explicit_current_weight')
        for m in re.finditer(r'\b(?:current weight|weight today)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(lb|lbs|pounds?|kg|kilograms?)\b',self.text,re.I):
            self.add('nutrition.current_weight.value',float(m[1]),m.start(),m.end(),'explicit_current_weight')
            self.add('nutrition.current_weight.unit','lb' if m[2].lower().startswith(('lb','pound')) else 'kg',m.start(),m.end(),'explicit_current_weight')
        self.rule('nutrition.bmi',r'\bBMI\s*[:=]?\s*(\d+(?:\.\d+)?)(?!\d|\.\d)',lambda m:float(m[1]),'explicit_bmi',score=True)
        # Only explicitly attributed clinician judgments, never score thresholds.
        for domain,label in [('physical_function','physical function'),('physical_performance','physical performance'),('falls','falls'),('cognition','cognition'),('psychological','mood'),('comorbidity','comorbidity'),('nutrition','nutrition'),('polypharmacy','polypharmacy'),('social_support','social support')]:
            for phrase,value in [('not impaired','not_impaired'),('impaired','impaired')]:
                self.rule(domain+'.clinician_status',r'\b(?:clinician|geriatrician|physician)\s+(?:assessment|impression)\s*:\s*'+label+r'\s*(?::|is)?\s*'+phrase+r'\b',value,'explicit_clinician_judgment',judgment=True)
            for m in re.finditer(r'\b(?:clinician|geriatrician|physician)\s+(?:assessment|impression)\s*:\s*'+label+r'\s*(?::|is)?\s*(?:may|might|possibly|possibly be|may be)\b[^.;\n]{0,50}',self.text,re.I):
                self.add(domain+'.clinician_status',None,m.start(),m.end(),'uncertain_clinician_judgment','uncertain_context')
        social={'interference_time_4wk':['all of the time','most of the time','some of the time','a little of the time','none of the time'],
                'change_6mo':['much less active','somewhat less active','about the same','somewhat more active','much more active'],
                'vs_peers':['much more limited','somewhat more limited','about the same','somewhat less limited','much less limited'],
                'interference_extent_4wk':['not at all','slightly','moderately','quite a bit','extremely']}
        labels={'interference_time_4wk':r'social activity interference time(?: in| over)? (?:the )?(?:past |last )?4 weeks',
                'change_6mo':r'social activity change(?: in| over)? (?:the )?(?:past |last )?6 months',
                'vs_peers':r'social activity (?:compared with|versus) peers',
                'interference_extent_4wk':r'social activity interference extent(?: in| over)? (?:the )?(?:past |last )?4 weeks'}
        for field,values in social.items():
            for value in values:self.rule('social_support.mos_social_activity.'+field,r'\b'+labels[field]+r'\s*:\s*'+value+r'\b',value.replace(' ','_'),'explicit_social_activity_item')

    def finish(self):
        schema,leaves=schema_leaves(); clinical={};audit=[]
        # Detect explicit SPPB consistency problems without calculating missing subscores.
        sppb=['physical_performance.sppb_'+s+'.value' for s in ['total','balance','gait','chair_stands']]
        vals=[{m['predicted_value'] for m in self.matches[p] if m['status']=='candidate'} for p in sppb]
        if all(len(v)==1 for v in vals) and sum(next(iter(v)) for v in vals[1:])!=next(iter(vals[0])):
            for p in sppb:
                for m in self.matches[p]:
                    if m['status']=='candidate':m['status']=m['review_reason']='inconsistent_sppb_components'
        # Values and their explicit units/qualifiers/denominators are coupled.
        # Equal numerators with conflicting denominators are not one reliable score.
        bases={p.rsplit('.',1)[0] for p in self.matches if p.endswith('.value')}
        for base in bases:
            paths=[base+'.'+suffix for suffix in ['value','max','unit','qualifier']]
            if any(len({m['predicted_value'] for m in self.matches.get(p,[]) if m['status']=='candidate'})>1 for p in paths):
                for p in paths:
                    for m in self.matches.get(p,[]):
                        if m['status']=='candidate':m['status']=m['review_reason']='conflicting_measurement_components'
            elif self.matches.get(base+'.value') and not any(m['status']=='candidate' for m in self.matches[base+'.value']):
                for p in paths[1:]:
                    for m in self.matches.get(p,[]):
                        if m['status']=='candidate':m['status']=m['review_reason']='unresolved_parent_value'
        # A device hierarchy is only applied to positive documented use, never to none conflicts.
        devices=self.matches.get('physical_function.assistive_device',[])
        current=[m for m in devices if m['status']=='candidate']
        if current and not any(m['predicted_value']=='none' for m in current):
            rank={'cane':1,'walker':2,'wheelchair':3};most=max(rank[m['predicted_value']] for m in current)
            for m in current:
                if rank[m['predicted_value']]<most:m['status']=m['review_reason']='less_supportive_documented_device'
        for path,node in leaves.items():
            matches=self.matches[path];valid=[m for m in matches if m['status']=='candidate']
            values={json.dumps(m['predicted_value']) for m in valid}
            state='unsupported' if path not in self.support else 'conflicting' if len(values)>1 or any(m['status']=='conflicting_measurement_components' for m in matches) else 'extracted' if len(values)==1 else 'ambiguous' if any(m['status']!='keyword_only' for m in matches) else 'not_found'
            accepted=valid if state=='extracted' else []
            rejected=[m for m in matches if m not in accepted]
            value=valid[0]['predicted_value'] if accepted else None
            if accepted:put(clinical,path,value)
            audit.append(dict(field_path=path,predicted_value=value,extraction_status=state,
                accepted_evidence=accepted,rejected_or_unresolved_candidates=rejected,
                rule_ids=sorted(self.support.get(path,[])),review_reason='conflicting_explicit_values' if state=='conflicting' else
                'machine_absence_is_not_clinical_missingness' if state=='not_found' else 'no_rule_implemented' if state=='unsupported' else state))
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(clinical)
        return clinical,audit


def extract(text,source_rows=()):
    engine=Extractor(text,source_rows);engine.scores();engine.function();engine.narrative()
    return engine.finish()
