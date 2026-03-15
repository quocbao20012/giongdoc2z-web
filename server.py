import os
import uuid
import time
import subprocess # THÊM THƯ VIỆN NÀY ĐỂ XỬ LÝ TỐC ĐỘ BẰNG FFMPEG
# Thêm Request vào đây để lấy IP chống spam
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import edge_tts
from sqlalchemy import Column, Integer, String, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- CẤU HÌNH HỆ THỐNG ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres.afeyunipehwlckquuizg:Bao_asd_qwe@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres")

MAX_CONCURRENT_JOBS = 50
active_jobs = 0
last_request_time = {}

engine = create_engine(DATABASE_URL, pool_size=20, max_overflow=30)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- DATABASE MODEL ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    balance = Column(Integer, default=1000)
    is_vip = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

# --- APP SETUP ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class TTSRequest(BaseModel):
    text: str; voice: str; rate: str; pitch: str; email: str
class AuthRequest(BaseModel):
    email: str; password: str

# --- UTILS XỬ LÝ TỐC ĐỘ (FFMPEG) ---
def parse_rate_to_atempo(rate_str: str) -> float:
    """Chuyển đổi chuỗi +100% thành hệ số 2.0 cho FFmpeg"""
    try:
        val = float(rate_str.replace('%', '').replace('+', ''))
        return 1.0 + (val / 100.0)
    except:
        return 1.0

def get_atempo_filter(speed: float) -> str:
    """Tạo bộ lọc atempo cho FFmpeg (Hỗ trợ cả tốc độ siêu nhanh/chậm)"""
    if speed < 0.5: speed = 0.5
    filters = []
    while speed > 2.0:
        filters.append("atempo=2.0")
        speed /= 2.0
    filters.append(f"atempo={speed}")
    return ",".join(filters)

def xoa_file_rac(path: str):
    """Xóa file sau khi khách đã tải xong để tiết kiệm bộ nhớ"""
    try:
        time.sleep(10)
        if os.path.exists(path):
            os.remove(path)
            print(f"✅ Đã dọn dẹp: {path}")
    except Exception as e:
        print(f"❌ Lỗi dọn dẹp: {e}")

# --- ROUTES ---
@app.get("/")
async def trang_chu():
    if active_jobs >= MAX_CONCURRENT_JOBS:
        return HTMLResponse(content="<h1>Hệ thống đang bận, vui lòng thử lại sau 30 giây!</h1>", status_code=503)
    
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>2z Studio AI đang hoạt động!</h1>")

@app.post("/api/tts")
async def generate_tts(req: TTSRequest, request: Request, background_tasks: BackgroundTasks):
    global active_jobs
    db = SessionLocal()
    
    try:
        # 1. Kiểm tra User
        user = db.query(User).filter(User.email == req.email).first()
        if not user: 
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản!")

        # 2. LÁ CHẮN BẢO VỆ (IP & CHỐNG SPAM)
        user_ip = request.client.host
        now = time.time()
        
        if user.is_vip:
            limit_time = 1      # VIP: 1 giây/lần
            max_chars = 100000  # VIP: 100k ký tự
        else:
            limit_time = 10     # Thường: 10 giây/lần
            max_chars = 2000    # Thường: 2k ký tự
            if len(req.text) > user.balance:
                raise HTTPException(status_code=400, detail="Số dư không đủ, vui lòng nạp thêm!")

        if user_ip in last_request_time:
            if now - last_request_time[user_ip] < limit_time:
                raise HTTPException(status_code=429, detail=f"Vui lòng đợi {int(limit_time - (now - last_request_time[user_ip]))}s")

        if len(req.text) > max_chars:
            raise HTTPException(status_code=400, detail=f"Văn bản quá dài! VIP tối đa {max_chars} ký tự.")

        # 3. XỬ LÝ CHÍNH
        active_jobs += 1
        last_request_time[user_ip] = now
        
        file_name = f"audio_{uuid.uuid4().hex}.mp3"
        temp_file = f"temp_{file_name}"
        
        speed_multiplier = parse_rate_to_atempo(req.rate)

        if speed_multiplier == 1.0:
            # Nếu tốc độ bình thường (1x), dùng thẳng Edge-TTS
            communicate = edge_tts.Communicate(text=req.text, voice=req.voice, rate="+0%", pitch=req.pitch)
            await communicate.save(file_name)
        else:
            # Nếu tốc độ khác 1x, dùng FFmpeg ép tốc độ để đảm bảo chính xác 100%
            communicate = edge_tts.Communicate(text=req.text, voice=req.voice, rate="+0%", pitch=req.pitch)
            await communicate.save(temp_file)
            
            filter_str = get_atempo_filter(speed_multiplier)
            subprocess.run(["ffmpeg", "-y", "-i", temp_file, "-filter:a", filter_str, "-vn", file_name], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(temp_file):
                os.remove(temp_file)

        # Trừ tiền nếu không phải VIP
        if not user.is_vip:
            user.balance -= len(req.text)
            db.commit()

        # Dọn dẹp sau khi gửi
        background_tasks.add_task(xoa_file_rac, file_name)
        
        return FileResponse(file_name, media_type="audio/mpeg")
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"🔥 Lỗi nghiêm trọng: {e}")
        raise HTTPException(status_code=500, detail=str(e)) # In ra lỗi thật để dễ sửa chữa
    finally:
        active_jobs -= 1
        db.close()

# --- AUTH API ---
@app.post("/api/register")
async def register(req: AuthRequest):
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == req.email).first():
            raise HTTPException(status_code=400, detail="Email này đã được đăng ký!")
        new_user = User(email=req.email, password=req.password)
        db.add(new_user)
        db.commit()
        return {"message": "Đăng ký thành công!", "balance": 1000, "is_vip": False}
    finally: db.close()

@app.post("/api/login")
async def login(req: AuthRequest):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == req.email).first()
        if not user or user.password != req.password:
            raise HTTPException(status_code=400, detail="Email hoặc mật khẩu không đúng!")
        return {"balance": user.balance, "is_vip": user.is_vip, "message": "Đăng nhập thành công!"}
    finally: db.close()
