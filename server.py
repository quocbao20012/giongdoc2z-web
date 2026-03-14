import os
import uuid
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- TÍCH HỢP GIAO DIỆN HTML VÀO PYTHON ---
@app.get("/")
async def trang_chu():
    # Khi có người truy cập tên miền, Python sẽ tự động đọc file index.html và hiển thị ra
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

class TTSRequest(BaseModel):
    text: str
    voice: str
    rate: str
    pitch: str
    email: str

class AuthRequest(BaseModel):
    email: str
    password: str

class UpgradeRequest(BaseModel):
    email: str

db_users = {}

# Hàm xóa file tự động dọn rác
def xoa_file_rac(path: str):
    if os.path.exists(path):
        os.remove(path)

@app.post("/api/tts")
async def generate_tts(req: TTSRequest, background_tasks: BackgroundTasks):
    try:
        # Tạo tên file ngẫu nhiên (Ví dụ: audio_a1b2c3d4.mp3) để tránh trùng lặp
        file_name = f"audio_{uuid.uuid4().hex}.mp3"
        
        communicate = edge_tts.Communicate(
            text=req.text, 
            voice=req.voice, 
            rate=req.rate, 
            pitch=req.pitch
        )
        
        await communicate.save(file_name)
        
        # Ra lệnh cho máy chủ: Sau khi gửi file cho người dùng xong thì xóa file này đi ngay lập tức
        background_tasks.add_task(xoa_file_rac, file_name)
        
        return FileResponse(file_name, media_type="audio/mpeg", filename="audio_2z.mp3")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi tạo audio: {str(e)}")

@app.post("/api/register")
async def register(req: AuthRequest):
    if req.email in db_users:
        raise HTTPException(status_code=400, detail="Email này đã được đăng ký!")
    db_users[req.email] = {"password": req.password, "balance": 1000, "is_vip": False}
    return {"message": "Đăng ký thành công!", "balance": 1000, "is_vip": False}

@app.post("/api/login")
async def login(req: AuthRequest):
    user = db_users.get(req.email)
    if not user or user["password"] != req.password:
        raise HTTPException(status_code=400, detail="Sai email hoặc mật khẩu!")
    return {"message": "Đăng nhập thành công!", "balance": user["balance"], "is_vip": user["is_vip"]}

@app.post("/api/upgrade")
async def upgrade_vip(req: UpgradeRequest):
    if req.email in db_users:
        db_users[req.email]["is_vip"] = True
        return {"message": "Đã nâng cấp VIP thành công!"}
    raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    # Thêm đường dẫn này vào gần chỗ @app.get("/")
@app.get("/sitemap.xml")
async def sitemap():
    with open("sitemap.xml", "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content, media_type="application/xml")
