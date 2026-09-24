from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from core import models, database
from api.routes import router

# Initialize database
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="MuleRun")

app.include_router(router, prefix="/api")

@app.get("/")
def read_root():
    return FileResponse(path="static/index.html")

@app.get("/health")
def health_check():
    return {"status": "running", "version": "0.2.0"}

@app.get("/agents")
def list_agents(db: Session = Depends(database.get_db)):
    return db.query(models.Agent).all()

app.mount("/static", StaticFiles(directory="static"), name="static")
