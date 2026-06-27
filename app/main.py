from fastapi import FastAPI

app = FastAPI(title="DarkAtlas Asset Management API")

@app.get("/")
def read_root():
    return {"message": "Welcome to DarkAtlas Asset Management API"}
