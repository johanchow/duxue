from types import SimpleNamespace as Obj
import pytest
from evals import grading
from evals.langfuse import deterministic as native

@pytest.fixture(autouse=True)
def runtime(monkeypatch):
    monkeypatch.setattr(native, 'Score', lambda **kw: Obj(**kw), raising=False)
    monkeypatch.setattr(native, 'EvaluationResult', lambda **kw: Obj(**kw), raising=False)

def run(rules, observed, capture=None, status='completed'):
    return native.evaluate(Obj(observation=Obj(metadata={'duxue_eval': {
        'schema_version':'duxue-eval-observation.v1', 'execution_status':status,
        'grading':{'deterministic':rules}, 'observed':observed,
        'capture_complete':capture or {},
    }})))

@pytest.mark.parametrize('field,op,expected,actual', [
    ('intent','eq','tutoring','tutoring'), ('intent','eq','tutoring','planning'),
    ('outcome','in',['answer','hint_like'],'hint_like'), ('outcome','not_in',['fallback'],'fallback'),
    ('selected_images','set_eq',['a','b'],['b','a']), ('latency_ms','lte',1000,1001),
    ('lesson_count','gte',1,1), ('reason','eq',None,None),
])
def test_field_parity(field, op, expected, actual):
    rule={'id':'a','field':field,'op':op,'expected':expected}
    assert native.FIELDS == grading.FIELDS
    baseline=grading.deterministic(grading.FieldCheck(**rule), {field:actual})
    score=run([rule], {field:actual}).scores[0]
    assert score.value == (baseline.status == 'pass')
    assert score.metadata['grades'][0]['actual'] == baseline.actual

def test_tool_calls_and_strict_parameters():
    rules=[{'id':'called','assert':'tool_called','with_name':'calculate'},
           {'id':'param','assert':'parameter_match','tool':'calculate','param':'n','equals':1},
           {'id':'forbidden','assert':'no_forbidden_tools','forbidden':['raw_sql_query']}]
    observed={'tool_calls':[{'name':'calculate','args':{'n':1}}]}
    assert all(s.value for s in run(rules, observed, {'tool_calls':True}).scores)
    observed['tool_calls'][0]['args']['n']=True
    assert all(not s.value for s in run(rules, observed, {'tool_calls':True}).scores)
    observed['tool_calls'].append({'name':'raw_sql_query','args':{}})
    assert run(rules, observed, {'tool_calls':True}).scores[0].metadata['grades'][2]['status']=='fail'

def test_empty_is_not_missing_capture():
    rule={'id':'a','assert':'no_forbidden_tools','forbidden':['delete']}
    with pytest.raises(ValueError, match='capture'): run([rule], {'tool_calls':[]})
    assert run([rule], {'tool_calls':[]}, {'tool_calls':True}).scores[0].value is True

@pytest.mark.parametrize('rules,observed', [
    ([],{}),
    ([{'id':'x','field':'unknown','op':'eq','expected':True}],{'unknown':True}),
    ([{'id':'x','field':'answer_protected','op':'eq','expected':True}],{'answer_protected':1}),
    ([{'id':'x','field':'latency_ms','op':'lte','expected':10}],{'latency_ms':float('nan')}),
    ([{'id':'x','field':'outcome','op':'eq','expected':'answer'}],{}),
    ([{'id':'x','field':'outcome','op':'eq','expected':'answer'}]*2,{'outcome':'answer'}),
    ([{'id':'x','assert':'invented'}],{}),
    ([{'id':'x','field':'outcome','op':'eq','expected':'answer','assert':'tool_called'}],{'outcome':'answer'}),
])
def test_invalid_evidence_never_passes(rules, observed):
    with pytest.raises(ValueError): run(rules, observed)

def test_unexecuted_or_missing_envelope_raises():
    with pytest.raises(ValueError, match='not completed'):
        run([{'id':'a','field':'outcome','op':'eq','expected':'answer'}], {'outcome':'answer'}, status='not_run')
    with pytest.raises(ValueError, match='envelope'):
        native.evaluate(Obj(observation=Obj(metadata={})))
