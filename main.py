import os
import json
import asyncio
import subprocess
from datetime import date

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from better_profanity import profanity
from dotenv import load_dotenv
load_dotenv()

class ProfanityRequest(BaseModel):
    text: str
    url: str 


app = FastAPI()
_crawl_lock = asyncio.Lock()

@app.get("/scrape", response_class=JSONResponse)
async def scrape(
    cutoff: str = Query("2025-01-01")
):
    try:
        _ = date.fromisoformat(cutoff)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid cutoff (expected YYYY-MM-DD)")

    if _crawl_lock.locked():
        raise HTTPException(status_code=409, detail="Crawler is already running")

    async with _crawl_lock:

        file_path = "res.jsonl"

        cmd = [
            os.sys.executable, "-m", "scrapy", "crawl", "tm_sections",
            "-a", f"cutoff={cutoff}",
            "-O", file_path,
            "-s", "LOG_LEVEL=ERROR"
        ]
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                cwd="themanufacturer",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Scrape timed out")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to launch scrapy: {e}")

        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            raise HTTPException(status_code=500, detail=f"Scrapy failed: {err[:4000]}")

        try:

            json_list = []
            file_path = f"./themanufacturer/{file_path}"
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        json_list.append(json.loads(line))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not read/parse output file: {e}")

        return JSONResponse(content=json_list)


@app.post("/profanity", response_class=JSONResponse)
async def check_profanity(request: ProfanityRequest):
    url , text = request.url, request.text
    return JSONResponse(content={"text": profanity.censor(text) , "url": url})


@app.get("/stocks", response_class=JSONResponse)
async def stocks():
    try:
        SYMBOLS_MAP = os.environ.get("SYMBOL_MAP", '{}')
        ALPHAVANTAGE_API_KEY= os.environ.get("ALPHAVANTAGE_API_KEY")
        print(ALPHAVANTAGE_API_KEY, SYMBOLS_MAP)
        successful_stocks = []
        
        async with httpx.AsyncClient() as client:
            await asyncio.sleep(5)  # Rate limit: 1 request per second
            for company, symbol in json.loads(SYMBOLS_MAP).items():
                if not symbol:
                    continue

                url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHAVANTAGE_API_KEY}"
                
                try:
                    response = await client.get(url)
                    print(company, symbol, response.status_code, response)
                    
                    if response.status_code == 200:
                        stock_data = response.json()
                        # Only add to output if we got valid data
                        res = {}
                        res["output"] = {
                            "company": company,
                            "symbol": symbol,
                            "data": stock_data
                        }
                        successful_stocks.append(res)
                    
                except httpx.RequestError as e:
                    continue
                    
                except Exception as e:
                    continue
                    
        return JSONResponse(content=successful_stocks)
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid SYMBOL_MAP configuration in environment")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing stocks: {str(e)}")
