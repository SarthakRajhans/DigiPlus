from app.ai import extract_json, normalize, fallback

def test_ai_structure():
    x=normalize(extract_json('```json\n{"summary":"Good", "decisions":["Ship"], "action_items":[{"title":"Deploy", "owner":"Sam", "due_date":"2026-11-01"}]}\n```'))
    assert x['mode']=='ai' and x['action_items'][0]['owner']=='Sam'

def test_invalid_date_not_trusted():
    x=normalize({'summary':'','decisions':[],'action_items':[{'title':'Do it','due_date':'tomorrow'}]})
    assert x['action_items'][0]['due_date'] is None

def test_no_fake_tasks_during_outage():
    assert fallback('Alice will deliver slides')['action_items']==[]
