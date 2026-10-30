from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .db import Base

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Meeting(Base):
    __tablename__ = 'meetings'
    id = Column(Integer, primary_key=True)
    title = Column(String(180), nullable=False)
    meeting_date = Column(String(10), nullable=False)
    participants = Column(JSON, nullable=False, default=list)
    agenda = Column(Text, default='')
    notes = Column(Text, default='')
    summary = Column(Text, default='')
    decisions = Column(JSON, default=list)
    status = Column(String(20), default='open')
    created_at = Column(DateTime, default=utcnow)
    tasks = relationship('Task', back_populates='meeting', foreign_keys='Task.meeting_id')

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    owner = Column(String(100), default='')
    due_date = Column(String(10), nullable=True)
    status = Column(String(20), default='open')
    outcome = Column(Text, default='')
    meeting_id = Column(Integer, ForeignKey('meetings.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    meeting = relationship('Meeting', foreign_keys=[meeting_id], back_populates='tasks')
    events = relationship('TaskEvent', back_populates='task', cascade='all, delete-orphan', order_by='TaskEvent.id')

class TaskEvent(Base):
    __tablename__ = 'task_events'
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=False)
    event = Column(String(40), nullable=False)
    detail = Column(Text, default='')
    created_at = Column(DateTime, default=utcnow)
    task = relationship('Task', back_populates='events')

class Knowledge(Base):
    __tablename__ = 'knowledge'
    id = Column(Integer, primary_key=True)
    title = Column(String(180), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
