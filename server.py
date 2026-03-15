import os
import uuid
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts
from sqlalchemy import Column, Integer, String, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- CẤU HÌNH HỆ THỐNG ---
# Thay mật khẩu và link cổng 6543 của bạn vào đây
DATABASE_URL = "postgresql://postgres.afeyunipehwlckquuizg:Bao_asd_qwe@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

# Giới hạn số người tạo cùng lúc (Gói Free nên để 3-5)
MAX_CONCURRENT_JOBS = 5
active_jobs = 0

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    balance = Column(Integer, default=1000)
    is_vip = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class TTSRequest(BaseModel):
    text: str; voice: str; rate: str; pitch: str; email: str
class AuthRequest(BaseModel):
    email: str; password: str

# Hàm xóa file rác (Chạy ngầm sau khi trả file cho khách)
def xoa_file_rac(path: str):
    try:
        if os.path.exists(path):
            # Đợi 5 giây để đảm bảo trình duyệt đã tải xong file
            time.sleep(5)
            os.remove(path)
            print(f"--- Đã dọn dẹp file rác: {path} ---")
    except Exception as e:
        print(f"Lỗi khi xóa file: {e}")

@app.get("/")
async def trang_chu():
    # Nếu server đang quá tải, báo bảo trì tự động
    if active_jobs >= MAX_CONCURRENT_JOBS:
        if os.path.exists("maintenance.html"):
            with open("maintenance.html", "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>Hệ thống đang bận, vui lòng quay lại sau 1 phút!</h1>")
    
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/api/tts")
async def generate_tts(req: TTSRequest, background_tasks: BackgroundTasks):
    global active_jobs
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == req.email).first()
        if not user: raise HTTPException(status_code=404, detail="User not found")
        if not user.is_vip and len(req.text) > user.balance:
            raise HTTPException(status_code=400, detail="Số dư không đủ!")

        # Tăng biến đếm công việc đang chạy
        active_jobs += 1
        
        file_name = f"audio_{uuid.uuid4().hex}.mp3"
        communicate = edge_tts.Communicate(text=req.text, voice=req.voice, rate=req.rate, pitch=req.pitch)
        await communicate.save(file_name)

        if not user.is_vip:
            user.balance -= len(req.text)
            db.commit()

        # THÊM NHIỆM VỤ XÓA FILE SAU KHI PHẢN HỒI
        background_tasks.add_task(xoa_file_rac, file_name)
        
        return FileResponse(file_name, media_type="audio/mpeg")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        active_jobs -= 1 # Giảm biến đếm khi xong việc
        db.close()

# --- AUTH API ---
@app.post("/api/register")
async def register(req: AuthRequest):
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == req.email).first():
            raise HTTPException(status_code=400, detail="Email đã tồn tại!")
        new_user = User(email=req.email, password=req.password)
        db.add(new_user)
        db.commit()
        return {"message": "Thành công!", "balance": 1000, "is_vip": False}
    finally: db.close()

@app.post("/api/login")
async def login(req: AuthRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == req.email).first()
        if not user or user.password != req.password:
            raise HTTPException(status_code=400, detail="Sai thông tin!")
        return {"balance": user.balance, "is_vip": user.is_vip}
    finally: db.close()
