from sqlalchemy import Column, Integer, String, Text, JSON, Float
from .database import Base

class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    tags = Column(JSON)
    source_url = Column(String)
    status = Column(String, default="active")
    
    # Jev Routing Fields (New)
    endpoint = Column(String, nullable=True)
    capabilities = Column(JSON, default=[])
    priority = Column(Integer, default=0)
    avg_cost = Column(Float, default=0.0)
    avg_latency = Column(Float, default=0.0)
