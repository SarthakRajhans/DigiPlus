import json, logging, os, time, uuid
from contextvars import ContextVar
from datetime import date
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from .db import Base, engine, get_db
from .models import Meeting, Task, TaskEvent, Knowledge
from .ai import extract, handoff, relevant_knowledge

Path('logs').mkdir(exist_ok=True)
request_id = ContextVar('request_id', default='system')
class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {'ts':self.formatTime(record), 'level':record.levelname, 'message':record.getMessage(), 'request_id':request_id.get()}
        for key in ('event', 'outcome', 'latency_ms', 'model', 'error_type', 'entity_id'):
            if hasattr(record,key): data[key] = getattr(record,key)
        return json.dumps(data)
logger = logging.getLogger('contextflow')
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.FileHandler('logs/app.jsonl', encoding='utf-8')
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

Base.metadata.create_all(bind=engine)
app = FastAPI(title='ContextFlow', version='1.0.0')
app.mount('/static', StaticFiles(directory=str(Path(__file__).resolve().parent.parent/'static')), name='static')

@app.middleware('http')
async def log_requests(request:Request, call_next):
    rid = request.headers.get('X-Request-ID', '')
    if not rid or len(rid)>80 or not all(c.isalnum() or c in '-_' for c in rid): rid = str(uuid.uuid4())
    token = request_id.set(rid)
    start = time.monotonic()
    try:
        response = await call_next(request)
        response.headers['X-Request-ID'] = rid
        logger.info('request', extra={'event':'request', 'outcome':str(response.status_code), 'latency_ms':round((time.monotonic()-start)*1000)})
        return response
    except Exception as exc:
        logger.exception('request_failed', extra={'event':'request_failed', 'error_type':type(exc).__name__})
        raise
    finally:
        request_id.reset(token)

class MeetingIn(BaseModel):
    title:str = Field(min_length=1,max_length=180)
    meeting_date:date
    participants:list[str] = Field(default_factory=list,max_length=50)
    agenda:str = Field(default='', max_length=12000)
    notes:str = Field(default='', max_length=40000)

class MeetingPatch(BaseModel):
    title:str | None = Field(default=None,min_length=1,max_length=180)
    agenda:str | None = None
    notes:str | None = None
    status:Literal['open','closed'] | None = None

class TaskIn(BaseModel):
    title:str = Field(min_length=1,max_length=300)
    owner:str = Field(default='',max_length=100)
    due_date:date | None = None
    meeting_id:int | None = None

class TaskPatch(BaseModel):
    title:str | None = Field(default=None,min_length=1,max_length=300)
    owner:str | None = Field(default=None,max_length=100)
    due_date:date | None = None
    status:Literal['open','in_progress','blocked','closed'] | None = None
    outcome:str | None = Field(default=None,max_length=10000)

class KBIn(BaseModel):
    title:str = Field(min_length=1,max_length=180)
    content:str = Field(min_length=1,max_length=40000)

def get_or_404(db, model, id):
    row = db.get(model,id)
    if not row: raise HTTPException(404, f'{model.__name__} not found')
    return row

def task_view(t):
    return {'id':t.id,'title':t.title,'owner':t.owner,'due_date':t.due_date,'status':t.status,'outcome':t.outcome,'meeting_id':t.meeting_id,'history':[{'event':e.event,'detail':e.detail,'at':e.created_at.isoformat()} for e in t.events]}

def meeting_view(m):
    return {'id':m.id,'title':m.title,'meeting_date':m.meeting_date,'participants':m.participants,'agenda':m.agenda,'notes':m.notes,'summary':m.summary,'decisions':m.decisions or [],'status':m.status,'tasks':[task_view(t) for t in m.tasks]}

def record(db, t, event, detail=''):
    db.add(TaskEvent(task_id=t.id,event=event,detail=detail))
    logger.info(event,extra={'event':event,'entity_id':t.id})

@app.get('/')
def index(): return FileResponse(Path(__file__).resolve().parent.parent/'static'/'index.html')

@app.get('/api/health')
def health(): return {'status':'ok','ai_configured':bool(os.getenv('AI_API_KEY') or os.getenv('OPENAI_API_KEY'))}

@app.get('/api/meetings')
def meetings(db:Session=Depends(get_db)):
    return [meeting_view(m) for m in db.scalars(select(Meeting).order_by(Meeting.id.desc())).all()]

@app.post('/api/meetings',status_code=201)
def create_meeting(data:MeetingIn,db:Session=Depends(get_db)):
    m=Meeting(title=data.title,meeting_date=data.meeting_date.isoformat(),participants=data.participants, agenda=data.agenda,notes=data.notes)
    db.add(m);db.commit();db.refresh(m)
    logger.info('meeting_created',extra={'event':'meeting_created','entity_id':m.id})
    return meeting_view(m)

@app.patch('/api/meetings/{id}')
def update_meeting(id:int,data:MeetingPatch,db:Session=Depends(get_db)):
    m=get_or_404(db,Meeting,id)
    for k,v in data.model_dump(exclude_unset=True).items(): setattr(m,k,v)
    db.commit();db.refresh(m)
    return meeting_view(m)

