from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from dotenv import load_dotenv

import requests
import logging
import os

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")
MONGO_URI = os.getenv("MONGO_URI")

app = FastAPI()

# Handle CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"{FRONTEND_URL}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB
client = AsyncIOMotorClient(MONGO_URI)
db = client.twitch
tokens_collection = db.tokens

# Token model
class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None

async def get_token() -> Optional[Token]:
    token_data = await tokens_collection.find_one({})
    if token_data:
        return Token(**token_data)
    return None


@app.get("/")
async def home():
    return {"message": "Search video games streams on Twitch."}

@app.get("/login")
async def login():
    auth_url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=user:read:email"
    )
    return RedirectResponse(auth_url)

@app.get("/callback")
async def callback(request: Request, token: Optional[Token] = Depends(get_token)):
    code = request.query_params.get('code')
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")

    # Exchange the authorization code for an access token
    token_url = "https://id.twitch.tv/oauth2/token"
    token_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    token_response = requests.post(token_url, data=token_data)
    token_json = token_response.json()

    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")

    if not access_token:
        error_description = token_json.get("error_description", "No error description provided")
        raise HTTPException(status_code=400, detail=f"Failed to obtain access token: {error_description}")

    # Save the token into DB
    await tokens_collection.update_one(
        {},
        {"$set": {"access_token": access_token, "refresh_token": refresh_token}},
        upsert=True
    )

    # Redirect back to the frontend after successful login
    return RedirectResponse(url=FRONTEND_URL)

@app.get("/api/get-game-id")
async def get_game_id(game_name: str, token: Token = Depends(get_token)):
    url = 'https://api.twitch.tv/helix/games'
    headers = {
        'Client-ID': CLIENT_ID,
        'Authorization': f'Bearer {token.access_token}'
    }
    params = {
        'name': game_name
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        games = data.get('data', [])
        if games:
            return JSONResponse(content={"game_id": games[0]['id']})
        else:
            raise HTTPException(status_code=404, detail="Game not found")
    else:
        raise HTTPException(status_code=response.status_code, detail="Error while getting game ID from Twitch")

@app.get("/api/search-videos")
async def search_videos(game_id: str, first: int = 10, after: str = None, token: Token = Depends(get_token)):
    url = f'https://api.twitch.tv/helix/videos'
    headers = {
        'Client-ID': CLIENT_ID,
        'Authorization': f'Bearer {token.access_token}'
    }

    params = {
            'game_id': game_id,
            'first': first
    }

    if after:
        params['after'] = after

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        videos = data.get('data', [])
        pagination = data.get('pagination', {})
        return JSONResponse(content={"videos": videos, "pagination": pagination})
    else:
        raise HTTPException(status_code=response.status_code, detail="Error while getting videos from Twitch")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

