import time
import uuid
from collections import defaultdict
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI()

# --- Assigned Variables ---
TOTAL_ORDERS = 47
RATE_LIMIT_REQUESTS = 16
RATE_LIMIT_WINDOW = 10.0 # seconds

# --- In-Memory Stores ---
idempotency_store = {}
rate_limits = defaultdict(list)

# --- BULLETPROOF MIDDLEWARE: Handles CORS & Rate Limiting ---
@app.middleware("http")
async def rate_limit_and_cors_middleware(request: Request, call_next):
    # 1. CORS Preflight Bypass
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        # Browser ko batana ki preflight pass ho gaya hai
        return response

    # 2. Rate Limiting Logic
    client_id = request.headers.get("x-client-id")
    if client_id:
        now = time.time()
        # Clean up timestamps older than 10 seconds (Sliding Window)
        rate_limits[client_id] = [t for t in rate_limits[client_id] if now - t < RATE_LIMIT_WINDOW]
        
        # Check if limit exceeded (16 requests in 10s)
        if len(rate_limits[client_id]) >= RATE_LIMIT_REQUESTS:
            oldest_request = rate_limits[client_id][0]
            retry_after = int(RATE_LIMIT_WINDOW - (now - oldest_request)) + 1
            
            # Return 429 Error with EXPOSED Retry-After Header
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests"},
                headers={
                    "Retry-After": str(max(1, retry_after)),
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Expose-Headers": "Retry-After"  # <--- THE MAGIC FIX
                }
            )
            
        # Add current request timestamp
        rate_limits[client_id].append(now)

    # 3. Process normal request
    response = await call_next(request)
    
    # Force CORS on all valid responses
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "Retry-After"
    return response

# --- ENDPOINTS ---

@app.post("/orders", status_code=201)
async def create_order(
    response: Response,
    idempotency_key: str = Header(None, alias="Idempotency-Key")
):
    # If key already used, return the exact same response
    if idempotency_key and idempotency_key in idempotency_store:
        response.status_code = 201
        return idempotency_store[idempotency_key]
        
    # Generate new order
    new_order_id = f"ord_{uuid.uuid4().hex[:8]}"
    order_data = {"id": new_order_id, "status": "created"}
    
    # Store it if an idempotency key was provided
    if idempotency_key:
        idempotency_store[idempotency_key] = order_data
        
    return order_data

@app.get("/orders")
async def get_orders(limit: int = 10, cursor: str = None):
    start_id = 1
    if cursor:
        try:
            start_id = int(cursor) + 1
        except ValueError:
            start_id = 1
            
    items = []
    next_cursor = None
    
    # Generate orders from start_id up to TOTAL_ORDERS (47)
    for i in range(start_id, TOTAL_ORDERS + 1):
        if len(items) < limit:
            items.append({"id": i, "details": f"Order #{i}"})
        else:
            break
            
    if items:
        last_id = items[-1]["id"]
        if last_id < TOTAL_ORDERS:
            next_cursor = str(last_id)
            
    return {
        "items": items,
        "next_cursor": next_cursor
    }