@app.post('/api/meetings/{id}/extract')
async def extract_meeting(id:int,db:Session=Depends(get_db)):
    m=get_or_404(db,Meeting,id)
    if not m.notes.strip(): raise HTTPException(422,'Add notes before generating a recap')
    result=await extract(m.notes,m.title)
    if result['mode']=='ai':
        m.summary=result['summary'];m.decisions=result['decisions']
        for item in result['action_items']:
            t=Task(title=item['title'],owner=item['owner'],due_date=item['due_date'],meeting_id=m.id)
            db.add(t);db.flush();record(db,t,'created','Extracted from meeting by AI; review suggested')
        db.commit()
    db.refresh(m)
    logger.info('recap_generated',extra={'event':'recap_generated','entity_id':m.id,'outcome':result['mode']})
    return {'result':result,'meeting':meeting_view(m)}

@app.post('/api/meetings/{id}/carry-forward')
def carry_forward(id:int,from_meeting_id:int,db:Session=Depends(get_db)):
    m=get_or_404(db,Meeting,id); source=get_or_404(db,Meeting,from_meeting_id)
    if m.id==source.id: raise HTTPException(422,'Cannot carry tasks to same meeting')
    tasks=db.scalars(select(Task).where(Task.meeting_id==source.id,Task.status!='closed')).all()
    existing = {t.id for t in m.tasks}
    # Preserve original task identity/history; don't duplicate or move provenance.
    # Link carried tasks through events, while keeping original meeting_id intact.
    carried=[]
    for t in tasks:
        if any(e.event=='carried_forward' and e.detail==str(m.id) for e in t.events): continue
        record(db,t,'carried_forward',str(m.id));carried.append(t.id)
    db.commit()
    logger.info('tasks_carried',extra={'event':'tasks_carried','entity_id':m.id})
    return {'carried_task_ids':carried,'source_meeting_id':source.id,'destination_meeting_id':m.id}

@app.get('/api/meetings/{id}/carried')
def carried(id:int,db:Session=Depends(get_db)):
    get_or_404(db,Meeting,id)
    tasks=db.scalars(select(Task).join(TaskEvent).where(TaskEvent.event=='carried_forward',TaskEvent.detail==str(id)).distinct()).all()
    return [task_view(t) for t in tasks]

@app.get('/api/tasks')
def tasks(db:Session=Depends(get_db)):
    return [task_view(t) for t in db.scalars(select(Task).order_by(Task.id.desc())).all()]

@app.post('/api/tasks',status_code=201)
def create_task(data:TaskIn,db:Session=Depends(get_db)):
    if data.meeting_id is not None: get_or_404(db,Meeting,data.meeting_id)
    t=Task(title=data.title,owner=data.owner,due_date=data.due_date.isoformat() if data.due_date else None,meeting_id=data.meeting_id)
    db.add(t);db.flush();record(db,t,'created','Manual creation');db.commit();db.refresh(t)
    return task_view(t)

@app.patch('/api/tasks/{id}')
def update_task(id:int,data:TaskPatch,db:Session=Depends(get_db)):
    t=get_or_404(db,Task,id)
    patch=data.model_dump(exclude_unset=True)
    if 'status' in patch and patch['status']=='closed' and not (patch.get('outcome') or t.outcome).strip():
        raise HTTPException(422,'An outcome is required to close an item')
    for k,v in patch.items():
        if k=='due_date' and v is not None: v=v.isoformat()
        old=getattr(t,k)
        if old!=v:
            setattr(t,k,v)
            if k=='owner': record(db,t,'reassigned',f'{old or "Unassigned"} -> {v or "Unassigned"}')
            elif k=='status' and v=='closed': record(db,t,'closed',patch.get('outcome') or t.outcome)
            else: record(db,t,'updated',f'{k} changed')
    db.commit();db.refresh(t)
    return task_view(t)

@app.get('/api/knowledge')
def knowledge(db:Session=Depends(get_db)):
    return [{'id':k.id,'title':k.title,'content':k.content} for k in db.scalars(select(Knowledge).order_by(Knowledge.id.desc())).all()]

@app.post('/api/knowledge',status_code=201)
def add_knowledge(data:KBIn,db:Session=Depends(get_db)):
    k=Knowledge(**data.model_dump());db.add(k);db.commit();db.refresh(k)
    logger.info('knowledge_created',extra={'event':'knowledge_created','entity_id':k.id})
    return {'id':k.id,'title':k.title,'content':k.content}

@app.get('/api/meetings/{id}/knowledge')
async def related(id:int,db:Session=Depends(get_db)):
    m=get_or_404(db,Meeting,id);docs=db.scalars(select(Knowledge)).all()
    ids=await relevant_knowledge(m.title+'\n'+m.notes,docs)
    return [{'id':d.id,'title':d.title,'content':d.content} for d in docs if d.id in ids]

@app.get('/api/radar')
def radar(db:Session=Depends(get_db)):
    today=date.today().isoformat()
    all_tasks=db.scalars(select(Task).where(Task.status!='closed')).all()
    result=[]
    for t in all_tasks:
        reasons=[]
        if not t.owner.strip(): reasons.append('Unassigned')
        if t.due_date and t.due_date<today: reasons.append('Overdue')
        if t.status=='blocked': reasons.append('Blocked')
        if reasons: result.append({'task':task_view(t),'reasons':reasons})
    return result

@app.post('/api/handoff')
async def handoff_brief(db:Session=Depends(get_db)):
    ms=db.scalars(select(Meeting).order_by(Meeting.id.desc()).limit(6)).all()
    ts=db.scalars(select(Task).where(Task.status!='closed').order_by(Task.id.desc()).limit(30)).all()
    payload={'meetings':[{'title':m.title,'date':m.meeting_date,'summary':m.summary,'decisions':m.decisions} for m in ms], 'open_tasks':[{'title':t.title,'owner':t.owner,'due_date':t.due_date,'status':t.status} for t in ts]}
    return await handoff(payload)
